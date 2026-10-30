"""Every system prompt the product sends, in one place, with a local hash.

Why centralize: a prompt is part of an artifact's provenance. When ``script.json`` records
``prompt_sha256``, that hash must describe the prompt the *code* sent — not a string a model
asserted about itself. A model-written hash is a claim; a locally computed one is a fact.

The hash is computed here, from these constants (or from an operator's saved override), so the
journal key and the artifact provenance agree by construction.
"""
from __future__ import annotations

import hashlib
from typing import Any

#: ResearchAgent: propose candidates and claims. The "never invent a URL" clause is the important
#: one — a model that fabricates a source produces a factual video built on nothing.
RESEARCH = (
    "You are a research agent for short vertical videos. "
    "Return ONLY a JSON object with keys: schema_version, topic, content_kind, candidates, "
    "sources, claims. content_kind is 'factual' or 'fictional'. For factual content, sources "
    "must contain at least one object with url and title. Never invent a URL you were not given; "
    "if you have no source, set content_kind to 'fictional'."
)

#: TopicSelectionAgent: pick one candidate and keep its sources attached.
TOPIC_SELECTION = (
    "You pick the single best angle for a 30-60 second vertical video. "
    "Return ONLY JSON: {schema_version, topic, content_kind, candidates, sources, claims}."
)

#: ScriptAgent: segments become scenes, so the segment count is a duration constraint.
SCRIPT = (
    "You write short-form vertical video scripts. Return ONLY JSON with keys: "
    "schema_version, hook, segments, cta, content_kind. "
    "segments is a list of {id, text, purpose} where purpose is one of hook/build/turn/payoff. "
    "Each segment becomes one scene, so 3-6 segments. Total spoken length must fit the requested "
    "duration."
)

#: CreativeDirectorAgent: a revise verdict must carry an actionable finding.
CREATIVE_REVIEW = (
    "You are a creative director reviewing a short-form script. Return ONLY JSON with keys: "
    "schema_version, verdict ('accept' or 'revise'), scores, findings, attempt. "
    "If verdict is 'revise' you MUST include at least one finding with segment_id, issue, fix. "
    "Be strict about a weak hook and a missing payoff."
)

#: StoryboardAgent: one scene per segment, with a camera and a motion declaration for each.
STORYBOARD = (
    "You turn a script into a scene-by-scene storyboard for a vertical video. Return ONLY JSON "
    "with keys: schema_version, scenes. Each scene has id, segment_id, duration_s, camera, motion, "
    "text, visual. Every scene MUST declare a camera and a motion; there is no default."
)

#: MetadataAgent: title/description/tags in the video's language.
METADATA = (
    "You write the publishing metadata for a short vertical video. Return ONLY JSON with keys: "
    "schema_version, title, description, tags, category, language. Write in the requested "
    "language, not the operator's."
)

#: AnimationAgent: the motion plan is the starting constraint set, not a free-form invention.
ANIMATION = (
    "You plan the motion for each scene of a vertical video. Return ONLY JSON with keys: "
    "schema_version, scenes. Each scene references its storyboard scene id and declares its "
    "camera and beats. Do not invent capabilities the renderer does not have."
)

#: The schema-repair prompt is deliberately terse: it is a correction, not a new task.
REPAIR = (
    "Your previous response was not valid against the required schema. Return ONLY a corrected "
    "JSON object that satisfies it. Do not change values you were not asked to change."
)

def _agent_classes() -> dict[str, Any]:
    """The agent classes, imported here so this module never depends on them at import time.

    ``packages.core.agents`` reaches for prompts, so a module-level import would be a cycle. This
    is called once, at the bottom of this module, to build ``SYSTEM_PROMPTS``.
    """
    from .agents.registry import AGENTS

    return dict(AGENTS)


#: Every prompt, by the agent that sends it.
#:
#: Derived from the agent classes rather than restated here. The class attribute is what the agent
#: actually sends, so a second copy of the text is a second thing that can drift — and it did: the
#: ``ScriptAgent`` constant above said "the requested duration" while the class said "30-60
#: seconds", which meant ``prompt_sha256`` hashed a prompt nobody had sent. Provenance that
#: disagrees with the call is worse than no provenance.
SYSTEM_PROMPTS: dict[str, str] = {
    agent_id: agent.system_prompt
    for agent_id, agent in _agent_classes().items()
}


def sha256(text: str) -> str:
    """The local hash of a prompt. Computed here so it cannot disagree with what was sent."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def effective(agent_id: str, override: str | None = None) -> str:
    """The prompt this agent will actually send: the operator's override, or the constant."""
    if override:
        return override
    try:
        return SYSTEM_PROMPTS[agent_id]
    except KeyError as exc:
        raise KeyError(f"no system prompt registered for {agent_id!r}") from exc
