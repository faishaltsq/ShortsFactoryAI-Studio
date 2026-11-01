"""Scene contract: the boundary between model output and rendered pixels.

A model writes these fields. It never writes JSX, CSS, HTML, or a shell command. Everything here
is validated before a renderer sees it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

TemplateId = Literal[
    "KineticTypography",
    "EducationalExplainer",
    "MotionComic",
    "HistoricalTimeline",
    "ParallaxStory",
    "InfographicMotion",
    "ObjectExplainer",
    "ProcessFlow",
    "MetricShift",
]

#: The object kinds the renderer can draw, mirrored from
#: ``packages/video/src/art/object-kinds.ts``. One list, imported by the storyboard sanitizer, the
#: QC gate and the API catalog: a kind invented in one place is a blank box on screen.
OBJECT_KINDS: tuple[str, ...] = (
    "gpu",
    "wafer",
    "serverRack",
    "dataCenter",
    "neuralNet",
    "database",
    "satellite",
    "antenna",
    "turbine",
    "solarPanel",
    "coolingFan",
    "phone",
    "drone",
    "rocket",
    "building",
    "meshTopology",
    "claySculpt",
    "cloudArch",
    "cpuProcessor",
    "quantumProcessor",
    "opticalFiber",
    "subseaCableCutaway",
    "ramenBowl",
    "cookingPot",
    "planetEarth",
    "microscope",
    "lightBulb",
    "factory",
    "stockChart",
)
ObjectKind = Literal[
    "gpu",
    "wafer",
    "serverRack",
    "dataCenter",
    "neuralNet",
    "database",
    "satellite",
    "antenna",
    "turbine",
    "solarPanel",
    "coolingFan",
    "phone",
    "drone",
    "rocket",
    "building",
    "meshTopology",
    "claySculpt",
    "cloudArch",
    "cpuProcessor",
    "quantumProcessor",
    "opticalFiber",
    "subseaCableCutaway",
    "ramenBowl",
    "cookingPot",
    "planetEarth",
    "microscope",
    "lightBulb",
    "factory",
    "stockChart",
]
#: Short captions drawn under an object. Long labels collide at 1080px wide.
OBJECT_LABELS: dict[str, str] = {
    "gpu": "GPU",
    "wafer": "Wafer",
    "serverRack": "Rak Server",
    "dataCenter": "Data Center",
    "neuralNet": "Neural Net",
    "database": "Database",
    "satellite": "Satelit",
    "antenna": "Menara Sinyal",
    "turbine": "Turbin",
    "solarPanel": "Panel Surya",
    "coolingFan": "Pendingin",
    "phone": "Ponsel",
    "drone": "Drone",
    "rocket": "Roket",
    "building": "Kantor",
    "meshTopology": "Mesh 3D",
    "claySculpt": "Clay Sculpt",
    "cloudArch": "Cloud Architecture",
    "cpuProcessor": "CPU Processor",
    "quantumProcessor": "Quantum Processor",
    "opticalFiber": "Optical Fiber",
    "subseaCableCutaway": "Kabel Bawah Laut (Cross-Section)",
    "ramenBowl": "Mangkok Mi",
    "cookingPot": "Panci Masak",
    "planetEarth": "Planet Bumi",
    "microscope": "Mikroskop Sains",
    "lightBulb": "Bohlam Inovasi",
    "factory": "Pabrik Industri",
    "stockChart": "Grafik Pasar / Tren",
}
#: Backdrops the renderer can stand an object in, mirrored from ``art/palette.ts``.
ENVIRONMENTS: tuple[str, ...] = (
    "dataCenter",
    "circuit",
    "space",
    "lab",
    "city",
    "grid",
    "abstract",
    "oceanFloor",
    "kitchen",
)
EnvironmentKind = Literal[
    "dataCenter",
    "circuit",
    "space",
    "lab",
    "city",
    "grid",
    "abstract",
    "oceanFloor",
    "kitchen",
]
#: Templates whose renderer reads ``scene.data``. The ported ``validateSceneData`` throws when
#: ``data`` is missing for these five and returns immediately for the two text templates, so
#: presence is checked here — at the contract boundary — and the *contents* stay the renderer's
#: job. Duplicating the shape rules in Python would drift from the TypeScript validator.
DATA_DRIVEN_TEMPLATES = frozenset(
    {
        "MotionComic",
        "HistoricalTimeline",
        "ParallaxStory",
        "InfographicMotion",
        "ObjectExplainer",
        "ProcessFlow",
        "MetricShift",
    }
)

ShotSize = Literal["wide", "medium", "close"]
CameraMove = Literal["static", "push", "pull", "pan", "tilt", "orbit"]
Easing = Literal[
    "linear",
    "power1.out",
    "power2.out",
    "power3.out",
    "power4.out",
    "power1.in",
    "power2.in",
    "power2.inOut",
    "sine.inOut",
]
TransitionKind = Literal["cut", "fade", "wipe", "push", "match"]
BeatKind = Literal["enter", "emphasis", "exit", "action", "reveal"]
Continuity = Literal["carry", "cut", "match"]
TextRole = Literal["title", "body", "caption", "label"]
LayoutMode = Literal[
    "DefaultHero",
    "SplitComparison",
    "RadialNetwork",
    "LeftRailProcess",
    "FullBleedFocus",
]


class CameraSpec(BaseModel):
    """Framing and movement.

    ``target`` is mandatory for any non-static move: a camera that moves without a subject is
    exactly the "unmotivated camera movement" the brief forbids, and making it a validation error
    is more reliable than making it a review comment.
    """

    model_config = ConfigDict(extra="forbid")

    shot: ShotSize = "wide"
    move: CameraMove = "static"
    target: str | None = None
    amplitude: float = Field(default=0.12, ge=0.0, le=1.0)
    ease: Easing = "power2.out"

    @model_validator(mode="after")
    def _target_required(self) -> CameraSpec:
        if self.move != "static" and not self.target:
            raise ValueError(f"camera.move={self.move} requires camera.target")
        if self.move == "static" and self.amplitude > 0.35:
            raise ValueError("camera.amplitude > 0.35 with move=static is a zoom, not a still")
        return self


class Beat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atFrame: int = Field(ge=0)
    kind: BeatKind
    subject: str = Field(min_length=1)


class MotionSpec(BaseModel):
    """How a scene moves. ``continuity`` decides whether the world survives the cut."""

    model_config = ConfigDict(extra="forbid")

    energy: float = Field(default=0.5, ge=0.0, le=1.0)
    continuity: Continuity = "cut"
    beats: list[Beat] = Field(default_factory=list)

    @model_validator(mode="after")
    def _energy_needs_beats(self) -> MotionSpec:
        if self.energy >= 0.75 and len(self.beats) < 2:
            raise ValueError("motion.energy >= 0.75 needs at least 2 beats")
        return self


class TextElementSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=400)
    role: TextRole = "body"
    atFrame: int = Field(default=0, ge=0)


class TransitionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TransitionKind = "cut"
    frames: int = Field(default=0, ge=0, le=60)


class WordTimestamp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=120)
    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> WordTimestamp:
        if self.endMs <= self.startMs:
            raise ValueError("word timestamp endMs must be greater than startMs")
        return self


class SubtitleCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def _ordered(self) -> SubtitleCue:
        if self.endMs <= self.startMs:
            raise ValueError("subtitle endMs must be greater than startMs")
        return self


class CausalStateSpec(BaseModel):
    """The four-part causal state cycle grounding a scene in physical transformation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    initial_state: str = Field(
        validation_alias=AliasChoices("initial_state", "initialState"),
        min_length=1,
        max_length=500,
    )
    causal_action: str = Field(
        validation_alias=AliasChoices("causal_action", "causalAction"),
        min_length=1,
        max_length=500,
    )
    resulting_state: str = Field(
        validation_alias=AliasChoices("resulting_state", "resultingState"),
        min_length=1,
        max_length=500,
    )
    transition: str = Field(
        min_length=1,
        max_length=500,
    )

    @field_validator(
        "initial_state",
        "causal_action",
        "resulting_state",
        "transition",
        mode="before",
    )
    @classmethod
    def _strip_whitespace(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class SceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sceneId: str = Field(min_length=1, max_length=64)
    template: TemplateId
    segment: str = Field(min_length=1, max_length=64)
    startFrame: int = Field(default=0, ge=0)
    durationInFrames: int = Field(default=300, ge=30, le=3000)
    assetRefs: list[str] = Field(default_factory=list)
    text: list[TextElementSpec] = Field(default_factory=list)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    motion: MotionSpec = Field(default_factory=MotionSpec)
    transition: TransitionSpec = Field(default_factory=TransitionSpec)
    audio: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    causal_state: CausalStateSpec | None = Field(
        default=None,
        validation_alias=AliasChoices("causal_state", "causalState"),
    )
    layout_mode: LayoutMode | None = Field(
        default=None,
        validation_alias=AliasChoices("layout_mode", "layoutMode"),
    )

    @model_validator(mode="after")
    def _data_required_for_data_driven_templates(self) -> SceneSpec:
        """A data-driven template with no ``data`` cannot render, so it must not validate.

        Presence only: ``{}`` is rejected as firmly as ``None``, because an empty payload fails
        the renderer's own per-template checks one layer later, after a job has been paid for.
        """
        if self.template in DATA_DRIVEN_TEMPLATES and not self.data:
            raise ValueError(
                f"scene {self.sceneId!r} uses template {self.template!r}, "
                "which requires scene.data"
            )
        return self

    @model_validator(mode="after")
    def _camera_target_exists(self) -> SceneSpec:
        if self.camera.move == "static":
            return self
        ids = {element.id for element in self.text}
        if self.camera.target not in ids:
            raise ValueError(
                f"camera.target={self.camera.target!r} does not name an element in scene "
                f"{self.sceneId!r} (have: {sorted(ids) or 'none'})"
            )
        return self

    @model_validator(mode="after")
    def _beats_within_scene(self) -> SceneSpec:
        for beat in self.motion.beats:
            if beat.atFrame >= self.durationInFrames:
                raise ValueError(
                    f"beat at frame {beat.atFrame} is outside scene {self.sceneId!r} "
                    f"(duration {self.durationInFrames})"
                )
        return self

    @model_validator(mode="after")
    def _orbit_needs_depth(self) -> SceneSpec:
        if self.camera.move == "orbit" and self.template not in {
            "ObjectExplainer",
            "ParallaxStory",
        }:
            raise ValueError(
                f"camera.move=orbit needs a depth-capable template, got {self.template!r}"
            )
        return self

    @property
    def end_frame(self) -> int:
        return self.startFrame + self.durationInFrames


__all__ = [
    "DATA_DRIVEN_TEMPLATES",
    "ENVIRONMENTS",
    "OBJECT_KINDS",
    "OBJECT_LABELS",
    "Beat",
    "CameraMove",
    "CameraSpec",
    "CausalStateSpec",
    "Continuity",
    "Easing",
    "EnvironmentKind",
    "LayoutMode",
    "MotionSpec",
    "ObjectKind",
    "SceneSpec",
    "ShotSize",
    "SubtitleCue",
    "TemplateId",
    "TextElementSpec",
    "TextRole",
    "TransitionKind",
    "TransitionSpec",
    "WordTimestamp",
]

