"""Agent class lookup, so the pipeline and the API agree on names."""

from __future__ import annotations

from . import Agent
from .concrete import (
    AnimationAgent,
    CreativeDirectorAgent,
    MetadataAgent,
    QualityAgent,
    ResearchAgent,
    ScriptAgent,
    StoryboardAgent,
    TopicSelectionAgent,
)

AGENTS: dict[str, type[Agent]] = {
    "ResearchAgent": ResearchAgent,
    "TopicSelectionAgent": TopicSelectionAgent,
    "ScriptAgent": ScriptAgent,
    "CreativeDirectorAgent": CreativeDirectorAgent,
    "StoryboardAgent": StoryboardAgent,
    "AnimationAgent": AnimationAgent,
    "QualityAgent": QualityAgent,
    "MetadataAgent": MetadataAgent,
}

#: Agents that make model calls, with the capability each one actually needs.
#: ``QualityAgent`` needs vision only for its visual pass, which is a separate, recorded step.
REQUIRED_CAPABILITIES: dict[str, frozenset[str]] = {
    "ResearchAgent": frozenset({"chat"}),
    "TopicSelectionAgent": frozenset({"chat"}),
    "ScriptAgent": frozenset({"chat", "json_schema"}),
    "CreativeDirectorAgent": frozenset({"chat"}),
    "StoryboardAgent": frozenset({"chat", "json_schema"}),
    "AnimationAgent": frozenset({"chat"}),
    "QualityAgent": frozenset({"chat"}),
    "MetadataAgent": frozenset({"chat"}),
}

#: Agents that are deterministic (no model call). They still appear in the studio.
DETERMINISTIC_AGENTS: dict[str, str] = {
    "AssetAgent": "resolves and checksums licensed assets",
    "AudioAgent": "synthesises narration and derives subtitle timing",
    "EditorAgent": "composes the final timeline and runs technical QC",
    "PublisherAgent": "uploads private-first and reconciles receipts",
    "DirectorAgent": "holds the operator's creative brief and approvals",
    "FactoryOrchestrator": "sequences stages, owns state and leases",
}
