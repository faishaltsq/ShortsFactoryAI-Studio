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
from dataclasses import replace
from typing import Any

from ..agents import CallContext, ModelOutputError
from ..agents.registry import AGENTS
from ..contracts.artifacts import ReviewArtifact, RevisionArtifact, RevisionAttempt, ScriptArtifact
from ..contracts.base import ArtifactValidationError, validate_artifact
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


def _with_provenance(
    payload: dict[str, Any], agent_name: str, ctxp: Any, state: Any
) -> dict[str, Any]:
    """Attach the locally computed provenance to a model artifact.

    The model writes the content; the code writes who produced it. ``prompt_sha256`` is hashed
    here, from the prompt this process actually sent, so the artifact's provenance is a fact about
    the run rather than the model's opinion of itself.
    """
    from ..agents.registry import AGENTS
    from ..prompts import sha256

    # The prompt that was sent is the agent's own effective prompt: the operator's override when
    # one is bound, otherwise the agent's constant. Reading it back off the context rather than
    # re-deriving it here is what keeps the hash and the call in agreement.
    override = getattr(ctxp, "system_prompt", None)
    if isinstance(override, str) and override:
        prompt = override
    else:
        prompt = AGENTS[agent_name].system_prompt
    payload["provenance"] = {
        "prompt_sha256": sha256(prompt),
        "producer": agent_name,
        "provider": ctxp.call.provider,
        "model": ctxp.call.model,
    }
    return payload


def _context(state: Any, job: JobRecord, agent_name: str) -> CallContext:
    """Resolve the agent's provider, honouring its binding and the job's mode."""
    from ..providers.registry import ProviderRegistry  # noqa: F401 - typing clarity

    binding = _binding_for(state, agent_name)
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
    return CallContext(
        call=call,
        provider=recorder,
        job_id=job.id,
        system_prompt=_prompt_override_for(state, agent_name),
    )


