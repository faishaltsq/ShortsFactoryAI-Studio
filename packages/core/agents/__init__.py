"""One class per agent. Typed input, typed output, its own provider binding.

An agent does three things: build a prompt, call the model through the router, and validate what
comes back. It never writes state, never touches the database, and never decides whether the job
succeeds — the runner does that by checking the artifact.

Structured output is the default. A model that returns prose where JSON was required gets one
bounded repair attempt, then the stage fails. Silently accepting prose and pattern-matching it into
a schema is how a pipeline produces plausible garbage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..contracts.base import Artifact, ArtifactValidationError, validate_artifact
from ..providers.base import Capability, Provider, ProviderError, ResolvedCall
from ..security.redact import redact


class ModelOutputError(RuntimeError):
    """The model's output could not be turned into the required artifact."""

    def __init__(self, code: str, detail: str, *, retryable: bool = True) -> None:
        self.code = code
        self.detail = detail
        self.retryable = retryable
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class CallContext:
    """Everything an agent needs to make one call. No global state."""

    call: ResolvedCall
    provider: Provider
    job_id: str | None = None


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response.

    Handles the three shapes models actually emit: bare JSON, a fenced block, and prose with a JSON
    object embedded. It does not attempt to repair malformed JSON — a repair guess is how a field
    silently becomes the wrong value.
    """
    candidate = text.strip()
    if candidate.startswith("{"):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    fenced = _JSON_BLOCK.search(text)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        break
    raise ModelOutputError(
        "schema_violation",
        f"no JSON object in the response: {redact(text[:160])}",
    )


class Agent:
    """Base class: one completion, one validated artifact, bounded repair."""

    name = "Agent"
    requires: frozenset[Capability] = frozenset({Capability.CHAT, Capability.JSON_SCHEMA})
    system_prompt = "You return only JSON."

    def __init__(self, ctx: CallContext) -> None:
        self.ctx = ctx

    # -- to override ------------------------------------------------------------------------
    def build_user_prompt(self, **kwargs: Any) -> str:
        raise NotImplementedError

    def contract(self) -> type[Artifact]:
        raise NotImplementedError

    # -- machinery --------------------------------------------------------------------------
    def call(self, *, task: str, **kwargs: Any) -> str:
        user = self.build_user_prompt(**kwargs)
        try:
            result = self.ctx.provider.complete(
                self.ctx.call, system=self.system_prompt, user=user, task=task
            )
        except ProviderError as exc:
            raise ModelOutputError(exc.code, exc.detail, retryable=exc.retryable) from exc
        return result.content

    def produce(self, *, task: str, **kwargs: Any) -> Artifact:
        """Call, parse, validate. One repair attempt on a schema violation, then fail."""
        raw = self.call(task=task, **kwargs)
        try:
            payload = extract_json(raw)
            return validate_artifact(self.contract(), payload)
        except (ModelOutputError, ArtifactValidationError) as first:
            repair_prompt = (
                f"{self.build_user_prompt(**kwargs)}\n\n"
                "Your previous answer was rejected: "
                f"{getattr(first, 'problems', None) or first}\n"
                "Return ONLY a corrected JSON object. No prose, no markdown."
            )
            try:
                result = self.ctx.provider.complete(
                    self.ctx.call, system=self.system_prompt, user=repair_prompt, task=task + ":repair"
                )
            except ProviderError as exc:
                raise ModelOutputError(exc.code, exc.detail, retryable=exc.retryable) from exc
            try:
                return validate_artifact(self.contract(), extract_json(result.content))
            except (ModelOutputError, ArtifactValidationError) as second:
                raise ModelOutputError(
                    "schema_violation",
                    f"repair failed: {getattr(second, 'problems', None) or second}",
                ) from second
