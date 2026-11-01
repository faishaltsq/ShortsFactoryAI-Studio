from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from packages.core.media.qc import (
    calculate_frame_delta,
    evaluate_bme_dynamics,
    evaluate_creative,
    extract_bme_frames,
    get_bme_frame_indices,
)


def test_frame_delta_identical_frames_is_zero() -> None:
    frame_a = bytes([0] * (100 * 100))
    frame_b = bytes([0] * (100 * 100))
    assert calculate_frame_delta(frame_a, frame_b) == 0.0


def test_frame_delta_opposite_frames_is_one() -> None:
    frame_a = bytes([0] * (100 * 100))
    frame_b = bytes([255] * (100 * 100))
    assert calculate_frame_delta(frame_a, frame_b) == 1.0


def test_frame_delta_mismatched_length_raises() -> None:
    frame_a = bytes([0] * 10)
    frame_b = bytes([0] * 12)
    with pytest.raises(ValueError, match="same length"):
        calculate_frame_delta(frame_a, frame_b)


def test_frame_delta_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        calculate_frame_delta(b"", b"")


def test_get_bme_frame_indices_standard_scene() -> None:
    # 60 frames starting at frame 100 -> b=106, m=130, e=154
    b, m, e = get_bme_frame_indices(100, 60)
    assert b == 106
    assert m == 130
    assert e == 154


def test_get_bme_frame_indices_short_scene_clamps() -> None:
    # 8 frames starting at frame 0 -> b=0, m=4, e=7
    b, m, e = get_bme_frame_indices(0, 8)
    assert b == 0
    assert m == 4
    assert e == 7


def test_evaluate_bme_dynamics_detects_static_scenes() -> None:
    scenes = [
        {"sceneId": "sc1", "startFrame": 0, "durationInFrames": 60},
        {"sceneId": "sc2", "startFrame": 60, "durationInFrames": 60},
    ]
    frame_blank = bytes([128] * (160 * 90))
    frame_motion = bytes([128 if i % 2 == 0 else 200 for i in range(160 * 90)])

    # Scene 1: blank -> blank -> blank (static)
    # Scene 2: blank -> motion -> blank (dynamic)
    bme_frames = [
        (frame_blank, frame_blank, frame_blank),
        (frame_blank, frame_motion, frame_blank),
    ]

    res = evaluate_bme_dynamics(scenes, bme_frames, min_delta=0.01)
    assert res["passed"] is False
    assert "sc1" in res["static_scenes"]
    assert "sc2" not in res["static_scenes"]
    assert len(res["scene_metrics"]) == 2
    assert res["scene_metrics"][0]["delta_bm"] == 0.0
    assert res["scene_metrics"][0]["delta_me"] == 0.0
    assert res["scene_metrics"][1]["delta_bm"] > 0.1


def test_evaluate_bme_dynamics_all_dynamic_passes() -> None:
    scenes = [{"sceneId": "sc1", "startFrame": 0, "durationInFrames": 60}]
    f1 = bytes([50] * 100)
    f2 = bytes([100] * 100)
    f3 = bytes([150] * 100)
    res = evaluate_bme_dynamics(scenes, [(f1, f2, f3)], min_delta=0.01)
    assert res["passed"] is True
    assert res["static_scenes"] == []


def test_evaluate_bme_dynamics_half_frozen_scene_is_flagged_static() -> None:
    scenes = [{"sceneId": "sc1", "startFrame": 0, "durationInFrames": 60}]
    f1 = bytes([50] * 100)
    f2 = bytes([100] * 100)
    f3 = bytes([100] * 100)  # Middle to End is identical (frozen)
    res = evaluate_bme_dynamics(scenes, [(f1, f2, f3)], min_delta=0.01)
    assert res["passed"] is False
    assert "sc1" in res["static_scenes"]
    assert res["scene_metrics"][0]["delta_me"] == 0.0
    assert res["scene_metrics"][0]["static"] is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required for extraction test")
def test_extract_bme_frames_real_video(tmp_path: Path) -> None:
    video_path = Path("evidence/topic-space.mp4")
    if not video_path.is_file():
        pytest.skip("evidence/topic-space.mp4 not present on host")

    points = [(6, 30, 54)]
    extracted = extract_bme_frames(video_path, points, width=160, height=90)
    assert len(extracted) == 1
    fb, fm, fe = extracted[0]
    assert len(fb) == 160 * 90
    assert len(fm) == 160 * 90
    assert len(fe) == 160 * 90


def test_evaluate_creative_integrates_bme_dynamics() -> None:
    props: dict[str, Any] = {
        "storyboard": {
            "schema_version": "1.0",
            "scenes": [
                {
                    "sceneId": "sc1",
                    "startFrame": 0,
                    "durationInFrames": 60,
                    "camera": {"shot": "close-up"},
                    "world": {"kind": "lab"},
                }
            ],
        }
    }
    audio: dict[str, Any] = {"narration": {"durationMs": 2000.0}}

    # Passing dynamics
    verdict_pass = evaluate_creative(
        props=props,
        audio=audio,
        review=None,
        script=None,
        assets=None,
        static_seconds=0.1,
        bme_dynamics={"passed": True, "static_scenes": [], "scene_metrics": []},
    )
    assert verdict_pass.checks["bme_dynamics"] is True
    assert "bme_dynamics" not in verdict_pass.failed

    # Failing dynamics
    verdict_fail = evaluate_creative(
        props=props,
        audio=audio,
        review=None,
        script=None,
        assets=None,
        static_seconds=0.1,
        bme_dynamics={"passed": False, "static_scenes": ["sc1"], "scene_metrics": []},
    )
    assert verdict_fail.checks["bme_dynamics"] is False
    assert "bme_dynamics" in verdict_fail.failed