def _prompt_override_for(state: Any, agent: str) -> str | None:
    """The operator's system-prompt override for one agent, or ``None``.

    Read from the same binding the provider comes from, so the prompt sent and the prompt hashed
    into provenance cannot disagree.
    """
    override = getattr(state, "bindings", {}).get(agent) if hasattr(state, "bindings") else None
    if isinstance(override, dict):
        candidate = override.get("system_prompt_override")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _binding_for(state: Any, agent: str) -> Binding:
    """The operator's binding for one agent, with the overrides that reach the call.

    ``_primary_for``/``_fallback_for`` answer "which provider"; this answers "with what
    configuration". They are one question, so they are one function: a binding that resolves a
    provider but drops ``model``/``temperature``/``max_tokens`` silently runs on provider defaults
    while the UI shows the operator's saved values.
    """
    override = getattr(state, "bindings", {}).get(agent) if hasattr(state, "bindings") else None
    override = override if isinstance(override, dict) else None
    primary = override.get("primary") if override else None
    fallback = override.get("fallback") if override else None
    model = override.get("model") if override else None
    temperature = override.get("temperature") if override else None
    max_tokens = override.get("max_tokens") if override else None
    return Binding(
        agent=agent,
        primary=primary if isinstance(primary, str) else None,
        fallback=tuple(f for f in fallback if isinstance(f, str)) if isinstance(fallback, list) else (),
        requires=frozenset(AGENTS[agent].requires),
        model=model if isinstance(model, str) else None,
        temperature=temperature if isinstance(temperature, (int, float)) and not isinstance(temperature, bool) else None,
        max_tokens=max_tokens if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) else None,
    )


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

        payload = _with_provenance(artifact.to_json(), agent_name, ctxp, state)
        ctx.write_artifact(produces, payload)
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
        revisions = _load_revisions(store, job_id)
        return {"script": store.read_artifact(job_id, "script.json"), "attempt": len(revisions.attempts)}

    def visual_plan_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        return {
            "script": store.read_artifact(job_id, "script.json"),
            "topic": store.read_artifact(job_id, "topic.json") if store.has_artifact(job_id, "topic.json") else {},
            "research": store.read_artifact(job_id, "research.json") if store.has_artifact(job_id, "research.json") else {},
        }

    def storyboard_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        script = store.read_artifact(job_id, "script.json")
        visual_plan = store.read_artifact(job_id, "visual-plan.json") if store.has_artifact(job_id, "visual-plan.json") else {}
        brief = (
            store.read_artifact(job_id, "creative-motion-brief.json")
            if store.has_artifact(job_id, "creative-motion-brief.json")
            else {}
        )
        from ..agents.asset_registry import AssetResolver
        assets_res, _ = AssetResolver.resolve_visual_plan(visual_plan, script) if visual_plan else ({}, [])
        return {
            "script": script,
            "visual_plan": visual_plan,
            "creative_motion_brief": brief,
            "brief": brief,
            "assets": assets_res,
            "fps": 30,
        }
    def metadata_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        # MetadataAgent reads the script; the topic and language come from the job payload, so the
        # title is written in the video's language rather than the operator's.
        return {
            "script": store.read_artifact(job_id, "script.json"),
            "topic": topic,
            "language": language,
        }
    def motion_plan_prompt(_store: JobStore, _job_id: str) -> dict[str, Any]:
        visual_plan = store.read_artifact(job_id, "visual-plan.json") if store.has_artifact(job_id, "visual-plan.json") else {}
        brief = (
            store.read_artifact(job_id, "creative-motion-brief.json")
            if store.has_artifact(job_id, "creative-motion-brief.json")
            else {}
        )
        return {
            "storyboard": store.read_artifact(job_id, "storyboard.json"),
            "visual_plan": visual_plan,
            "creative_motion_brief": brief,
            "brief": brief,
            "previous_style": None,
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
            agent_name="CreativeDirectorAgent",
            stage_state=JobState.CREATIVE_REVIEW,
            produces="visual-plan.json",
            task="visual_plan",
            kwargs_fn=visual_plan_prompt,
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
        stages.append(
            _dynamic_stage(
                state,
                agent_name="AnimationAgent",
                stage_state=JobState.STORYBOARD_READY,
                produces="motion-plan.json",
                task="motion_plan",
                kwargs_fn=motion_plan_prompt,
            )
        )
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
    from .resources import admit_render_stage

    video_dir = _video_dir()
    # The renderer is the job's choice and the stage refuses anything it does not know, so a typo
    # in the payload cannot quietly render with the primary and record a different name.
    return [
        build_asset_stage(state, video_dir=video_dir),
        build_audio_stage(state),
        admit_render_stage(state, build_render_stage(state, video_dir=video_dir, renderer=renderer)),
        _qa_decision_stage(
            build_technical_qc_stage(state),
            lambda artifact, _job_id: artifact.get("passed") is True,
        ),
        _qa_decision_stage(
            build_editorial_qc_stage(state),
            lambda artifact, _job_id: (
                (artifact.get("technical") or {}).get("passed") is True
                and (artifact.get("creative") or {}).get("passed") is True
                and (artifact.get("visual") or {}).get("status") != "failed"
            ),
        ),
        replace(
            build_readiness_stage(state),
            done_when=lambda artifact, job_id: _readiness_current(state.store, job_id, artifact),
        ),
    ]


def _qa_decision_stage(
    stage: Stage, succeeded: Callable[[dict[str, Any], str], bool],
) -> Stage:
    """Reuse passing QA, but preserve an already recorded refusal without another vision call."""
    def run(ctx: StageContext) -> StageOutcome:
        if ctx.store.has_artifact(ctx.job_id, stage.contract_artifact) and stage.contract is not None:
            recorded: dict[str, Any] | None
            try:
                recorded = ctx.store.read_artifact(ctx.job_id, stage.contract_artifact)
                validate_artifact(stage.contract, recorded)
            except (ArtifactValidationError, ValueError, OSError):
                recorded = None
            if recorded is not None and not succeeded(recorded, ctx.job_id):
                reason = recorded.get("reason") or recorded.get("failed") or "recorded QA verdict did not pass"
                raise StageError(
                    "qa_blocked",
                    f"{stage.contract_artifact}: {redact(str(reason))}. "
                    "Explicit rework must invalidate this verdict before another assessment.",
                    retryable=False,
                )
        return stage.run(ctx)

    return replace(stage, run=run, done_when=succeeded)


def _readiness_current(store: JobStore, job_id: str, artifact: dict[str, Any]) -> bool:
    from ..media.qc import sha256_file
    from .editorial import compute_inputs_hash

    if artifact.get("ready") is not True:
        return False
    render = store.read_artifact(job_id, "render.json")
    audio = store.read_artifact(job_id, "audio.json")
    storyboard = store.read_artifact(job_id, "storyboard.json")
    technical = store.read_artifact(job_id, "technical-qc.json")
    expected = compute_inputs_hash(
        render_sha256=str(render.get("sha256") or ""),
        narration_ms=float((audio.get("narration") or {}).get("durationMs") or 0),
        storyboard=storyboard,
    )
    return (
        artifact.get("inputs_sha256") == technical.get("inputs_sha256") == expected
        and sha256_file(store.job_dir(job_id) / "output.mp4") == render.get("sha256")
    )


def _dynamic_stage(state: Any, *, agent_name: str, stage_state: JobState, produces: str,
                   task: str, kwargs_fn: Callable[[JobStore, str], dict[str, Any]]) -> Stage:
    from ..agents.registry import AGENTS as _AGENTS

    agent_inst = _AGENTS[agent_name](_null_context())
    agent_inst.current_task = task
    contract = agent_inst.contract()
    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        job = store.get(job_id)
        # A recorded revise decision is not permission to buy the same review again. The
        # controller consumes its findings; changed scripts explicitly invalidate this file.
        if agent_name == "CreativeDirectorAgent" and produces == "review.json" and store.has_artifact(job_id, produces):
            try:
                recorded = ReviewArtifact.model_validate(store.read_artifact(job_id, produces))
            except (ValueError, OSError):
                recorded = None
            if recorded is not None and recorded.verdict == "revise":
                ctx.write_artifact(produces, recorded.to_json())
                return StageOutcome(
                    ok=True, control="revision_required", artifacts=[produces],
                    detail="creative review requested a revision",
                )
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
            ctx.write_artifact(produces, _with_provenance(artifact.to_json(), agent_name, ctxp, state))
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

        ctx.write_artifact(produces, _with_provenance(artifact.to_json(), agent_name, ctxp, state))
        out_artifacts = [produces]
        if produces == "visual-plan.json":
            brief_dict = _derive_creative_motion_brief(artifact)
            ctx.write_artifact(
                "creative-motion-brief.json",
                _with_provenance(brief_dict, agent_name, ctxp, state),
            )
            out_artifacts.append("creative-motion-brief.json")
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
        return StageOutcome(ok=True, artifacts=out_artifacts)

    return Stage(
        name=agent_name,
        state=stage_state,
        produces=(produces,),
        run=run,
        contract=contract,
        contract_artifact=produces,
        done_when=(
            (lambda artifact, _job_id: artifact.get("verdict") == "accept")
            if (agent_name == "CreativeDirectorAgent" and produces == "review.json") else None
        ),
    )


def _derive_creative_motion_brief(visual_plan: Any) -> dict[str, Any]:
    from ..contracts.artifacts import CreativeMotionBriefArtifact

    if isinstance(visual_plan, dict):
        from ..contracts.artifacts import VisualPlanArtifact

        try:
            visual_plan = VisualPlanArtifact.model_validate(visual_plan)
        except Exception:
            pass

    def _get(obj: Any, *keys: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] is not None:
                    return obj[k]
            return default
        for k in keys:
            v = getattr(obj, k, None)
            if v is not None:
                return v
        return default

    beats = _get(visual_plan, "beats", default=[]) or []
    visual_thesis = _get(
        visual_plan, "visual_thesis", "visualThesis", "reasoning", default=""
    ) or "Educational visual progression for short-form animation."

    theme = _get(visual_plan, "theme", default="editorialLight") or "editorialLight"
    style_intent = _get(visual_plan, "style_intent", "styleIntent")
    if style_intent:
        if isinstance(style_intent, dict) and style_intent.get("theme"):
            theme = style_intent["theme"]
        elif hasattr(style_intent, "model_fields_set") and "theme" in style_intent.model_fields_set:
            theme = style_intent.theme
        elif theme == "editorialLight" and getattr(style_intent, "theme", None):
            theme = style_intent.theme

    primary_motifs: list[str] = list(
        _get(visual_plan, "primary_visual_motifs", "primaryVisualMotifs", default=[]) or []
    )
    reusable: list[str] = list(
        _get(visual_plan, "reusable_motifs", "reusableMotifs", default=[]) or []
    )
    arc_parts: list[str] = []

    for beat in beats:
        subjs = _get(beat, "primarySubjects", "primary_subjects", default=[]) or []
        if isinstance(subjs, str):
            subjs = [p.strip() for p in subjs.split(",") if p.strip()]
        for subj in subjs:
            if subj and subj not in primary_motifs:
                primary_motifs.append(str(subj))

        objs = _get(beat, "requiredObjects", "required_objects", default=[]) or []
        if isinstance(objs, str):
            objs = [p.strip() for p in objs.split(",") if p.strip()]
        for obj in objs:
            if obj and obj not in reusable:
                reusable.append(str(obj))

        concept = _get(beat, "conceptToExplain", "concept_to_explain", "concept", default="")
        if concept:
            arc_parts.append(str(concept))

    narrative_arc = (
        _get(visual_plan, "narrative_arc", "narrativeArc")
        or (" -> ".join(arc_parts) if arc_parts else "Input -> Analysis -> Resolution")
    )
    if not primary_motifs:
        primary_motifs = ["diagram", "conceptNode"]

    art_dir = _get(visual_plan, "art_direction", "artDirection")
    art_dict: dict[str, Any] = {
        "palette": theme,
        "primary_accent": "#0055FF",
        "secondary_accent": "#FF4400",
        "background": "#F8FAFC",
        "typography_style": "boldSans",
    }
    if isinstance(art_dir, dict):
        for k, v in art_dir.items():
            if v is not None:
                art_dict[k] = v
    elif hasattr(art_dir, "model_dump"):
        for k, v in art_dir.model_dump().items():
            if v is not None:
                art_dict[k] = v

    pacing_strategy = (
        _get(visual_plan, "pacing_strategy", "pacingStrategy")
        or "Dynamic pacing matched to visual beats."
    )
    scene_transitions = (
        _get(visual_plan, "scene_transitions", "sceneTransitions")
        or ["cut", "wipe", "slideUp", "zoom"]
    )
    motion_complexity_budget = (
        _get(visual_plan, "motion_complexity_budget", "motionComplexityBudget")
        or "medium"
    )

    brief = CreativeMotionBriefArtifact(
        visual_thesis=visual_thesis,
        art_direction=art_dict,
        narrative_arc=narrative_arc,
        primary_visual_motifs=primary_motifs,
        pacing_strategy=pacing_strategy,
        reusable_motifs=reusable or primary_motifs[:2],
        scene_transitions=scene_transitions,
        motion_complexity_budget=motion_complexity_budget,
    )
    return brief.to_json()


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
    """Run the chain and at most ``MAX_REVISIONS`` durable, evidence-backed script revisions."""
    cancel = cancel or NullCancel()
    try:
        revisions = _load_revisions(state.store, job_id)
    except (ValueError, OSError):
        return _revision_block(
            state, job_id, keeper, "revision_evidence_invalid",
            "Cannot resume: revisions.json is unreadable or violates the revision contract. "
            "Restore the recorded revision evidence before retrying.",
        )
    while True:
        if revisions.attempts and revisions.attempts[-1].phase != "applied":
            stopped = _resume_revision(state, job_id, revisions, keeper=keeper, cancel=cancel)
            if stopped is not None:
                return stopped
        report = run_stages(
            store=state.store, job_id=job_id, stages=build_stages(state, job_id),
            keeper=keeper, cancel=cancel,
        )
        if report.get("stopped") != "revision_required":
            if report["ok"]:
                if not keeper.renew():
                    return {"job_id": job_id, "ok": False, "stopped": "lease_lost", "stages": []}
                state.store.set_error(job_id, "")
            return report
        if len(revisions.attempts) >= MAX_REVISIONS:
            return _revision_block(
                state, job_id, keeper, "revision_limit",
                f"Creative review still requests changes after {MAX_REVISIONS} recorded revisions. "
                "Review the persisted findings before explicit rework.",
            )
        before = ScriptArtifact.model_validate(state.store.read_artifact(job_id, "script.json"))
        review = ReviewArtifact.model_validate(state.store.read_artifact(job_id, "review.json"))
        revisions.attempts.append(RevisionAttempt(
            attempt=len(revisions.attempts) + 1, before_script=before, review=review,
        ))
        # Reserve the attempt and its exact inputs before any paid request. Its identity and the
        # ceiling survive process restarts, including a crash immediately after this commit.
        state.store.commit_stage(
            job_id, token=keeper.token,
            json_artifacts=[("revisions.json", revisions.to_json())],
        )


def _load_revisions(store: JobStore, job_id: str) -> RevisionArtifact:
    if not store.has_artifact(job_id, "revisions.json"):
        return RevisionArtifact()
    return RevisionArtifact.model_validate(store.read_artifact(job_id, "revisions.json"))


def _revision_block(
    state: Any, job_id: str, keeper: LeaseKeeper, code: str, detail: str,
) -> dict[str, Any]:
    if not keeper.renew():
        return {"job_id": job_id, "ok": False, "stopped": "lease_lost", "stages": []}
    current = state.store.get(job_id).state
    state.store.commit_stage(
        job_id, token=keeper.token,
        target=JobState.BLOCKED if current != JobState.BLOCKED else None, detail=detail,
    )
    state.store.set_error(job_id, detail)
    return {
        "job_id": job_id, "ok": False, "stopped": code, "detail": detail,
        "stages": [{"name": "ScriptAgent", "ok": False, "detail": detail}],
    }


def _resume_revision(
    state: Any, job_id: str, revisions: RevisionArtifact, *,
    keeper: LeaseKeeper, cancel: CancelToken,
) -> dict[str, Any] | None:
    store = state.store
    attempt = revisions.attempts[-1]
    if attempt.phase == "unchanged":
        return _revision_block(
            state, job_id, keeper, "revision_unchanged",
            f"ScriptAgent revision {attempt.attempt} did not change authored script content. "
            "The original script and downstream outputs were preserved; review the recorded findings.",
        )
    if not keeper.renew():
        return {"job_id": job_id, "ok": False, "stopped": "lease_lost", "stages": []}
    if cancel.is_cancelled():
        store.commit_stage(job_id, token=keeper.token, target=JobState.CANCELLED,
                           detail="cancelled before applying a revision")
        return {"job_id": job_id, "ok": False, "stopped": "cancelled", "stages": []}
    if attempt.phase == "prepared":
        job = store.get(job_id)
        kwargs = {
            "topic": store.read_artifact(job_id, "topic.json"),
            "duration_s": int(job.payload.get("target_duration_s", 45)),
            "language": job.payload.get("language", "id"),
            "previous_script": attempt.before_script.to_json(),
            "review": attempt.review.to_json(),
            "revision_attempt": attempt.attempt,
        }
        candidate_name = f"revision-{attempt.attempt}-script.json"
        if job.state != JobState.SCRIPT_GENERATED:
            store.commit_stage(job_id, token=keeper.token, target=JobState.SCRIPT_GENERATED,
                               detail=f"ScriptAgent revision {attempt.attempt} resumed")
        stage = _dynamic_stage(
            state, agent_name="ScriptAgent", stage_state=JobState.SCRIPT_GENERATED,
            produces=candidate_name, task="script", kwargs_fn=lambda _store, _job_id: kwargs,
        )
        report = run_stages(
            store=store, job_id=job_id, stages=[stage], keeper=keeper, cancel=cancel,
        )
        if not report["ok"]:
            return report
        candidate = ScriptArtifact.model_validate(store.read_artifact(job_id, candidate_name))
        attempt.candidate_script = candidate
        if candidate.authored_content_hash() == attempt.before_script.authored_content_hash():
            attempt.phase = "unchanged"
        else:
            attempt.phase = "generated"
            downstream = False
            names = {"qa-contact-sheet.jpg", "render-props.json"}
            for stage in build_stages(state, job_id):
                if downstream:
                    names.update(stage.produces)
                if stage.name == "ScriptAgent":
                    downstream = True
            attempt.invalidated_artifacts = sorted(
                name for name in names if store.has_artifact(job_id, name)
            )
        # Candidate content and the invalidation decision are durable before canonical outputs
        # change. A crash from here must finish this same decision, not ask the model again.
        validate_artifact(RevisionArtifact, revisions.to_json())
        store.commit_stage(
            job_id, token=keeper.token,
            json_artifacts=[("revisions.json", revisions.to_json())],
        )
        if attempt.phase == "unchanged":
            return _resume_revision(state, job_id, revisions, keeper=keeper, cancel=cancel)
    if not keeper.renew():
        return {"job_id": job_id, "ok": False, "stopped": "lease_lost", "stages": []}
    if cancel.is_cancelled():
        store.commit_stage(job_id, token=keeper.token, target=JobState.CANCELLED,
                           detail="cancelled before applying a revision")
        return {"job_id": job_id, "ok": False, "stopped": "cancelled", "stages": []}
    if attempt.candidate_script is None:
        raise ArtifactValidationError("revisions", ["generated revision is missing its candidate script"])
    attempt.phase = "applied"
    validate_artifact(RevisionArtifact, revisions.to_json())
    store.commit_stage(
        job_id, token=keeper.token, remove_artifacts=attempt.invalidated_artifacts,
        json_artifacts=[
            ("script.json", attempt.candidate_script.to_json()),
            ("revisions.json", revisions.to_json()),
        ],
        detail=f"ScriptAgent revision {attempt.attempt} applied",
    )
    return None
