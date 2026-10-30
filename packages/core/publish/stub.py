"""A publication transport that records every call, for tests and for a dry run.

It lives in ``packages/`` rather than ``tests/`` because the stage needs *something* to talk to in
an offline build, and a stub that is only reachable from tests cannot be used to exercise the stage
from a script. It performs no I/O and contacts nothing.

The call log is the assertion surface: "no duplicate upload" is proven by counting ``insert`` calls
across a sequence, so the log has to be exact and append-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .reconcile import key_marker
from .transport import (
    InsertRequest,
    InsertResult,
    RemoteVideo,
    ThumbnailResult,
    TransportRefused,
    TransportUncertain,
)


@dataclass
class InsertCall:
    request: InsertRequest
    outcome: str  # "inserted" | "refused" | "uncertain"


@dataclass
class ThumbnailCall:
    video_id: str
    thumbnail_path: str


@dataclass
class StubTransport:
    """Scripted outcomes, an append-only call log, and a fake remote channel.

    ``script`` is consumed in order: each ``insert`` takes the next entry. An exhausted script
    inserts successfully, so a test that only cares about the first call does not have to script
    every later one.
    """

    name: str = "stub"
    script: list[str] = field(default_factory=list)
    remote: list[RemoteVideo] = field(default_factory=list)
    inserts: list[InsertCall] = field(default_factory=list)
    thumbnail_calls: list[ThumbnailCall] = field(default_factory=list)
    list_calls: int = 0
    #: Set to make ``list_private`` raise, to prove reconciliation propagates rather than guesses.
    list_error: Exception | None = None
    _refusal: tuple[str, str] = field(default=("no_credential", "refused before send"))
    _uncertainty: tuple[str, str] = field(default=("provider_timeout", "timeout after send"))

    # -- scripting helpers ------------------------------------------------------------------
    def refuse_next(self, code: str = "no_credential", detail: str = "no token configured") -> None:
        self.script.append("refused")
        self._refusal = (code, detail)

    def be_uncertain_next(self, code: str = "provider_timeout", detail: str = "timeout after 30s") -> None:
        self.script.append("uncertain")
        self._uncertainty = (code, detail)

    def succeed_next(self) -> None:
        self.script.append("inserted")

    def add_remote(self, video_id: str, *, title: str = "", privacy: str = "private",
                   idempotency_key: str = "", description: str = "") -> RemoteVideo:
        """Add a video that already exists remotely.

        ``idempotency_key`` models a transport whose API exposes a custom field.
        ``description`` models the fallback: the key embedded as a marker, which is what a real
        transport without custom metadata has to do. Pass one or the other.
        """
        video = RemoteVideo(
            video_id=video_id,
            title=title,
            privacy=privacy,
            idempotency_key=idempotency_key,
            metadata={"description": description} if description else {},
        )
        self.remote.append(video)
        return video

    @property
    def insert_count(self) -> int:
        """How many times ``insert`` was entered. The duplicate-upload assertion."""
        return len(self.inserts)

    # -- the protocol -----------------------------------------------------------------------
    def insert(self, request: InsertRequest) -> InsertResult:
        outcome = self.script.pop(0) if self.script else "inserted"
        self.inserts.append(InsertCall(request=request, outcome=outcome))
        if outcome == "refused":
            code, detail = getattr(self, "_refusal", ("no_credential", "refused before send"))
            raise TransportRefused(code, detail)
        if outcome == "uncertain":
            code, detail = getattr(self, "_uncertainty", ("provider_timeout", "timeout after send"))
            raise TransportUncertain(code, detail)
        video_id = f"stub-{len(self.inserts):04d}"
        # The remote object records the key two ways, so both matching paths are exercised:
        # the explicit field (a transport with custom metadata) and the description marker (a
        # transport without one). Reconciliation reads the field first, then the marker.
        self.remote.append(
            RemoteVideo(
                video_id=video_id,
                title=request.title,
                privacy=request.privacy,
                idempotency_key=request.idempotency_key,
                metadata={"description": f"{request.description} {key_marker(request.idempotency_key)}".strip()},
            )
        )
        return InsertResult(video_id=video_id, detail="inserted by stub")

    def list_private(self) -> list[RemoteVideo]:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return list(self.remote)

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> ThumbnailResult:
        self.thumbnail_calls.append(ThumbnailCall(video_id=video_id, thumbnail_path=thumbnail_path))
        return ThumbnailResult(
            url=f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
            detail="thumbnail set by stub",
        )
