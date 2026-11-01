"""Editorial QC: deterministic measurements plus one vision call, composed into the gate verdict.

This module sits in ``orchestration`` because it is the one place that may import both sides of the
graph: ``media`` (ffprobe, detectors, contact sheet) and ``agents`` (the vision pass). Nothing
below it imports upward.

Two responsibilities, kept separate on purpose:

``build_qa_artifact`` / ``build_readiness``
    Pure. Given the three verdicts and a checksum result, produce artifacts that validate. No
    database, no filesystem, no provider — so the gate can be tested exhaustively without a job.

``build_editorial_qc_stage``
    The stage. It measures, calls vision once, writes ``qc.json`` and ``qa-contact-sheet.jpg``,
    then raises ``qa_blocked`` if the verdict is not a pass. It writes the artifact **before**
    raising, so a blocked job still carries the evidence that blocked it.

A blocked gate records a repair with ``action: "blocked"`` and an empty ``artifacts_invalidated``.
That empty list is the truthful statement that nothing was re-authored: re-running a deterministic
black or frozen render cannot converge, so this build has no automatic repair.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..agents.vision import inspect_frames, skip_no_provider
from ..contracts.artifacts import (
    QaArtifact,
    ReadinessArtifact,
    StoryboardArtifact,
    TechnicalQaArtifact,
)
from ..contracts.base import validate_artifact
from ..contracts.state import JobState
from ..media.qc import (
    content_hash,
    evaluate_creative,
    evaluate_technical,
    extract_contact_sheet,
    measure_loudness,
    measure_static,
    run_detectors,
    sha256_file,
    verify_voice_locale,
)
from ..providers.base import Capability, CapabilityMismatch, Provider, ResolvedCall
from ..security.redact import redact
from .runner import Stage, StageContext, StageError, StageOutcome

QA_NAME = "qc.json"
TECHNICAL_NAME = "technical-qc.json"
READINESS_NAME = "readiness.json"
SHEET_NAME = "qa-contact-sheet.jpg"
QC_AGENT = "QualityAgent"
READINESS_AGENT = "DirectorAgent"
REASON_LIMIT = 300


def repair_record(*, target: str, reason: str, attempt: int = 0) -> dict[str, Any]:
    """One recorded decision. ``artifacts_invalidated`` is empty because nothing was rewritten."""
    return {
        "attempt": attempt,
        "target": target,
        "reason": redact(reason, limit=REASON_LIMIT),
        "artifacts_invalidated": [],
        "action": "blocked",
    }


def compute_inputs_hash(
    *, render_sha256: str, narration_ms: float, storyboard: dict[str, Any]
) -> str:
    """Bind a verdict to the exact bytes and timings it judged.

    A re-render changes ``render_sha256``; a re-voiced script changes ``narration_ms``; a retimed
    storyboard changes its own hash. Any of those must expire the verdict rather than leave a pass
    attached to a file that no longer exists.

    The storyboard is canonicalised through its contract first. A raw ``storyboard.json`` and the
    same file re-read as a model differ by the defaults the contract fills in, so hashing the raw
    dict in one place and the model in another would produce two different "input hashes" for the
    same job — and the gate would refuse its own stage's artifact.

    ``Artifact.content_hash`` is used rather than ``model_dump`` because it already excludes
    ``created_at``, which the base class stamps with the current whole second. Hashing that field
    made the verdict depend on the clock: 40 identical calls produced 3 distinct hashes, so the
    gate could refuse a correct job at 12:00:01 for a verdict computed at 12:00:00 — and, worse,
    a stale verdict recomputed within the same second would match. One rule, defined once, in the
    class whose docstring states it.
    """
    try:
        digest = StoryboardArtifact.model_validate(storyboard).content_hash()
    except Exception:  # noqa: BLE001 - an invalid storyboard still needs a stable hash
        digest = content_hash(storyboard)
    return content_hash(
        {
            "render_sha256": render_sha256,
            "narration_ms": round(float(narration_ms), 3),
            "storyboard": digest,
        }
    )


def build_qa_artifact(
    *,
    technical: dict[str, Any],
    creative: dict[str, Any],
    visual: dict[str, Any],
    repairs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose ``qc.json``. The technical block is a summary; the detail lives in technical-qc.json."""
    payload = {
        "schema_version": 1,
        "technical": {
            "passed": bool(technical.get("passed")),
            "failed": list(technical.get("failed") or []),
            "reason": str(technical.get("reason") or ""),
            "checks": dict(technical.get("checks") or {}),
        },
        "creative": {
            "passed": bool(creative.get("passed")),
            "metrics": dict(creative.get("metrics") or {}),
            "thresholds": dict(creative.get("thresholds") or {}),
            "failed": list(creative.get("failed") or []),
            "reason": str(creative.get("reason") or ""),
        },
        "visual": {
            "status": str(visual.get("status")),
            "provider": visual.get("provider"),
            "frames_extracted": int(visual.get("frames_extracted") or 0),
            "frames_inspected": int(visual.get("frames_inspected") or 0),
            "findings": list(visual.get("findings") or []),
            "model": str(visual.get("model") or ""),
            "reason": str(visual.get("reason") or ""),
        },
        "repairs": list(repairs),
    }
    validate_artifact(QaArtifact, payload)
    return payload


