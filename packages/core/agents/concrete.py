"""The agents that exist in Phase 1, with their prompts and contracts.

Every prompt states the exact JSON shape. Every contract is the artifact model, so a field the
prompt forgot is a validation failure rather than a silent default.
"""

from __future__ import annotations

import json
import re
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
from ..contracts.scene import DATA_DRIVEN_TEMPLATES, OBJECT_KINDS, OBJECT_LABELS
from ..providers.base import Capability
from . import Agent

STORYBOARD_SCHEMA = json.dumps(
    {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "midnight",
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 300,
                "assetRefs": [],
                "text": [{"id": "t1", "text": "...", "role": "title", "atFrame": 0}],
                "camera": {
                    "shot": "wide",
                    "move": "push",
                    "target": "t1",
                    "amplitude": 0.12,
                    "ease": "linear",
                },
                "motion": {
                    "energy": 0.6,
                    "continuity": "cut",
                    "beats": [
                        {"atFrame": 0, "kind": "enter", "subject": "t1"},
                        {"atFrame": 90, "kind": "action", "subject": "t1"},
                    ],
                },
                "transition": {"kind": "cut", "frames": 0},
                "data": {
                    "title": "...",
                    "caption": "...",
                    "environment": "dataCenter",
                    "objects": [
                        {"kind": "gpu", "x": 0.5, "y": 0.34, "size": 0.46, "at": 0, "label": "GPU"},
                        {"kind": "serverRack", "x": 0.28, "y": 0.62, "size": 0.26, "at": 14},
                    ],
                    "callouts": [{"object": 0, "text": "...", "dx": 0.0, "dy": -0.14, "at": 40}],
                    "flows": [{"from": 1, "to": 0, "label": "data", "at": 34}],
                },
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
    "ObjectExplainer",
    "ProcessFlow",
    "MetricShift",
)

#: Topic keywords → (backdrop, hero object, supporting objects). Ordered: the first matching row
#: wins, so the specific topics sit above the general ones.
TOPIC_VISUALS: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = (
    (
        ("data center", "datacenter", "server", "rak", "hosting", "penyimpanan", "storage"),
        "dataCenter",
        ("serverRack", "dataCenter", "coolingFan"),
    ),
    (
        ("gpu", "grafis", "akselerator", "chip", "semikonduktor", "wafer", "transistor", "nvidia"),
        "circuit",
        ("gpu", "wafer", "coolingFan"),
    ),
    (
        ("satelit", "orbit", "antariksa", "roket", "nasa", "luar angkasa", "mars", "bulan", "space"),
        "space",
        ("satellite", "antenna", "rocket"),
    ),
    (
        ("energi", "listrik", "daya", "turbin", "surya", "solar", "emisi", "karbon"),
        "grid",
        ("turbine", "solarPanel", "coolingFan"),
    ),
    (
        ("internet", "jaringan", "sinyal", "5g", "koneksi", "bandwidth", "telekomunikasi", "wifi"),
        "grid",
        ("antenna", "serverRack", "phone"),
    ),
    (
        ("startup", "bisnis", "perusahaan", "unicorn", "ipo", "pendanaan", "modal", "pasar"),
        "city",
        ("building", "database", "neuralNet"),
    ),
    (
        ("hp", "ponsel", "smartphone", "aplikasi", "software", "android", "ios", "perangkat"),
        "city",
        ("phone", "database", "serverRack"),
    ),
    (
        ("drone", "robot", "otomasi", "pabrik", "manufaktur", "gudang"),
        "lab",
        ("drone", "gpu", "serverRack"),
    ),
    (
        ("otak", "ingatan", "mimpi", "tidur", "memori", "belajar", "pikiran"),
        "grid",
        ("neuralNet", "database", "gpu"),
    ),
    (
        ("gunung", "vulkan", "magma", "lava", "erupsi", "gempa", "geologi", "iklim", "cuaca", "samudra"),
        "grid",
        ("satellite", "drone", "antenna"),
    ),
    (
        ("ai", "kecerdasan", "model", "neural", "llm", "machine learning", "pelatihan", "training", "inferensi"),
        "grid",
        ("neuralNet", "gpu", "database"),
    ),
)

#: Fallback when no topic keyword matches: still an object, never a blank stage.
DEFAULT_VISUAL: tuple[str, tuple[str, ...]] = ("abstract", ("gpu", "neuralNet", "database"))

_STAGED_ASSET = re.compile(r"assets/[a-f0-9]{64}\.(png|jpe?g|webp)")


def _scene_text(scene: dict[str, Any]) -> str:
    """Everything a viewer would read in this scene, lowercased, for topic matching."""
    parts = [str(scene.get("segment") or "")]
    for element in scene.get("text") or []:
        if isinstance(element, dict):
            parts.append(str(element.get("text") or ""))
    data = scene.get("data")
    if isinstance(data, dict):
        parts.append(str(data.get("title") or ""))
        parts.append(str(data.get("caption") or ""))
    return " ".join(parts).lower()


def _topic_visual(text: str) -> tuple[str, tuple[str, ...]]:
    for keywords, environment, kinds in TOPIC_VISUALS:
        if any(word in text for word in keywords):
            return environment, kinds
    return DEFAULT_VISUAL


def _object_label(kind: str) -> str:
    return OBJECT_LABELS.get(kind, kind)


def fill_explainer(data: dict[str, Any], scene: dict[str, Any], index: int) -> None:
    """Give an ``ObjectExplainer`` scene a stage that matches its own words.

    The storyboard model is asked for objects, and usually supplies them. When it does not — or
    when it names a kind the renderer has no drawing for — the scene is rebuilt from its topic so
    a scene is never a blank backdrop with a title over it.
    """
    environment, kinds = _topic_visual(_scene_text(scene))

    objects = data.get("objects")
    usable: list[dict[str, Any]] = []
    if isinstance(objects, list):
        for item in objects:
            if isinstance(item, dict) and item.get("kind") in OBJECT_KINDS:
                usable.append(item)
    if not usable:
        usable = [
            {"kind": kinds[0], "x": 0.5, "y": 0.34, "size": 0.46, "at": 0, "label": _object_label(kinds[0])},
            {"kind": kinds[1], "x": 0.28, "y": 0.62, "size": 0.26, "at": 14, "label": _object_label(kinds[1])},
            {"kind": kinds[2], "x": 0.72, "y": 0.62, "size": 0.26, "at": 26, "label": _object_label(kinds[2])},
        ]
    data["objects"] = usable[:5]
    data.setdefault("environment", environment)
    if data.get("environment") not in {
        "dataCenter", "circuit", "space", "lab", "city", "grid", "abstract"
    }:
        data["environment"] = environment
    if not isinstance(data.get("callouts"), list):
        data["callouts"] = [
            {"object": 0, "text": str(scene.get("segment") or "")[:48] or "Objek utama", "dx": 0.0, "dy": -0.14, "at": 40}
        ]
    if not isinstance(data.get("flows"), list):
        # Flow from the supporting objects into the hero: the visual claim is that the parts feed
        # the subject, which is what an explainer scene is for.
        data["flows"] = [
            {"from": i, "to": 0, "at": 34 + i * 8}
            for i in range(1, len(data["objects"]))
        ]


def fill_process_flow(data: dict[str, Any], scene: dict[str, Any], index: int) -> bool:
    """Keep a declared step chain; otherwise report that the scene needs rebuilding."""
    steps = data.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        return False
    cleaned: list[dict[str, Any]] = []
    for item in steps[:5]:
        if not isinstance(item, dict) or not str(item.get("label") or "").strip():
            return False
        cleaned.append(
            {"label": str(item["label"])[:34], "detail": str(item.get("detail") or "")[:70] or None}
        )
    for step in cleaned:
        if step["detail"] is None:
            step.pop("detail")
    data["steps"] = cleaned
    data.setdefault("environment", "circuit")
    return True


def fill_metric_shift(data: dict[str, Any], scene: dict[str, Any], index: int) -> bool:
    """Keep declared metrics when they are numeric; otherwise rebuild as an explainer."""
    metrics = data.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        return False
    cleaned: list[dict[str, Any]] = []
    for item in metrics[:4]:
        if not isinstance(item, dict):
            return False
        raw = item.get("value")
        # A bool is an int in Python; `true` is not a measurement.
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return False
        value = float(raw)
        if value < 0:
            return False
        entry: dict[str, Any] = {"label": str(item.get("label") or "Nilai")[:34], "value": value}
        if item.get("unit"):
            entry["unit"] = str(item["unit"])[:16]
        cleaned.append(entry)
    data["metrics"] = cleaned
    data.setdefault("maxValue", max(m["value"] for m in cleaned) or 1)
    data.setdefault("decimals", 0)
    data.setdefault("environment", "grid")
    return True


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
        "Prefer 'ObjectExplainer': the picture must explain the subject without subtitles. Never produce a text-only slide. "
        "Every scene declares environment ('dataCenter', 'circuit', 'space', 'lab', 'city', 'grid', 'abstract') and 1-3 objects "
        "from: gpu, wafer, serverRack, dataCenter, neuralNet, database, satellite, antenna, turbine, solarPanel, coolingFan, "
        "phone, drone, rocket, building. Objects are things, never people: no characters, presenters, faces or poses. "
        "Use 'ProcessFlow' when the segment explains how something works, and 'MetricShift' when it compares quantities. "
        "Vary environments and objects across scenes so consecutive scenes do not look identical. Give every scene at least one beat."
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
        payload.setdefault("theme", "dusk")
        payload.setdefault("subtitles", [])
        scenes = payload.get("scenes")
        if isinstance(scenes, list):
            valid_roles = {"title", "body", "caption", "label"}
            moves = ["push", "pan", "pull", "tilt"]
            current_frame = 0
            for sc_idx, sc in enumerate(scenes):
                if not isinstance(sc, dict):
                    continue
                trans = sc.get("transition")
                if not isinstance(trans, dict):
                    sc["transition"] = {"kind": "cut", "frames": 0}
                # Every scene renders as an informative graphic. A model that names a text-only
                # template for a visual topic still gets objects, and an id we do not ship is
                # replaced rather than silently rendered as a blank frame.
                tmpl = sc.get("template")
                if tmpl in ("EducationalExplainer", "KineticTypography"):
                    tmpl = "ObjectExplainer"
                    sc["template"] = tmpl
                elif tmpl not in TEMPLATES:
                    tmpl = "ObjectExplainer"
                    sc["template"] = tmpl

                data = sc.get("data")
                if not isinstance(data, dict):
                    data = {}
                    sc["data"] = data

                if tmpl == "ObjectExplainer":
                    fill_explainer(data, sc, sc_idx)
                elif tmpl == "ProcessFlow":
                    if not fill_process_flow(data, sc, sc_idx):
                        sc["template"] = "ObjectExplainer"
                        fill_explainer(data, sc, sc_idx)
                elif tmpl == "MetricShift":
                    if not fill_metric_shift(data, sc, sc_idx):
                        sc["template"] = "ObjectExplainer"
                        fill_explainer(data, sc, sc_idx)
                elif tmpl in DATA_DRIVEN_TEMPLATES and not data:
                    sc["template"] = "ObjectExplainer"
                    fill_explainer(data, sc, sc_idx)

                # Only staged rasters may reach the browser. A pseudo-ref such as ``character:maya``
                # is dropped here rather than failing the renderer's own guard an hour later.
                refs = sc.get("assetRefs")
                if isinstance(refs, list):
                    sc["assetRefs"] = [
                        r for r in refs if isinstance(r, str) and _STAGED_ASSET.fullmatch(r)
                    ]
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
                elif move == "orbit" and sc.get("template") not in {"ObjectExplainer", "ParallaxStory"}:
                    cam["move"] = "push"
                    cam["target"] = first_text_id

                # Normalize motion beats within scene relative duration
                motion = sc.get("motion")
                if not isinstance(motion, dict):
                    motion = {"energy": 0.6, "continuity": "cut", "beats": []}
                    sc["motion"] = motion
                beats = motion.get("beats")
                if not isinstance(beats, list) or not beats:
                    motion["beats"] = [
                        {"atFrame": 0, "kind": "enter", "subject": "actor:0"},
                        {"atFrame": max(1, duration // 3), "kind": "action", "subject": "actor:0"},
                        {"atFrame": max(2, (duration * 2) // 3), "kind": "emphasis", "subject": "actor:0"},
                    ]
                else:
                    for b in beats:
                        if not isinstance(b, dict):
                            continue
                        bf = int(b.get("atFrame") or 0)
                        if bf >= current_frame and current_frame > 0:
                            bf -= current_frame
                        b["atFrame"] = max(0, min(duration - 1, bf))
                        if not b.get("subject"):
                            b["subject"] = "actor:0"
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
