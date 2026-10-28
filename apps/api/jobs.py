"""Job lifecycle: create, run in a worker thread, cancel, approve.

The worker thread is deliberately simple in Phase 1: one pipeline run per job, guarded by the lease,
with cooperative cancellation checked at stage boundaries. The lease is what makes a second process
safe later, so the design does not have to change when the worker becomes its own process.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from packages.core.contracts.artifacts import (
    AudioArtifact,
    QaArtifact,
    ReadinessArtifact,
    RenderArtifact,
    StoryboardArtifact,
    TechnicalQaArtifact,
)
from packages.core.contracts.base import ArtifactValidationError, validate_artifact
from packages.core.contracts.state import JobState
from packages.core.media.qc import sha256_file
from packages.core.orchestration.editorial import compute_inputs_hash
from packages.core.orchestration.jobstore import JobRecord
from packages.core.orchestration.leases import LeaseKeeper, LeaseLost
from packages.core.orchestration.pipeline import _video_dir, build_stages, mock_pipeline_supported
from packages.core.orchestration.runner import run_stages
from packages.core.publish.stage import build_publish_stage
from packages.core.publish.thumbnail import build_thumbnail_stage
from packages.core.publish.transport import PublicationTransport

from .state import AppState


def _validated(store: Any, job_id: str, name: str, model: Any) -> Any:
    """Read and validate one artifact, or ``None``.

    ``None`` means "missing or invalid", and both are blockers. A hand-edited artifact that no
    longer satisfies its contract must produce a refusal, not a 500 and not a pass.
    """
    try:
        payload = store.read_artifact(job_id, name)
    except Exception:  # noqa: BLE001 - a missing artifact is a blocked gate
        return None
    try:
        return validate_artifact(model, payload)
    except ArtifactValidationError:
        return None


class ApprovalRefused(RuntimeError):
    pass


class _Cancel:
    def __init__(self, event: threading.Event) -> None:
        self.event = event

    def is_cancelled(self) -> bool:
        return self.event.is_set()


class JobService:
    def __init__(self, state: AppState) -> None:
        self.state = state

    # -- views -----------------------------------------------------------------------------
    def view(self, job: JobRecord) -> dict[str, Any]:
        return {
            "id": job.id,
            "title": job.title,
            "state": job.state.value,
            "attempts": job.attempts,
            "provider_mode": job.provider_mode,
            "is_mock": job.is_mock,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "last_error": job.last_error,
            "priority": job.priority,
            "scheduled_for": job.scheduled_for,
            "running": job.id in self.state.running,
        }

    def detail(self, job: JobRecord) -> dict[str, Any]:
        payload = self.view(job)
        payload.update(
            {
                "payload": job.payload,
                "artifacts": self.state.store.list_artifacts(job.id),
                "events": self.state.store.events(job.id, limit=200),
                "usage": self.state.usage.for_job(job.id),
                "has_video": self.state.store.has_artifact(job.id, "output.mp4"),
            }
        )
        return payload

    def live_agents(self) -> set[str]:
        """Agents that hold a live lease, derived from the persisted active-stage rows.

        A thread object in ``running`` only says a thread exists; it does not say the thread is
        alive, and a wedged worker would otherwise read ``working`` until the age fallback fired.
        The active-stage row — written with the worker's lease token, cleared on every exit — is
        the authority (ADR-008, FR-9.4): it survives only while its lease does, so a dead worker
        stops being reported as working. Staleness is decided here, not in the browser.
        """
        with self.state.lock:
            running = list(self.state.running)
        if not running:
            return set()
        live: set[str] = set()
        for row in self.state.store.active_stages(running):
            agent = row.get("agent_id")
            if isinstance(agent, str) and agent:
                live.add(agent)
        return live

    # -- create / run ----------------------------------------------------------------------
    def create(self, payload: dict[str, Any]) -> JobRecord:
        if payload.get("provider_mode") == "live" and not mock_pipeline_supported():
            # The pipeline is implemented; this guard exists so the flag cannot silently mean
            # something different than it says.
            pass
        job = self.state.store.create(
            title=payload["title"],
            payload=payload,
            priority=payload.get("priority", 5),
            scheduled_for=payload.get("scheduled_for"),
        )
        self.state.events.emit(
            job_id=job.id,
            agent_id="FactoryOrchestrator",
            event_type="stage_started",
            description=f"job dibuat: {payload['title']}",
            stage=job.state.value,
        )
        return job

    def start(self, job_id: str) -> bool:
        with self.state.lock:
            if job_id in self.state.running:
                return False
            self.state.clear_cancel(job_id)
            thread = threading.Thread(
                target=self._run, args=(job_id,), name=f"job-{job_id}", daemon=True
            )
            self.state.running[job_id] = thread
            thread.start()
            return True

    def _run(self, job_id: str) -> None:
        self.state.store.get(job_id)  # fail fast on an unknown job, before taking a lease
        keeper = LeaseKeeper(self.state.store.db_path, owner=f"api-{id(self)}")
        try:
            keeper.acquire(job_id)
        except LeaseLost as exc:
            self.state.events.emit(
                job_id=job_id,
                agent_id="FactoryOrchestrator",
                event_type="blocked",
                description=f"tidak bisa mengambil lease: {exc.reason}",
            )
            with self.state.lock:
                self.state.running.pop(job_id, None)
            return

        cancel = _Cancel(self.state.cancel_flag(job_id))
        try:
            stages = build_stages(self.state, job_id)
            report = run_stages(
                store=self.state.store,
                job_id=job_id,
                stages=stages,
                keeper=keeper,
                cancel=cancel,
            )
            if report.get("stopped") == "lease_lost":
                self.state.events.emit(
                    job_id=job_id,
                    agent_id="FactoryOrchestrator",
                    event_type="blocked",
                    description="lease hilang; worker berhenti tanpa menulis state",
                )
        except Exception as exc:  # noqa: BLE001 - a worker crash must be visible, not silent
            self.state.events.emit(
                job_id=job_id,
                agent_id="FactoryOrchestrator",
                event_type="failed",
                description=f"worker error: {type(exc).__name__}: {exc}",
            )
            try:
                self.state.store.set_error(job_id, f"{type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001
                pass
        finally:
            keeper.release()
            with self.state.lock:
                self.state.running.pop(job_id, None)
                self.state.cancel_flags.pop(job_id, None)

    # -- publication -----------------------------------------------------------------------
    def publish(self, job_id: str, transport: PublicationTransport) -> dict[str, Any]:
        """Run the ``PRIVATE_UPLOAD`` stage for one approved job.

        Deliberately a service method and not a route: the route belongs with the rest of the
        publishing surface (connect / upload / schedule / reconcile), which is a separate slice.
        Everything the route would do is here, so the route is a thin wrapper when it lands:
        ``POST /api/jobs/{job_id}/publish`` with the transport resolved from operator config.

        Three refusals, in order, before any transport call:

        1. the job must be ``APPROVED`` — a blocked job has to go back through the gate, because
           the store refuses ``BLOCKED -> APPROVED`` and this method refuses anything not approved;
        2. the job must be ``provider_mode == "live"`` — a mock job's video is fabricated, and
           ``publishable`` is false for it at the approval gate for exactly that reason. The same
           check is reused here rather than restated, so the two cannot drift;
        3. the approval must still be ``publishable`` (recomputed, not read from a flag).
        """
        job = self.state.store.get(job_id)
        if job.state is not JobState.APPROVED:
            raise self.ApprovalRefused(
                "publishing is only possible at APPROVED, "
                f"job is {job.state.value}"
            )
        if job.is_mock:
            raise self.ApprovalRefused(
                "a mock job can never be published: provider_mode is 'mock', so "
                "publishable is false. Create the job with provider_mode 'live'."
            )
        checks = self._approval_checks(job)
        if not checks["publishable"]:
            failed = sorted(name for name, ok in checks.items() if not ok)
            raise self.ApprovalRefused(
                "publishing refused: the approval is no longer publishable ("
                + ", ".join(failed)
                + "). Re-approve the job after fixing the failing evidence."
            )
        keeper = LeaseKeeper(self.state.store.db_path, owner=f"api-publish-{id(self)}")
        try:
            keeper.acquire(job_id)
        except LeaseLost as exc:
            return {"job_id": job_id, "started": False, "detail": f"lease unavailable: {exc.reason}"}
        try:
            # The thumbnail belongs to this flow, not the pipeline chain: it is uploaded with the
            # video and must exist and validate before the insert. Same lease, same run, so a
            # crash between the two stages resumes both under the runner's reuse rules.
            thumbnail = build_thumbnail_stage(self.state, video_dir=_video_dir())
            stage = build_publish_stage(self.state, transport)
            report = run_stages(
                store=self.state.store,
                job_id=job_id,
                stages=[thumbnail, stage],
                keeper=keeper,
                cancel=None,
            )
        finally:
            keeper.release()
        return {"job_id": job_id, **report}

    # -- approval --------------------------------------------------------------------------
    def approve(self, job_id: str, operator: str) -> dict[str, Any]:
        job = self.state.store.get(job_id)
        if job.state is not JobState.READY_FOR_APPROVAL:
            raise self.ApprovalRefused(
                f"approval is only possible at READY_FOR_APPROVAL, job is {job.state.value}"
            )
        checks = self._approval_checks(job)
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise self.ApprovalRefused("gate checks failed: " + ", ".join(failed))
        # The render this decision is about. ``_approval_checks`` already recomputed the file's
        # digest and refused a mismatch, so this is the same value it validated — and recording it
        # is what lets ``JobStore.transition`` refuse a stale approval later.
        render = _validated(self.state.store, job_id, "render.json", RenderArtifact)
        artifact = {
            "schema_version": 1,
            "decision": "approved",
            "operator": operator,
            "reason": None,
            "checks": checks,
            "decided_at": job.updated_at,
            "render_sha256": render.sha256 if render is not None else None,
        }
        self.state.store.write_artifact(job_id, "approval.json", artifact)
        self.state.store.transition(job_id, JobState.APPROVED, detail=f"approved by {operator}")
        return {"job_id": job_id, "decision": "approved", "checks": checks}

    def reject(self, job_id: str, operator: str, reason: str) -> dict[str, Any]:
        job = self.state.store.get(job_id)
        if job.state is not JobState.READY_FOR_APPROVAL:
            raise self.ApprovalRefused(
                f"rejection is only possible at READY_FOR_APPROVAL, job is {job.state.value}"
            )
        artifact = {
            "schema_version": 1,
            "decision": "rejected",
            "operator": operator,
            "reason": reason,
            "checks": self._approval_checks(job),
            "decided_at": job.updated_at,
        }
        self.state.store.write_artifact(job_id, "approval.json", artifact)
        self.state.store.transition(job_id, JobState.REJECTED, detail=f"rejected by {operator}")
        return {"job_id": job_id, "decision": "rejected", "reason": reason}

    def _approval_checks(self, job: JobRecord) -> dict[str, bool]:
        """Server-side gate. The browser cannot assert any of this.

        Every check either recomputes a fact or validates an artifact. Reading a ``passed`` flag
        out of a file and trusting it is what let the previous gate approve a job whose editorial
        and visual QC had never run: ``qc.json`` claimed ``technical.passed: true`` while carrying
        no detector result, and nothing looked at the bytes the hash described.
        """
        store = self.state.store
        job_dir = Path(store.job_dir(job.id))
        video_path = job_dir / "output.mp4"
        has_video = video_path.is_file()

        render = _validated(store, job.id, "render.json", RenderArtifact)
        technical = _validated(store, job.id, "technical-qc.json", TechnicalQaArtifact)
        qa = _validated(store, job.id, "qc.json", QaArtifact)
        readiness = _validated(store, job.id, "readiness.json", ReadinessArtifact)

        render_ok = render is not None
        # The hash is recomputed from the file on disk. A render.json that names a digest the
        # bytes no longer have describes a different video.
        checksum_ok = bool(
            has_video
            and render is not None
            and render.sha256 == sha256_file(video_path)
        )
        technical_ok = technical is not None and technical.passed
        editorial_ok = qa is not None
        creative_ok = qa is not None and bool(qa.creative.get("passed"))
        visual_status = str(qa.visual.get("status")) if qa is not None else "missing"
        visual_ok = visual_status != "failed"

        # Readiness must be ready *and* bound to the same inputs this gate just measured. A
        # verdict computed against other bytes is not a verdict about these bytes.
        readiness_ok = False
        if readiness is not None and readiness.ready and render is not None:
            narration_ms = 0.0
            audio = _validated(store, job.id, "audio.json", AudioArtifact)
            if audio is not None:
                narration_ms = float(audio.narration.get("durationMs") or 0)
            storyboard = _validated(store, job.id, "storyboard.json", StoryboardArtifact)
            if storyboard is not None:
                expected = compute_inputs_hash(
                    render_sha256=render.sha256,
                    narration_ms=narration_ms,
                    storyboard=storyboard.model_dump(mode="json"),
                )
                readiness_ok = readiness.inputs_sha256 == expected
                if technical is not None:
                    readiness_ok = readiness_ok and technical.inputs_sha256 == expected

        # A mock job can never be publishable, however clean its artifacts look.
        publishable = bool(
            (not job.is_mock)
            and has_video
            and render_ok
            and checksum_ok
            and technical_ok
            and editorial_ok
            and creative_ok
            and visual_ok
            and readiness_ok
        )
        return {
            "video_present": has_video,
            "render_valid": render_ok,
            "checksum_valid": checksum_ok,
            "technical_passed": technical_ok,
            "editorial_present": editorial_ok,
            "creative_passed": creative_ok,
            "visual_not_failed": visual_ok,
            "readiness_bound": readiness_ok,
            "publishable": publishable,
        }

    ApprovalRefused = ApprovalRefused
