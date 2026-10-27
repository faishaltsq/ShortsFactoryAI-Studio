"""Reconciliation: resolve ``uncertain`` by reading, never by writing to the remote.

The rule this implements is narrow on purpose. Reconciliation may:

* **confirm** — the video exists remotely, so adopt its id and record how it was found;
* **clear** — the video provably does not exist, so the record is reset to a state the operator
  can deliberately re-run.

It may **never** insert. A reconciler that uploads is just a retry with extra steps, and the whole
reason ``uncertain`` exists is that a retry is the duplicate.

Matching is by the idempotency key. Because a remote API may not expose a custom key field, the
key travels inside the payload the transport actually sends: :func:`key_marker` embeds it in the
description, and :func:`key_from_description` reads it back. When neither the explicit field nor
the marker is present, matching falls back to title + privacy, which can only narrow candidates —
an ambiguous result is reported as ``unresolved`` rather than guessed. A wrong match would be worse
than an unresolved one: it would confirm an upload that is not this job's video.

**The not-found branch clears the record, and that is a deliberate choice.** Two candidates:

``cleared``  (chosen) the listing succeeded and no match exists, so the earlier request almost
             certainly never landed. The record is reset to ``initiating`` with a
             ``reconciled_not_found`` receipt, and the operator decides whether to publish again.
``refuse``   keep the record ``uncertain`` forever. Safer against a duplicate, but it makes the
             job permanently un-publishable on a false positive — exactly the failure
             DATA_CONTRACTS §13 warns about ("otherwise the job becomes permanently
             un-uploadable").

Clearing is chosen because "no match" is *positive* evidence from a successful read, not an
absence of evidence. The residual risk is a remote listing that is incomplete or eventually
consistent, so the receipt records how many private videos were seen and the docstring says the
operator must confirm the listing looked complete. A clear never retries by itself: it changes a
record, and the next insert is a separate, deliberate call.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..contracts.artifacts import PublicationArtifact
from ..orchestration.jobstore import ArtifactNotFound, JobStore
from .transport import PublicationTransport, RemoteVideo

PUBLICATION_NAME = "publication.json"

#: Where the key is embedded in a payload a transport actually sends. Chosen so a real transport
#: with no custom-metadata field can still round-trip it: the description is the one free-text
#: field every video API exposes on read.
KEY_MARKER_PREFIX = "#sf-key:"


def key_marker(idempotency_key: str) -> str:
    """The marker a transport embeds in the description so the key can be read back."""
    return f"{KEY_MARKER_PREFIX}{idempotency_key}"


def key_from_description(description: str) -> str:
    """Extract the marker from a description, or ``""`` when it carries none."""
    if not description:
        return ""
    for token in str(description).split():
        if token.startswith(KEY_MARKER_PREFIX):
            return token[len(KEY_MARKER_PREFIX) :].strip()
    return ""


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _sent(publication: PublicationArtifact) -> dict[str, Any]:
    """The last ``insert_sent`` receipt, which is what reconciliation matches against."""
    for receipt in reversed(publication.receipts):
        if receipt.get("step") == "insert_sent":
            return receipt
    return {}


def _remote_key(remote: RemoteVideo) -> str:
    """The key a remote object carries: the explicit field first, then the description marker."""
    if remote.idempotency_key:
        return remote.idempotency_key
    return key_from_description(str(remote.metadata.get("description") or ""))


def _matches(remote: RemoteVideo, publication: PublicationArtifact) -> bool:
    """Exact key match when the remote carries one; otherwise title + privacy."""
    remote_key = _remote_key(remote)
    if remote_key:
        return remote_key == publication.idempotency_key
    sent = _sent(publication).get("sent") or {}
    title = str(sent.get("title") or "")
    privacy = str(sent.get("privacy") or "private")
    return bool(title) and remote.title == title and remote.privacy == privacy


def _load(store: JobStore, job_id: str) -> PublicationArtifact:
    try:
        payload = store.read_artifact(job_id, PUBLICATION_NAME)
    except ArtifactNotFound as exc:
        raise ValueError(
            f"no {PUBLICATION_NAME} for job {job_id}; there is nothing to reconcile"
        ) from exc
    return PublicationArtifact.model_validate(payload)


def reconcile_uncertain(
    store: JobStore,
    job_id: str,
    transport: PublicationTransport,
) -> PublicationArtifact:
    """Resolve an ``uncertain`` publication against the remote channel. Never inserts.

    Reads ``publication.json``, requires ``phase == "uncertain"``, lists the channel's private
    videos, and matches on the idempotency key (see the module docstring for the marker).

    * found exactly one → ``confirmed``, adopting the remote id, receipt ``reconciled_found``.
    * found none → ``initiating``, receipt ``reconciled_not_found``; the operator may publish
      again, and nothing is retried automatically.
    * more than one → the record is left ``uncertain`` and ``ValueError`` is raised: an ambiguous
      match must not be resolved by picking one.

    Raises ``ValueError`` for a ``confirmed`` or ``initiating`` record: a healthy record is not
    "fixed" by reconciling it, and silently rewriting one would erase the evidence that the
    upload happened.
    """
    publication = _load(store, job_id)

    if publication.phase == "confirmed":
        raise ValueError(
            f"publication for job {job_id} is already 'confirmed' (video_id="
            f"{publication.video_id}); there is nothing to reconcile"
        )
    if publication.phase != "uncertain":
        raise ValueError(
            f"publication for job {job_id} is {publication.phase!r}, not 'uncertain'; "
            "reconciliation only applies to an uncertain record"
        )

    remote = transport.list_private()
    candidates = [video for video in remote if _matches(video, publication)]
    at = _now()

    if len(candidates) == 1:
        video = candidates[0]
        found_via = "idempotency_key" if _remote_key(video) else "title+privacy"
        confirmed = PublicationArtifact(
            phase="confirmed",
            video_id=video.video_id,
            privacy=publication.privacy,
            publish_at=publication.publish_at,
            idempotency_key=publication.idempotency_key,
            attempt=publication.attempt,
            receipts=[
                *publication.receipts,
                {
                    "step": "reconciled_found",
                    "at": at,
                    "ok": True,
                    "detail": (
                        f"adopted existing video {video.video_id}; matched on {found_via}; "
                        "no insert performed"
                    ),
                },
            ],
        )
        store.write_artifact(job_id, PUBLICATION_NAME, confirmed.to_json())
        return confirmed

    if len(candidates) > 1:
        raise ValueError(
            f"{len(candidates)} remote videos match idempotency key "
            f"{publication.idempotency_key}; refusing to guess between "
            + ", ".join(video.video_id for video in candidates)
        )

    cleared = PublicationArtifact(
        phase="initiating",
        video_id=None,
        privacy=publication.privacy,
        publish_at=publication.publish_at,
        idempotency_key=publication.idempotency_key,
        attempt=publication.attempt,
        receipts=[
            *publication.receipts,
            {
                "step": "reconciled_not_found",
                "at": at,
                "ok": True,
                "detail": (
                    f"no private upload matched idempotency key "
                    f"{publication.idempotency_key} among {len(remote)} private video(s); "
                    "the earlier request created nothing, so the record is reset for a "
                    "deliberate retry"
                ),
            },
        ],
    )
    store.write_artifact(job_id, PUBLICATION_NAME, cleared.to_json())
    return cleared
