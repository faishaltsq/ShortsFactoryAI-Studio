"""The publication transport boundary: two operations, and a three-way outcome.

The operations are the minimum that makes idempotent publishing possible:

* ``insert`` — create a private video, returning either an id or a *maybe*.
* ``list_private`` — read what actually exists, which is the only way to resolve a *maybe*.

``list_private`` is not a convenience. Without it, ``uncertain`` could only be resolved by an
operator looking at a web UI, and the reconciliation rule in FR-8.3 could not be implemented at all.

**The outcome is three-way, not two.** A boolean forces a timeout-after-send to be reported as a
failure, and a failure is retried, and a retry is the duplicate. So:

``InsertResult``   the request left and succeeded; the id is known.
``TransportRefused`` the request provably did not leave (no credential, rejected before send).
``TransportUncertain`` the request may have left and the outcome is unknown (timeout after send,
    connection reset mid-flight, a 5xx with no body).

Only ``TransportRefused`` is retryable. The distinction is the entire feature: the code that raises
these is responsible for knowing whether the bytes went out, and the transport is the only place
that knowledge exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class InsertRequest:
    """What to upload. No vendor field names: a transport adapts this to its own API."""

    idempotency_key: str
    video_path: str
    title: str
    description: str = ""
    tags: tuple[str, ...] = ()
    privacy: str = "private"
    #: Bytes of the file, recorded in the ``insert_sent`` receipt so a reconciliation can match
    #: a remote object even when the remote API exposes no key.
    byte_size: int = 0
    #: Content digest of the file. The remote side does not see this; it is what ties a remote
    #: object back to local bytes if a transport can read a checksum back.
    content_sha256: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def sent_payload(self) -> dict[str, Any]:
        """What is recorded in the ``insert_sent`` receipt.

        Deliberately a summary, not the file: a receipt must be actionable and bounded. It names
        everything needed to recognise this upload on the remote side and nothing that would make
        an artifact grow with the video.
        """
        return {
            "idempotency_key": self.idempotency_key,
            "title": self.title,
            "privacy": self.privacy,
            "bytes": self.byte_size,
            "sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class InsertResult:
    """The request left and succeeded. ``video_id`` is the remote identifier."""

    video_id: str
    detail: str = ""


@dataclass(frozen=True)
class RemoteVideo:
    """One existing remote object, as much as the transport can see."""

    video_id: str
    title: str = ""
    privacy: str = "private"
    #: The remote's own marker, when it exposes one. A transport that cannot store a custom key
    #: returns ``""`` and reconciliation falls back to title + privacy matching.
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TransportRefused(RuntimeError):
    """The request provably did not leave. Safe to retry.

    Raised for a pre-flight refusal: no credential, an expired token, a rejected file, a
    validation error answered before the body was sent. The transport asserts this, so it must
    only be raised when that is actually known.
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class TransportUncertain(RuntimeError):
    """The request may have left. **Never** retryable; reconcile instead.

    Raised for a timeout after send, a connection reset mid-flight, or any response that cannot
    prove the create did not happen. Carrying ``detail`` is not enough to decide, so the caller
    must record the attempt and stop.
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@runtime_checkable
class PublicationTransport(Protocol):
    """Two operations. A transport that needs a third does not belong behind this boundary yet."""

    name: str

    def insert(self, request: InsertRequest) -> InsertResult: ...

    def list_private(self) -> list[RemoteVideo]: ...


#: The receipt step name that marks "a request may have left". The contract validator looks for
#: this exact value, so it lives here as the single definition.
INSERT_SENT_STEP = "insert_sent"


def sent_receipt(request: InsertRequest, *, at: str, detail: str = "") -> dict[str, Any]:
    """Build the ``insert_sent`` receipt an uncertain record must carry."""
    return {
        "step": INSERT_SENT_STEP,
        "at": at,
        "sent": request.sent_payload(),
        "ok": False,
        "detail": detail,
    }
