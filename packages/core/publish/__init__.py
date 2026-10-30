"""Publication: the boundary between "a render exists" and "a video exists on a channel".

This package deliberately contains **no network client**. It defines the vocabulary a transport
must speak (:mod:`packages.core.publish.transport`), the stage that drives one
(:mod:`packages.core.publish.stage`), and reconciliation for the case where the outcome is unknown
(:mod:`packages.core.publish.reconcile`).

The rule the whole package exists to enforce is FR-8.3: publishing is idempotent. An outcome that
may or may not have happened blocks every retry until an operator reconciles, because a blind retry
after a timeout that succeeded creates a duplicate upload — a side effect no local transaction can
undo.

Why the transport is a Protocol here and not an implementation: ``core`` may not depend on a
vendor SDK, and the interesting logic (key derivation, uncertain-vs-retryable classification,
reconciliation) is testable without one. A concrete transport is a later, separate addition.
"""

from __future__ import annotations

from .reconcile import key_from_description, key_marker, reconcile_uncertain
from .stage import PUBLICATION_NAME, build_publish_stage, derive_idempotency_key
from .thumbnail import THUMB_NAME, build_thumbnail_stage
from .transport import (
    INSERT_SENT_STEP,
    InsertRequest,
    InsertResult,
    PublicationTransport,
    RemoteVideo,
    ThumbnailResult,
    ThumbnailTransport,
    TransportRefused,
    TransportUncertain,
    sent_receipt,
)

__all__ = [
    "INSERT_SENT_STEP",
    "PUBLICATION_NAME",
    "THUMB_NAME",
    "InsertRequest",
    "InsertResult",
    "PublicationTransport",
    "ThumbnailResult",
    "ThumbnailTransport",
    "key_from_description",
    "key_marker",
    "RemoteVideo",
    "TransportRefused",
    "TransportUncertain",
    "build_publish_stage",
    "build_thumbnail_stage",
    "derive_idempotency_key",
    "reconcile_uncertain",
    "sent_receipt",
]