def build_readiness(
    *,
    technical: dict[str, Any],
    creative: dict[str, Any],
    visual: dict[str, Any],
    checksum_valid: bool,
    inputs_sha256: str,
) -> dict[str, Any]:
    """The gate verdict. Every blocker is named, not just the first one found."""
    technical_ok = bool(technical.get("passed"))
    creative_ok = bool(creative.get("passed"))
    visual_status = str(visual.get("status"))
    visual_ok = visual_status != "failed"
    checks = {
        "technical": technical_ok,
        "creative": creative_ok,
        "visual": visual_ok,
        "checksum": bool(checksum_valid),
    }
    blockers = sorted(name for name, ok in checks.items() if not ok)
    payload = {
        "schema_version": 1,
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "technical_passed": technical_ok,
        "creative_passed": creative_ok,
        "visual_status": visual_status,
        "inputs_sha256": inputs_sha256,
        "reason": "ready for operator approval" if not blockers else "blocked: " + ", ".join(blockers),
    }
    validate_artifact(ReadinessArtifact, payload)
    return payload


# -- the stages --------------------------------------------------------------------------------


def _storyboard(job_dir: Path) -> dict[str, Any]:
    """The timed props, which is what the renderer consumed."""
    path = job_dir / "render-props.json"
    if path.is_file():
        props_payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        body = props_payload.get("storyboard")
        return body if isinstance(body, dict) else props_payload
    text = (job_dir / "storyboard.json").read_text(encoding="utf-8")
    storyboard: dict[str, Any] = json.loads(text)
    return storyboard


def _detectors(path: Path) -> dict[str, Any]:
    return {name: result.to_json() for name, result in run_detectors(path).items()}


def _vision_call(state: Any, job: Any) -> tuple[ResolvedCall, Provider] | None:
    """Resolve a vision-capable provider, or ``None`` when the configuration has none.

    Resolution goes through the same ``resolve_call`` every other call uses, so the capability
    filter and the credential path are identical. ``CapabilityMismatch``/``NoProviderAvailable``
    are the expected answers when the operator has configured no sight: that is a skip, not a
    failure. Resolution happens before any request, which is why a text-only provider can never
    be asked to look at a frame.
    """
    from ..providers.base import NoProviderAvailable
    from ..providers.resolve import Binding, resolve_call
    from ..providers.usage import RecordingProvider

    requires = frozenset({Capability.CHAT, Capability.VISION})
    override = getattr(state, "bindings", {}).get(QC_AGENT) if hasattr(state, "bindings") else None
    override = override if isinstance(override, dict) else None
    model = override.get("model") if override else None
    temperature = override.get("temperature") if override else None
    max_tokens = override.get("max_tokens") if override else None
    binding = Binding(
        agent=QC_AGENT,
        primary=_primary_for(state),
        fallback=(),
        requires=requires,
        model=model if isinstance(model, str) else None,
        temperature=temperature if isinstance(temperature, (int, float)) and not isinstance(temperature, bool) else None,
        max_tokens=max_tokens if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) else None,
    )
    try:
        call, transport = resolve_call(
            binding=binding,
            registry=state.registry,
            store=state.secrets,
            transports=state.transports,
            allow_mock_fallback=False,
        )
    except (CapabilityMismatch, NoProviderAvailable):
        return None
    spec = state.registry.specs.get(call.provider)
    recorder = RecordingProvider(
        transport,
        tracker=state.usage,
        agent=QC_AGENT,
        job_id=getattr(job, "id", None),
        price_in=spec.price_in_per_mtok if spec else None,
        price_out=spec.price_out_per_mtok if spec else None,
    )
    return call, recorder


