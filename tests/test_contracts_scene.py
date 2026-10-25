"""Scene validation: the rules that stop unmotivated motion and broken framing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.contracts import CameraSpec, SceneSpec, StoryboardArtifact


def _scene(**overrides):
    base = dict(
        sceneId="sc1",
        template="IllustratedStory",
        segment="s1",
        startFrame=0,
        durationInFrames=300,
        text=[{"id": "t1", "text": "Halo", "role": "title"}],
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
