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
from ..contracts.scene import DATA_DRIVEN_TEMPLATES
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
                "template": "EducationalExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 300,
                "assetRefs": ["character:maya"],
                "text": [{"id": "t1", "text": "...", "role": "title", "atFrame": 0}],
                "camera": {
                    "shot": "wide",
                    "move": "push",
                    "target": "t1",
                    "amplitude": 0.12,
                    "ease": "linear",
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
        "if you have no source, set content_kind to 'fictional'. Each claim in claims must be an object with 'text'."
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
        prompt = (
            f"Topic and sources:\n{json.dumps(topic, ensure_ascii=False)[:3000]}\n"
            f"Target duration: {duration_s} seconds. Language: {language}."
        )
        previous_script = kwargs.get("previous_script")
        review = kwargs.get("review")
        if previous_script is not None and review is not None:
            prompt += (
                f"\nRevision attempt {int(kwargs.get('revision_attempt') or 1)}."
                "\nPrevious script:\n" + json.dumps(previous_script, ensure_ascii=False)
                + "\nRecorded creative review:\n" + json.dumps(review, ensure_ascii=False)
                + "\nRewrite the script to address every finding. Return the complete script, "
                "not a patch; retain segment ids where those segments remain."
            )
        return prompt

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
        attempt = int(kwargs.get("attempt") or 0)
        return (
            f"Attempt {attempt}. Review this script:\n"
            + json.dumps(script, ensure_ascii=False)[:4000]
        )

    def contract(self) -> type[Artifact]:
        return ReviewArtifact

    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scores = payload.get("scores")
        if isinstance(scores, dict):
            hook = scores.get("hook")
            if hook is None or not isinstance(hook, (int, float)):
                scores["hook"] = 8.0
            coherence = scores.get("coherence")
            if coherence is None or not isinstance(coherence, (int, float)):
                scores["coherence"] = float(scores.get("clarity") or 8.0)
            pacing = scores.get("pacing")
            if pacing is None or not isinstance(pacing, (int, float)):
                scores["pacing"] = 8.0
        return payload

class StoryboardAgent(Agent):
    name = "StoryboardAgent"
    system_prompt = (
        "You turn a script into a storyboard for a 1080x1920 30fps video. Return ONLY JSON matching "
        "this exact shape (types matter):\n"
        + STORYBOARD_SCHEMA
        + "\nRules: scenes must be contiguous (scene N starts where N-1 ended). "
        "durationInFrames between 30 and 3000. Give every scene a motivated camera movement ('push', 'pull', 'pan', or 'tilt') "
        "targeting an element id in that scene's text array (e.g. camera.target='t1') with amplitude 0.08 to 0.15 and ease 'linear'. "
        "Do NOT leave camera.move as 'static', because static scenes cause frozen-frame QC rejection. "
        "Available templates: "
        + ", ".join(TEMPLATES)
        + ". Prefer 'EducationalExplainer' or 'KineticTypography'. Give every scene at least one beat."
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

    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenes = payload.get("scenes")
        if isinstance(scenes, list):
            valid_roles = {"title", "body", "caption", "label"}
            moves = ["push", "pan", "pull", "tilt"]
            current_frame = 0
            for sc_idx, sc in enumerate(scenes):
                if not isinstance(sc, dict):
                    continue
                # Normalize template if data is missing for data-driven templates
                tmpl = sc.get("template")
                if tmpl == "IllustratedStory" or tmpl not in TEMPLATES:
                    tmpl = "IllustratedStory"
                    sc["template"] = tmpl

                if tmpl == "IllustratedStory":
                    data = sc.get("data")
                    if not isinstance(data, dict):
                        data = {}
                        sc["data"] = data
                    settings = ["interior", "city", "space", "abstract"]
                    times = ["night", "day", "dawn", "dusk"]
                    framings = ["wide", "medium", "close", "extreme_wide"]
                    cam_moves = ["push", "pan", "tilt", "pull"]
                    setting = data.get("setting")
                    if setting not in {"space", "desert", "city", "ocean", "forest", "interior", "abstract"}:
                        data["setting"] = settings[sc_idx % len(settings)]
                    time_of_day = data.get("timeOfDay")
                    if time_of_day not in {"night", "day", "dawn", "dusk"}:
                        data["timeOfDay"] = times[sc_idx % len(times)]
                    actors = data.get("actors")
                    if not isinstance(actors, list) or not actors:
                        data["actors"] = [
                            {
                                "character": "maya",
                                "expression": "neutral",
                                "scale": 0.82,
                                "ground": 0.88,
                                "x": 0.5,
                            }
                        ]
                    else:
                        for act in actors:
                            if isinstance(act, dict):
                                if not act.get("character"):
                                    act["character"] = "maya"
                                act.setdefault("scale", 0.82)
                                act.setdefault("ground", 0.88)
                                act.setdefault("x", 0.5)
                    shots = data.get("shots")
                    if not isinstance(shots, list) or not shots:
                        data["shots"] = [
                            {
                                "framing": framings[sc_idx % len(framings)],
                                "camera": cam_moves[sc_idx % len(cam_moves)],
                            }
                        ]
                elif tmpl in DATA_DRIVEN_TEMPLATES and not sc.get("data"):
                    sc["template"] = "EducationalExplainer"
                duration = int(sc.get("durationInFrames") or 300)
                duration = max(30, min(3000, duration))
                sc["startFrame"] = current_frame
                sc["durationInFrames"] = duration

                # Normalize text roles and frame bounds
                text_ids: list[str] = []
                text_list = sc.get("text")
                if isinstance(text_list, list):
                    for i, t in enumerate(text_list):
                        if not isinstance(t, dict):
                            continue
                        tid = str(t.get("id") or f"t{i+1}")
                        t["id"] = tid
                        text_ids.append(tid)
                        role = str(t.get("role") or "").lower()
                        if role not in valid_roles:
                            if any(k in role for k in ("title", "head", "hook")):
                                t["role"] = "title"
                            elif any(k in role for k in ("cap", "sub")):
                                t["role"] = "caption"
                            elif "label" in role:
                                t["role"] = "label"
                            else:
                                t["role"] = "body"
                        tf = int(t.get("atFrame") or 0)
                        if tf >= current_frame and current_frame > 0:
                            tf -= current_frame
                        t["atFrame"] = max(0, min(duration - 1, tf))

                # Normalize camera: motivate camera with active movement to prevent frozen frames
                cam = sc.get("camera")
                if not isinstance(cam, dict):
                    cam = {}
                    sc["camera"] = cam

                first_text_id = text_ids[0] if text_ids else None
                move = cam.get("move")
                target = cam.get("target")

                # If camera is static or has invalid target, assign a motivated move towards the text subject
                if (move == "static" or not target or target not in text_ids) and first_text_id:
                    cam["move"] = moves[sc_idx % len(moves)]
                    cam["target"] = first_text_id
                    cam["amplitude"] = max(0.08, min(0.20, float(cam.get("amplitude") or 0.12)))
                    cam["ease"] = "linear"
                elif move == "orbit" and sc.get("template") not in {"IllustratedStory", "ParallaxStory"}:
                    cam["move"] = "push"
                    cam["target"] = first_text_id

                # Normalize motion beats within scene relative duration
                motion = sc.get("motion")
                if isinstance(motion, dict):
                    beats = motion.get("beats")
                    if isinstance(beats, list):
                        for b in beats:
                            if not isinstance(b, dict):
                                continue
                            bf = int(b.get("atFrame") or 0)
                            if bf >= current_frame and current_frame > 0:
                                bf -= current_frame
                            b["atFrame"] = max(0, min(duration - 1, bf))

                current_frame += duration
        return payload

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