def _primary_for(state: Any) -> str | None:
    """The same binding precedence the pipeline uses, without importing it."""
    bindings = getattr(state, "bindings", {}) or {}
    override = bindings.get(QC_AGENT) if isinstance(bindings, dict) else None
    if override:
        primary: object = override.get("primary")
        return primary if isinstance(primary, str) else None
    for spec in state.registry.enabled():
        if spec.transport != "mock":
            spec_id: object = spec.id
            return spec_id if isinstance(spec_id, str) else None
    return "mock" if state.registry.specs.get("mock") else None


def build_editorial_qc_stage(state: Any) -> Stage:
    """``EDITORIAL_QC``: measure, inspect, write ``qc.json`` + the sheet, then gate.

    Not wired into ``pipeline._render_stages`` yet — that file is owned by the audio work. The
    builder is complete so the wiring is a one-line append when the file is free.
    """

    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        from .pipeline import _emit  # local import: pipeline imports runner

        _emit(state, job_id, JobState.EDITORIAL_QC.value, "stage_started", "QualityAgent mulai",
              agent=QC_AGENT)
        job_dir = Path(store.job_dir(job_id))
        job = store.get(job_id)
        try:
            props = _storyboard(job_dir)
            audio = store.read_artifact(job_id, "audio.json")
            storyboard = store.read_artifact(job_id, "storyboard.json")
            job_lang = str(job.payload.get("language") or "id")
            locale_ok, locale_err = verify_voice_locale(audio, language=job_lang)
            if not locale_ok:
                raise RuntimeError(f"Voice locale check failed: {locale_err}")
            render = store.read_artifact(job_id, "render.json")
            technical = store.read_artifact(job_id, TECHNICAL_NAME)
            video = job_dir / str(render.get("src") or "output.mp4")

            narration_ms = float((audio.get("narration") or {}).get("durationMs") or 0)
            inputs_sha256 = compute_inputs_hash(
                render_sha256=str(render.get("sha256") or ""),
                narration_ms=narration_ms,
                storyboard=storyboard,
            )

            static_seconds, _ = measure_static(video)
            creative = evaluate_creative(
                props={"storyboard": props},
                audio=audio,
                review=_optional(store, job_id, "review.json"),
                script=_optional(store, job_id, "script.json"),
                assets=_optional(store, job_id, "assets.json"),
                static_seconds=static_seconds,
                history=_history(store, job_id),
            ).as_creative()

            sheet_path = ctx.alloc(SHEET_NAME)
            try:
                _, frames_extracted = extract_contact_sheet(video, {"storyboard": props}, sheet_path)
            except RuntimeError as exc:
                frames_extracted = 0
                sheet_note = redact(str(exc), limit=200)
            else:
                sheet_note = ""

            resolved = _vision_call(state, job)
            if resolved is None:
                visual = skip_no_provider(frames_extracted=frames_extracted).to_json()
            elif frames_extracted == 0:
                visual = {
                    "status": "failed",
                    "provider": resolved[0].provider,
                    "frames_extracted": 0,
                    "frames_inspected": 0,
                    "findings": [
                        {"atMs": 0, "issue": f"contact sheet unavailable: {sheet_note}", "severity": "blocker"}
                    ],
                    "model": resolved[0].model,
                    "reason": "no contact sheet could be produced",
                }
            else:
                from ..providers.base import VisionImage

                images = [VisionImage(data=sheet_path.read_bytes(), media_type="image/jpeg")]
                visual = inspect_frames(
                    call=resolved[0],
                    provider=resolved[1],
                    images=images,
                    storyboard={"storyboard": props},
                ).to_json()

            checksum_valid = sha256_file(video) == str(render.get("sha256") or "")
            readiness = build_readiness(
                technical=technical,
                creative=creative,
                visual=visual,
                checksum_valid=checksum_valid,
                inputs_sha256=inputs_sha256,
            )
            repairs = [
                repair_record(
                    target=blocker,
                    reason=_blocker_reason(blocker, technical, creative, visual, checksum_valid),
                )
                for blocker in readiness["blockers"]
            ]

            qa = build_qa_artifact(
                technical=technical, creative=creative, visual=visual, repairs=repairs
            )
            ctx.write_artifact(QA_NAME, qa)
        except StageError:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure here is a QC failure, not a crash
            detail = redact(f"{type(exc).__name__}: {exc}", limit=400)
            _emit(state, job_id, JobState.EDITORIAL_QC.value, "failed", detail, agent=QC_AGENT)
            raise StageError("qa_blocked", detail, retryable=False) from exc

        if not readiness["ready"]:
            reason = "editorial QC failed: " + ", ".join(readiness["blockers"])
            _emit(state, job_id, JobState.EDITORIAL_QC.value, "blocked", reason, agent=QC_AGENT)
            raise StageError("qa_blocked", reason, retryable=False)

        _emit(
            state,
            job_id,
            JobState.EDITORIAL_QC.value,
            "stage_completed",
            "QualityAgent selesai",
            agent=QC_AGENT,
            progress=1.0,
        )
        if sheet_path.is_file():
            ctx.stage_file(SHEET_NAME, sheet_path)
        return StageOutcome(ok=True, artifacts=[QA_NAME, SHEET_NAME])

    return Stage(
        name=QC_AGENT,
        state=JobState.EDITORIAL_QC,
        produces=(QA_NAME,),
        run=run,
        contract=QaArtifact,
        contract_artifact=QA_NAME,
    )


