"""Provider contract: capabilities, results, and the frozen call value.

Every backend implements this and nothing else. A transport that needs a new knob gets a field on
``ResolvedCall``; it does not get a mutable attribute on a shared object.
"""

from __future__ import annotations

import base64
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


class VisionUnsupported(ValueError):
    """A transport was asked to look at an image and cannot.

    Distinct from ``CapabilityMismatch``: that one is a configuration problem caught before any
    call. This one is a transport that has no image path at all (``mock``, ``cli``), and it must
    stay unreachable for a provider that declares ``vision`` in the first place.
    """

    def __init__(self, transport: str) -> None:
        self.transport = transport
        super().__init__(
            f"transport {transport!r} cannot inspect images; it cannot declare the vision capability"
        )


#: Formats every supported API accepts. Anything else is rejected before a request is built,
#: because a provider's "unsupported media type" arrives after the bytes have already left.
VISION_MEDIA_TYPES = frozenset({"image/png", "image/jpeg"})

#: A contact sheet is ~200 KB. This cap exists so a bug that passes raw frames cannot upload a
#: gigabyte, not because a provider refuses larger images.
MAX_VISION_BYTES = 5 * 1024 * 1024

#: Magic prefixes, so ``media_type`` is checked against the bytes instead of trusted.
_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


@dataclass(frozen=True)
class VisionImage:
    """One image, held as bytes and never as a path.

    ``repr`` is overridden because a dataclass repr would print the payload, and the first place
    a payload shows up is a traceback in a log file.
    """

    data: bytes
    media_type: str = "image/png"
    label: str = ""

    def __post_init__(self) -> None:
        if self.media_type not in VISION_MEDIA_TYPES:
            raise ValueError(
                f"unsupported media_type {self.media_type!r}; expected one of "
                f"{sorted(VISION_MEDIA_TYPES)}"
            )
        if not self.data:
            raise ValueError("vision image is empty")
        if len(self.data) > MAX_VISION_BYTES:
            raise ValueError(
                f"vision image too large: {len(self.data)} bytes > {MAX_VISION_BYTES}"
            )
        if not any(self.data.startswith(magic) for magic in _MAGIC):
            raise ValueError("vision image does not look like PNG or JPEG")
        actual = next(mime for magic, mime in _MAGIC.items() if self.data.startswith(magic))
        if actual != self.media_type:
            raise ValueError(
                f"vision image media_type {self.media_type!r} does not look like the bytes "
                f"({actual})"
            )

    def __repr__(self) -> str:
        return f"VisionImage(media_type={self.media_type!r}, bytes={len(self.data)}, label={self.label!r})"

    @property
    def byte_size(self) -> int:
        return len(self.data)

    def data_uri(self) -> str:
        return f"data:{self.media_type};base64,{base64.b64encode(self.data).decode('ascii')}"

    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def to_json(self) -> dict[str, Any]:
        """What may be persisted. Never the payload."""
        return {"media_type": self.media_type, "bytes": len(self.data), "label": self.label}


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

    def complete_vision(
        self,
        call: ResolvedCall,
        *,
        system: str,
        user: str,
        task: str,
        images: list[VisionImage],
    ) -> ProviderResult: ...

    def list_models(self, call: ResolvedCall) -> list[str] | None: ...


def now_ms() -> int:
    return int(time.time() * 1000)
