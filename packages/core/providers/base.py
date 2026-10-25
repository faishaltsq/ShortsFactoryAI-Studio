"""Provider contract: capabilities, results, and the frozen call value.

Every backend implements this and nothing else. A transport that needs a new knob gets a field on
``ResolvedCall``; it does not get a mutable attribute on a shared object.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class Capability(str, Enum):
    """What a model can actually do. Declared by the operator, never inferred from a model name.

    Inferring "this model name contains 'vision' so it can see" is how a system ends up claiming a
    text model inspected video frames.
    """

    CHAT = "chat"
    JSON_SCHEMA = "json_schema"
    TOOLS = "tools"
    VISION = "vision"


@dataclass(frozen=True)
class Health:
    ok: bool
    detail: str = ""
    latency_ms: int = 0

    @classmethod
    def up(cls, detail: str = "", latency_ms: int = 0) -> Health:
        return cls(True, detail, latency_ms)

    @classmethod
    def down(cls, detail: str) -> Health:
        return cls(False, detail, 0)


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class ProviderResult:
    content: str
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    elapsed_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """A call failed permanently, after its own bounded retries.

    ``code`` is a stable taxonomy value the orchestrator maps to a job state; ``detail`` is safe to
    show an operator (already redacted by the transport).
    """

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        provider: str = "",
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.detail = detail
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"{code}: {detail}")


class CapabilityMismatch(ValueError):
    """A binding requires a capability its provider does not declare.

    Raised during resolution, before any network call. This is a configuration error the operator
    must fix, not a runtime failure to retry.
    """

    def __init__(self, agent: str, provider: str, missing: frozenset[Capability]) -> None:
        self.agent = agent
        self.provider = provider
        self.missing = missing
        names = ", ".join(sorted(cap.value for cap in missing))
        super().__init__(
            f"{agent} requires [{names}] but provider {provider!r} does not declare it"
        )


class NoProviderAvailable(RuntimeError):
    """No candidate provider could serve this call.

    In live mode this is fatal for the job. It is never converted into a mock success: a live job
    that silently degrades to mock produces fabricated content that looks real.
    """

    def __init__(self, agent: str, reasons: list[str]) -> None:
        self.agent = agent
        self.reasons = reasons
        super().__init__(f"no provider available for {agent}: " + "; ".join(reasons))


@dataclass(frozen=True)
class ResolvedCall:
    """Everything a transport needs, frozen.

    The ``credential`` field holds the *value*, resolved at call time by the resolver and dropped
    when the call returns. It is excluded from ``repr`` so an accidental log of this object cannot
    leak it.
    """

    provider: str
    transport: str
    base_url: str
    model: str
    temperature: float | None
    max_tokens: int | None
    timeout_s: float
    max_retries: int
    capabilities: frozenset[Capability]
    allow_private_hosts: bool
    params: dict[str, Any] = field(default_factory=dict)
    credential: str = field(default="", repr=False)

    @property
    def has_credential(self) -> bool:
        return bool(self.credential)


@runtime_checkable
class Provider(Protocol):
    """A transport. Stateless with respect to configuration: all of it arrives in ``call``."""

    name: str
    transport: str

    def health(self, call: ResolvedCall) -> Health: ...

    def complete(self, call: ResolvedCall, *, system: str, user: str, task: str) -> ProviderResult: ...

    def list_models(self, call: ResolvedCall) -> list[str] | None: ...


def now_ms() -> int:
    return int(time.time() * 1000)