def build_technical_qc_stage(state: Any) -> Stage:
    """``TECHNICAL_QC``: measure the file, write ``technical-qc.json``, then gate.

    The artifact is written **before** the failure is raised. A blocked job that carries no
    measurement is a job the operator has to re-run blind.

    Not wired into ``pipeline._render_stages`` yet — that file is owned by the in-flight audio
    work. The builder is complete and tested, so wiring is a one-line append.
    """

    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        from .pipeline import _emit  # local import: pipeline imports runner

        _emit(state, job_id, JobState.TECHNICAL_QC.value, "stage_started", "QualityAgent mulai",
              agent=QC_AGENT)
        job_dir = Path(store.job_dir(job_id))
        try:
            render = store.read_artifact(job_id, "render.json")
            video = job_dir / str(render.get("src") or "output.mp4")
            props_path = job_dir / "render-props.json"
            props = (
                json.loads(props_path.read_text(encoding="utf-8"))
                if props_path.is_file()
                else {"storyboard": store.read_artifact(job_id, "storyboard.json")}
            )
            audio = store.read_artifact(job_id, "audio.json")
            from ..media.render import probe_media

            probe = probe_media(video)
        except Exception as exc:  # noqa: BLE001 - an unreadable input is a QC failure
            detail = redact(f"{type(exc).__name__}: {exc}", limit=400)
            _emit(state, job_id, JobState.TECHNICAL_QC.value, "failed", detail, agent=QC_AGENT)
            raise StageError("qa_blocked", f"cannot probe the render: {detail}", retryable=False) from exc

        try:
            verdict = evaluate_technical(
                probe=probe,
                props=props,
                audio=audio,
                detectors=run_detectors(video),
                loudness=measure_loudness(video),
                sha256=sha256_file(video),
                render=render,
            )
        except Exception as exc:  # noqa: BLE001 - a measurement failure is not a pass
            detail = redact(f"{type(exc).__name__}: {exc}", limit=400)
            _emit(state, job_id, JobState.TECHNICAL_QC.value, "failed", detail, agent=QC_AGENT)
            raise StageError("qa_blocked", f"technical measurement failed: {detail}", retryable=False) from exc

        narration_ms = float((audio.get("narration") or {}).get("durationMs") or 0)
        payload = verdict.as_technical()
        payload["inputs_sha256"] = compute_inputs_hash(
            render_sha256=str(render.get("sha256") or ""),
            narration_ms=narration_ms,
            storyboard=store.read_artifact(job_id, "storyboard.json"),
        )
        validate_artifact(TechnicalQaArtifact, payload)
        ctx.write_artifact(TECHNICAL_NAME, payload)

        if not verdict.passed:
            reason = "technical QC failed: " + ", ".join(verdict.failed)
            _emit(state, job_id, JobState.TECHNICAL_QC.value, "blocked", reason, agent=QC_AGENT)
            raise StageError("qa_blocked", reason, retryable=False)

        _emit(
            state,
            job_id,
            JobState.TECHNICAL_QC.value,
            "stage_completed",
            "QualityAgent selesai",
            agent=QC_AGENT,
            progress=1.0,
        )
        return StageOutcome(ok=True, artifacts=[TECHNICAL_NAME])

    return Stage(
        name=QC_AGENT,
        state=JobState.TECHNICAL_QC,
        produces=(TECHNICAL_NAME,),
        run=run,
        contract=TechnicalQaArtifact,
        contract_artifact=TECHNICAL_NAME,
    )


