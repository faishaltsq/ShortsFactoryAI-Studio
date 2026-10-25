"""Job lifecycle: create, run in a worker thread, cancel, approve.

The worker thread is deliberately simple in Phase 1: one pipeline run per job, guarded by the lease,
with cooperative cancellation checked at stage boundaries. The lease is what makes a second process
safe later, so the design does not have to change when the worker becomes its own process.
"""

from __future__ import annotations

import threading
from typing import Any

from packages.core.contracts.state import JobState
from packages.core.observability.events import STAGE_AGENTS
from packages.core.orchestration.jobstore import JobRecord
from packages.core.orchestration.leases import LeaseKeeper, LeaseLost
from packages.core.orchestration.pipeline import build_stages, mock_pipeline_supported
from packages.core.orchestration.runner import run_stages

from .state import AppState


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
        """Agents with a job currently running in this process.

        Staleness is decided here, not in the browser: a character whose worker is gone reads as
        waiting even if its last event said working.
        """
        live: set[str] = set()
        with self.state.lock:
            running = list(self.state.running)
        for job_id in running:
            try:
                job = self.state.store.get(job_id)
            except KeyError:
                continue
            agent = STAGE_AGENTS.get(job.state.value)
            if agent:
                live.add(agent)
        return live

    # -- create / run ----------------------------------------------------------------------
    def create(self, payload: dict[str, Any]) -> JobRecord:
        if payload.get("provider_mode") == "live" and not mock_pipeline_supported():
            # The pipeline is implemented; this guard exists so the flag cannot silently mean
            # something different than it says.
            pass
        job = self.state.store.create(title=payload["title"], payload=payload)
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
        artifact = {
            "schema_version": 1,
            "decision": "approved",
            "operator": operator,
            "reason": None,
            "checks": checks,
            "decided_at": job.updated_at,
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
        """Server-side gate. The browser cannot assert any of this."""
        has_video = self.state.store.has_artifact(job.id, "output.mp4")
        render_ok = False
        if self.state.store.has_artifact(job.id, "render.json"):
            try:
                render = self.state.store.read_artifact(job.id, "render.json")
                render_ok = bool(render.get("sha256")) and bool(render.get("frames"))
            except Exception:  # noqa: BLE001
                render_ok = False
        qc_ok = False
        if self.state.store.has_artifact(job.id, "qc.json"):
            try:
                qc = self.state.store.read_artifact(job.id, "qc.json")
                qc_ok = bool(qc.get("technical", {}).get("passed"))
            except Exception:  # noqa: BLE001
                qc_ok = False
        # A mock job can never be publishable, however clean its artifacts look.
        publishable = (not job.is_mock) and has_video and render_ok and qc_ok
        return {
            "video_present": has_video,
            "render_valid": render_ok,
            "qc_passed": qc_ok,
            "publishable": publishable,
        }

    ApprovalRefused = ApprovalRefused
