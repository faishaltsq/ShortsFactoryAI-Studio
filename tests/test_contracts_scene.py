"""Scene validation: the rules that stop unmotivated motion and broken framing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.contracts import CameraSpec, SceneSpec, StoryboardArtifact, WordTimestamp


def _scene(**overrides):
    base = dict(
        sceneId="sc1",
        template="ObjectExplainer",
        segment="s1",
        startFrame=0,
        durationInFrames=300,
        text=[{"id": "t1", "text": "Halo", "role": "title"}],
        # ObjectExplainer is data-driven, so the fixture carries a minimal valid payload.
        data={
            "setting": "desert",
            "timeOfDay": "dusk",
            "actors": [
                {
                    "pose": "stand",
                    "x": 0.5,
                    "ground": 0.72,
                    "scale": 1,
                    "facing": "right",
                    "tone": "primary",
                    "silhouette": False,
                }
            ],
            "props": [],
            "fx": [],
            "shots": [{"framing": "wide", "camera": "static", "weight": 1}],
        },
    )
    base.update(overrides)
    return base


def test_static_camera_needs_no_target():
    scene = SceneSpec.model_validate(_scene())
    assert scene.camera.move == "static"


def test_moving_camera_without_target_is_rejected():
    with pytest.raises(ValidationError) as exc:
        SceneSpec.model_validate(_scene(camera={"shot": "close", "move": "push"}))
    assert "requires camera.target" in str(exc.value)


def test_moving_camera_target_must_exist_in_the_scene():
    with pytest.raises(ValidationError) as exc:
        SceneSpec.model_validate(
            _scene(camera={"shot": "close", "move": "push", "target": "nope"})
        )
    assert "does not name an element" in str(exc.value)


def test_moving_camera_with_real_target_is_accepted():
    scene = SceneSpec.model_validate(
        _scene(camera={"shot": "close", "move": "push", "target": "t1", "amplitude": 0.2})
    )
    assert scene.camera.target == "t1"


def test_orbit_is_rejected_on_flat_templates():
    with pytest.raises(ValidationError) as exc:
        SceneSpec.model_validate(
            _scene(
                template="KineticTypography",
                camera={"move": "orbit", "target": "t1"},
            )
        )
    assert "depth-capable" in str(exc.value)


def test_beat_outside_the_scene_is_rejected():
    with pytest.raises(ValidationError) as exc:
        SceneSpec.model_validate(
            _scene(motion={"beats": [{"atFrame": 900, "kind": "enter", "subject": "t1"}]})
        )
    assert "outside scene" in str(exc.value)


def test_high_energy_needs_beats():
    with pytest.raises(ValidationError) as exc:
        SceneSpec.model_validate(_scene(motion={"energy": 0.9}))
    assert "at least 2 beats" in str(exc.value)


def test_amplitude_on_a_static_camera_is_rejected():
    with pytest.raises(ValidationError) as exc:
        CameraSpec(move="static", amplitude=0.8)
    assert "not a still" in str(exc.value)


def test_storyboard_scenes_must_be_contiguous():
    with pytest.raises(ValidationError) as exc:
        StoryboardArtifact.model_validate(
            {
                "scenes": [
                    _scene(sceneId="a", startFrame=0, durationInFrames=100),
                    _scene(sceneId="b", startFrame=200, durationInFrames=100),
                ]
            }
        )
    assert "expected 100" in str(exc.value)


def test_storyboard_total_frames_sums_scenes():
    board = StoryboardArtifact.model_validate(
        {
            "scenes": [
                _scene(sceneId="a", startFrame=0, durationInFrames=100),
                _scene(sceneId="b", startFrame=100, durationInFrames=200),
            ]
        }
    )
    assert board.total_frames == 300


DATA_DRIVEN = ("MotionComic", "HistoricalTimeline", "ParallaxStory", "InfographicMotion",
               "ObjectExplainer")


@pytest.mark.parametrize("template", DATA_DRIVEN)
def test_a_data_driven_template_without_data_is_rejected(template):
    """The renderer throws for these five, so the contract must refuse them one layer earlier."""
    with pytest.raises(ValidationError) as exc:
        SceneSpec.model_validate(_scene(template=template, data=None))
    message = str(exc.value)
    assert "requires scene.data" in message
    assert template in message


def test_a_text_template_without_data_is_accepted():
    scene = SceneSpec.model_validate(_scene(template="KineticTypography", data=None))
    assert scene.data is None


def test_empty_data_is_not_presence():
    with pytest.raises(ValidationError) as exc:
        SceneSpec.model_validate(_scene(template="ObjectExplainer", data={}))
    assert "requires scene.data" in str(exc.value)


def test_word_timestamp_valid():
    wt = WordTimestamp(word="Remotion", startMs=100, endMs=450)
    assert wt.word == "Remotion"
    assert wt.startMs == 100
    assert wt.endMs == 450


def test_word_timestamp_rejected_when_unordered():
    with pytest.raises(ValidationError) as exc:
        WordTimestamp(word="Test", startMs=500, endMs=300)
    assert "endMs must be greater than startMs" in str(exc.value)


def test_scene_spec_causal_state_cycle() -> None:
    from packages.core.contracts.scene import CausalStateSpec, SceneSpec

    causal = CausalStateSpec(
        initial_state="Satelit GPS mengorbit bumi memancarkan sinyal waktu uncorrected.",
        causal_action="Dilatasi waktu gravitasi mempercepat jam atom satelit 38 mikrodetik per hari.",
        resulting_state="Posisi peta melenceng 11 kilometer jika koreksi relativitas tidak diterapkan.",
        transition="Zoom fokus ke penerima GPS ponsel yang menyinkronkan data koreksi.",
    )
    assert causal.initial_state != ""
    assert causal.causal_action != ""
    assert causal.resulting_state != ""
    assert causal.transition != ""

    scene = SceneSpec(
        sceneId="scene_01",
        template="ObjectExplainer",
        segment="seg_01",
        startFrame=0,
        durationInFrames=180,
        data={"objects": [{"kind": "satellite", "x": 0.5, "y": 0.45, "size": 0.5}]},
        causal_state=causal,
        layout_mode="SplitComparison",
    )
    assert scene.causal_state is not None
    assert scene.causal_state.causal_action.startswith("Dilatasi waktu")
    assert scene.layout_mode == "SplitComparison"


def test_scene_spec_causal_state_coercion_and_camel_case() -> None:
    from packages.core.contracts.scene import SceneSpec

    scene = SceneSpec.model_validate(
        {
            "sceneId": "scene_02",
            "template": "ObjectExplainer",
            "segment": "seg_02",
            "startFrame": 0,
            "durationInFrames": 180,
            "data": {"objects": []},
            "causal_state": {
                "initialState": "  Satelit awal  ",
                "causalAction": "  Relativitas  ",
                "resultingState": "  Waktu bergeser  ",
                "transition": "  Sinkronisasi  ",
            },
            "layout_mode": "RadialNetwork",
        }
    )
    assert scene.causal_state is not None
    assert scene.causal_state.initial_state == "Satelit awal"
    assert scene.causal_state.causal_action == "Relativitas"
    assert scene.causal_state.resulting_state == "Waktu bergeser"
    assert scene.causal_state.transition == "Sinkronisasi"
    assert scene.layout_mode == "RadialNetwork"


def test_causal_state_spec_empty_string_rejected() -> None:
    from packages.core.contracts.scene import CausalStateSpec

    with pytest.raises(ValidationError):
        CausalStateSpec(
            initial_state="   ",
            causal_action="aksi",
            resulting_state="hasil",
            transition="transisi",
        )


def test_storyboard_agent_sanitizes_causal_state_and_layout_mode() -> None:
    from packages.core.agents.concrete import StoryboardAgent

    agent = StoryboardAgent.__new__(StoryboardAgent)
    raw_payload = {
        "theme": "editorialLight",
        "fps": 30,
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 120,
                "text": [{"id": "t1", "text": "Orbit", "role": "title"}],
                "causalState": {
                    "initialState": "  Kondisi awal satelit  ",
                    "causalAction": "  Efek relativistik  ",
                    "resultingState": "  Offset waktu mikrodetik  ",
                    "transition": "  Pergeseran fokus  ",
                },
                "layoutMode": "splitcomparison",
                "data": {"objects": [{"kind": "satellite", "x": 0.5, "y": 0.45, "size": 0.5}]},
            }
        ],
        "subtitles": [],
    }

    sanitized = agent.sanitize_payload(raw_payload)
    sc = sanitized["scenes"][0]
    assert "causalState" not in sc
    assert "layoutMode" not in sc
    assert sc["layout_mode"] == "SplitComparison"
    assert sc["causal_state"] == {
        "initial_state": "Kondisi awal satelit",
        "causal_action": "Efek relativistik",
        "resulting_state": "Offset waktu mikrodetik",
        "transition": "Pergeseran fokus",
    }



