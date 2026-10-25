"""HTTP surface. Composition root only: every route delegates, none implements a rule.

Local-first, so the default is no auth token at all: the server binds loopback and the dashboard is
same-origin. When ``STUDIO_API_TOKEN`` is set, every mutating route requires it, because the moment
someone opens the port beyond loopback the difference matters.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from packages.core.contracts.state import JobState
from packages.core.observability.events import AGENT_IDS, snapshot
from packages.core.orchestration.jobstore import ArtifactNotFound
from packages.core.providers.base import (
    Capability,
)
from packages.core.providers.registry import ProviderSpec
from packages.core.security.netguard import BlockedTarget
from packages.core.security.redact import redact

from .jobs import JobService
from .schemas import (
    ApproveBody,
    CancelBody,
    CreateJobBody,
    ProviderBody,
    RejectBody,
    TestProviderBody,
)
from .settings import Settings
from .state import AppState

POLL_S = 0.5


def create_app(state: AppState | None = None) -> FastAPI:
    settings = state.settings if state else Settings.from_env()
    app_state = state or AppState.build(settings)
    service = JobService(app_state)

    app = FastAPI(title="ShortsFactoryAI Studio", version="0.1.0")
    app.state.studio = app_state
    app.state.jobs = service

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
            app_state.store.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
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
        }

    @app.put("/api/providers")
    def upsert_provider(
        body: ProviderBody, _: None = Depends(require_token)
    ) -> dict[str, Any]:
        credential: dict[str, str] | None = None
        if body.credential_secret:
            # Seal the value immediately; the plaintext never reaches the registry or a response.
            ref = app_state.secrets.put(f"provider-{body.id}", body.credential_secret)
            credential = ref.to_json()
        elif body.credential_env:
            credential = {"env": body.credential_env}
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
            )
        except (ValueError, BlockedTarget) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app_state.upsert_provider(spec)
        return {"provider": spec.public_view()}

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

    return app


def _single_binding(spec: ProviderSpec):
    """A minimal binding for a diagnostic call: the provider's own model, no overrides."""
    from packages.core.providers.resolve import Binding

    return Binding(agent="FactoryOrchestrator", primary=spec.id)


app = create_app()
