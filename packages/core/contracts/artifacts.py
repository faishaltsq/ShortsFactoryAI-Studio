"""Every artifact an agent may produce.

One file, because the whole point is that the vocabulary is visible in one place. Each model
carries ``kind`` so a file on disk can prove what it claims to be.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .base import Artifact
from .scene import SceneSpec, SubtitleCue

ContentKind = Literal["factual", "fictional"]
ProviderMode = Literal["live", "mock"]
RendererId = Literal["remotion", "bang-motion"]


class ResearchArtifact(Artifact):
    kind = "research"

    topic: str = Field(min_length=1)
    content_kind: ContentKind = "factual"
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _factual_needs_sources(self) -> ResearchArtifact:
        # A factual script with no source cannot be verified later, so it cannot be produced.
        if self.content_kind == "factual" and not self.sources:
            raise ValueError("factual research requires at least one source")
        return self


class ScriptArtifact(Artifact):
    kind = "script"

    hook: str = Field(min_length=1, max_length=400)
    segments: list[dict[str, Any]] = Field(min_length=1)
    cta: str = ""
    content_kind: ContentKind = "factual"
    #: Provenance (prompt_sha256, producer, provider, model) lives on the Artifact base and is
    #: attached by the code that made the call — never written by the model.

    @model_validator(mode="after")
    def _segments_have_ids(self) -> ScriptArtifact:
        seen: set[str] = set()
        for segment in self.segments:
            sid = segment.get("id")
            if not sid:
                raise ValueError("every script segment needs an id")
            if sid in seen:
                raise ValueError(f"duplicate segment id {sid!r}")
            seen.add(sid)
        return self


class ReviewArtifact(Artifact):
    kind = "review"

    verdict: Literal["accept", "revise"] = "revise"
    scores: dict[str, float] = Field(default_factory=dict)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    attempt: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _revise_needs_findings(self) -> ReviewArtifact:
        if self.verdict == "revise" and not self.findings:
            raise ValueError("a revise verdict must state at least one finding")
        return self


class StoryboardArtifact(Artifact):
    kind = "storyboard"

    fps: int = Field(default=30, ge=1, le=60)
    width: int = Field(default=1080, ge=16)
    height: int = Field(default=1920, ge=16)
    theme: str = "dusk"
    scenes: list[SceneSpec] = Field(min_length=1)
    subtitles: list[SubtitleCue] = Field(default_factory=list)

    @model_validator(mode="after")
    def _contiguous_scenes(self) -> StoryboardArtifact:
        expected = 0
        for scene in self.scenes:
            if scene.startFrame != expected:
                raise ValueError(
                    f"scene {scene.sceneId!r} starts at {scene.startFrame}, expected {expected}"
                )
            expected += scene.durationInFrames
        return self

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> StoryboardArtifact:
        ids = [scene.sceneId for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene ids must be unique")
        return self

    @property
    def total_frames(self) -> int:
        return sum(scene.durationInFrames for scene in self.scenes)


class MotionPlanArtifact(Artifact):
    kind = "motion-plan"

    renderer: RendererId = "remotion"
    style_brief: dict[str, Any] = Field(default_factory=dict)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    anti_patterns_checked: list[str] = Field(default_factory=list)


class AssetsArtifact(Artifact):
    kind = "assets"

    characters: list[dict[str, Any]] = Field(default_factory=list)
    backgrounds: list[dict[str, Any]] = Field(default_factory=list)
    audio: list[dict[str, Any]] = Field(default_factory=list)
    manifest_sha256: str = ""

    @model_validator(mode="after")
    def _licences_present(self) -> AssetsArtifact:
        for group in ("backgrounds", "audio"):
            for item in getattr(self, group):
                if not item.get("license"):
                    raise ValueError(f"{group} asset {item.get('id')!r} has no license")
        return self


class AudioArtifact(Artifact):
    kind = "audio"

    narration: dict[str, Any] = Field(default_factory=dict)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    subtitles: list[SubtitleCue] = Field(default_factory=list)
    mix: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _timings_inside_narration(self) -> AudioArtifact:
        duration = self.narration.get("durationMs")
        if not isinstance(duration, int) or duration <= 0:
            raise ValueError("narration.durationMs must be a positive integer")
        if not isinstance(self.narration.get("src"), str) or not self.narration.get("src"):
            raise ValueError("narration.src is required")
        if not isinstance(self.narration.get("voice"), str) or not self.narration.get("voice"):
            raise ValueError("narration.voice is required")
        if not self.scenes:
            raise ValueError("scene timings must cover the narration")
        last_end = 0
        for scene in self.scenes:
            start, end = scene.get("startMs"), scene.get("endMs")
            if not isinstance(start, int) or not isinstance(end, int) or start != last_end or end <= start or end > duration:
                raise ValueError("scene timings must be contiguous inside narration duration")
            last_end = end
        if last_end != duration:
            raise ValueError("scene timings must cover the whole narration duration")
        cue_end = 0
        for cue in self.subtitles:
            if cue.startMs < cue_end or cue.endMs > duration:
                raise ValueError("subtitle cues must be ordered and inside narration duration")
            cue_end = cue.endMs
        return self


class RenderArtifact(Artifact):
    kind = "render"

    src: str = "output.mp4"
    sha256: str = Field(min_length=64, max_length=64)
    bytes: int = Field(ge=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    frames: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    video_codec: str = "h264"
    #: None for a silent render. A file with no audio stream has no audio codec, and claiming
    #: "aac" would describe an intent rather than the bytes on disk.
    audio_codec: str | None = None
    pix_fmt: str = "yuv420p"
    renderer: RendererId = "remotion"
    renderer_version: str = ""
    scene_hashes: dict[str, str] = Field(default_factory=dict)


VisualStatus = Literal["passed", "failed", "skipped_no_vision_provider"]

#: A repair is a recorded decision, never a hidden retry. ``blocked`` is the only automatic
#: outcome this build can produce: re-running a deterministic black or frozen render cannot
#: converge, so an automatic repair loop would spend time to reach the same failure.
REPAIR_ACTIONS = frozenset({"blocked", "rerendered", "re-authored"})


class TechnicalQaArtifact(Artifact):
    """FR-7.1, measured. One boolean per check, plus the value it was judged against.

    ``passed`` is not free-standing: the validator recomputes it from ``checks`` and ``failed``.
    That is the whole point — the artifact in ``data/jobs/4145e5b9e03c87d7/qc.json`` claimed
    ``technical.passed: true`` while carrying no detector results at all, and nothing in the
    contract could object.
    """

    kind = "technical-qc"

    passed: bool = False
    checks: dict[str, bool] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, str] = Field(default_factory=dict)
    failed: list[str] = Field(default_factory=list)
    detectors: dict[str, dict[str, Any]] = Field(default_factory=dict)
    inputs_sha256: str = Field(default="", min_length=64, max_length=64)
    reason: str = ""

    @field_validator("checks", mode="before")
    @classmethod
    def _checks_are_booleans(cls, value: Any) -> Any:
        """Lax bool coercion turns ``"yes"`` into ``True``. A check is a measurement, not a vibe."""
        if isinstance(value, dict):
            bad = sorted(name for name, item in value.items() if not isinstance(item, bool))
            if bad:
                raise ValueError(f"technical checks must be booleans, got non-boolean for {bad}")
        return value

    @model_validator(mode="after")
    def _thresholds_are_recorded(self) -> TechnicalQaArtifact:
        if not self.thresholds:
            raise ValueError("technical QC must record the thresholds it was judged against")
        return self

    @model_validator(mode="after")
    def _passed_matches_the_checks(self) -> TechnicalQaArtifact:
        if not self.passed:
            return self
        if self.failed:
            raise ValueError(
                f"technical QC cannot claim passed=true while naming failures: {self.failed}"
            )
        untrue = sorted(name for name, ok in self.checks.items() if not ok)
        if untrue:
            raise ValueError(
                f"technical QC cannot claim passed=true with failing checks: {untrue}"
            )
        return self


class ReadinessArtifact(Artifact):
    """The gate verdict, recomputed from the artifacts rather than copied from them.

    ``READY_FOR_APPROVAL`` is entered only when this artifact says ``ready``. It carries the input
    hashes so a re-render invalidates a stale verdict instead of leaving a pass attached to bytes
    that no longer exist.
    """

    kind = "readiness"

    ready: bool = False
    checks: dict[str, bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    technical_passed: bool = False
    creative_passed: bool = False
    visual_status: VisualStatus = "skipped_no_vision_provider"
    inputs_sha256: str = Field(default="", min_length=64, max_length=64)
    reason: str = ""

    @model_validator(mode="after")
    def _ready_matches_its_evidence(self) -> ReadinessArtifact:
        if not self.ready:
            return self
        if self.blockers:
            raise ValueError(f"readiness cannot be true while blockers remain: {self.blockers}")
        untrue = sorted(name for name, ok in self.checks.items() if not ok)
        if untrue:
            raise ValueError(f"readiness cannot be true with failing checks: {untrue}")
        if not self.technical_passed:
            raise ValueError("readiness cannot be true when technical QC did not pass")
        if not self.creative_passed:
            raise ValueError("readiness cannot be true when creative QC did not pass")
        if self.visual_status == "failed":
            raise ValueError("readiness cannot be true when visual QC failed")
        return self


class QaArtifact(Artifact):
    kind = "qa"

    technical: dict[str, Any] = Field(default_factory=dict)
    creative: dict[str, Any] = Field(default_factory=dict)
    visual: dict[str, Any] = Field(default_factory=dict)
    repairs: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _visual_status_is_explicit(self) -> QaArtifact:
        status = self.visual.get("status")
        allowed = {"passed", "failed", "skipped_no_vision_provider"}
        if status not in allowed:
            raise ValueError(
                f"visual.status must be one of {sorted(allowed)}; got {status!r}. "
                "A missing status is not a pass."
            )
        return self

    @model_validator(mode="after")
    def _technical_pass_is_explicit(self) -> QaArtifact:
        if not isinstance(self.technical.get("passed"), bool):
            raise ValueError(
                "technical.passed must be an explicit boolean; a missing pass is not a pass"
            )
        return self

    @model_validator(mode="after")
    def _creative_pass_is_explicit_and_measured(self) -> QaArtifact:
        if not isinstance(self.creative.get("passed"), bool):
            raise ValueError(
                "creative.passed must be an explicit boolean; a missing pass is not a pass"
            )
        metrics = self.creative.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError(
                "creative.metrics must carry the measured values a verdict was based on"
            )
        return self

    @model_validator(mode="after")
    def _visual_counts_are_consistent(self) -> QaArtifact:
        status = self.visual.get("status")
        inspected = self.visual.get("frames_inspected")
        if not isinstance(inspected, int) or inspected < 0:
            raise ValueError("visual.frames_inspected must be a non-negative integer")
        if status == "passed" and inspected < 1:
            raise ValueError(
                "visual.status=passed requires frames_inspected >= 1; a provider that saw "
                "nothing cannot pass"
            )
        if status == "skipped_no_vision_provider":
            if inspected != 0:
                raise ValueError(
                    "visual.status=skipped_no_vision_provider requires frames_inspected == 0"
                )
            if self.visual.get("provider") is not None:
                raise ValueError(
                    "visual.status=skipped_no_vision_provider cannot name a provider"
                )
        return self

    @model_validator(mode="after")
    def _repairs_are_well_formed(self) -> QaArtifact:
        for index, record in enumerate(self.repairs):
            if not isinstance(record, dict):
                raise ValueError(f"repairs[{index}] must be an object")
            missing = [
                key
                for key in ("attempt", "target", "reason", "artifacts_invalidated", "action")
                if key not in record
            ]
            if missing:
                raise ValueError(f"repairs[{index}] is missing {missing}")
            if record["action"] not in REPAIR_ACTIONS:
                raise ValueError(
                    f"repairs[{index}].action must be one of {sorted(REPAIR_ACTIONS)}; "
                    f"got {record['action']!r}"
                )
            if not isinstance(record["artifacts_invalidated"], list):
                raise ValueError(f"repairs[{index}].artifacts_invalidated must be a list")
        return self


class ApprovalArtifact(Artifact):
    kind = "approval"

    decision: Literal["approved", "rejected"]
    operator: str = Field(min_length=1)
    reason: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)
    decided_at: str = ""
    #: The render this decision was made about. Recorded so a stale approval cannot authorise a
    #: different file: ``JobStore.transition`` refuses ``APPROVED`` when this does not match
    #: ``render.json.sha256`` at transition time. Optional because an artifact written before this
    #: field existed must still parse — and it is then refused at the transition, not here.
    render_sha256: str | None = None

    @model_validator(mode="after")
    def _rejection_has_reason(self) -> ApprovalArtifact:
        if self.decision == "rejected" and not (self.reason or "").strip():
            raise ValueError("a rejection must state a reason")
        return self

    @property
    def publishable(self) -> bool:
        return bool(self.decision == "approved" and self.checks.get("publishable"))


class MetadataArtifact(Artifact):
    kind = "metadata"

    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list)
    category_id: str = "22"
    made_for_kids: bool = False
    synthetic_media: bool = True
    thumbnail: dict[str, Any] = Field(default_factory=dict)


class PublicationArtifact(Artifact):
    kind = "publication"

    phase: Literal["initiating", "uncertain", "confirmed", "scheduled"] = "initiating"
    video_id: str | None = None
    privacy: Literal["private", "unlisted", "public"] = "private"
    publish_at: str | None = None
    receipts: list[dict[str, Any]] = Field(default_factory=list)
    #: Derived from ``render.json.sha256`` plus the job id, so a re-run cannot mint a new one.
    #: This is what makes an upload idempotent: the same key means the same bytes.
    idempotency_key: str = Field(min_length=16)
    #: How many insert attempts have been made. Incremented only when a request may have left.
    attempt: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _public_needs_confirmation_receipt(self) -> PublicationArtifact:
        if self.privacy == "public":
            confirmed = any(r.get("step") == "public_confirm" and r.get("ok") for r in self.receipts)
            if not confirmed:
                raise ValueError("a public publication needs a public_confirm receipt")
        return self

    @model_validator(mode="after")
    def _uncertain_must_say_what_it_sent(self) -> PublicationArtifact:
        """``uncertain`` means "a request may have left and we do not know the outcome".

        That claim is only actionable if it carries the evidence: an ``insert_sent`` receipt with
        a timestamp and the payload that was sent. Without it an operator cannot reconcile, and a
        retry would be a blind duplicate — exactly what FR-8.3 forbids.
        """
        if self.phase != "uncertain":
            return self
        sent = [r for r in self.receipts if r.get("step") == "insert_sent"]
        if not sent:
            raise ValueError(
                "an uncertain publication needs an insert_sent receipt recording that the "
                "request may have left; without it the record is not actionable"
            )
        receipt = sent[-1]
        if not str(receipt.get("at") or "").strip():
            raise ValueError("an insert_sent receipt must record 'at' (when the request left)")
        if not isinstance(receipt.get("sent"), dict) or not receipt["sent"]:
            raise ValueError(
                "an insert_sent receipt must record 'sent' (what was sent), so a reconciliation "
                "can match it against the remote channel"
            )
        return self

    @model_validator(mode="after")
    def _confirmed_needs_a_video_id(self) -> PublicationArtifact:
        """``confirmed`` asserts a video exists; without an id that assertion is unverifiable."""
        if self.phase == "confirmed" and not str(self.video_id or "").strip():
            raise ValueError("a confirmed publication must carry video_id")
        return self
