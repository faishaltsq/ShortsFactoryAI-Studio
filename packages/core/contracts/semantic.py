"""Rendered-pixel semantic evidence. Declarations describe requirements, never observations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import Artifact, content_hash

SemanticStatus = Literal["PASS", "FAIL", "UNVERIFIED"]
SemanticCategory = Literal[
    "subject_fidelity",
    "causal_fidelity",
    "narration_alignment",
    "spatial_continuity",
    "composition",
    "scientific_accuracy",
    "typography_branding",
    "visual_repetition",
]
SEMANTIC_CATEGORIES: tuple[SemanticCategory, ...] = (
    "subject_fidelity",
    "causal_fidelity",
    "narration_alignment",
    "spatial_continuity",
    "composition",
    "scientific_accuracy",
    "typography_branding",
    "visual_repetition",
)
Digest = str


class ManualReviewPolicyArtifact(Artifact):
    kind = "manual-review-policy"

    job_id: str = Field(min_length=1)
    render_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator: str = Field(min_length=1, max_length=120)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=1000)
    allow_unverified: Literal[True]
    policy: Literal["operator_render_review_v1"] = "operator_render_review_v1"

    @model_validator(mode="after")
    def explicit_operator(self) -> ManualReviewPolicyArtifact:
        if not self.operator.strip() or not self.reason.strip():
            raise ValueError("manual review requires a named operator and a nonblank reason")
        return self

    def permits(
        self, job_id: str | None, render_sha256: str | None, inputs_sha256: str, context_sha256: str | None
    ) -> bool:
        return (self.job_id, self.render_sha256, self.inputs_sha256, self.context_sha256) == (
            job_id,
            render_sha256,
            inputs_sha256,
            context_sha256,
        )


class VisualFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    frame_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    frame: int = Field(ge=0)
    at_ms: float = Field(ge=0, allow_inf_nan=False)
    roles: list[Literal["begin", "middle", "end", "action", "transition_before", "transition_after"]]
    file: str = Field(pattern=r"^qa-frame-[0-9]{5}\.png$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_ref: str = Field(min_length=1)
    evidence_source: Literal["rendered_mp4"] = "rendered_mp4"


class VisualEvidenceArtifact(Artifact):
    kind = "visual-evidence"

    job_id: str = Field(min_length=1)
    render_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fps: float | None = Field(gt=0, allow_inf_nan=False)
    scene_ids: list[str]
    requirements: dict[str, str]
    frames: list[VisualFrame]
    complete: bool = False
    reason: str = Field(min_length=1)
    inspection_ref: Literal["qc.json#semantic"] = "qc.json#semantic"
    inspection_status: SemanticStatus = "UNVERIFIED"
    provider: str | None = None
    model: str | None = None

    def evidence_payload(self) -> dict[str, Any]:
        """Immutable request input; interpretation receipts and wall clock are not frame evidence."""
        return self.model_dump(mode="json", exclude={"created_at", "inspection_status", "provider", "model"})

    def evidence_hash(self) -> str:
        return content_hash(self.evidence_payload())

    @model_validator(mode="after")
    def honest_coverage(self) -> VisualEvidenceArtifact:
        if len(set(self.scene_ids)) != len(self.scene_ids) or set(self.requirements) != set(self.scene_ids):
            raise ValueError("scene identities and requirements must agree")
        ids = [frame.frame_id for frame in self.frames]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate frame identity")
        for frame in self.frames:
            if self.fps is None:
                raise ValueError("frames require measured timing")
            if frame.scene_id not in self.requirements or frame.requirement_ref != frame.scene_id:
                raise ValueError("frame must identify its actual scene and requirement")
            if abs(frame.at_ms - frame.frame * 1000 / self.fps) > 0.001:
                raise ValueError("timestamp must identify the decoded frame")
        if self.complete:
            if not self.scene_ids or not self.frames:
                raise ValueError("complete evidence cannot be empty")
            for scene in self.scene_ids:
                roles = {role for frame in self.frames if frame.scene_id == scene for role in frame.roles}
                if not {"begin", "middle", "end", "action"} <= roles:
                    raise ValueError(
                        "complete evidence requires beginning/middle/end/action coverage for every scene"
                    )
        return self


class SemanticCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scene_id: str = Field(min_length=1)
    category: SemanticCategory
    status: SemanticStatus
    reason: str = Field(min_length=1, max_length=2000)
    observation: str = Field(min_length=1, max_length=2000)
    frame_ids: list[str]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    source_ids: list[str] = Field(default_factory=list)
    severity: Literal["blocker", "major", "minor", "info"] = "info"
    repair_scope: Literal["storyboard", "tsx", "asset_geometry", "none"] = "none"

    @model_validator(mode="after")
    def evidence_required(self) -> SemanticCriterion:
        if len(set(self.frame_ids)) != len(self.frame_ids):
            raise ValueError("evidence references must be unique")
        if self.status != "UNVERIFIED" and (not self.frame_ids or self.confidence < 0.75):
            raise ValueError("inspected conclusions require frames and sufficient declared confidence")
        if self.status == "FAIL" and (self.repair_scope == "none" or self.severity == "info"):
            raise ValueError("FAIL requires actionable repair scope and severity")
        if self.status == "UNVERIFIED" and self.repair_scope != "none":
            raise ValueError("UNVERIFIED must not request creative repair")
        return self


class SemanticInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    job_id: str = Field(min_length=1)
    render_sha256: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    inputs_sha256: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    scene_ids: list[str] = Field(min_length=1)
    status: SemanticStatus
    provider: str | None
    model: str | None
    evidence_source: Literal["rendered_pixels", "unavailable"] = "rendered_pixels"
    criteria: list[SemanticCriterion] = Field(min_length=1)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Vision interpretation is uncertain evidence, not ground truth; sampled frames do not prove every video frame.",
        ]
    )

    @model_validator(mode="after")
    def consistent_coverage(self) -> SemanticInspection:
        if len(set(self.scene_ids)) != len(self.scene_ids):
            raise ValueError("scene ids must be unique")
        expected = {(scene, category) for scene in self.scene_ids for category in SEMANTIC_CATEGORIES}
        actual = [(item.scene_id, item.category) for item in self.criteria]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("each scene requires each of the eight categories exactly once")
        statuses = {item.status for item in self.criteria}
        derived = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
        if self.status != derived:
            raise ValueError("overall status must reflect all inspected criteria")
        if statuses != {"UNVERIFIED"}:
            if not self.provider or not self.model or self.evidence_source != "rendered_pixels":
                raise ValueError("inspected conclusions require actual provider/model provenance")
        return self
