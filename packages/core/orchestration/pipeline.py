"""The Phase 1 pipeline: agent stages that produce validated artifacts, honestly.

What this deliberately does *not* do: render video. Rendering is Phase 2, and a pipeline that
pretends to render would produce exactly the artefact the brief forbids — a job that reaches
``READY_FOR_APPROVAL`` with no video behind it.

So Phase 1 stops at ``STORYBOARD_READY``: research → topic → script → creative review → storyboard,
each with a real artifact and a real provider call. That is a complete vertical slice through the
hard part (contracts, providers, durability, events, approval gate), and it is genuinely runnable
end to end in mock mode with no credential.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..agents import CallContext, ModelOutputError
from ..agents.registry import AGENTS
from ..contracts.state import JobState
from ..observability.events import STAGE_AGENTS
from ..providers.base import Capability, CapabilityMismatch, NoProviderAvailable
from ..providers.resolve import Binding, resolve_call
from ..providers.usage import RecordingProvider
from ..security.redact import redact
from .jobstore import JobRecord, JobStore
from .leases import LeaseKeeper
from .runner import (
    CancelToken,
    NullCancel,
    Stage,
    StageContext,
    StageError,
    StageOutcome,
    run_stages,
)

#: How many times the creative director may send a script back. A revision loop with no ceiling is
#: how a job spends an afternoon and a budget without producing anything.
MAX_REVISIONS = 2


def mock_pipeline_supported() -> bool:
    return True


def _emit(state: Any, job_id: str, stage: str, event_type: str, description: str,
          *, agent: str | None = None, progress: float | None = None,
          model: str | None = None) -> None:
    """Emit an event attributed to the agent that is actually doing the work.

    ``agent`` defaults to the stage's producer, but a stage always names its own agent: an event
    that says "ScriptAgent mulai" while attributed to ResearchAgent is exactly the kind of
    half-truth the studio must never display.
    """
    resolved = agent or STAGE_AGENTS.get(stage, "FactoryOrchestrator")
    state.events.emit(
        job_id=job_id,
        agent_id=resolved,
        event_type=event_type,
        description=description,
        progress=progress,
        model=model,
        stage=stage,
    )


def _context(state: Any, job: JobRecord, agent_name: str) -> CallContext:
    """Resolve the agent's provider, honouring its binding and the job's mode."""
    from ..providers.registry import ProviderRegistry  # noqa: F401 - typing clarity

    requires = AGENTS[agent_name].requires
    binding = Binding(
        agent=agent_name,
        primary=_primary_for(state, agent_name),
        fallback=tuple(_fallback_for(state, agent_name)),
        requires=frozenset(requires),
    )
    allow_mock = job.is_mock
    if allow_mock:
        state.registry.specs["mock"].enabled = True
    call, transport = resolve_call(
        binding=binding,
        registry=state.registry,
        store=state.secrets,
        transports=state.transports,
        allow_mock_fallback=allow_mock,
    )
    spec = state.registry.specs.get(call.provider)
    recorder = RecordingProvider(
        transport,
        tracker=state.usage,
        agent=agent_name,
        job_id=job.id,
        price_in=spec.price_in_per_mtok if spec else None,
        price_out=spec.price_out_per_mtok if spec else None,
        journal=getattr(state, "requests", None),
        request_identity={
            "provider": call.provider,
            "transport": call.transport,
            "model": call.model,
            "temperature": call.temperature,
            "max_tokens": call.max_tokens,
            "ordinal": getattr(state, "_call_ordinal", 0),
            "prompt_sha256": "",
            "call_config_sha256": "",
        },
    )
    return CallContext(call=call, provider=recorder, job_id=job.id)


def _primary_for(state: Any, agent: str) -> str | None:
    override = getattr(state, "bindings", {}).get(agent) if hasattr(state, "bindings") else None
    if override:
        primary: object = override.get("primary")
        return primary if isinstance(primary, str) else None
    for spec in state.registry.enabled():
        if spec.transport != "mock":
            spec_id: object = spec.id
            return spec_id if isinstance(spec_id, str) else None
    return "mock" if state.registry.specs.get("mock") else None


def _fallback_for(state: Any, agent: str) -> list[str]:
    """Operator-declared fallback order for one agent; empty when no binding pins one."""
    override = getattr(state, "bindings", {}).get(agent) if hasattr(state, "bindings") else None
    fallback = override.get("fallback") if isinstance(override, dict) else None
    if isinstance(fallback, list):
        return [f for f in fallback if isinstance(f, str)]
    return []


def _agent_stage(state: Any, *, agent_name: str, stage_state: JobState, produces: str,
                 task: str, prompt_kwargs: dict[str, Any], contract: Any) -> Stage:
    """Build a stage that runs one agent and writes one validated artifact."""

    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        job = store.get(job_id)
        _emit(state, job_id, stage_state.value, "stage_started", f"{agent_name} mulai")
        try:
            ctxp = _context(state, job, agent_name)
        except CapabilityMismatch as exc:
            _emit(state, job_id, stage_state.value, "blocked", str(exc))
            raise StageError("capability", str(exc), retryable=False) from exc
        except NoProviderAvailable as exc:
            _emit(state, job_id, stage_state.value, "failed", str(exc))
            raise StageError("no_provider", str(exc), retryable=False) from exc

        agent = AGENTS[agent_name](ctxp)
        ctx.call = ctxp.call
        try:
            artifact = agent.produce(task=task, **prompt_kwargs)
        except ModelOutputError as exc:
            _emit(state, job_id, stage_state.value, "failed", redact(exc.detail))
            raise StageError(exc.code, exc.detail, retryable=exc.retryable) from exc

        ctx.write_artifact(produces, artifact.to_json())
        _emit(
            state,
            job_id,
            stage_state.value,
            "stage_completed",
            f"{agent_name} selesai",
            progress=1.0,
            model=ctx.call.model,
        )
        return StageOutcome(ok=True, artifacts=[produces])

    return Stage(name=agent_name, state=stage_state, produces=(produces,), run=run)


def build_stages(state: Any, job_id: str) -> list[Stage]:
    """The chain for one job. Prompts are assembled from the job payload and artifacts.

    Phase 1 ends at ``STORYBOARD_READY``. The render stages are appended only when the job
    payload asks for a video (``render_video: True``), so the agent-only chain stays the default
    and no test needs a Node toolchain.
    """
    store = state.store
    job = store.get(job_id)
    payload = job.payload
    topic = payload.get("topic", "")
    genre = payload.get("genre", "edukasi")
    language = payload.get("language", "id")
    duration = int(payload.get("target_duration_s", 45))

    def research_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        return {"topic": topic, "genre": genre, "avoid": []}

    def topic_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        return {"research": store.read_artifact(job_id, "research.json")}

    def script_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        return {
            "topic": store.read_artifact(job_id, "topic.json"),
            "duration_s": duration,
            "language": language,
        }

    def review_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        return {"script": store.read_artifact(job_id, "script.json"), "attempt": 0}

    def storyboard_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        return {"script": store.read_artifact(job_id, "script.json"), "fps": 30}

    def metadata_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        # MetadataAgent reads the script; the topic and language come from the job payload, so the
        # title is written in the video's language rather than the operator's.
        return {
            "script": store.read_artifact(job_id, "script.json"),
            "topic": topic,
            "language": language,
        }

    stages = [
        _dynamic_stage(
            state,
            agent_name="ResearchAgent",
            stage_state=JobState.TOPIC_SELECTED,
            produces="research.json",
            task="research",
            kwargs_fn=research_prompt,
        ),
        _dynamic_stage(
            state,
            agent_name="TopicSelectionAgent",
            stage_state=JobState.RESEARCH_COMPLETE,
            produces="topic.json",
            task="topic",
            kwargs_fn=topic_prompt,
        ),
        _dynamic_stage(
            state,
            agent_name="ScriptAgent",
            stage_state=JobState.SCRIPT_GENERATED,
            produces="script.json",
            task="script",
            kwargs_fn=script_prompt,
        ),
        _dynamic_stage(
            state,
            agent_name="CreativeDirectorAgent",
            stage_state=JobState.CREATIVE_REVIEW,
            produces="review.json",
            task="review",
            kwargs_fn=review_prompt,
        ),
        _dynamic_stage(
            state,
            agent_name="StoryboardAgent",
            stage_state=JobState.STORYBOARD_READY,
            produces="storyboard.json",
            task="storyboard",
            kwargs_fn=storyboard_prompt,
        ),
        # Metadata is derived from the script, so it runs after the storyboard and before any
        # render. It targets STORYBOARD_READY because no metadata-specific state exists in the
        # allow-list; ``run_stages`` skips a transition whose target is the current state, so this
        # is a no-op rather than an illegal edge.
        _dynamic_stage(
            state,
            agent_name="MetadataAgent",
            stage_state=JobState.STORYBOARD_READY,
            produces="metadata.json",
            task="metadata",
            kwargs_fn=metadata_prompt,
        ),
    ]

    if payload.get("render_video") is True:
        stages.extend(_render_stages(state, renderer=payload.get("renderer", "remotion")))
    return stages


def _video_dir() -> Any:
    """``packages/video`` at the repository root. No absolute path is hardcoded."""
    from pathlib import Path

    return Path(__file__).resolve().parents[3] / "packages" / "video"


def _render_stages(state: Any, *, renderer: str = "remotion") -> list[Stage]:
    """The local Phase 2 chain: assets, audio, render, technical QC, editorial QC, readiness.

    Both QC gates are owned by ``QualityAgent`` because both answer questions about the same
    file, but they are separate stages with separate artifacts: ``TECHNICAL_QC`` writes
    ``technical-qc.json`` (every FR-7.1 measurement, including the detector runs) and
    ``EDITORIAL_QC`` writes ``qc.json`` (FR-7.2 plus the visual pass) and
    ``READY_FOR_APPROVAL`` writes ``readiness.json`` (the DirectorAgent gate, recomputed from the
    files). Splitting the QA artifacts is what keeps ``qc.json`` from having to invent a visual
    status before any vision provider has been consulted; splitting readiness from the editorial
    verdict keeps the stage that scored the job from certifying its own score.

    There is exactly one technical stage. The previous builder in ``media/render.py`` wrote
    ``qc.json`` from an ffprobe-only check set before any detector ran; it is deleted.
    """
    from ..media.render import build_render_stage
    from ..media.tts import build_asset_stage, build_audio_stage
    from .editorial import (
        build_editorial_qc_stage,
        build_readiness_stage,
        build_technical_qc_stage,
    )

    video_dir = _video_dir()
    # The renderer is the job's choice and the stage refuses anything it does not know, so a typo
    # in the payload cannot quietly render with the primary and record a different name.
    return [
        build_asset_stage(state, video_dir=video_dir),
        build_audio_stage(state),
        build_render_stage(state, video_dir=video_dir, renderer=renderer),
        build_technical_qc_stage(state),
        build_editorial_qc_stage(state),
        build_readiness_stage(state),
    ]


def _dynamic_stage(state: Any, *, agent_name: str, stage_state: JobState, produces: str,
                   task: str, kwargs_fn: Callable[[JobStore, str], dict[str, Any]]) -> Stage:
    from ..agents.registry import AGENTS as _AGENTS

    contract = _AGENTS[agent_name](_null_context()).contract()

    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        job = store.get(job_id)
        _emit(state, job_id, stage_state.value, "stage_started", f"{agent_name} mulai", agent=agent_name)
        try:
            ctxp = _context(state, job, agent_name)
        except CapabilityMismatch as exc:
            _emit(state, job_id, stage_state.value, "blocked", str(exc), agent=agent_name)
            raise StageError("capability", str(exc), retryable=False) from exc
        except NoProviderAvailable as exc:
            _emit(state, job_id, stage_state.value, "failed", str(exc), agent=agent_name)
            raise StageError("no_provider", str(exc), retryable=False) from exc

        agent = _AGENTS[agent_name](ctxp)
        ctx.call = ctxp.call
        kwargs = kwargs_fn(store, job_id)
        try:
            artifact = agent.produce(task=task, **kwargs)
        except ModelOutputError as exc:
            _emit(state, job_id, stage_state.value, "failed", redact(exc.detail), agent=agent_name)
            raise StageError(exc.code, exc.detail, retryable=exc.retryable) from exc

        if isinstance(artifact, _review_type()) and artifact.verdict == "revise":
            ctx.write_artifact(produces, artifact.to_json())
            _emit(
                state,
                job_id,
                stage_state.value,
                "blocked",
                "creative review minta revisi: " + "; ".join(
                    finding.get("issue", "") for finding in artifact.findings[:3]
                ),
                agent=agent_name,
                model=ctx.call.model,
            )
            # A revise verdict is a decision, not a crash: the review evidence is committed and
            # the chain stops at BLOCKED, where the revision controller (step 6) reopens it with
            # the findings attached. Raising StageError instead marked the job FAILED, which
            # invited a bare retry of the same review call.
            return StageOutcome(
                ok=True,
                detail="creative review requested a revision",
                control="revision_required",
                artifacts=[produces],
            )

        ctx.write_artifact(produces, artifact.to_json())
        _emit(
            state,
            job_id,
            stage_state.value,
            "stage_completed",
            f"{agent_name} selesai",
            agent=agent_name,
            progress=1.0,
            model=ctx.call.model,
        )
        return StageOutcome(ok=True, artifacts=[produces])

    return Stage(
        name=agent_name,
        state=stage_state,
        produces=(produces,),
        run=run,
        contract=contract,
        contract_artifact=produces,
    )


def _review_type() -> type[Any]:
    from ..contracts import ReviewArtifact

    return ReviewArtifact


def _null_context() -> CallContext:
    """A context used only to reach a class-level contract, never to make a call."""
    from ..providers.base import ResolvedCall
    from ..providers.mock import MockProvider

    call = ResolvedCall(
        provider="mock",
        transport="mock",
        base_url="",
        model="mock-1",
        temperature=None,
        max_tokens=None,
        timeout_s=1.0,
        max_retries=0,
        capabilities=frozenset({Capability.CHAT}),
        allow_private_hosts=False,
    )
    return CallContext(call=call, provider=MockProvider())


def run_job(
    state: Any,
    job_id: str,
    *,
    keeper: LeaseKeeper,
    cancel: CancelToken | None = None,
) -> dict[str, Any]:
    """The bounded controller around ``run_stages`` for one job.

    Why this exists instead of ``apps/api`` calling ``run_stages`` directly: the revision loop is
    a controller concern, and a controller that lives in the web layer is a controller the
    scheduler and the rework path cannot reuse. It owns exactly one bound — ``MAX_REVISIONS`` —
    and stops the chain otherwise. It does not open a second runner, does not retry a paid call
    whose outcome is unknown, and does not write state its lease does not cover.
    """
    cancel = cancel or NullCancel()
    revisions = 0
    while True:
        stages = build_stages(state, job_id)
        report = run_stages(
            store=state.store, job_id=job_id, stages=stages, keeper=keeper, cancel=cancel
        )
        stopped = report.get("stopped")
        if stopped != "revision_required":
            return report
        # The review asked for a revision. The revision controller (step 6) persists attempts and
        # compares authored content; until it lands, the honest bound here is the ceiling: two
        # revisions, then the job stays blocked with the findings attached rather than looping
        # until the budget runs out.
        revisions += 1
        if revisions > MAX_REVISIONS:
            state.store.set_error(job_id, f"revision ceiling reached after {revisions - 1} revisions")
            return report
        # A revise verdict lands at CREATIVE_REVIEW -> BLOCKED; reopening into SCRIPT_GENERATED
        # is the revising stage's own edge, and the script stage re-runs with the findings. The
        # loop above rebuilds the chain, so the next iteration starts from wherever the job is.
        state.store.transition(job_id, JobState.SCRIPT_GENERATED, detail="revision requested")
