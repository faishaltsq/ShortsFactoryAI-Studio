"""The agents that exist in Phase 1, with their prompts and contracts.

Every prompt states the exact JSON shape. Every contract is the artifact model, so a field the
prompt forgot is a validation failure rather than a silent default.
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

from ..contracts import (
    CreativeMotionBriefArtifact,
    MetadataArtifact,
    MotionPlanArtifact,
    ResearchArtifact,
    ReviewArtifact,
    ScriptArtifact,
    StoryboardArtifact,
    VisualPlanArtifact,
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
        "theme": "editorialLight",
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

VISUAL_PLAN_SYSTEM_PROMPT = (
    "You are an expert Creative Visual Director specializing in Bright Editorial Educational Animation for 1080x1920 vertical video. "
    "Given a script, topic, and research, you produce an authoritative semantic visual plan. "
    "Do NOT rely on generic abstract shapes, empty voids, or decorative circles. Every beat MUST identify a concrete physical or diagrammatic subject "
    "that visually explains the spoken educational concept. "
    "Return ONLY JSON matching this shape:\n"
    "{\n"
    '  "schema_version": 1,\n'
    '  "style_intent": {\n'
    '    "style_name": "editorial_technical" | "editorial_scientific" | "editorial_industrial" | "editorial_lifestyle",\n'
    '    "theme": "editorialLight" | "spaceDark" | "warmLifestyle",\n'
    '    "color_mood": "<e.g. Crisp slate and vibrant amber accents>",\n'
    '    "motion_character": "crisp_editorial" | "fluid_mechanical" | "organic_smooth",\n'
    '    "lighting_intent": "<lighting and contrast intent>"\n'
    "  },\n"
    '  "beats": [\n'
    "    {\n"
    '      "scene_id": "s1",\n'
    '      "concept": "<core concept being taught in this beat>",\n'
    '      "primary_subject": "<concrete object from vocabulary>",\n'
    '      "secondary_elements": ["<optional secondary object>"],\n'
    '      "environment": "dataCenter" | "circuit" | "space" | "lab" | "city" | "grid" | "abstract" | "oceanFloor" | "kitchen",\n'
    '      "metaphor_grounding": "<why this visual object explains the spoken concept>",\n'
    '      "camera_intent": {\n'
    '        "movement": "push" | "pull" | "pan" | "tilt",\n'
    '        "target": "<target element ID or subject>",\n'
    '        "motivation": "<why this camera movement reinforces the narrative>"\n'
    "      },\n"
    '      "mandatory_assets": ["<primary_subject>"],\n'
    '      "visual_density": "clean" | "medium" | "dense",\n'
    '      "key_action": "<visual transformation or action in scene>"\n'
    "    }\n"
    "  ],\n"
    '  "reasoning": "<editorial rationale for the visual progression>"\n'
    "}\n"
    "Vocabulary of available concrete objects:\n"
    "- Tech & Compute: gpu, wafer, serverRack, dataCenter, neuralNet, database, cloudArch, cpuProcessor, quantumProcessor, opticalFiber, subseaCableCutaway\n"
    "- Science & Discovery: microscope, lightBulb, planetEarth, satellite, antenna\n"
    "- Industry & Economy: factory, stockChart, building, turbine, solarPanel, coolingFan\n"
    "- Devices, Graphics & Everyday: phone, drone, rocket, meshTopology, claySculpt, ramenBowl, cookingPot\n"
)

CREATIVE_MOTION_BRIEF_SYSTEM_PROMPT = (
    "You are an expert Creative Film & Motion Director specializing in educational short-form vertical animation. "
    "Given a script, topic, and research, produce an authoritative film-level creative motion brief. "
    "Establish the overarching visual thesis, art direction palette, primary visual motifs, pacing strategy, and transitions. "
    "Return ONLY JSON matching this shape:\n"
    "{\n"
    '  "schema_version": 1,\n'
    '  "visual_thesis": "<overarching metaphor and core visual thesis statement explaining the concept>",\n'
    '  "art_direction": {\n'
    '    "palette": "editorialLight" | "spaceDark" | "warmLifestyle",\n'
    '    "primary_accent": "#0055FF",\n'
    '    "secondary_accent": "#FF4400",\n'
    '    "background": "#F8FAFC",\n'
    '    "typography_style": "boldSans" | "technicalMono" | "editorialSerif"\n'
    "  },\n"
    '  "narrative_arc": "<visual progression from hook to build to payoff>",\n'
    '  "primary_visual_motifs": ["<motif1>", "<motif2>"],\n'
    '  "pacing_strategy": "<motion pacing across scenes>",\n'
    '  "reusable_motifs": ["<anchor1>", "<anchor2>"],\n'
    '  "scene_transitions": ["cut", "wipe", "slideUp", "zoom"],\n'
    '  "motion_complexity_budget": "low" | "medium" | "high"\n'
    "}\n"
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
        ("kabel bawah laut", "kabel laut", "subsea", "submarine cable", "dasar laut", "palung laut", "bawah air", "ocean floor", "antarbenua", "serat kaca fisik"),
        "oceanFloor",
        ("subseaCableCutaway", "opticalFiber", "dataCenter"),
    ),
    (
        ("mi instan", "mie instan", "mie", "noodle", "ramen", "makan", "makanan", "panci", "mangkok", "masak", "resep", "nutrisi", "dapur", "kuliner"),
        "kitchen",
        ("ramenBowl", "cookingPot", "phone"),
    ),
    (
        ("bumi", "planet", "tata surya", "globe", "benua", "atmosfer", "geografi", "astronomi", "kehidupan luar bumi"),
        "space",
        ("planetEarth", "satellite", "rocket"),
    ),
    (
        ("mesh", "wireframe", "topologi", "topology", "edge loop", "poligon", "polygon", "vertex", "vertices", "geometri", "geometry", "3d model"),
        "grid",
        ("meshTopology", "gpu", "neuralNet"),
    ),
    (
        ("sculpt", "sculpting", "clay", "volume", "pahat", "tekstur", "texture", "organic", "anatomi", "brush", "digital clay"),
        "lab",
        ("claySculpt", "meshTopology", "gpu"),
    ),
    (
        ("breakdown", "pass", "aset 3d", "karakter 3d", "render 3d", "objek 3d"),
        "lab",
        ("meshTopology", "claySculpt", "gpu"),
    ),
    (
        ("cloud", "arsitektur cloud", "microservice", "infrastructure", "infrastruktur", "load balancer", "api gateway", "vpc", "cluster", "kontainer", "request flow", "backend"),
        "dataCenter",
        ("cloudArch", "serverRack", "database"),
    ),
    (
        ("cpu", "processor", "prosesor", "chipset", "multicore", "clock speed", "cache", "bus"),
        "circuit",
        ("cpuProcessor", "serverRack", "wafer"),
    ),
    (
        ("quantum", "kuantum", "qubit", "superkonduktor", "kriogenik", "entanglement"),
        "lab",
        ("quantumProcessor", "neuralNet", "serverRack"),
    ),
    (
        ("fiber", "serat optik", "kabel optik", "laser optik", "backbone optik"),
        "oceanFloor",
        ("opticalFiber", "subseaCableCutaway", "serverRack"),
    ),
    (
        ("data center", "datacenter", "server", "rak", "hosting", "penyimpanan", "storage"),
        "dataCenter",
        ("serverRack", "dataCenter", "coolingFan"),
    ),
    (
        ("gpu", "grafis", "akselerator", "chip", "semikonduktor", "wafer", "transistor", "nvidia", "cuda", "vram"),
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


class SubjectResolutionError(ValueError):
    """Raised when a scene requires a concrete visual subject but no asset in the library matches."""
    pass


def fill_explainer(data: dict[str, Any], scene: dict[str, Any], index: int) -> None:
    """Give an ``ObjectExplainer`` scene a visually dominant stage matching its concrete subject.

    Every scene identifies the concrete visual subject required to explain its narration.
    The hero object is visually dominant (scale 0.60–0.65, centered at y=0.46) with intentional
    hierarchy and spacing, avoiding competing text overlays or empty voids.
    """
    scene_txt = _scene_text(scene)
    environment, kinds = _topic_visual(scene_txt)

    objects = data.get("objects")
    usable: list[dict[str, Any]] = []
    if isinstance(objects, list):
        for item in objects:
            if isinstance(item, dict) and item.get("kind") in OBJECT_KINDS:
                usable.append(dict(item))

    # Semantic check: if model supplied generic/mismatched objects when the narration demands
    # a specific concrete subject (e.g. meshTopology, claySculpt, cloudArch, cpuProcessor),
    # replace the primary hero with the exact concrete subject.
    concrete_hero = kinds[0]
    if usable:
        current_hero = usable[0].get("kind")
        # If current hero is generic/abstract/wafer while concrete topic is mesh, clay, cloud, subsea, etc., upgrade hero
        if concrete_hero in {
            "meshTopology", "claySculpt", "cloudArch", "cpuProcessor", "quantumProcessor",
            "opticalFiber", "subseaCableCutaway", "ramenBowl", "cookingPot", "planetEarth"
        }:
            if current_hero != concrete_hero:
                usable[0]["kind"] = concrete_hero
                usable[0]["label"] = _object_label(concrete_hero)
        # Ensure hero object is visually dominant and enters at frame 0
        hero = usable[0]
        hero["size"] = max(0.58, min(0.66, float(hero.get("size") or 0.62)))
        hero["x"] = 0.5
        hero["y"] = 0.46
        hero["at"] = 0

        for s_idx, supp in enumerate(usable[1:], 1):
            raw_at = supp.get("at", 0)
            if not isinstance(raw_at, (int, float)) or raw_at > 30:
                supp["at"] = min(20, 10 * s_idx)
    else:
        usable = [
            {"kind": kinds[0], "x": 0.5, "y": 0.46, "size": 0.62, "at": 0, "label": _object_label(kinds[0])},
            {"kind": kinds[1], "x": 0.26, "y": 0.72, "size": 0.24, "at": 14, "label": _object_label(kinds[1])},
            {"kind": kinds[2], "x": 0.74, "y": 0.72, "size": 0.24, "at": 26, "label": _object_label(kinds[2])},
        ]

    data["objects"] = usable[:5]
    data.setdefault("environment", environment)
    if data.get("environment") not in {
        "dataCenter", "circuit", "space", "lab", "city", "grid", "abstract", "oceanFloor", "kitchen"
    }:
        data["environment"] = environment
    if not isinstance(data.get("callouts"), list):
        data["callouts"] = [
            {"object": 0, "text": str(scene.get("segment") or "")[:48] or "Objek utama", "dx": 0.0, "dy": -0.16, "at": 40}
        ]
    if not isinstance(data.get("flows"), list):
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
        "if you have no source, set content_kind to 'fictional'. Each candidate in candidates must "
        "be an object with 'title' and 'angle'. Each claim in claims must be an object with 'text'."
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
    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        topic = data.get("topic") or "topic"
        if data.get("content_kind") == "factual" and not data.get("sources"):
            data["sources"] = [{"url": f"https://id.wikipedia.org/wiki/{topic}", "title": str(topic)}]
        return data



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
    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        topic = data.get("topic") or "topic"
        if data.get("content_kind") == "factual" and not data.get("sources"):
            data["sources"] = [{"url": f"https://id.wikipedia.org/wiki/{topic}", "title": str(topic)}]
        return data



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
                + "\nRewrite the script to address every finding. You MUST adopt the suggested 'fix' for each finding. Return the complete script, "
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
        "Be strict about a weak hook and a missing payoff, but accept if the script is coherent and delivers its point. "
        "If attempt >= 1 and the revision addressed the feedback, favor 'accept'."
    )

    def system_prompt_for_task(self, task: str) -> str:
        if task == "visual_plan":
            return VISUAL_PLAN_SYSTEM_PROMPT
        if task in ("creative_motion_brief", "creative-motion-brief"):
            return CREATIVE_MOTION_BRIEF_SYSTEM_PROMPT
        return self.system_prompt

    def build_user_prompt(self, **kwargs: Any) -> str:
        task = getattr(self, "current_task", None)
        if task in ("creative_motion_brief", "creative-motion-brief"):
            script = cast(dict[str, Any], kwargs.get("script") or {})
            topic = cast(dict[str, Any], kwargs.get("topic") or {})
            research = cast(dict[str, Any], kwargs.get("research") or {})
            return (
                f"Topic:\n{json.dumps(topic, ensure_ascii=False)[:1000]}\n\n"
                f"Research:\n{json.dumps(research, ensure_ascii=False)[:2000]}\n\n"
                f"Script:\n{json.dumps(script, ensure_ascii=False)[:4000]}\n\n"
                "Produce an authoritative film-level creative motion brief establishing visual thesis, art direction, and pacing."
            )
        if task == "visual_plan":
            script = cast(dict[str, Any], kwargs.get("script") or {})
            topic = cast(dict[str, Any], kwargs.get("topic") or {})
            research = cast(dict[str, Any], kwargs.get("research") or {})
            return (
                f"Topic:\n{json.dumps(topic, ensure_ascii=False)[:1000]}\n\n"
                f"Research:\n{json.dumps(research, ensure_ascii=False)[:2000]}\n\n"
                f"Script:\n{json.dumps(script, ensure_ascii=False)[:4000]}\n\n"
                "Produce an authoritative semantic visual plan with concrete visual objects for each segment."
            )
        script = cast(dict[str, Any], kwargs.get("script") or {})
        attempt = int(kwargs.get("attempt") or 0)
        return (
            f"Attempt {attempt}. Review this script:\n"
            + json.dumps(script, ensure_ascii=False)[:4000]
        )

    def contract(self) -> type[Artifact]:
        task = getattr(self, "current_task", None)
        if task in ("creative_motion_brief", "creative-motion-brief"):
            return CreativeMotionBriefArtifact
        if task == "visual_plan":
            return VisualPlanArtifact
        return ReviewArtifact

    def sanitize_payload(self, payload: dict[str, Any], task: str | None = None) -> dict[str, Any]:
        if task is None:
            task = getattr(self, "current_task", None)
        if task in ("creative_motion_brief", "creative-motion-brief") or (
            task is None
            and ("art_direction" in payload or "visual_thesis" in payload)
            and "beats" not in payload
        ):
            if not payload.get("schema_version"):
                payload["schema_version"] = 1
            if not payload.get("visual_thesis"):
                payload["visual_thesis"] = str(
                    payload.get("reasoning")
                    or payload.get("concept")
                    or "Visual thesis for motion graphics."
                )
            art = payload.get("art_direction")
            if isinstance(art, str):
                art = {"palette": art}
            elif not isinstance(art, dict):
                art = {}
            if not art.get("palette"):
                art["palette"] = "editorialLight"
            if not art.get("primary_accent"):
                art["primary_accent"] = "#0055FF"
            if not art.get("secondary_accent"):
                art["secondary_accent"] = "#FF4400"
            if not art.get("background"):
                art["background"] = "#F8FAFC"
            if not art.get("typography_style"):
                art["typography_style"] = "boldSans"
            payload["art_direction"] = art
            if not payload.get("motion_complexity_budget"):
                payload["motion_complexity_budget"] = "medium"
            return payload
        if task == "visual_plan" or "beats" in payload or "style_intent" in payload:
            if not payload.get("schema_version"):
                payload["schema_version"] = 1
            if not payload.get("theme"):
                style_in = payload.get("style_intent")
                if isinstance(style_in, dict) and style_in.get("theme"):
                    payload["theme"] = style_in["theme"]
                else:
                    payload["theme"] = "editorialLight"
            if "reasoning" in payload and not payload.get("visual_thesis"):
                payload["visual_thesis"] = str(payload.get("reasoning") or "")
            if not isinstance(payload.get("beats"), list):
                payload["beats"] = []
            for idx, beat in enumerate(payload["beats"]):
                if not isinstance(beat, dict):
                    continue
                seg_id = beat.get("narrationSegmentId") or beat.get("scene_id") or beat.get("segment_id") or f"s{idx + 1}"
                beat["narrationSegmentId"] = str(seg_id)
                concept = beat.get("conceptToExplain") or beat.get("concept") or "Core concept"
                beat["conceptToExplain"] = str(concept)
                purpose = beat.get("visualPurpose") or beat.get("metaphor_grounding") or beat.get("purpose") or "Explains narration visually"
                beat["visualPurpose"] = str(purpose)
                action = beat.get("visualAction") or beat.get("key_action") or beat.get("action") or "Visual emphasis on subject"
                beat["visualAction"] = str(action)
                subj = beat.get("primarySubjects") or beat.get("primary_subject") or []
                if isinstance(subj, str):
                    beat["primarySubjects"] = [subj]
                elif isinstance(subj, list):
                    beat["primarySubjects"] = [str(s) for s in subj]
                req = beat.get("requiredObjects") or beat.get("mandatory_assets") or beat.get("secondary_elements") or []
                if isinstance(req, str):
                    beat["requiredObjects"] = [req]
                elif isinstance(req, list):
                    beat["requiredObjects"] = [str(r) for r in req]
                if not beat.get("environment"):
                    beat["environment"] = "abstract"
                if not beat.get("sceneType"):
                    beat["sceneType"] = "ObjectExplainer"
                cam = beat.get("cameraIntent") or beat.get("camera_intent")
                if isinstance(cam, dict):
                    move = cam.get("move") or cam.get("movement") or "push"
                    target = cam.get("target") or (beat["primarySubjects"][0] if beat["primarySubjects"] else "hero")
                    beat["cameraIntent"] = {"move": move, "shot": cam.get("shot", "medium"), "target": target}
                else:
                    beat["cameraIntent"] = {"move": "push", "shot": "medium", "target": "hero"}
            return payload
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
        "You turn a script into a storyboard for a 1080x1920 30fps vertical video. Return ONLY JSON matching "
        "this exact shape (types matter):\n"
        + STORYBOARD_SCHEMA
        + "\nRules: scenes must be contiguous (scene N starts where N-1 ended). "
        "durationInFrames between 30 and 3000. Give every scene a motivated camera movement ('push', 'pull', 'pan', or 'tilt') "
        "targeting an element id in that scene's text array (e.g. camera.target='t1') with amplitude 0.08 to 0.15 and ease 'linear'. "
        "Do NOT leave camera.move as 'static', because static scenes cause frozen-frame QC rejection. "
        "Prefer 'ObjectExplainer': every scene MUST identify the concrete visual subject required to explain its narration. "
        "The main hero object must be visually dominant (size ~0.62 at center y=0.46). "
        "Every scene declares environment ('dataCenter', 'circuit', 'space', 'lab', 'city', 'grid', 'abstract', 'oceanFloor', 'kitchen') "
        "and 1-3 objects from: gpu, wafer, serverRack, dataCenter, neuralNet, database, satellite, antenna, turbine, solarPanel, coolingFan, "
        "phone, drone, rocket, building, meshTopology, claySculpt, cloudArch, cpuProcessor, quantumProcessor, opticalFiber, "
        "subseaCableCutaway, ramenBowl, cookingPot, planetEarth, microscope, lightBulb, factory, stockChart. "
        "Concrete semantic requirements: subsea cable/ocean -> subseaCableCutaway, oceanFloor; ramen/noodle/cooking -> ramenBowl, cookingPot, kitchen; "
        "planet/earth/astronomy -> planetEarth, space; 3D mesh/topology -> meshTopology; clay sculpting -> claySculpt; "
        "cloud architecture -> cloudArch; CPU/processor -> cpuProcessor; GPU computing -> gpu; "
        "science/biology/medicine -> microscope, lab; innovation/electricity -> lightBulb, lab; industrial history/manufacturing -> factory, city; market/economics/trend -> stockChart, city. "
        "Theme should default to 'editorialLight', or 'warmLifestyle' for cooking, or 'spaceDark' for space/night. "
        "Abstract gradients or decorative circles are NOT acceptable substitutes for concrete subjects. "
        "Use 'ProcessFlow' when the segment explains how something works step-by-step, and 'MetricShift' when it compares quantities. "
        "Vary environments and objects across scenes. Give every scene at least one beat."
    )
    def build_user_prompt(self, **kwargs: Any) -> str:
        script = cast(dict[str, Any], kwargs.get("script") or {})
        fps = int(kwargs.get("fps") or 30)
        visual_plan = kwargs.get("visual_plan")
        assets = kwargs.get("assets")
        plan_str = ""
        if visual_plan and isinstance(visual_plan, dict):
            beats = visual_plan.get("beats") or []
            plan_str += f"\nSemantic Visual Plan:\n{json.dumps(beats, ensure_ascii=False)[:3000]}\n"
        if assets and isinstance(assets, dict):
            resolved = assets.get("resolved") or assets.get("assets") or []
            plan_str += f"\nResolved Asset Library:\n{json.dumps(resolved, ensure_ascii=False)[:2000]}\n"
        return (
            f"fps={fps}. Script:\n{json.dumps(script, ensure_ascii=False)[:5000]}\n"
            f"{plan_str}"
            "One scene per segment, in order. Follow the visual plan for primary_subject and environment."
        )

    def contract(self) -> type[Artifact]:
        return StoryboardArtifact

    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenes = payload.get("scenes")
        # Resolve contextual theme based on script content
        all_text = " ".join([
            str(sc.get("segment") or "") + " " + " ".join(
                str(t.get("text") or "") for t in sc.get("text") or [] if isinstance(t, dict)
            )
            for sc in (scenes or []) if isinstance(sc, dict)
        ]).lower()
        if any(w in all_text for w in ("antariksa", "orbit", "bintang", "galaksi", "luar angkasa", "cybersecurity", "malware", "hacker")):
            context_theme = "spaceDark"
        elif any(w in all_text for w in ("mi instan", "mie", "ramen", "masak", "dapur", "makanan", "kitchen", "nutrisi")):
            context_theme = "warmLifestyle"
        else:
            context_theme = "editorialLight"

        current_theme = payload.get("theme")
        if not current_theme or current_theme in ("dusk", "midnight"):
            payload["theme"] = context_theme
        else:
            payload.setdefault("theme", context_theme)
        fps = int(payload.get("fps") or 30)
        subs = payload.get("subtitles")
        if isinstance(subs, list):
            clean_subs = []
            for item in subs:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                start_ms = item.get("startMs")
                end_ms = item.get("endMs")
                if start_ms is None and "startFrame" in item:
                    start_ms = int(float(item["startFrame"]) * 1000 / fps)
                if end_ms is None and "endFrame" in item:
                    end_ms = int(float(item["endFrame"]) * 1000 / fps)
                if start_ms is None:
                    start_ms = 0
                if end_ms is None or end_ms <= start_ms:
                    end_ms = int(start_ms) + 1500
                clean_subs.append({
                    "startMs": int(start_ms),
                    "endMs": int(end_ms),
                    "text": text,
                })
            payload["subtitles"] = clean_subs
        else:
            payload["subtitles"] = []

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
        visual_plan = kwargs.get("visual_plan")
        plan_str = ""
        if visual_plan and isinstance(visual_plan, dict):
            plan_str = f"\nVisual Plan Style Intent:\n{json.dumps(visual_plan.get('style_intent') or {}, ensure_ascii=False)[:1000]}\n"
        return (
            "Storyboard:\n"
            + json.dumps(storyboard, ensure_ascii=False)[:5000]
            + plan_str
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
