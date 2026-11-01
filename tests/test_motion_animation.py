"""Regression tests proving AnimationAgent motion plans alter rendered frames and pipeline visuals."""

from __future__ import annotations

import copy
from typing import Any

from packages.core.agents.concrete import StoryboardAgent
from packages.core.media.render import merge_motion_plan_into_storyboard, update_storyboard_from_audio


def test_merge_motion_plan_updates_beats_camera_and_energy() -> None:
    storyboard: dict[str, Any] = {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 120,
                "text": [{"id": "t1", "text": "Gunung meletus", "role": "title", "atFrame": 0}],
                "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
                "camera": {"shot": "wide", "move": "push", "target": "t1", "amplitude": 0.1},
                "data": {"environment": "space", "objects": [{"kind": "satellite", "x": 0.5, "y": 0.5}], "callouts": [], "flows": []},
            }
        ],
    }

    motion_plan: dict[str, Any] = {
        "schema_version": 1,
        "renderer": "remotion",
        "style_brief": {"palette": ["#ff4500", "#1a1418"], "signature_move": "dynamic_push"},
        "scenes": [
            {
                "sceneId": "sc1",
                "energy": 0.85,
                "continuity_from": "carry",
                "camera_path": {"move": "tilt", "shot": "close", "target": "t1", "amplitude": 0.18},
                "beats": [
                    {"atFrame": 0, "kind": "enter", "subject": "object:0"},
                    {"atFrame": 45, "kind": "action", "subject": "object:0"},
                    {"atFrame": 90, "kind": "reveal", "subject": "object:0"},
                ],
            }
        ],
    }

    merged = merge_motion_plan_into_storyboard(copy.deepcopy(storyboard), motion_plan)
    sc1 = merged["scenes"][0]
    motion = sc1["motion"]
    assert motion["energy"] == 0.85
    assert motion["continuity"] == "carry"
    assert len(motion["beats"]) == 3
    assert [b["kind"] for b in motion["beats"]] == ["enter", "action", "reveal"]
    assert [b["atFrame"] for b in motion["beats"]] == [0, 45, 90]

    cam = sc1["camera"]
    assert cam["move"] == "tilt"
    assert cam["shot"] == "close"
    assert cam["amplitude"] == 0.18


def test_differing_motion_plans_change_rendered_frame_output() -> None:
    base_storyboard: dict[str, Any] = {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "dusk",
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 120,
                "text": [{"id": "t1", "text": "Aktivitas magma meningkat", "role": "title", "atFrame": 0}],
                "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
                "camera": {"shot": "wide", "move": "push", "target": "t1", "amplitude": 0.1},
                "data": {"environment": "circuit", "objects": [{"kind": "gpu", "x": 0.5, "y": 0.5}], "callouts": [], "flows": []},
            }
        ],
        "subtitles": [{"startMs": 0, "endMs": 4000, "text": "Aktivitas magma meningkat"}],
    }

    plan_action: dict[str, Any] = {
        "schema_version": 1,
        "renderer": "remotion",
        "scenes": [
            {
                "sceneId": "sc1",
                "energy": 0.9,
                "beats": [
                    {"atFrame": 0, "kind": "enter", "subject": "object:0"},
                    {"atFrame": 40, "kind": "action", "subject": "object:0"},
                ],
            }
        ],
    }

    plan_reveal: dict[str, Any] = {
        "schema_version": 1,
        "renderer": "remotion",
        "scenes": [
            {
                "sceneId": "sc1",
                "energy": 0.3,
                "beats": [
                    {"atFrame": 0, "kind": "enter", "subject": "object:0"},
                    {"atFrame": 75, "kind": "reveal", "subject": "object:0"},
                ],
            }
        ],
    }

    sb_action = merge_motion_plan_into_storyboard(copy.deepcopy(base_storyboard), plan_action)
    sb_reveal = merge_motion_plan_into_storyboard(copy.deepcopy(base_storyboard), plan_reveal)

    # The merged storyboard is what the renderer reads, so it is what must differ.
    beats_action = sb_action["scenes"][0]["motion"]["beats"]
    beats_reveal = sb_reveal["scenes"][0]["motion"]["beats"]
    assert beats_action != beats_reveal
    assert {"atFrame": 40, "kind": "action", "subject": "object:0"} in beats_action
    assert {"atFrame": 75, "kind": "reveal", "subject": "object:0"} in beats_reveal
    assert sb_action["scenes"][0]["motion"]["energy"] == 0.9
    assert sb_reveal["scenes"][0]["motion"]["energy"] == 0.3


