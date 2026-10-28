"""HTTP surface. Composition root only: every route delegates, none implements a rule.

Local-first, so the default is no auth token at all: the server binds loopback and the dashboard is
same-origin. When ``STUDIO_API_TOKEN`` is set, every mutating route requires it, because the moment
someone opens the port beyond loopback the difference matters.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from packages.core.contracts.state import JobState
from packages.core.observability.events import AGENT_IDS, snapshot
from packages.core.orchestration.jobstore import ArtifactNotFound
from packages.core.orchestration.scheduler import SCHEDULABLE_STATES
from packages.core.orchestration.scheduler import _utc_now as _scheduler_now
from packages.core.providers.base import (
    Capability,
)
from packages.core.providers.registry import ProviderSpec
from packages.core.security.netguard import BlockedTarget
from packages.core.security.redact import redact

from .config import ConfigError
from .jobs import JobService
from .schemas import (
    AgentBindingUpdate,
    ApproveBody,
    BindingsBody,
    CancelBody,
    CreateJobBody,
    DiscoverTopicsBody,
    MetadataBody,
    ProviderBody,
    PublishBody,
    ReconcileBody,
    RejectBody,
    RetryRequestBody,
    SettingsBody,
    TestProviderBody,
)
from .settings import Settings
from .state import AppState

#: States that must never be entered by a plain ``/run``. ``BLOCKED`` is absent: reopening
#: eligible blocked work is what an explicit rework/resume operation does (step 8), so drafts and
#: blocked jobs stay runnable while terminal/paused/gate/publication states need a decision.
_RUN_INELIGIBLE = frozenset(
    {
        JobState.CANCELLED,
        JobState.REJECTED,
        JobState.PUBLISHED,
        JobState.SCHEDULED,
        JobState.APPROVED,
        JobState.READY_FOR_APPROVAL,
        JobState.PRIVATE_UPLOAD,
        JobState.PAUSED,
    }
)

POLL_S = 0.5

#: States where a metadata edit is meaningful: the render exists and the operator is deciding.
#: Before ``READY_FOR_APPROVAL`` the metadata agent has not written its draft yet, so an edit would
#: be silently overwritten; after a terminal state there is nothing left to publish.
METADATA_EDITABLE_STATES = frozenset(
    {
        JobState.READY_FOR_APPROVAL,
        JobState.APPROVED,
        JobState.PRIVATE_UPLOAD,
        JobState.SCHEDULED,
        JobState.BLOCKED,
    }
)


def _recover_interrupted(app_state: AppState, service: JobService) -> list[str]:
    """Requeue jobs whose worker died mid-run.

    A job whose ``state`` is a running stage but whose lease expired has no live worker: the
    process that held it is gone, and the stage's artifacts are on disk. Such a job is re-Started
    through the same ``JobService.start`` an operator would use — the runner then reuses completed
    stages from their artifacts and repeats none of the paid work. This is the Phase 1 'crash
    recovery' requirement; without it a restart strands every in-flight job in a state nothing
    will ever advance.

    Only an *expired* lease qualifies. A job whose lease is still live has a worker somewhere, and
    stealing its work would duplicate it.
    """
    from packages.core.contracts.state import JobState
    from packages.core.orchestration.leases import unexpired_jobs

    running_states = [
        job
        for job in app_state.store.list(limit=500)
        if job.state
        in {
            JobState.IDEA_DISCOVERY,
            JobState.TOPIC_SELECTED,
            JobState.RESEARCH_COMPLETE,
            JobState.SCRIPT_GENERATED,
            JobState.CREATIVE_REVIEW,
            JobState.STORYBOARD_READY,
            JobState.ASSETS_READY,
            JobState.AUDIO_READY,
            JobState.RENDERING,
            JobState.TECHNICAL_QC,
            JobState.EDITORIAL_QC,
        }
    ]
    if not running_states:
        return []

    # Jobs whose lease expired AND that this process is not already running. The second check is
    # what makes recovery safe to call on a live app: it never touches a thread that exists.
    expired = unexpired_jobs.__wrapped__(app_state.store.db_path, [j.id for j in running_states]) \
        if hasattr(unexpired_jobs, "__wrapped__") else \
        _expired_only(app_state.store.db_path, [j.id for j in running_states])
    already = set(app_state.running)
    recover = [j.id for j in running_states if j.id in expired and j.id not in already]
    for job_id in recover:
        service.start(job_id)
    return recover


def _expired_only(db_path, job_ids):
    """``unexpired_jobs`` inverted: the job ids whose lease is missing or expired."""
    from datetime import datetime as dt

    from packages.core.orchestration.leases import read_leases

    leases = read_leases(db_path, job_ids)
    now = dt.now(UTC)
    held = {
        job_id
        for job_id in job_ids
        if job_id in leases
        and dt.fromisoformat(leases[job_id].expires_at) > now
    }
    return {j for j in job_ids if j not in held}


def create_app(state: AppState | None = None) -> FastAPI:
    settings = state.settings if state else Settings.from_env()
    app_state = state or AppState.build(settings)
    service = JobService(app_state)

    app = FastAPI(title="ShortsFactoryAI Studio", version="0.1.0")
    app.state.studio = app_state
    app.state.jobs = service

    # Only a fresh process recovers: a caller that passed its own ``AppState`` (every test) owns
    # its lifecycle, and a recovery sweep on construction would fight the caller's threads.
    if state is None:
        recovered = _recover_interrupted(app_state, service)
        if recovered:
            app.state.recovered_jobs = recovered



    # ---------------------------------------------------------------- auth
    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = app_state.settings.api_token
        if not expected:
            return  # local-only default: no token configured
        if authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="invalid or missing token")

    # ---------------------------------------------------------------- health
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": app.version,
            "jobs": len(app_state.store.list(limit=500)),
            "vision_available": app_state.vision_available(),
            "provider_mode": "mock" if app_state.registry.specs.get("mock") else "live",
        }

    # ---------------------------------------------------------------- jobs
    @app.get("/api/jobs")
    def list_jobs(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return {"jobs": [service.view(job) for job in app_state.store.list(limit=limit)]}

    @app.get("/api/jobs/upcoming")
    def upcoming_jobs() -> dict[str, Any]:
        """Calendar view: scheduled jobs ordered by start time, then priority.

        Read-only projection — the schedule decides when *production* may start, never the
        approval gate or anything after it.
        """
        now = _scheduler_now()
        rows = [
            job
            for job in app_state.store.list(limit=500)
            if job.scheduled_for is not None and job.state in SCHEDULABLE_STATES
        ]
        rows.sort(key=lambda job: (job.scheduled_for or "", job.priority, job.created_at))
        return {
            "now": now,
            "upcoming": [service.view(job) for job in rows],
            "awaiting_schedule": [
                service.view(job)
                for job in app_state.store.list(states=list(SCHEDULABLE_STATES), limit=500)
                if job.scheduled_for is None
            ],
        }

    @app.post("/api/jobs", status_code=201)
    def create_job(body: CreateJobBody, _: None = Depends(require_token)) -> dict[str, Any]:
        try:
            job = service.create(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return service.view(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            job = app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        return service.detail(job)

    @app.post("/api/jobs/{job_id}/run", status_code=202)
    def run_job(job_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        try:
            job = app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        # A terminal, paused, approval-waiting or publishing job is not a stage chain: the stage
        # runner would refuse the transition anyway, but the operator deserves the real reason
        # (409) instead of a worker that starts, fails, and blocks the job. Reopen paths are
        # explicit: /rework from an eligible blocked state, or approve/reject at the gate.
        if job.state in _RUN_INELIGIBLE:
            raise HTTPException(
                status_code=409,
                detail=f"job is {job.state.value}; only a draft or eligible blocked work can run",
            )
        started = service.start(job_id)
        if not started:
            raise HTTPException(status_code=409, detail="job is already running")
        return {"started": True, "job_id": job_id}

    @app.post("/api/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(
        job_id: str, body: CancelBody | None = None, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        try:
            job = app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        if job.state in {JobState.PUBLISHED, JobState.CANCELLED, JobState.REJECTED}:
            raise HTTPException(status_code=409, detail=f"job is already {job.state.value}")
        app_state.request_cancel(job_id)
        return {"cancel_requested": True, "job_id": job_id, "reason": (body.reason if body else "")}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        try:
            app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        app_state.store.delete(job_id)
        return {"deleted": job_id}

    @app.get("/api/jobs/{job_id}/artifact/{name}")
    def get_artifact(job_id: str, name: str) -> Any:
        try:
            return JSONResponse(app_state.store.read_artifact(job_id, name))
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="invalid artifact name") from exc

    @app.get("/api/jobs/{job_id}/video")
    def get_video(job_id: str, range_header: str | None = Header(default=None, alias="Range")) -> Response:
        path = app_state.store.job_dir(job_id) / "output.mp4"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no validated video for this job")
        data = path.read_bytes()
        size = len(data)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": "video/mp4",
            "Content-Disposition": 'inline; filename="output.mp4"',
        }
        if range_header and range_header.startswith("bytes="):
            try:
                spec = range_header.split("=", 1)[1].split(",")[0]
                start_raw, _, end_raw = spec.partition("-")
                start = int(start_raw) if start_raw else 0
                end = int(end_raw) if end_raw else size - 1
            except ValueError:
                raise HTTPException(status_code=416, detail="malformed Range") from None
            if start >= size or end < start:
                raise HTTPException(
                    status_code=416,
                    detail="range not satisfiable",
                    headers={"Content-Range": f"bytes */{size}"},
                )
            end = min(end, size - 1)
            chunk = data[start : end + 1]
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            return Response(content=chunk, status_code=206, headers=headers, media_type="video/mp4")
        return Response(content=data, headers=headers, media_type="video/mp4")

    # ---------------------------------------------------------------- approval
    @app.post("/api/jobs/{job_id}/approve")
    def approve_job(
        job_id: str, body: ApproveBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        try:
            return service.approve(job_id, body.operator)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        except service.ApprovalRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/reject")
    def reject_job(
        job_id: str, body: RejectBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        try:
            return service.reject(job_id, body.operator, body.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        except service.ApprovalRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # ---------------------------------------------------------------- studio
    @app.get("/api/studio/snapshot")
    def studio_snapshot(job_id: str | None = None) -> dict[str, Any]:
        return snapshot(app_state.events, job_id=job_id, live_agents=service.live_agents())

    @app.get("/api/studio/history")
    def studio_history(job_id: str, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return {"events": [event.to_json() for event in app_state.events.history(job_id, limit=limit)]}

    @app.get("/api/studio/stream")
    async def studio_stream(request: Request, after: int = Query(default=0, ge=0)) -> StreamingResponse:
        async def generator():
            cursor = after
            idle_ticks = 0
            while True:
                if await request.is_disconnected():
                    return
                events = app_state.events.page(after=cursor, limit=100)
                if events:
                    idle_ticks = 0
                    for event in events:
                        cursor = event.event_id
                        payload = json.dumps(event.to_json(), ensure_ascii=False)
                        yield f"id: {event.event_id}\ndata: {payload}\n\n"
                else:
                    idle_ticks += 1
                    if idle_ticks % 20 == 0:
                        yield ": keepalive\n\n"
                import asyncio

                await asyncio.sleep(POLL_S)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/studio/agents")
    def studio_agents() -> dict[str, Any]:
        return {"agents": list(AGENT_IDS)}

    # ---------------------------------------------------------------- providers
    @app.get("/api/providers")
    def list_providers() -> dict[str, Any]:
        return {
            "providers": app_state.provider_specs(),
            "vision_available": app_state.vision_available(),
            "bindings": [
                {"agent": agent, **binding} for agent, binding in app_state.bindings.items()
            ],
        }

    @app.put("/api/providers/bindings")
    def put_bindings(body: BindingsBody, _: None = Depends(require_token)) -> dict[str, Any]:
        """Replace the whole binding set. Unknown agents fail here, before anything binds."""
        known = set(AGENT_IDS)
        for binding in body.bindings:
            if binding.agent not in known:
                raise HTTPException(status_code=422, detail=f"unknown agent {binding.agent}")
        app_state.bindings = {
            b.agent: {"primary": b.primary, "fallback": list(b.fallback)} for b in body.bindings
        }
        return {"status": "ok", "bindings": body.bindings}

    @app.put("/api/providers")
    def upsert_provider(
        body: ProviderBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        # Credential policy: an omitted/empty credential input preserves the existing reference,
        # a nonempty value replaces it, and only an explicit clear removes it. Preserving is what
        # keeps an unrelated label or URL edit from silently unbinding a working credential.
        existing = None
        try:
            existing = app_state.registry.get(body.id)
        except KeyError:
            existing = None
        if body.credential_secret and body.credential_env:
            raise HTTPException(
                status_code=422,
                detail="send credential_secret or credential_env, not both",
            )
        if body.clear_credential and (body.credential_secret or body.credential_env):
            raise HTTPException(
                status_code=422,
                detail="clear_credential cannot be combined with a replacement credential",
            )
        credential: dict[str, str] | None
        if body.credential_secret:
            # Seal the value immediately; the plaintext never reaches the registry or a response.
            ref = app_state.secrets.put(f"provider-{body.id}", body.credential_secret)
            credential = ref.to_json()
        elif body.credential_env:
            credential = {"env": body.credential_env}
        elif body.clear_credential:
            credential = None
        else:
            credential = dict(existing.credential) if existing is not None else None
        try:
            spec = ProviderSpec(
                id=body.id,
                label=body.label,
                transport=body.transport,
                base_url=body.base_url,
                model=body.model,
                capabilities=[Capability(cap) for cap in body.capabilities],
                timeout_s=body.timeout_s,
                max_retries=body.max_retries,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
                allow_private_hosts=body.allow_private_hosts,
                enabled=body.enabled,
                cli_command=body.cli_command,
                credential=credential,
                price_in_per_mtok=body.price_in_per_mtok,
                price_out_per_mtok=body.price_out_per_mtok,
            )
        except (ValueError, BlockedTarget) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app_state.upsert_provider(spec)
        _persist_provider(app_state, spec)
        return {"provider": spec.public_view()}

    @app.delete("/api/providers/{provider_id}", status_code=200)
    def delete_provider(provider_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        """Remove a provider. Refused while a persisted binding still references it (409):
        deleting the provider a binding names would leave the binding pointing at nothing, which
        is a silent misconfiguration rather than a visible error.
        """
        from .config import ConfigError, ConfigStore

        store = ConfigStore(app_state.settings.studio_config, secrets=app_state.secrets)
        try:
            config = store.load()
        except ConfigError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        referencing = sorted(
            str(binding.get("agent"))
            for binding in config.bindings
            if binding.get("primary") == provider_id
            or provider_id in (binding.get("fallback") or [])
        )
        if referencing:
            raise HTTPException(
                status_code=409,
                detail="provider is still bound to: " + ", ".join(referencing),
            )
        config.providers = [e for e in config.providers if e.get("id") != provider_id]
        config.credential_origins.pop(provider_id, None)
        try:
            store.save(config)
        except ConfigError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        app_state.registry.specs.pop(provider_id, None)
        app_state._publish_configured_rates()  # noqa: SLF001 - same object, one republish path
        return {"deleted": provider_id}

    @app.post("/api/providers/test")
    def test_provider(
        body: TestProviderBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        try:
            spec = app_state.registry.get(body.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown provider") from exc
        transport = app_state.transports.get(spec.transport)
        if transport is None:
            raise HTTPException(status_code=422, detail="transport unavailable")
        from packages.core.providers.resolve import build_call
        from packages.core.security.secretstore import CredentialRef

        credential = app_state.secrets.resolve(CredentialRef.parse(spec.credential))
        call = build_call(spec, binding=_single_binding(spec), credential=credential)
        health = transport.health(call)
        return {
            "id": spec.id,
            "ok": health.ok,
            "detail": redact(health.detail, secrets=(credential,)),
            "latency_ms": health.latency_ms,
            # A reachability probe is not a proof of authentication. Say so, in the payload.
            "note": "reachability only; a completion is what proves the credential and model",
        }

    @app.get("/api/providers/{provider_id}/models")
    def provider_models(provider_id: str) -> dict[str, Any]:
        try:
            spec = app_state.registry.get(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown provider") from exc
        transport = app_state.transports.get(spec.transport)
        if transport is None:
            raise HTTPException(status_code=422, detail="transport unavailable")
        from packages.core.providers.resolve import build_call
        from packages.core.security.secretstore import CredentialRef

        credential = app_state.secrets.resolve(CredentialRef.parse(spec.credential))
        call = build_call(spec, binding=_single_binding(spec), credential=credential)
        models = transport.list_models(call)
        if models is None:
            raise HTTPException(
                status_code=422, detail="this provider does not expose a model list"
            )
        return {"models": models}

    # ---------------------------------------------------------------- usage
    @app.get("/api/usage/today")
    def usage_today() -> dict[str, Any]:
        return app_state.usage.today()

    @app.get("/api/usage/job/{job_id}")
    def usage_job(job_id: str) -> dict[str, Any]:
        return {"rows": app_state.usage.for_job(job_id)}

    # ---------------------------------------------------------------- publishing
    def _transport(name: str):
        """Resolve a publication transport by name.

        Only the offline stub exists. A real transport is a later, separate addition; refusing an
        unknown name here is what stops a typo from silently publishing through the stub and
        recording an upload that never happened.
        """
        from packages.core.publish.stub import StubTransport

        if name != "stub":
            raise HTTPException(status_code=422, detail=f"unknown transport {name!r}")
        return StubTransport()

    @app.post("/api/jobs/{job_id}/publish")
    def publish_job(
        job_id: str, body: PublishBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        transport = _transport(body.transport)
        try:
            report = service.publish(job_id, transport)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        except service.ApprovalRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {**report, "transport": body.transport}

    @app.post("/api/jobs/{job_id}/publish/reconcile")
    def reconcile_job(
        job_id: str, body: ReconcileBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        from packages.core.publish.reconcile import reconcile_uncertain

        try:
            app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        transport = _transport(body.transport)
        try:
            publication = reconcile_uncertain(app_state.store, job_id, transport)
        except ValueError as exc:
            # A healthy record, a missing record, or an ambiguous match: all 409, because all of
            # them are "this cannot be reconciled", not a malformed request.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "job_id": job_id,
            "phase": publication.phase,
            "video_id": publication.video_id,
            "idempotency_key": publication.idempotency_key,
            "attempt": publication.attempt,
            "receipt_steps": [str(r.get("step")) for r in publication.receipts],
        }

    # ---------------------------------------------------------------- metadata
    METADATA_NAME = "metadata.json"

    @app.get("/api/jobs/{job_id}/metadata")
    def get_metadata(job_id: str) -> Any:
        try:
            return JSONResponse(app_state.store.read_artifact(job_id, METADATA_NAME))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/metadata")
    def edit_metadata(
        job_id: str, body: MetadataBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        """Edit title/description/tags.

        Refused before ``READY_FOR_APPROVAL`` because metadata for a video that does not exist yet
        is metadata for nothing — and the metadata agent writes a first draft at that point, so an
        earlier edit would be silently overwritten.
        """
        from packages.core.contracts.artifacts import MetadataArtifact
        from packages.core.contracts.base import ArtifactValidationError, validate_artifact

        try:
            job = app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        if job.state not in METADATA_EDITABLE_STATES:
            raise HTTPException(
                status_code=409,
                detail=(
                    "metadata can only be edited at or after READY_FOR_APPROVAL, "
                    f"job is {job.state.value}"
                ),
            )
        try:
            current = app_state.store.read_artifact(job_id, METADATA_NAME)
        except ArtifactNotFound:
            current = MetadataArtifact(title=job.title or job.id).to_json()
        patch = body.model_dump(exclude_none=True)
        merged = {**current, **patch}
        try:
            artifact = validate_artifact(MetadataArtifact, merged)
        except ArtifactValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app_state.store.write_artifact(job_id, METADATA_NAME, artifact.to_json())
        return artifact.to_json()

    # ---------------------------------------------------------------- usage summary
    # ---------------------------------------------------------------- request journal
    @app.get("/api/jobs/{job_id}/requests")
    def job_requests(job_id: str) -> dict[str, Any]:
        """Safe per-request status summaries for one job. No payload content, ever."""
        try:
            app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        journal = getattr(app_state, "requests", None)
        if journal is None:
            return {"job_id": job_id, "requests": [], "uncertain": []}
        return {
            "job_id": job_id,
            "requests": journal.statuses(job_id),
            "uncertain": journal.uncertain(job_id),
        }

    @app.post("/api/jobs/{job_id}/requests/{request_key}/retry")
    def retry_request(
        job_id: str,
        request_key: str,
        body: RetryRequestBody,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        """Record the operator's decision to make a fresh, deliberate attempt.

        The honest guarantee is stated plainly in the response: this cannot make the remote call
        exactly-once, because nobody — including the provider — can retract a call whose outcome
        was never observed. What it *does* guarantee is that nothing retries automatically after
        an unknown outcome, and that every committed response is reused. The next attempt is a new
        attempt number for the same logical request, with the operator's name on the decision.
        """
        app_state.store.get(job_id)  # 404 on an unknown job
        journal = getattr(app_state, "requests", None)
        if journal is None:
            raise HTTPException(status_code=409, detail="request journal unavailable")
        uncertain = journal.uncertain(job_id)
        row = next((r for r in uncertain if r["request_key"] == request_key), None)
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="that request is not waiting for acknowledgement",
            )
        journal.acknowledge(
            request_key=request_key, attempt=row["attempt"], operator=body.operator
        )
        return {
            "job_id": job_id,
            "request_key": request_key,
            "next_attempt": journal.next_attempt(request_key),
            "acknowledged_by": body.operator,
            "note": (
                "outcome remains unknown; the next attempt is deliberate and recorded. "
                "Exactly-once remote execution cannot be enforced by this system."
            ),
        }

    @app.get("/api/usage/summary")
    def usage_summary() -> dict[str, Any]:
        """Per-day, per-agent and per-model totals.

        ``cost_usd`` is 0.0 unless the operator configured prices on the provider
        (``price_in_per_mtok`` / ``price_out_per_mtok``). ``price_configured`` says which case a
        row is in, so an unpriced zero is never presented as "free".
        """
        return app_state.usage.summary()

    # ---------------------------------------------------------------- topic discovery
    @app.post("/api/topics/discover")
    def discover_topics(body: DiscoverTopicsBody) -> dict[str, Any]:
        """Run one discovery: propose candidates, record them, return them.

        Proposals are metadata only — no job row is created here. Creating a job stays an
        explicit operator action; a scheduler that spends money unattended stays off.
        """
        from packages.core.orchestration.discovery import build_discovery_stage
        from packages.core.orchestration.runner import StageError

        discovery_id = f"disc-{uuid.uuid4().hex[:12]}"
        stage = build_discovery_stage(app_state, limit=body.limit)
        try:
            # A discovery is outside any job: no lease, no cancellation, no artifacts to stage.
            # The context exists so the stage body speaks the same protocol as every other stage.
            from packages.core.orchestration.runner import NullCancel, StageContext

            ctx = StageContext(
                app_state.store,
                discovery_id,
                Path(tempfile.gettempdir()) / f"disc-{discovery_id}",
                cancel=NullCancel(),
            )
            outcome = stage.run(ctx)
        except StageError as exc:
            payload = {
                "discovery_id": discovery_id,
                "status": "blocked",
                "reason": f"{exc.code}: {exc.detail}",
            }
            app_state.store.record_topic_discovery(
                discovery_id=discovery_id, payload=payload, titles=[]
            )
            raise HTTPException(status_code=503, detail=payload["reason"]) from exc
        recorded = app_state.store.topic_discovery(discovery_id) or {}
        return {
            "discovery_id": discovery_id,
            "status": "ok" if outcome.ok else "blocked",
            "provider_mode": recorded.get("provider_mode"),
            "candidates": recorded.get("candidates", []),
            "avoid": recorded.get("avoid", []),
        }

    # ---------------------------------------------------------------- settings and agents
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        """Budget and render settings. Storage paths are read-only and reported as-is."""
        from .config import ConfigStore

        store = ConfigStore(app_state.settings.studio_config, secrets=app_state.secrets)
        try:
            config = store.load()
        except ConfigError as exc:
            # A malformed configuration is a visible sanitized error, never a partial guess.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "budget": config.budget.to_json(),
            "render": config.render.to_json(),
            "storage": {
                "data_dir": str(app_state.settings.data_dir),
                "jobs_dir": str(app_state.settings.jobs_dir),
                "secrets_dir": str(app_state.settings.secrets_dir),
            },
        }

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, _: None = Depends(require_token)) -> dict[str, Any]:
        """Replace the budget and/or render settings. Only those two groups are writable."""
        from .config import BudgetConfig, ConfigStore, RenderConfig

        store = ConfigStore(app_state.settings.studio_config, secrets=app_state.secrets)
        try:
            config = store.load()
            if body.budget is not None:
                config.budget = BudgetConfig(
                    max_daily_tokens=body.budget.max_daily_tokens,
                    max_daily_cost_usd=body.budget.max_daily_cost_usd,
                    unlimited=body.budget.unlimited,
                )
            if body.render is not None:
                config.render = RenderConfig(
                    min_free_ram_mib=body.render.min_free_ram_mib,
                    min_free_vram_mib=body.render.min_free_vram_mib,
                    allow_unmeasured_gpu=body.render.allow_unmeasured_gpu,
                )
            store.save(config)
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app_state.usage.set_limits(
            max_daily_tokens=config.budget.max_daily_tokens,
            max_daily_cost_usd=config.budget.max_daily_cost_usd,
            unlimited=config.budget.unlimited,
        )
        return {"budget": config.budget.to_json(), "render": config.render.to_json()}

    @app.get("/api/agents")
    def list_agents() -> dict[str, Any]:
        """Every agent with its kind, required capabilities and current binding."""
        from packages.core.agents.registry import AGENTS
        from packages.core.observability.events import AGENT_IDS
        from packages.core.providers.base import Capability

        configured = app_state.bindings
        agents: list[dict[str, Any]] = []
        for agent_id in sorted(AGENT_IDS):
            agent = AGENTS.get(agent_id)
            requires = sorted(getattr(agent, "requires", []) or []) if agent else ["chat"]
            binding = configured.get(agent_id, {})
            gaps = _capability_gaps(app_state, [Capability(c) for c in requires])
            agents.append(
                {
                    "id": agent_id,
                    "kind": "llm" if agent is not None else "deterministic",
                    "requires": requires,
                    "binding": {
                        "primary": binding.get("primary"),
                        "fallback": binding.get("fallback", []),
                        "model": binding.get("model"),
                        "temperature": binding.get("temperature"),
                        "max_tokens": binding.get("max_tokens"),
                        "system_prompt_override": binding.get("system_prompt_override"),
                    },
                    "capability_gaps": gaps,
                }
            )
        return {"agents": agents}

    @app.put("/api/agents/{agent_id}/binding")
    def put_agent_binding(
        agent_id: str, body: AgentBindingUpdate, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        """Save one agent's binding. Every configured candidate must satisfy the binding
        (ADR-003): a primary that cannot serve the agent is refused here, not hidden behind a
        compatible fallback at call time."""
        from packages.core.agents.registry import AGENTS
        from packages.core.providers.base import CapabilityMismatch
        from packages.core.providers.resolve import Binding, resolve_call

        if agent_id not in AGENT_IDS:
            raise HTTPException(status_code=422, detail=f"unknown agent {agent_id!r}")
        agent = AGENTS.get(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=422,
                detail=f"{agent_id} is deterministic and has no model controls",
            )
        requires = frozenset(getattr(agent, "requires", []) or [])
        binding = Binding(
            agent=agent_id,
            primary=body.primary,
            fallback=tuple(body.fallback),
            requires=requires,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        # Resolve against the real registry: an unknown id, a duplicate candidate or an
        # incompatible primary is a 422 before anything is saved.
        try:
            resolve_call(
                binding=binding,
                registry=app_state.registry,
                store=app_state.secrets,
                transports=app_state.transports,
                allow_mock_fallback=True,
            )
        except CapabilityMismatch as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - an unusable candidate is a 422, not a 500
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        from .config import ConfigStore

        store = ConfigStore(app_state.settings.studio_config, secrets=app_state.secrets)
        try:
            config = store.load()
        except ConfigError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        entry: dict[str, Any] = {
            "agent": agent_id,
            "primary": body.primary,
            "fallback": list(body.fallback),
        }
        for key, value in (
            ("model", body.model),
            ("temperature", body.temperature),
            ("max_tokens", body.max_tokens),
            ("system_prompt_override", body.system_prompt_override),
        ):
            if value is not None:
                entry[key] = value
        config.bindings = [b for b in config.bindings if b.get("agent") != agent_id] + [entry]
        try:
            store.save(config)
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with app_state.lock:
            app_state.bindings[agent_id] = entry
        return {"agent": agent_id, "binding": entry}

    return app


def _persist_provider(app_state: Any, spec: ProviderSpec) -> None:
    """Write one provider into ``studio.json`` durably, replacing its previous entry.

    The credential's *origin* is persisted next to it, so a later URL edit cannot rebind a
    credential that was validated against a different host. A provider is only in the durable file
    if the save succeeded: a registry-only edit would vanish on restart, which is the "my settings
    did not stick" bug class.
    """
    from .config import ConfigError, ConfigStore

    store = ConfigStore(app_state.settings.studio_config, secrets=app_state.secrets)
    try:
        config = store.load()
        config.providers = [
            entry for entry in config.providers if entry.get("id") != spec.id
        ] + [spec.durable_view()]
        config.credential_origins[spec.id] = _origin(spec.base_url)
        store.save(config)
    except ConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _origin(base_url: str) -> dict[str, Any]:
    """The ``(scheme, host, port)`` a credential is bound to. Never a full URL with a path."""
    from urllib.parse import urlsplit

    parts = urlsplit(base_url)
    return {
        "scheme": parts.scheme,
        "host": parts.hostname,
        "port": parts.port,
    }


def _capability_gaps(app_state: Any, requires: list[Any]) -> list[str]:
    """Capabilities no enabled provider declares, for the binding that would be used."""
    if not requires:
        return []
    available: set[Any] = set()
    for spec in app_state.registry.enabled():
        available.update(spec.capabilities)
    return [cap.value for cap in requires if cap not in available]


def _single_binding(spec: ProviderSpec):

    """A minimal binding for a diagnostic call: the provider's own model, no overrides."""
    from packages.core.providers.resolve import Binding

    return Binding(agent="FactoryOrchestrator", primary=spec.id)


app = create_app()
