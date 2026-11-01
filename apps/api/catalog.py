"""Read-only catalog of built-in capabilities, not an external plugin installer."""

from __future__ import annotations

from typing import Any, get_args

from packages.core.contracts.scene import (
    ENVIRONMENTS,
    OBJECT_KINDS,
    OBJECT_LABELS,
    BeatKind,
    CameraMove,
    TemplateId,
    TextRole,
    TransitionKind,
)


def installed_catalog() -> dict[str, Any]:
    """Use shipped contracts, never operator credentials or job data.

    The catalog describes what the *informative* engine can draw: scene templates, the object
    library, the backdrops those objects stand in, and the visual vocabulary a storyboard may use.
    It no longer lists characters, poses, expressions or motion presets — those belonged to the
    retired character engine and listing them would advertise a capability the renderer does not
    have.

    A renderer entry describes its implementation; it does not assert that Chrome, ffmpeg or GPU
    admission has been checked.
    """
    return {
        "templates": list(get_args(TemplateId)),
        "objects": [{"id": kind, "label": OBJECT_LABELS.get(kind, kind)} for kind in OBJECT_KINDS],
        "environments": list(ENVIRONMENTS),
        "visual": {
            "beat_kinds": list(get_args(BeatKind)),
            "camera_moves": list(get_args(CameraMove)),
            "transitions": list(get_args(TransitionKind)),
            "text_roles": list(get_args(TextRole)),
        },
        "renderers": [
            {
                "id": "remotion",
                "label": "Remotion",
                "description": "Komposisi React/TypeScript dari storyboard tervalidasi.",
            },
        ],
    }
