"""The agents that exist in Phase 1, with their prompts and contracts.

Every prompt states the exact JSON shape. Every contract is the artifact model, so a field the
prompt forgot is a validation failure rather than a silent default.
"""

from __future__ import annotations

import json
from typing import Any, cast

from ..contracts import (
    MetadataArtifact,
    MotionPlanArtifact,
    ResearchArtifact,
    ReviewArtifact,
    ScriptArtifact,
    StoryboardArtifact,
)
from ..contracts.base import Artifact
from ..providers.base import Capability
from . import Agent

STORYBOARD_SCHEMA = json.dumps(
    {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "dusk",
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "IllustratedStory",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 300,
                "assetRefs": ["character:maya"],
                "text": [{"id": "t1", "text": "...", "role": "title", "atFrame": 0}],
                "camera": {
                    "shot": "wide",
                    "move": "static",
                    "target": None,
                    "amplitude": 0.12,
                    "ease": "power2.out",
                },
                "motion": {
                    "energy": 0.5,
                    "continuity": "cut",
                    "beats": [{"atFrame": 0, "kind": "enter", "subject": "t1"}],
                },
                "transition": {"kind": "cut", "frames": 0},
            }
        ],
        "subtitles": [],
    },
    indent=2,
)

TEMPLATES = (
    "KineticTypography",
    "EducationalExplainer",
    "MotionComic",
    "HistoricalTimeline",
    "ParallaxStory",
    "InfographicMotion",
    "IllustratedStory",
)


