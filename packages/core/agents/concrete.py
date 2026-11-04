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
    MotionCodeArtifact,
    MotionPlanArtifact,
    ResearchArtifact,
    ReviewArtifact,
    ScriptArtifact,
    StoryboardArtifact,
    VisualPlanArtifact,
)
from ..contracts.base import Artifact
from ..contracts.scene import (
    DATA_DRIVEN_TEMPLATES,
    OBJECT_KINDS,
    OBJECT_LABELS,
    CausalStateSpec,
)
from ..media.codeguard import CodeGuard
from ..providers.base import Capability
from . import Agent, CallContext
from .skill_loader import MotionSkillLoader, SkillBundle

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
                "causal_state": {
                    "initial_state": "Satelit GPS mengorbit bumi memancarkan sinyal waktu uncorrected.",
                    "causal_action": "Dilatasi waktu gravitasi mempercepat jam atom satelit 38 mikrodetik per hari.",
                    "resulting_state": "Posisi peta melenceng 11 kilometer jika koreksi relativitas tidak diterapkan.",
                    "transition": "Zoom fokus ke penerima GPS ponsel yang menyinkronkan data koreksi.",
                },
                "layout_mode": "DefaultHero",
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
    "You are an expert Creative Film & Motion Director specializing in educational short-form "
    "vertical animation (1080x1920). Given a script, topic, and research, you decide the creative "
    "identity of the whole film BEFORE any shot is planned, and every later stage is governed by "
    "what you write here.\n"
    "The working principle is: ILLUSTRATE THE NOUN. ANIMATE THE VERB. SHOW THE CONSEQUENCE.\n"
    "Decide, and commit:\n"
    "- What the film argues (narrative_thesis) and what it looks like (visual_thesis).\n"
    "- The one organising image the film returns to (visual_metaphor) and the motifs that carry it.\n"
    "- The world the subject actually lives in (subject_environment) - a foundry, a data hall, an "
    "ocean trench, a cell. It must come from the subject, not from a house style.\n"
    "- A palette, and WHY it is that palette (palette_rationale) - this is an explanation of a "
    "choice, not a restatement of the hex values.\n"
    "- How type behaves as a design element (typography_direction), how the camera behaves "
    "(camera_language), and what motion means in this film (motion_language): what moves, why, and "
    "what the viewer reads from it.\n"
    "- How the film advances (scene_progression), the rule that joins one shot to the next "
    "(transition_strategy), where it peaks (visual_climax), and what the viewer is left with "
    "(ending_payoff).\n"
    "Do not default to a dark background, a gradient, or a colour unrelated to the topic. Choose "
    "the treatment the topic earns: bright editorial illustration, clean technical vector "
    "animation, an educational diagram, a spatial infographic, cinematic typography, a process "
    "visualisation, an architectural cutaway, or a product-style animation. One coherent visual "
    "system, with intentional variation inside it. You are not required to use every treatment.\n"
    "Return ONLY JSON matching this shape:\n"
    "{\n"
    '  "schema_version": 1,\n'
    '  "narrative_thesis": "<what the film argues, in one sentence>",\n'
    '  "visual_thesis": "<what the film looks like, and the core metaphor it is built on>",\n'
    '  "visual_metaphor": "<the single organising image the whole film returns to>",\n'
    '  "art_direction": {\n'
    '    "palette": "editorialLight" | "spaceDark" | "warmLifestyle",\n'
    '    "primary_accent": "#0055FF",\n'
    '    "secondary_accent": "#FF4400",\n'
    '    "background": "#F8FAFC",\n'
    '    "typography_style": "boldSans" | "technicalMono" | "editorialSerif"\n'
    "  },\n"
    '  "subject_environment": "<the world this subject lives in, and why that world>",\n'
    '  "palette_rationale": "<why these colours, in terms of the subject>",\n'
    '  "typography_direction": "<how type is used as a design element, not which font>",\n'
    '  "camera_language": "<framing and movement across the film, and what it says>",\n'
    '  "motion_language": "<what motion means here: cause, direction, scale, transformation>",\n'
    '  "narrative_arc": "<visual progression from hook to build to payoff>",\n'
    '  "scene_progression": "<how the film advances shot to shot>",\n'
    '  "transition_strategy": "<the rule that joins one shot to the next>",\n'
    '  "scene_transitions": ["cut", "wipe", "slideUp", "zoom"],\n'
    '  "primary_visual_motifs": ["<motif1>", "<motif2>"],\n'
    '  "reusable_motifs": ["<an object or treatment that survives across shots>"],\n'
    '  "pacing_strategy": "<motion pacing across scenes>",\n'
    '  "motion_complexity_budget": "low" | "medium" | "high",\n'
    '  "visual_climax": "<the shot where the film peaks, and what is on screen>",\n'
    '  "ending_payoff": "<what the viewer is left with>"\n'
    "}\n"
    "Write every field. An empty field is a decision you did not make, and the stages after you "
    "will guess instead.\n"
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
        ("mi instan", "mie instan", "mie", "noodle", "ramen", "makan", "makanan", "panci", "mangkok", "masak", "resep", "nutrisi", "dapur", "kuliner", "adonan", "goreng", "minyak", "rebus", "keriting", "pengawet", "spons"),
        "kitchen",
        ("ramenBowl", "cookingPot", "factory"),
    ),
    (
        ("bakteri", "mikroba", "sel", "virus", "kuman", "mikroskop", "biologi", "kelembaban", "kelembapan", "organisme", "higienis"),
        "lab",
        ("microscope", "cookingPot", "ramenBowl"),
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
        for word in keywords:
            if re.search(r"\b" + re.escape(word) + r"\b", text):
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
            "opticalFiber", "subseaCableCutaway", "ramenBowl", "cookingPot", "planetEarth",
            "microscope", "factory"
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
            visual_plan = cast(dict[str, Any], kwargs.get("visual_plan") or {})
            language = str(kwargs.get("language") or "id")
            return (
                f"Narration language: {language}\n\n"
                f"Topic:\n{json.dumps(topic, ensure_ascii=False)[:2000]}\n\n"
                f"Research:\n{json.dumps(research, ensure_ascii=False)[:3000]}\n\n"
                f"Script:\n{json.dumps(script, ensure_ascii=False)[:6000]}\n\n"
                f"Planned visual beats (already decided — make the film's identity govern them, "
                f"do not restate them):\n{json.dumps(visual_plan, ensure_ascii=False)[:3000]}\n\n"
                "Decide the film's creative identity: what it argues, what it looks like, the "
                "world its subject lives in, why that palette, how type and camera and motion "
                "behave, how the film advances, where it peaks, and what the viewer is left with. "
                "Write every field of the JSON shape."
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

STORYBOARD_SYSTEM_PROMPT = (
    "You turn a script into a storyboard for a 1080x1920 30fps vertical video. Return ONLY JSON matching "
    "this exact shape (types matter):\n"
    + STORYBOARD_SCHEMA
    + "\nRules: scenes must be contiguous (scene N starts where N-1 ended). "
    "durationInFrames between 30 and 3000. Give every scene a motivated camera movement ('push', 'pull', 'pan', or 'tilt') "
    "targeting an element id in that scene's text array (e.g. camera.target='t1') with amplitude 0.08 to 0.15 and ease 'linear'. "
    "Do NOT leave camera.move as 'static', because static scenes cause frozen-frame QC rejection. "
    "Prefer 'ObjectExplainer': every scene MUST identify the concrete visual subject required to explain its narration. "
    "The main hero object must be visually dominant (size ~0.62 at center y=0.46). "
    "For every scene, specify causal_state with initial_state, causal_action, resulting_state, and transition. "
    "Choose an expressive layout_mode: DefaultHero, SplitComparison, RadialNetwork, LeftRailProcess, or FullBleedFocus. "
    "Every scene declares environment ('dataCenter', 'circuit', 'space', 'lab', 'city', 'grid', 'abstract', 'oceanFloor', 'kitchen') "
    "and 1-3 objects from: gpu, wafer, serverRack, dataCenter, neuralNet, database, satellite, antenna, turbine, solarPanel, coolingFan, "
    "phone, drone, rocket, building, meshTopology, claySculpt, cloudArch, cpuProcessor, quantumProcessor, opticalFiber, "
    "subseaCableCutaway, ramenBowl, cookingPot, planetEarth, microscope, lightBulb, factory, stockChart. "
    "Concrete semantic requirements: subsea cable/ocean -> subseaCableCutaway, oceanFloor; ramen/noodle/cooking -> ramenBowl, cookingPot, kitchen; "
    "planet/earth/astronomy -> planetEarth, space; 3D mesh/topology -> meshTopology; clay sculpting -> claySculpt; "
    "cloud architecture -> cloudArch; CPU/processor -> cpuProcessor; GPU computing -> gpu; "
    "science/biology/medicine -> microscope, lab; innovation/electricity -> lightBulb, lab; industrial history/manufacturing -> factory, city; market/economics/trend -> stockChart, city. "
    "Shot, not slide: every scene is a shot with a narrative purpose, and it shows an initial "
    "state, then the action that changes it, then the resulting state. A shot whose only change is "
    "a text swap is a slide; give it a subject that transforms. "
    "Continuity: when the same subject or mechanism carries into the next shot, declare "
    '"continuity": "carry" and repeat the same object kind so it stays recognisable across the '
    "cut. Do not reset the world after every sentence, and do not carry a subject the next segment "
    "is not about. "
    'Set theme from the creative brief\'s art_direction.palette when a brief is provided - it is the '
    "director's decision. Only when no brief is given, default to 'editorialLight', "
    "'warmLifestyle' for cooking, or 'spaceDark' for space/night. "
    "Abstract gradients or decorative circles are NOT acceptable substitutes for concrete subjects. "
    "Use 'ProcessFlow' when the segment explains how something works step-by-step, and 'MetricShift' when it compares quantities. "
    "Vary environments and objects across scenes. Give every scene at least one beat."
)


class StoryboardAgent(Agent):
    name = "StoryboardAgent"
    system_prompt = STORYBOARD_SYSTEM_PROMPT
    def build_user_prompt(self, **kwargs: Any) -> str:
        script = cast(dict[str, Any], kwargs.get("script") or {})
        fps = int(kwargs.get("fps") or 30)
        visual_plan = kwargs.get("visual_plan")
        assets = kwargs.get("assets")
        brief = kwargs.get("creative_motion_brief") or kwargs.get("brief") or {}
        plan_str = ""
        if visual_plan and isinstance(visual_plan, dict):
            beats = visual_plan.get("beats") or []
            plan_str += f"\nSemantic Visual Plan:\n{json.dumps(beats, ensure_ascii=False)[:3000]}\n"
        if assets and isinstance(assets, dict):
            resolved = assets.get("resolved") or assets.get("assets") or []
            plan_str += f"\nResolved Asset Library:\n{json.dumps(resolved, ensure_ascii=False)[:2000]}\n"
        brief_str = ""
        if isinstance(brief, dict) and any(
            brief.get(key) for key in ("art_direction", "visual_thesis", "subject_environment")
        ):
            # The director decided the film's identity before the shots. Handing it here is what
            # keeps one art direction across the storyboard instead of a per-scene guess: the
            # theme you emit must be the brief's palette, not the system prompt's house default.
            brief_keys = (
                "narrative_thesis", "visual_thesis", "visual_metaphor", "art_direction",
                "subject_environment", "palette_rationale", "typography_direction",
                "camera_language", "motion_language", "scene_progression",
                "transition_strategy", "primary_visual_motifs", "reusable_motifs",
                "visual_climax", "ending_payoff",
            )
            brief_str = (
                "\nCreative brief (governs every scene; this is the director's decision, not a "
                "suggestion):\n"
                f"{json.dumps({k: brief.get(k) for k in brief_keys if brief.get(k)}, ensure_ascii=False, indent=2)[:4000]}\n"
                "Use the brief's art_direction.palette as the theme. Do not substitute a house "
                "default. Carry the camera_language, motion_language and transition_strategy into "
                "the per-scene camera, motion and transition fields, and keep every reusable_motif "
                "recognisable from the scene it first appears in.\n"
            )
        return (
            f"fps={fps}. Script:\n{json.dumps(script, ensure_ascii=False)[:5000]}\n"
            f"{brief_str}"
            f"{plan_str}"
            "One scene per segment, in order. Follow the brief for art direction and the visual "
            "plan for primary_subject and environment."
        )

    def contract(self) -> type[Artifact]:
        return StoryboardArtifact

    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenes = payload.get("scenes")
        # The director's palette wins. The keyword heuristic below is a fallback for a job that has
        # no brief at all, because overriding a decided art direction with a keyword guess is how a
        # film ends up with a different look per scene — the exact failure the brief exists to stop.
        brief_palette = ""
        kwargs = getattr(self, "current_kwargs", None)
        if isinstance(kwargs, dict):
            brief = kwargs.get("creative_motion_brief") or kwargs.get("brief") or {}
            if isinstance(brief, dict):
                art = brief.get("art_direction")
                if isinstance(art, dict) and isinstance(art.get("palette"), str):
                    brief_palette = art["palette"].strip()
        if brief_palette:
            payload["theme"] = brief_palette
            return self._finish_sanitize(payload, scenes)

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
        return self._finish_sanitize(payload, scenes)

    def _finish_sanitize(self, payload: dict[str, Any], scenes: Any) -> dict[str, Any]:
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

                # Normalize causal_state and layout_mode
                raw_causal = sc.get("causal_state") if "causal_state" in sc else sc.get("causalState")
                sc.pop("causalState", None)
                if isinstance(raw_causal, CausalStateSpec):
                    sc["causal_state"] = raw_causal
                elif isinstance(raw_causal, dict):
                    init_s = str(
                        raw_causal.get("initial_state") or raw_causal.get("initialState") or ""
                    ).strip()
                    action_s = str(
                        raw_causal.get("causal_action") or raw_causal.get("causalAction") or ""
                    ).strip()
                    result_s = str(
                        raw_causal.get("resulting_state") or raw_causal.get("resultingState") or ""
                    ).strip()
                    trans_s = str(raw_causal.get("transition") or "").strip()
                    if init_s or action_s or result_s or trans_s:
                        sc["causal_state"] = {
                            "initial_state": init_s or "Keadaan awal sistem.",
                            "causal_action": action_s or "Aksi kausal pengubah sistem.",
                            "resulting_state": result_s or "Kondisi hasil perubahan sistem.",
                            "transition": trans_s or "Transisi fokus visual ke aspek berikutnya.",
                        }
                    else:
                        sc["causal_state"] = None
                else:
                    sc["causal_state"] = None

                raw_layout = sc.get("layout_mode") if "layout_mode" in sc else sc.get("layoutMode")
                sc.pop("layoutMode", None)
                if isinstance(raw_layout, str) and raw_layout.strip():
                    cleaned_layout = raw_layout.strip()
                    valid_layouts = {
                        "defaulthero": "DefaultHero",
                        "splitcomparison": "SplitComparison",
                        "radialnetwork": "RadialNetwork",
                        "leftrailprocess": "LeftRailProcess",
                        "fullbleedfocus": "FullBleedFocus",
                    }
                    sc["layout_mode"] = valid_layouts.get(cleaned_layout.lower(), "DefaultHero")
                else:
                    sc["layout_mode"] = None

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


class MotionCoderAgent(Agent):
    name = "MotionCoderAgent"
    requires = frozenset({Capability.CHAT})
    system_prompt = (
        "You are a motion director who writes Remotion code. You do not build slides; you direct "
        "shots.\n"
        "The working principle is: ILLUSTRATE THE NOUN. ANIMATE THE VERB. SHOW THE CONSEQUENCE.\n"
        "You are given the film's creative brief, the narration it must sync to, the shot plan, "
        "the assets that exist, and the measured timing of every shot. Compose the film from those "
        "decisions rather than from a template.\n"
        "Rules of craft:\n"
        "- Every beat answers: what should the viewer understand, what object or phenomenon stands "
        "for it, what changes visually, what causes that change, what state results, and how the "
        "next shot continues it.\n"
        "- Motion communicates cause, direction, scale, relationship, transformation, progression "
        "and consequence. It is not decoration. Do not add floating particles, idle drift or a "
        "repeated spring purely to make frames differ: a scene whose only movement is a decorative "
        "layer is a defect even when it measures as dynamic.\n"
        "- Keep objects recognisable across shots where the brief says a motif recurs. A subject "
        "that survives a cut must still be the same subject.\n"
        "- Text is a design element and may carry the film. A title never has to stay on screen for "
        "a whole shot, and a shot is never required to have one.\n"
        "- Match the brief's palette, typography and camera language. Where the brief is silent, "
        "serve the subject rather than a house style.\n"
        "Technical contract:\n"
        "- 1080x1920 at the given fps, deterministic frame-based animation only. No randomness, no "
        "Date.now(), no Math.random().\n"
        "- Use useCurrentFrame(), interpolate(), spring(), <Sequence>/<Series>, SVG paths, "
        "transforms and masks. Reusable primitives are for technical behaviour (a tracking camera, "
        "a path reveal, a diagram construction), never for a fixed scene appearance.\n"
        "- Timing comes from the narration. A visual change that is supposed to land on a spoken "
        "word is placed at that word's frame, taken from the timing you were given.\n"
        "- Measured keyframes at the start, middle and end of every shot must differ. Achieve that "
        "with the subject's own transformation, a camera move, or a progressive reveal - not with "
        "an ambient layer.\n"
        "- Different topics must not produce the same root layout with different labels.\n"
        "- Allowed imports: react, remotion, @remotion/*, and local ./ modules. Never import fs, "
        "path, os, child_process or any other Node builtin.\n"
        "Return ONLY a JSON object matching the motion-code schema with keys: "
        "schema_version, entry_component, files, dependencies, skill_hashes, validated_by_codeguard, issues. "
        "'files' maps filename (e.g. 'RootComposition.tsx', 'Scene01.tsx') to valid TSX source."
    )

    #: The installed skills that are always worth their tokens. The router names every other skill,
    #: so a motion coder that has it can ask for the right one instead of being handed all of them.
    ALWAYS_SKILLS: tuple[str, ...] = ("remotion-best-practices",)

    def __init__(self, ctx: CallContext) -> None:
        super().__init__(ctx)
        self.skill_loader = MotionSkillLoader()
        self._skills_bundle: SkillBundle | None = None
        self._selected_skills: list[str] = []

    # -- skill selection --------------------------------------------------------------------

    def _shot_needs(self, shots: list[dict[str, Any]], brief: dict[str, Any]) -> str:
        """The free-text description of what these shots need, used to rank installed skills.

        The signal is *per shot*: a film with one diagram shot and one typography shot needs both
        skills, which is the whole reason the selection is not a fixed list. It is deliberately
        derived from what the shots declare rather than from the narration, because a skill that
        teaches how to draw an SVG path is not chosen by the word "submarine".
        """
        parts: list[str] = []
        for shot in shots:
            for key in ("sceneType", "visualPurpose", "visualAction", "environment"):
                value = shot.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
            raw_camera = shot.get("camera")
            camera: dict[str, Any] = raw_camera if isinstance(raw_camera, dict) else {}
            for key in ("move", "shot"):
                value = camera.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
            if shot.get("continuity") == "carry":
                parts.append("continuity carry match cut")
            subjects = shot.get("subjects")
            if isinstance(subjects, list):
                parts.extend(str(item) for item in subjects)
        for key in ("motion_language", "camera_language", "typography_direction"):
            value = brief.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
        return " ".join(parts)

    def _select_skills(self, shots: list[dict[str, Any]], brief: dict[str, Any], **kwargs: Any) -> None:
        """Rank the installed skills for these shots, then load the budgeted bundle.

        The budget is an operator setting, passed in as a prompt kwarg, because the right size
        depends on the endpoint's context window and the operator's token budget rather than on
        anything this repo can know.
        """
        limit = kwargs.get("skill_limit")
        budget = kwargs.get("skill_token_budget")
        limit = limit if isinstance(limit, int) and limit > 0 else 4
        budget = budget if isinstance(budget, int) and budget > 0 else 3000
        available = set(self.skill_loader.list_available_skills())
        ranked = self.skill_loader.rank(self._shot_needs(shots, brief), limit=limit)
        selected = [name for name in self.ALWAYS_SKILLS if name in available]
        for name in ranked:
            if name not in selected:
                selected.append(name)
        # ``rank`` already caps at ``limit``; the always-list may push the total one past it, which
        # is intentional — the router is an index, not a competitor for relevance.
        self._selected_skills = selected[: max(limit, len(self.ALWAYS_SKILLS))] if selected else []
        self._skills_bundle = self.skill_loader.load_bundle(self._selected_skills, max_tokens=budget)

    def system_prompt_for_task(self, task: str) -> str:
        base = super().system_prompt_for_task(task)
        bundle = getattr(self, "_skills_bundle", None)
        if bundle is None:
            # No prompt has been assembled yet, so no shot plan exists to rank against: a direct
            # caller, or the repair round that happens before the first user prompt is built. The
            # always-skills are loaded rather than nothing, because a missing reference block is
            # indistinguishable downstream from a film whose shots needed none.
            available = set(self.skill_loader.list_available_skills())
            self._selected_skills = [name for name in self.ALWAYS_SKILLS if name in available]
            bundle = self.skill_loader.load_bundle(self._selected_skills, max_tokens=3000)
            self._skills_bundle = bundle
        if not bundle.content:
            return base
        provenance = ", ".join(sorted(bundle.skill_hashes))
        return (
            f"{base}\n\n"
            f"Remotion skill reference selected for this film's shots ({provenance}):\n"
            f"{bundle.content}"
        )

    # -- the shot plan ----------------------------------------------------------------------

    @staticmethod
    def _objects_of(scene: dict[str, Any]) -> list[str]:
        raw_data = scene.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        raw = data.get("objects")
        kinds: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    kind = item.get("kind") or item.get("id")
                else:
                    kind = item
                if isinstance(kind, str) and kind:
                    kinds.append(kind)
        return kinds

    def _shot_plan(
        self,
        storyboard: dict[str, Any],
        visual_plan: dict[str, Any],
        script: dict[str, Any],
        timing: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """One entry per shot, carrying the directing decisions and the measured timing.

        The storyboard's scene and the visual plan's beat are the same unit of work described by
        two stages, so they are joined: by ``segment``/``narrationSegmentId`` when that matches,
        otherwise by position, because both are ordered and a mismatch in naming must not silently
        drop the directing decisions.
        """
        raw_beats = visual_plan.get("beats")
        beats: list[dict[str, Any]] = [
            item
            for item in (raw_beats if isinstance(raw_beats, list) else [])
            if isinstance(item, dict)
        ]
        by_segment: dict[str, dict[str, Any]] = {}
        # Only id-less beats are eligible for the positional join. A plan that covers some segments
        # would otherwise hand its first beat to the first *scene* and mis-attribute every directing
        # decision after it — the narration says one thing and the brief's purpose says another.
        positional: list[dict[str, Any]] = []
        for plan_beat in beats:
            key = plan_beat.get("narrationSegmentId")
            if isinstance(key, str) and key:
                by_segment[key] = plan_beat
            else:
                positional.append(plan_beat)

        raw_narration = script.get("segments")
        narration_by_id: dict[str, str] = {}
        for item in raw_narration if isinstance(raw_narration, list) else []:
            if isinstance(item, dict) and item.get("id") is not None:
                narration_by_id[str(item["id"])] = str(item.get("text") or "")

        timing_by_id: dict[str, dict[str, Any]] = {}
        timing_slots: list[dict[str, Any]] = []
        for timing_slot in timing.get("scenes") or []:
            if not isinstance(timing_slot, dict):
                continue
            timing_slots.append(timing_slot)
            if timing_slot.get("sceneId"):
                timing_by_id[str(timing_slot["sceneId"])] = timing_slot

        raw_scenes = storyboard.get("scenes")
        scene_list: list[Any] = raw_scenes if isinstance(raw_scenes, list) else []
        shots: list[dict[str, Any]] = []
        previous_objects: list[str] = []
        for index, scene in enumerate(scene_list):
            if not isinstance(scene, dict):
                continue
            segment = str(scene.get("segment") or "")
            joined: dict[str, Any] | None = by_segment.get(segment)
            if joined is None and index < len(positional):
                joined = positional[index]
            beat: dict[str, Any] = joined or {}
            raw_data = scene.get("data")
            data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
            raw_causal = scene.get("causal_state")
            causal: dict[str, Any] = raw_causal if isinstance(raw_causal, dict) else {}
            raw_motion = scene.get("motion")
            motion: dict[str, Any] = raw_motion if isinstance(raw_motion, dict) else {}
            raw_camera = scene.get("camera")
            camera: dict[str, Any] = raw_camera if isinstance(raw_camera, dict) else {}
            raw_transition = scene.get("transition")
            transition: dict[str, Any] = (
                raw_transition if isinstance(raw_transition, dict) else {}
            )
            objects = self._objects_of(scene)
            shot_timing = timing_by_id.get(str(scene.get("sceneId")))
            if shot_timing is None and index < len(timing_slots):
                shot_timing = timing_slots[index]

            shots.append(
                {
                    "index": index,
                    "sceneId": scene.get("sceneId"),
                    "segment": segment,
                    # -- narrative purpose
                    "narration": narration_by_id.get(segment, ""),
                    "conceptToExplain": beat.get("conceptToExplain") or data.get("heading") or "",
                    "visualPurpose": beat.get("visualPurpose") or "",
                    "narrationAlignment": beat.get("narrationAlignment") or "",
                    "evidenceReferences": beat.get("evidenceReferences") or [],
                    # -- visual subject and world
                    "sceneType": beat.get("sceneType") or scene.get("template") or "",
                    "template": scene.get("template") or "",
                    "layoutMode": scene.get("layout_mode") or "",
                    "subjects": (
                        beat.get("primarySubjects")
                        or ([data.get("heading")] if data.get("heading") else [])
                    ),
                    "objects": objects,
                    "requiredObjects": beat.get("requiredObjects") or [],
                    "environment": beat.get("environment") or data.get("environment") or "",
                    "assets": scene.get("assetRefs") or [],
                    # -- camera framing and movement
                    "camera": {
                        "shot": camera.get("shot") or "medium",
                        "move": camera.get("move") or "static",
                        "target": camera.get("target") or "",
                        "amplitude": camera.get("amplitude"),
                        "ease": camera.get("ease"),
                        "intent": beat.get("cameraIntent") or {},
                    },
                    # -- the causal cycle: initial state -> action -> resulting state
                    "initialState": causal.get("initial_state") or "",
                    "action": causal.get("causal_action") or beat.get("visualAction") or "",
                    "resultingState": causal.get("resulting_state") or "",
                    "cause": causal.get("transition") or "",
                    # -- duration, in frames, measured where a measurement exists
                    "durationFrames": scene.get("durationInFrames"),
                    "estimatedDurationFrames": (shot_timing or {}).get("estimatedDurationFrames"),
                    "measuredStartFrame": (shot_timing or {}).get("startFrame"),
                    "measuredDurationFrames": (shot_timing or {}).get("durationFrames"),
                    "measuredStartMs": (shot_timing or {}).get("startMs"),
                    "measuredEndMs": (shot_timing or {}).get("endMs"),
                    # -- how this shot joins the next
                    "transition": transition.get("kind") or "cut",
                    "transitionFrames": transition.get("frames"),
                    "beats": motion.get("beats") or [],
                    # -- visual continuity with the previous shot
                    "continuity": motion.get("continuity") or "cut",
                    "carriedObjects": sorted(set(objects) & set(previous_objects)),
                    "textRoles": sorted(
                        {
                            str(el.get("role"))
                            for el in (scene.get("text") or [])
                            if isinstance(el, dict) and el.get("role")
                        }
                    ),
                }
            )
            previous_objects = objects
        return shots

    # -- the prompt -------------------------------------------------------------------------

    def build_user_prompt(self, **kwargs: Any) -> str:
        storyboard = kwargs.get("storyboard") or {}
        brief = kwargs.get("creative_motion_brief") or kwargs.get("brief") or {}
        visual_plan = kwargs.get("visual_plan") or {}
        script = kwargs.get("script") or {}
        research = kwargs.get("research") or {}
        topic = kwargs.get("topic") or {}
        assets = kwargs.get("assets") or {}
        timing = kwargs.get("narration_timing") or {}
        fps = int(kwargs.get("fps") or storyboard.get("fps") or 30) or 30
        width = int(storyboard.get("width") or 1080)
        height = int(storyboard.get("height") or 1920)

        if not isinstance(storyboard, dict):
            storyboard = {}
        if not isinstance(brief, dict):
            brief = {}
        if not isinstance(visual_plan, dict):
            visual_plan = {}
        if not isinstance(timing, dict):
            timing = {}

        shots = self._shot_plan(storyboard, visual_plan, script, timing)
        other_kwargs = {k: v for k, v in kwargs.items() if k != "brief"}
        self._select_skills(shots, brief, **other_kwargs)

        brief_block = {
            key: brief.get(key)
            for key in (
                "narrative_thesis",
                "visual_thesis",
                "visual_metaphor",
                "art_direction",
                "subject_environment",
                "palette_rationale",
                "typography_direction",
                "camera_language",
                "motion_language",
                "narrative_arc",
                "scene_progression",
                "transition_strategy",
                "scene_transitions",
                "primary_visual_motifs",
                "reusable_motifs",
                "pacing_strategy",
                "motion_complexity_budget",
                "visual_climax",
                "ending_payoff",
            )
            if brief.get(key) not in (None, "", [], {})
        }
        # An empty brief is reported as empty rather than filled with defaults here: a default
        # invented at this stage would read downstream as a decision the director made.
        missing_brief = [
            key
            for key in ("narrative_thesis", "visual_thesis", "art_direction", "camera_language",
                        "motion_language", "transition_strategy", "visual_climax", "ending_payoff")
            if brief.get(key) in (None, "", [], {})
        ]
        if missing_brief:
            brief_block["_not_decided"] = missing_brief

        timing_block = {
            key: timing.get(key)
            for key in ("source", "note", "engine", "voice", "durationMs", "fps")
            if timing.get(key) not in (None, "")
        }
        total_frames = storyboard.get("scenes")
        total = sum(
            int(scene.get("durationInFrames") or 0)
            for scene in (total_frames or [])
            if isinstance(scene, dict)
        )

        return (
            f"Direct and build this film as Remotion TSX.\n"
            f"Format: {width}x{height}, {fps} fps, {total} frames total, "
            f"{len(shots)} shots.\n\n"
            f"## Creative brief (the film's identity - it governs every shot)\n"
            f"{json.dumps(brief_block, ensure_ascii=False, indent=2)}\n\n"
            f"## Narration timing ({timing_block.get('source', 'estimated')})\n"
            f"{timing_block.get('note', '')}\n"
            f"{json.dumps(timing_block, ensure_ascii=False)}\n\n"
            f"## Shot plan ({len(shots)} shots, in order)\n"
            f"{json.dumps(shots, ensure_ascii=False, indent=2)}\n\n"
            f"## Available assets (draw only these)\n"
            f"{json.dumps(assets, ensure_ascii=False)[:4000]}\n\n"
            f"## What the film is about\n"
            f"{json.dumps(topic, ensure_ascii=False)[:2000]}\n\n"
            f"## Facts the narration asserts (do not contradict them)\n"
            f"{json.dumps(research, ensure_ascii=False)[:4000]}\n\n"
            "## Requirements\n"
            f"1. Entry point RootComposition.tsx composing all {len(shots)} shots in order, plus "
            "one component per shot (Scene01.tsx, Scene02.tsx, ...).\n"
            "2. Place each shot at its measured start frame and give it "
            "its durationInFrames. Where a measured duration disagrees with the storyboard's "
            "estimate, the measured one wins and the difference is a retiming, not an error.\n"
            "3. Land each visual change that belongs to a spoken phrase on that phrase's frame, "
            "using the timing above.\n"
            "4. Give every shot a distinct composition derived from its own subject, environment "
            "and causal cycle. One root layout with different labels is the failure this "
            "requirement exists to prevent.\n"
            "5. Serve the shot's stated purpose, subjects and causal cycle. The initial state, the "
            "action and the resulting state are all visible, in that order, and the change is "
            "caused by the action rather than by a cut.\n"
            "6. A shot marked continuity 'carry' keeps its carriedObjects recognisable from the "
            "previous shot. Do not reset the world after every sentence.\n"
            "7. Beginning/middle/end keyframes (frames 6, duration/2, duration-6) must all differ, "
            "achieved through the subject's own transformation, a camera move the brief's camera "
            "language allows, or a progressive reveal. A decorative layer added to satisfy this is "
            "a defect, not a solution.\n"
            "8. Deterministic frame-based animation only. No randomness, no wall-clock time.\n"
            "9. Imports limited to react, remotion, @remotion/*, and local ./ modules.\n"
            "Return JSON only."
        )

    def contract(self) -> type[Artifact]:
        return MotionCodeArtifact

    def sanitize_payload(self, payload: dict[str, Any], task: str | None = None) -> dict[str, Any]:
        raw_version = payload.get("schema_version")
        if isinstance(raw_version, str):
            cleaned = raw_version.lstrip("vV").split(".")[0].strip()
            payload["schema_version"] = int(cleaned) if cleaned.isdigit() else 1
        elif isinstance(raw_version, (int, float)):
            payload["schema_version"] = int(raw_version)
        else:
            payload["schema_version"] = 1
        entry = str(payload.get("entry_component") or "RootComposition").strip()
        payload["entry_component"] = entry or "RootComposition"

        raw_files = payload.get("files")
        if not isinstance(raw_files, dict):
            raw_files = {}
        files: dict[str, str] = {str(k): str(v) for k, v in raw_files.items()}
        payload["files"] = files

        raw_deps = payload.get("dependencies")
        if not isinstance(raw_deps, list):
            raw_deps = ["react", "remotion"]
        payload["dependencies"] = [str(d) for d in raw_deps if isinstance(d, str)]

        bundle = getattr(self, "_skills_bundle", None)
        # Provenance, not a model answer, so the model's own list is discarded outright: a list
        # echoed by the model is a claim about its context, which is exactly what this field exists
        # to make checkable. The value is ``<skill>:<sha256>`` so the artifact names *what* was
        # read, not merely that something was.
        hashes = getattr(bundle, "skill_hashes", None)
        if isinstance(hashes, dict) and hashes:
            payload["skill_hashes"] = [f"{name}:{digest}" for name, digest in sorted(hashes.items())]
        elif bundle is not None and getattr(bundle, "sha256_hash", None):
            payload["skill_hashes"] = [bundle.sha256_hash]
        else:
            payload["skill_hashes"] = []

        guard = CodeGuard()
        all_issues: list[str] = []
        results_valid: list[bool] = []
        for filename, source in files.items():
            result = guard.validate_source(source, filename=filename)
            results_valid.append(result.valid)
            all_issues.extend(result.issues)

        # ponytail: empty file map treated as valid by codeguard; pipeline stage checks presence of entry component.
        validated = all(results_valid) if results_valid else True
        payload["validated_by_codeguard"] = validated
        payload["issues"] = all_issues
        return payload


__all__ = [
    "AnimationAgent",
    "CreativeDirectorAgent",
    "MetadataAgent",
    "MotionCoderAgent",
    "QualityAgent",
    "ResearchAgent",
    "ScriptAgent",
    "StoryboardAgent",
    "TopicSelectionAgent",
]