def build_readiness_stage(state: Any) -> Stage:
    """``READY_FOR_APPROVAL``: recompute the bindings from disk and write ``readiness.json``.

    This is the DirectorAgent gate. It does not re-score anything: it re-reads ``render.json``,
    ``audio.json``, ``storyboard.json``, ``technical-qc.json`` and ``qc.json``, recomputes the
    input hash from the bytes on disk, and refuses to certify a job whose artifacts have drifted
    since the editorial stage wrote them.

    Why a separate stage rather than letting the editorial stage write the verdict:

    - ``TECHNICAL_QC -> READY_FOR_APPROVAL`` is not in the allow-list, so an editorial stage that
      declared ``READY_FOR_APPROVAL`` could never be validated; and a stage that stays at
      ``EDITORIAL_QC`` never advances the job there at all, because the runner transitions only
      to ``stage.state``.
    - The stage that decided the creative score must not also certify that its own decision is
      safe to approve. Recomputing from the files is the cheapest second opinion available, and
      the approval gate then recomputes a third time.
    """

    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        from .pipeline import _emit  # local import: pipeline imports runner

        _emit(state, job_id, JobState.READY_FOR_APPROVAL.value, "stage_started",
              "DirectorAgent memeriksa kelayakan", agent=READINESS_AGENT)
        job_dir = Path(store.job_dir(job_id))
        try:
            render = store.read_artifact(job_id, "render.json")
            audio = store.read_artifact(job_id, "audio.json")
            storyboard = store.read_artifact(job_id, "storyboard.json")
            technical = store.read_artifact(job_id, TECHNICAL_NAME)
            qa = store.read_artifact(job_id, QA_NAME)
            video = job_dir / str(render.get("src") or "output.mp4")
            narration_ms = float((audio.get("narration") or {}).get("durationMs") or 0)
            expected = compute_inputs_hash(
                render_sha256=str(render.get("sha256") or ""),
                narration_ms=narration_ms,
                storyboard=storyboard,
            )
            checksum_valid = sha256_file(video) == str(render.get("sha256") or "")
        except Exception as exc:  # noqa: BLE001 - unreadable evidence is a blocked gate
            detail = redact(f"{type(exc).__name__}: {exc}", limit=400)
            _emit(state, job_id, JobState.READY_FOR_APPROVAL.value, "failed", detail,
                  agent=READINESS_AGENT)
            raise StageError("qa_blocked", f"cannot read the QC evidence: {detail}",
                             retryable=False) from exc

        readiness = build_readiness(
            technical=technical,
            creative=qa.get("creative") or {},
            visual=qa.get("visual") or {},
            checksum_valid=checksum_valid,
            inputs_sha256=expected,
        )
        # A stage whose inputs have drifted must not certify. ``technical-qc.json`` is the
        # artifact that records a measurement together with the hash of what it measured, so it
        # is the authoritative binding; ``qc.json`` carries verdicts only and no hash, which is
        # why it is not consulted here.
        recorded = technical.get("inputs_sha256")
        if isinstance(recorded, str) and recorded and recorded != expected:
            readiness = build_readiness(
                technical={**technical, "passed": False},
                creative=qa.get("creative") or {},
                visual=qa.get("visual") or {},
                checksum_valid=False,
                inputs_sha256=expected,
            )
            readiness["blockers"] = sorted(set(readiness["blockers"]) | {"inputs_drifted"})
            readiness["ready"] = False
            readiness["reason"] = "blocked: " + ", ".join(readiness["blockers"])
        ctx.write_artifact(READINESS_NAME, readiness)

        if not readiness["ready"]:
            reason = "not ready for approval: " + ", ".join(readiness["blockers"])
            _emit(state, job_id, JobState.READY_FOR_APPROVAL.value, "blocked", reason,
                  agent=READINESS_AGENT)
            raise StageError("qa_blocked", reason, retryable=False)

        _emit(
            state,
            job_id,
            JobState.READY_FOR_APPROVAL.value,
            "stage_completed",
            "DirectorAgent selesai",
            agent=READINESS_AGENT,
            progress=1.0,
        )
        return StageOutcome(ok=True, artifacts=[READINESS_NAME])

    return Stage(
        name=READINESS_AGENT,
        state=JobState.READY_FOR_APPROVAL,
        produces=(READINESS_NAME,),
        run=run,
        contract=ReadinessArtifact,
        contract_artifact=READINESS_NAME,
    )