class ResearchAgent(Agent):
    name = "ResearchAgent"
    system_prompt = (
        "You are a research agent for short vertical videos. "
        "Return ONLY a JSON object with keys: schema_version, topic, content_kind, candidates, "
        "sources, claims. content_kind is 'factual' or 'fictional'. For factual content, sources "
        "must contain at least one object with url and title. Never invent a URL you were not given; "
        "if you have no source, set content_kind to 'fictional'."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        topic = str(kwargs.get("topic") or "")
        genre = str(kwargs.get("genre") or "")
        avoid = cast(list[str], kwargs.get("avoid") or [])
        return (
            f"Topic: {topic or '(discover one)'}\nGenre: {genre}\n"
            f"Recent titles to avoid repeating: {avoid or 'none'}\n"
            "Produce 3 candidate angles and the sources you actually rely on."
        )

    def contract(self) -> type[Artifact]:
        return ResearchArtifact


class TopicSelectionAgent(Agent):
    name = "TopicSelectionAgent"
    system_prompt = (
        "You pick the single best angle for a 30-60 second vertical video. "
        "Return ONLY JSON: {schema_version, topic, content_kind, candidates, sources, claims}."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        research = cast(dict[str, Any], kwargs.get("research") or {})
        return (
            "Choose one candidate from this research and keep its sources:\n"
            + json.dumps(research, ensure_ascii=False)[:4000]
        )

    def contract(self) -> type[Artifact]:
        return ResearchArtifact


class ScriptAgent(Agent):
    name = "ScriptAgent"
    system_prompt = (
        "You write short-form vertical video scripts. Return ONLY JSON with keys: "
        "schema_version, hook, segments, cta, content_kind. "
        "segments is a list of {id, text, purpose} where purpose is one of hook/build/turn/payoff. "
        "Each segment becomes one scene, so 3-6 segments. Total spoken length must fit 30-60 seconds."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        topic = cast(dict[str, Any], kwargs.get("topic") or {})
        duration_s = cast(int, kwargs.get("duration_s") or 45)
        language = str(kwargs.get("language") or "en")
        return (
            f"Topic and sources:\n{json.dumps(topic, ensure_ascii=False)[:3000]}\n"
            f"Target duration: {duration_s} seconds. Language: {language}."
        )

    def contract(self) -> type[Artifact]:
        return ScriptArtifact


class CreativeDirectorAgent(Agent):
    name = "CreativeDirectorAgent"
    requires = frozenset({Capability.CHAT})
    system_prompt = (
        "You are a creative director reviewing a short-form script. Return ONLY JSON with keys: "
        "schema_version, verdict ('accept' or 'revise'), scores, findings, attempt. "
        "If verdict is 'revise' you MUST include at least one finding with segment_id, issue, fix. "
        "Be strict about a weak hook and a missing payoff."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        script = cast(dict[str, Any], kwargs.get("script") or {})
        attempt = int(kwargs.get("attempt") or 1)
        return (
            f"Attempt {attempt}. Review this script:\n"
            + json.dumps(script, ensure_ascii=False)[:4000]
        )

    def contract(self) -> type[Artifact]:
        return ReviewArtifact


class StoryboardAgent(Agent):
    name = "StoryboardAgent"
    system_prompt = (
        "You turn a script into a storyboard for a 1080x1920 30fps video. Return ONLY JSON matching "
        "this exact shape (types matter):\n"
        + STORYBOARD_SCHEMA
        + "\nRules: scenes must be contiguous (scene N starts where N-1 ended). "
        "durationInFrames between 30 and 3000. If camera.move is not 'static', camera.target MUST "
        "be the id of an element in that scene's text array. Available templates: "
        + ", ".join(TEMPLATES)
        + ". Use at most one push or pull in the whole video. Give every scene at least one beat."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        script = cast(dict[str, Any], kwargs.get("script") or {})
        fps = int(kwargs.get("fps") or 30)
        return (
            f"fps={fps}. Script:\n{json.dumps(script, ensure_ascii=False)[:5000]}\n"
            "One scene per segment, in order."
        )

    def contract(self) -> type[Artifact]:
        return StoryboardArtifact


class AnimationAgent(Agent):
    name = "AnimationAgent"
    requires = frozenset({Capability.CHAT})
    system_prompt = (
        "You design motion for a short vertical video. Return ONLY JSON with keys: schema_version, "
        "renderer, style_brief, scenes, anti_patterns_checked. "
        "style_brief has palette (list of hex), fonts (list), signature_move (string). "
        "scenes is a list of {sceneId, beats, camera_path, continuity_from}. "
        "Avoid: static slideshow, generic fade transitions, one flat background for the whole video."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        storyboard = cast(dict[str, Any], kwargs.get("storyboard") or {})
        previous_style = cast(dict[str, Any] | None, kwargs.get("previous_style"))
        return (
            "Storyboard:\n"
            + json.dumps(storyboard, ensure_ascii=False)[:5000]
            + "\nPrevious video style to differ from: "
            + json.dumps(previous_style or {}, ensure_ascii=False)[:800]
        )

    def contract(self) -> type[Artifact]:
        return MotionPlanArtifact


class MetadataAgent(Agent):
    name = "MetadataAgent"
    requires = frozenset({Capability.CHAT})
    system_prompt = (
        "You write YouTube Shorts metadata in the video's language. Return ONLY JSON with keys: "
        "schema_version, title, description, tags, category_id, made_for_kids, synthetic_media, "
        "thumbnail. title max 100 characters. synthetic_media must be true for AI-generated video."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        script = cast(dict[str, Any], kwargs.get("script") or {})
        topic = str(kwargs.get("topic") or "")
        language = str(kwargs.get("language") or "en")
        return (
            f"Language: {language}. Topic: {topic}\nScript:\n"
            + json.dumps(script, ensure_ascii=False)[:3000]
        )

    def contract(self) -> type[Artifact]:
        return MetadataArtifact


class QualityAgent(Agent):
    """Editorial review. Visual inspection needs a separate vision-capable call, recorded separately."""

    name = "QualityAgent"
    requires = frozenset({Capability.CHAT})
    system_prompt = (
        "You review a storyboard for pacing, clarity and text density. Return ONLY JSON with keys: "
        "schema_version, verdict, scores, findings, attempt. verdict is 'accept' or 'revise'. "
        "Flag any scene whose text is too long to read in its duration, and any run of scenes with "
        "identical framing."
    )

    def build_user_prompt(self, **kwargs: Any) -> str:
        storyboard = cast(dict[str, Any], kwargs.get("storyboard") or {})
        return "Storyboard:\n" + json.dumps(storyboard, ensure_ascii=False)[:6000]

    def contract(self) -> type[Artifact]:
        return ReviewArtifact


__all__ = [
    "AnimationAgent",
    "CreativeDirectorAgent",
    "MetadataAgent",
    "QualityAgent",
    "ResearchAgent",
    "ScriptAgent",
    "StoryboardAgent",
    "TopicSelectionAgent",
]
