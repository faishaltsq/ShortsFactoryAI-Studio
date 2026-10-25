"""Artifact contracts. This package imports nothing else from the project.

Every artifact that crosses an agent boundary is defined here, validated here, and exported
to JSON Schema from here. If a field is not in a contract, it does not exist.
"""

from .artifacts import (
    ApprovalArtifact,
    AssetsArtifact,
    AudioArtifact,
    MetadataArtifact,
    MotionPlanArtifact,
    PublicationArtifact,
    QaArtifact,
    RenderArtifact,
    ResearchArtifact,
    ReviewArtifact,
    ScriptArtifact,
    StoryboardArtifact,
)
from .base import Artifact, ArtifactValidationError, content_hash, validate_artifact
from .scene import CameraSpec, MotionSpec, SceneSpec, SubtitleCue, TemplateId
from .state import JobState, StudioStatus, allowed_transitions, assert_transition

__all__ = [
    "ApprovalArtifact",
    "Artifact",
    "ArtifactValidationError",
    "AssetsArtifact",
    "AudioArtifact",
    "CameraSpec",
    "JobState",
    "MetadataArtifact",
    "MotionPlanArtifact",
    "MotionSpec",
    "PublicationArtifact",
    "QaArtifact",
    "RenderArtifact",
    "ResearchArtifact",
    "ReviewArtifact",
    "SceneSpec",
    "ScriptArtifact",
    "StoryboardArtifact",
    "StudioStatus",
    "SubtitleCue",
    "TemplateId",
    "allowed_transitions",
    "assert_transition",
    "content_hash",
    "validate_artifact",
]
