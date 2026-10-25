"""Every artifact an agent may produce.

One file, because the whole point is that the vocabulary is visible in one place. Each model
carries ``kind`` so a file on disk can prove what it claims to be.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

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
    prompt_hash: str = ""

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
    audio_codec: str = "aac"
    pix_fmt: str = "yuv420p"
    renderer: RendererId = "remotion"
    renderer_version: str = ""
    scene_hashes: dict[str, str] = Field(default_factory=dict)


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


class ApprovalArtifact(Artifact):
    kind = "approval"

    decision: Literal["approved", "rejected"]
    operator: str = Field(min_length=1)
    reason: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)
    decided_at: str = ""

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

    @model_validator(mode="after")
    def _public_needs_confirmation_receipt(self) -> PublicationArtifact:
        if self.privacy == "public":
            confirmed = any(r.get("step") == "public_confirm" and r.get("ok") for r in self.receipts)
            if not confirmed:
                raise ValueError("a public publication needs a public_confirm receipt")
        return self
