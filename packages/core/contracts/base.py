"""Artifact base class, canonical hashing, and validation entry point."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ArtifactValidationError(ValueError):
    """An artifact failed its own contract. Never caught and downgraded to a warning."""

    def __init__(self, kind: str, problems: list[str]) -> None:
        self.kind = kind
        self.problems = problems
        super().__init__(f"{kind} invalid: " + "; ".join(problems))


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


class Artifact(BaseModel):
    """Base for every persisted artifact.

    ``schema_version`` is part of the payload, not a wrapper, so an artifact read back from disk
    can prove what wrote it. Extra keys are forbidden: a field that is not in the contract must not
    silently travel through the pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ClassVar[str] = "artifact"

    schema_version: int = 1
    created_at: str = Field(default_factory=_utc_now)

    def canonical_json(self) -> str:
        """Deterministic JSON: sorted keys, no whitespace, no NaN.

        ``created_at`` is excluded so that re-serialising an unchanged artifact yields the same
        hash; otherwise every read would look like a modification.
        """
        payload = self.model_dump(mode="json", exclude={"created_at"})
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def content_hash(payload: Any) -> str:
    """Hash arbitrary JSON-able content the same way artifacts are hashed."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_artifact(model: type[Artifact], payload: dict[str, Any]) -> Artifact:
    """Parse or raise ``ArtifactValidationError`` with every problem, not just the first.

    Pydantic reports one error at a time when used naively; an operator debugging a rejected
    storyboard wants the whole list.
    """
    from pydantic import ValidationError

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"]) or "<root>"
            problems.append(f"{loc}: {err['msg']}")
        raise ArtifactValidationError(model.kind, problems) from exc
