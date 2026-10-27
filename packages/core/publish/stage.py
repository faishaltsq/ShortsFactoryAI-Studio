"""The publish stage: ``APPROVED -> PRIVATE_UPLOAD``, idempotently.

Three rules, and the third is the one that is easy to get wrong:

1. **The key is derived, never minted.** ``derive_idempotency_key(job_id, render_sha256)`` is a
   pure function of the job and the bytes. Re-running the stage cannot produce a different key,
   so "the same video" is a property of the data rather than of a variable that survived in
   memory.

2. **A confirmed publication is never re-inserted.** If ``publication.json`` for this key is
   already ``confirmed``, the stage reports reuse and returns without touching the transport.

3. **An uncertain publication blocks.** It does not retry, and it does not insert. It raises a
   non-retryable ``publication_uncertain`` naming reconciliation, because the only safe next step
   is to find out what actually happened.

The pre-flight/uncertain split is delegated to the transport, which is the only code that knows
whether the bytes went out. A ``TransportRefused`` is retryable and writes nothing; a
``TransportUncertain`` writes the uncertain record and is not retryable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

from ..contracts.artifacts import PublicationArtifact, RenderArtifact
from ..contracts.base import validate_artifact
from ..contracts.state import JobState
from ..orchestration.jobstore import ArtifactNotFound, JobStore
from ..orchestration.runner import Stage, StageContext, StageError, StageOutcome
from .transport import (
    InsertRequest,
    PublicationTransport,
    TransportRefused,
    TransportUncertain,
    sent_receipt,
)

PUBLICATION_NAME = "publication.json"
RENDER_NAME = "render.json"

#: How long a derived key is. 32 hex chars of sha256 is 128 bits: a collision is not a concern,
#: and the value is short enough to store as a remote title suffix if a transport must.
KEY_LENGTH = 32


def derive_idempotency_key(job_id: str, render_sha256: str) -> str:
    """A stable key for (job, bytes). Pure, so a restart cannot change it.

    Both inputs matter: the same bytes in two different jobs are two different uploads, and the
    same job rendered twice is one video whose bytes changed — which is a new upload, and must be
    a new key so a stale confirmation cannot be reused.
    """
    if not job_id.strip():
        raise ValueError("idempotency key needs a job id")
    if not render_sha256.strip():
        raise ValueError("idempotency key needs a render sha256; without it the key cannot bind to bytes")
    material = f"{job_id}\x00{render_sha256}".encode()
    return hashlib.sha256(material).hexdigest()[:KEY_LENGTH]


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _read_publication(store: JobStore, job_id: str) -> PublicationArtifact | None:
    """Read and validate the existing publication, or ``None``.

    An artifact that fails validation is treated as absent **for the purpose of deciding whether
    to insert** — which is safe only because the insert path then writes a fresh record. It is not
    treated as confirmed, so it can never authorise skipping an upload.
    """
    try:
        payload = store.read_artifact(job_id, PUBLICATION_NAME)
    except ArtifactNotFound:
        return None
    try:
        return validate_artifact(PublicationArtifact, payload)  # type: ignore[return-value]
    except Exception:  # noqa: BLE001 - an unreadable record is not evidence of an upload
        return None


def _render_sha256(store: JobStore, job_id: str) -> str:
    try:
        payload = store.read_artifact(job_id, RENDER_NAME)
    except ArtifactNotFound as exc:
        raise StageError(
            "render_missing",
            f"{RENDER_NAME} does not exist, so there is nothing to publish",
            retryable=False,
        ) from exc
    render = validate_artifact(RenderArtifact, payload)
    digest = getattr(render, "sha256", "")
    if not digest:
        raise StageError("render_missing", f"{RENDER_NAME} records no sha256", retryable=False)
    return str(digest)


def _title(store: JobStore, job_id: str) -> tuple[str, str]:
    """The title and description to publish, from ``metadata.json`` when it exists.

    Falls back to the job title rather than inventing marketing copy: a missing metadata stage is
    a missing input, not a licence to generate text at publish time.
    """
    try:
        metadata = store.read_artifact(job_id, "metadata.json")
    except ArtifactNotFound:
        metadata = {}
    title = str(metadata.get("title") or store.get(job_id).title or job_id)[:100]
    return title, str(metadata.get("description") or "")


def build_publish_stage(state: Any, transport: PublicationTransport) -> Stage:
    """The ``PRIVATE_UPLOAD`` stage.

    ``transport`` is injected rather than resolved from configuration: the stage must be provable
    with a stub, and there is no live transport in this build. A later wiring point resolves one
    from operator configuration and passes it here unchanged.
    """
    store = state.store

    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        from ..orchestration.pipeline import _emit  # local import: pipeline imports runner

        _emit(state, job_id, "PRIVATE_UPLOAD", "stage_started", "PublisherAgent mulai",
              agent="PublisherAgent")

        digest = _render_sha256(store, job_id)
        key = derive_idempotency_key(job_id, digest)
        existing = _read_publication(store, job_id)

        if existing is not None and existing.idempotency_key != key:
            # A record for different bytes. It cannot authorise this upload, and it must not be
            # overwritten silently either: an operator needs to know a different render was
            # published for this job.
            raise StageError(
                "publication_key_mismatch",
                f"{PUBLICATION_NAME} was written for idempotency key {existing.idempotency_key} "
                f"but the current render derives {key}; reconcile the previous record before "
                "publishing this render",
                retryable=False,
            )

        if existing is not None and existing.phase == "confirmed":
            _emit(
                state,
                job_id,
                "PRIVATE_UPLOAD",
                "artifact_reused",
                f"already published as {existing.video_id}; not uploading again",
                agent="PublisherAgent",
                progress=1.0,
            )
            return StageOutcome(
                ok=True,
                reused=True,
                artifacts=[PUBLICATION_NAME],
                detail=f"confirmed publication reused (video_id={existing.video_id})",
            )

        if existing is not None and existing.phase == "uncertain":
            message = (
                "publication is uncertain: an earlier insert may have created a video "
                f"(attempt {existing.attempt}). Retrying would risk a duplicate. "
                "Reconcile before publishing again: list the channel's private uploads and match "
                f"idempotency key {key}."
            )
            _emit(state, job_id, "PRIVATE_UPLOAD", "blocked", message, agent="PublisherAgent")
            raise StageError("publication_uncertain", message, retryable=False)

        video_path = Path(store.job_dir(job_id)) / "output.mp4"
        if not video_path.is_file():
            raise StageError(
                "render_missing",
                "output.mp4 does not exist, so there is nothing to publish",
                retryable=False,
            )
        title, description = _title(store, job_id)
        request = InsertRequest(
            idempotency_key=key,
            video_path=str(video_path),
            title=title,
            description=description,
            privacy="private",
            byte_size=video_path.stat().st_size,
            content_sha256=digest,
        )
        attempt = (existing.attempt if existing is not None else 0) + 1

        try:
            result = transport.insert(request)
        except TransportRefused as exc:
            # Provably did not leave. Retryable, and nothing is written: an artifact claiming an
            # attempt that never happened would be a lie the operator would later reconcile.
            _emit(state, job_id, "PRIVATE_UPLOAD", "failed", exc.detail, agent="PublisherAgent")
            raise StageError(exc.code, exc.detail, retryable=True) from exc
        except TransportUncertain as exc:
            receipt = sent_receipt(request, at=_now(), detail=exc.detail)
            payload = PublicationArtifact(
                phase="uncertain",
                video_id=None,
                privacy="private",
                idempotency_key=key,
                attempt=attempt,
                receipts=[receipt],
            ).to_json()
            ctx.write_artifact(PUBLICATION_NAME, payload)
            message = (
                f"insert may have succeeded but the outcome is unknown ({exc.detail}). "
                "Recorded as uncertain; retrying would risk a duplicate upload. Reconcile by "
                f"matching idempotency key {key} against the channel's private uploads."
            )
            _emit(state, job_id, "PRIVATE_UPLOAD", "blocked", message, agent="PublisherAgent")
            raise StageError("publication_uncertain", message, retryable=False) from exc

        payload = PublicationArtifact(
            phase="confirmed",
            video_id=result.video_id,
            privacy="private",
            idempotency_key=key,
            attempt=attempt,
            receipts=[
                {
                    "step": "upload",
                    "at": _now(),
                    "sent": request.sent_payload(),
                    "ok": True,
                    "detail": result.detail or f"inserted as {result.video_id}",
                }
            ],
        ).to_json()
        ctx.write_artifact(PUBLICATION_NAME, payload)
        _emit(
            state,
            job_id,
            "PRIVATE_UPLOAD",
            "stage_completed",
            f"PublisherAgent selesai: private upload {result.video_id}",
            agent="PublisherAgent",
            progress=1.0,
        )
        return StageOutcome(
            ok=True,
            artifacts=[PUBLICATION_NAME],
            detail=f"uploaded as {result.video_id}",
        )

    return Stage(
        name="PublisherAgent",
        state=_private_upload_state(),
        produces=(PUBLICATION_NAME,),
        run=run,
        contract=PublicationArtifact,
        contract_artifact=PUBLICATION_NAME,
        # An ``uncertain`` publication is a *valid* artifact describing an unknown outcome. The
        # default runner rule ("valid artifact means done") would report it as reused/succeeded on
        # the next run, claiming an upload that may never have happened. Only a confirmed record
        # *for the current bytes* is a finished stage: a re-render changes the derived key, and a
        # confirmation for the old key must not be reported as done.
        done_when=lambda payload, job_id: (
            payload.get("phase") == "confirmed"
            and payload.get("idempotency_key") == _key_for(store, job_id)
        ),
    )


def _key_for(store: JobStore, job_id: str) -> str | None:
    """The idempotency key for the job's current bytes, or ``None`` when it cannot be derived."""
    try:
        return derive_idempotency_key(job_id, _render_sha256(store, job_id))
    except (StageError, ArtifactNotFound):
        return None


def _private_upload_state() -> JobState:
    return JobState.PRIVATE_UPLOAD
