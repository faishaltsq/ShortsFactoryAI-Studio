"""Read-only catalog of built-in capabilities, not an external plugin installer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict

from packages.core.contracts.scene import CameraMove, TemplateId, TransitionKind
from packages.core.motion.emit import BEAT_KINDS, EXPRESSIONS, MOTION_PRESETS, POSES

CHARACTER_MANIFEST = Path(__file__).resolve().parents[2] / "config" / "characters.json"


class _Character(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    version: str
    displayName: str
    artStyle: str
    poses: list[str]
    expressions: list[str]
    gestures: list[str]
    clothingVariants: list[str]
    mouthShapes: list[str]
    license: str
    provenance: str


class _Manifest(BaseModel):
    characters: list[_Character]


def installed_catalog() -> dict[str, Any]:
    """Use shipped contracts and the generated manifest, never operator credentials or job data.

    A renderer entry describes its implementation; it does not assert that Chrome, ffmpeg or GPU
    admission has been checked. Motion lists describe the secondary emitter's supported vocabulary;
    a character's own vocabulary remains separate where the renderers differ.
    """
    manifest = _Manifest.model_validate(json.loads(CHARACTER_MANIFEST.read_text(encoding="utf-8")))
    return {
        "templates": list(get_args(TemplateId)),
        "characters": [character.model_dump() for character in manifest.characters],
        "motion": {
            "poses": sorted(POSES),
            "expressions": sorted(EXPRESSIONS),
            "presets": sorted(MOTION_PRESETS),
            "beat_kinds": sorted(BEAT_KINDS),
            "camera_moves": list(get_args(CameraMove)),
            "transitions": list(get_args(TransitionKind)),
        },
        "renderers": [
            {
                "id": "remotion",
                "label": "Remotion",
                "description": "Komposisi React/TypeScript dari storyboard tervalidasi.",
            },
            {
                "id": "bang-motion",
                "label": "Motion HTML lokal",
                "description": "Emitter HTML deterministik, tanpa CDN atau kode buatan model.",
            },
        ],
    }
