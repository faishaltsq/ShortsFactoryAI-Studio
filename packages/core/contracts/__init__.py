"""Artifact contracts. This package imports nothing else from the project.

Every artifact that crosses an agent boundary is defined here, validated here, and exported
to JSON Schema from here. If a field is not in a contract, it does not exist.
"""

from .artifacts import (
    ApprovalArtifact,
    ArtDirectionSpec,
    AssetsArtifact,
    AudioArtifact,
    CameraIntent,
    CreativeMotionBriefArtifact,
    MetadataArtifact,
    MotionPlanArtifact,
    PublicationArtifact,
    QaArtifact,
    RenderArtifact,
    ResearchArtifact,
    ReviewArtifact,
    RevisionArtifact,
    ScriptArtifact,
    StoryboardArtifact,
    StyleIntent,
    VisualBeatPlan,
    VisualPlanArtifact,
)
from .base import Artifact, ArtifactValidationError, content_hash, validate_artifact
from .scene import (
    CameraSpec,
    CausalStateSpec,
    LayoutMode,
    MotionSpec,
    SceneSpec,
    SubtitleCue,
    TemplateId,
    WordTimestamp,
)
from .state import JobState, StudioStatus, allowed_transitions, assert_transition

__all__ = [
    "ApprovalArtifact",
    "ArtDirectionSpec",
    "Artifact",
    "ArtifactValidationError",
    "AssetsArtifact",
    "AudioArtifact",
    "CameraIntent",
    "CameraSpec",
    "CausalStateSpec",
    "CreativeMotionBriefArtifact",
    "JobState",
    "LayoutMode",
    "MetadataArtifact",
    "MotionPlanArtifact",
    "MotionSpec",
    "PublicationArtifact",
    "QaArtifact",
    "RenderArtifact",
    "ResearchArtifact",
    "ReviewArtifact",
    "RevisionArtifact",
    "SceneSpec",
    "ScriptArtifact",
    "StoryboardArtifact",
    "StudioStatus",
    "StyleIntent",
    "SubtitleCue",
    "TemplateId",
    "VisualBeatPlan",
    "VisualPlanArtifact",
    "WordTimestamp",
    "allowed_transitions",
    "assert_transition",
    "content_hash",
    "validate_artifact",
]