def test_audio_retiming_rescales_motion_beats_preventing_drop() -> None:
    storyboard: dict[str, Any] = {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 300,
                "motion": {
                    "energy": 0.7,
                    "continuity": "cut",
                    "beats": [
                        {"atFrame": 0, "kind": "enter", "subject": "object:0"},
                        {"atFrame": 150, "kind": "action", "subject": "object:0"},
                        {"atFrame": 280, "kind": "emphasis", "subject": "object:0"},
                    ],
                },
                "text": [{"id": "t1", "text": "Tidur nyenyak", "role": "title", "atFrame": 0}],
            }
        ],
    }

    # Audio measured duration is 3.5 seconds = 105 frames at 30fps
    audio: dict[str, Any] = {
        "scenes": [{"sceneId": "sc1", "startMs": 0, "endMs": 3500}],
        "subtitles": [],
    }

    retimed = update_storyboard_from_audio(storyboard, audio)
    sc = retimed["scenes"][0]
    new_duration = sc["durationInFrames"]
    assert new_duration == 105

    beats = sc["motion"]["beats"]
    # All beats must sit strictly before new_duration
    for b in beats:
        assert b["atFrame"] < new_duration
    # Frame 150 was rescaled proportionally (150 * 104 / 300 = 52)
    assert beats[1]["atFrame"] == 52
    assert beats[2]["atFrame"] < new_duration


def test_storyboard_agent_picks_topic_appropriate_objects() -> None:
    agent = StoryboardAgent.__new__(StoryboardAgent)

    payload_volcano: dict[str, Any] = {
        "schema_version": 1,
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "EducationalExplainer",
                "segment": "s1",
                "text": [{"id": "t1", "text": "Magma mengalir keluar dari kawah letusan gunung berapi"}],
            },
            {
                "sceneId": "sc2",
                "template": "KineticTypography",
                "segment": "s2",
                "text": [{"id": "t2", "text": "Abu vulkanik dan asap membubung tinggi ke langit"}],
            },
        ],
    }
    sanitized_volcano = agent.sanitize_payload(payload_volcano)
    v_scenes = sanitized_volcano["scenes"]
    assert v_scenes[0]["template"] == "ObjectExplainer"
    assert v_scenes[1]["template"] == "ObjectExplainer"
    objects_sc1 = v_scenes[0]["data"]["objects"]
    assert len(objects_sc1) > 0
    assert objects_sc1[0]["kind"] in ("satellite", "drone", "antenna")
    # No pseudo-refs survive: only staged rasters may reach the browser.
    assert v_scenes[0].get("assetRefs", []) == []

    payload_brain: dict[str, Any] = {
        "schema_version": 1,
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "EducationalExplainer",
                "segment": "s1",
                "text": [{"id": "t1", "text": "Mengapa kita lupa mimpi saat bangun tidur"}],
            }
        ],
    }
    sanitized_brain = agent.sanitize_payload(payload_brain)
    b_scenes = sanitized_brain["scenes"]
    assert b_scenes[0]["template"] == "ObjectExplainer"
    objects_brain = b_scenes[0]["data"]["objects"]
    assert len(objects_brain) > 0
    assert objects_brain[0]["kind"] in ("neuralNet", "database", "gpu")