def _optional(store: Any, job_id: str, name: str) -> dict[str, Any] | None:
    try:
        artifact: dict[str, Any] = store.read_artifact(job_id, name)
        return artifact
    except Exception:  # noqa: BLE001 - an absent optional input is a missing check, not a crash
        return None


def _history(store: Any, job_id: str) -> list[dict[str, Any]]:
    """Style signatures of up to ten prior rendered jobs, newest first.

    Only jobs with both ``render-props.json`` and ``render.json`` count: an unrendered job has no
    style to compare against. The signature is built by ``media.qc._style_signature`` — the same
    function ``evaluate_creative`` compares against — so the two cannot drift. An earlier version
    rebuilt the shot token from ``dict.values()``, which depends on JSON key order and would have
    silently compared ``wide/pushIn`` against ``pushIn/wide``.
    """
    from ..media.qc import _style_signature

    signatures: list[dict[str, Any]] = []
    try:
        root = Path(store.job_dir(job_id)).parent
        candidates = sorted(
            (path for path in root.iterdir() if path.is_dir() and path.name != job_id),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            props_path = candidate / "render-props.json"
            if not props_path.is_file() or not (candidate / "render.json").is_file():
                continue
            try:
                payload = json.loads(props_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            signatures.append(_style_signature(payload))
            if len(signatures) >= 10:
                break
    except OSError:
        return []
    return signatures


def _blocker_reason(
    blocker: str,
    technical: dict[str, Any],
    creative: dict[str, Any],
    visual: dict[str, Any],
    checksum_valid: bool,
) -> str:
    if blocker == "technical":
        return "technical checks failed: " + ", ".join(technical.get("failed") or ["unknown"])
    if blocker == "creative":
        return "creative checks failed: " + ", ".join(creative.get("failed") or ["unknown"])
    if blocker == "visual":
        issues = [item.get("issue") for item in visual.get("findings") or [] if isinstance(item, dict)]
        return "visual QC failed: " + "; ".join(str(issue) for issue in issues[:3] or ["unknown"])
    if blocker == "checksum":
        return "output.mp4 does not match render.json.sha256"
    return f"{blocker} failed"


__all__ = [
    "QA_NAME",
    "READINESS_AGENT",
    "READINESS_NAME",
    "SHEET_NAME",
    "TECHNICAL_NAME",
    "build_editorial_qc_stage",
    "build_qa_artifact",
    "build_readiness_stage",
    "build_technical_qc_stage",
    "build_readiness",
    "compute_inputs_hash",
    "repair_record",
]
