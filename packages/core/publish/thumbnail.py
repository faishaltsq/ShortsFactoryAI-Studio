"""The thumbnail stage: render ``thumb.png`` and record its digest in ``metadata.json``.

Why this is a stage and not a side effect of the publish stage: the thumbnail is a *rendered
artifact*, and the rule that a stage may only report ``completed`` once its artifact exists and
validates applies to it exactly as it does to the video. Publishing then reads the recorded digest
instead of re-rendering something at upload time.

The stage renders the ``Thumbnail`` composition from the same ``render-props.json`` the video used,
so the thumbnail and the video cannot disagree about the storyboard. It writes the digest into
``MetadataArtifact.thumbnail`` — the field existed since Phase 1 and nothing ever filled it.

Deliberately not wired into ``build_stages``: the thumbnail belongs to the publish flow (it is
uploaded with the video), and the publish stage runs outside the ``IDEA_DISCOVERY`` chain. The
wiring point is ``JobService.publish`` (``apps/api/jobs.py``), which appends this stage before the
publish stage in the same ``run_stages`` call; the stage therefore declares ``PRIVATE_UPLOAD``,
the only legal forward edge from ``APPROVED``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..contracts.artifacts import MetadataArtifact
from ..contracts.base import validate_artifact
from ..contracts.state import JobState
from ..media.qc import sha256_file
from ..media.render import render_storyboard
from ..orchestration.jobstore import JobStore
from ..orchestration.runner import Stage, StageError, StageOutcome

THUMB_NAME = "thumb.png"
METADATA_NAME = "metadata.json"
PROPS_NAME = "render-props.json"
#: The Remotion composition registered in ``packages/video/src/Root.tsx``.
THUMBNAIL_COMPOSITION = "Thumbnail"


def build_thumbnail_stage(state: Any, *, video_dir: Path, token: str | None = None) -> Stage:
    store = state.store

    def run(_store: JobStore, job_id: str) -> StageOutcome:
        from ..orchestration.pipeline import _emit

        _emit(state, job_id, "STORYBOARD_READY", "stage_started", "thumbnail mulai",
              agent="MetadataAgent")

        props = Path(store.job_dir(job_id)) / PROPS_NAME
        if not props.is_file():
            raise StageError(
                "render_missing",
                f"{PROPS_NAME} does not exist, so there is nothing to render a thumbnail from",
                retryable=False,
            )

        metadata_payload = store.read_artifact(job_id, METADATA_NAME)
        metadata = validate_artifact(MetadataArtifact, metadata_payload)

        out = Path(store.job_dir(job_id)) / THUMB_NAME
        tmp = out.with_name(f".{THUMB_NAME}.tmp.png")
        try:
            render_storyboard(
                video_dir=Path(video_dir),
                props_path=props,
                out_path=tmp,
                composition=THUMBNAIL_COMPOSITION,
            )
        except Exception as exc:  # noqa: BLE001 - any render failure is a stage failure
            tmp.unlink(missing_ok=True)
            raise StageError(
                "thumbnail_failed", f"{type(exc).__name__}: {exc}", retryable=True
            ) from exc

        if not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            raise StageError(
                "thumbnail_failed", "the renderer produced no thumbnail file", retryable=True
            )
        digest = sha256_file(tmp)
        updated = metadata.model_copy(
            update={"thumbnail": {"path": THUMB_NAME, "sha256": digest, "bytes": tmp.stat().st_size}}
        )
        if token is None:
            # No lease token in play (unit-level use): promote directly, as before.
            os.replace(tmp, out)
            store.write_artifact(job_id, METADATA_NAME, updated.to_json())
        else:
            # The png and the metadata naming it must land together or not at all, and only
            # while this worker still owns the job: commit_stage checks the lease, promotes
            # both files, and advances APPROVED -> PRIVATE_UPLOAD in one guarded step.
            store.commit_stage(
                job_id,
                token=token,
                json_artifacts=[(METADATA_NAME, updated.to_json())],
                files=[(THUMB_NAME, tmp)],
                target=JobState.PRIVATE_UPLOAD,
                detail="ThumbnailAgent completed",
            )

        _emit(
            state, job_id, "STORYBOARD_READY", "stage_completed",
            "thumbnail selesai", agent="MetadataAgent", progress=1.0,
        )
        return StageOutcome(ok=True, artifacts=[THUMB_NAME, METADATA_NAME], detail=digest)

    return Stage(
        name="ThumbnailAgent",
        state=_thumbnail_state(),
        produces=(THUMB_NAME, METADATA_NAME),
        run=run,
        contract=MetadataArtifact,
        contract_artifact=METADATA_NAME,
        # The stage is done only when the digest it recorded matches the file on disk: a
        # ``metadata.json`` whose thumbnail entry predates a re-render must not count as done.
        done_when=lambda payload, job_id: _thumbnail_is_current(store, job_id, payload),
    )


def _thumbnail_is_current(store: JobStore, job_id: str, payload: dict[str, Any]) -> bool:
    thumb = payload.get("thumbnail") or {}
    recorded = str(thumb.get("sha256") or "")
    path = Path(store.job_dir(job_id)) / str(thumb.get("path") or THUMB_NAME)
    if not recorded or not path.is_file():
        return False
    return sha256_file(path) == recorded


def _thumbnail_state() -> JobState:
    """The stage's declared state: ``APPROVED -> PRIVATE_UPLOAD`` is the only legal forward edge
    here, and the thumbnail is part of exactly that move — the publish flow's own transition.
    Declaring ``STORYBOARD_READY`` (the pre-wiring value) made the chain validator refuse any
    publish, correctly."""
    return JobState.PRIVATE_UPLOAD
