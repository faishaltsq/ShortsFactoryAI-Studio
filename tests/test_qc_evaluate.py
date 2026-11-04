"""The technical and creative evaluators: pure decisions over real measurements.

Two rules shape this file.

1. **The expected values come from ``render-props.json`` and ``audio.json``, never from
   ``render.json``.** A render that reports its own frame count can never disagree with itself;
   the real job at ``data/jobs/4145e5b9e03c87d7`` did exactly that and passed.
2. **A detector that did not run is a failure.** ``scripts/verify_video.py`` prints it as WARN,
   which is defensible for a manual gate and indefensible inside the pipeline: a QC stage that
   cannot measure must not report success.
"""

from __future__ import annotations

import json

import pytest

from packages.core.media.qc import (
    CREATIVE_THRESHOLDS,
    TECHNICAL_THRESHOLDS,
    DetectorResult,
    evaluate_creative,
    evaluate_technical,
    measure_static_time,
    parse_detector_output,
)

FPS = 30
#: 3 scenes x 100 frames = 300 frames = 10.000 s.
PROPS = {
    "storyboard": {
        "fps": FPS,
        "width": 1080,
        "height": 1920,
        "theme": "dusk",
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 100,
                "assetRefs": [],
                "text": [{"id": "t1", "text": "Satu", "role": "title", "atFrame": 0}],
                "camera": {"shot": "wide", "move": "static", "amplitude": 0.12},
                "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
                "transition": {"kind": "cut", "frames": 0},
                "data": {
                    "environment": "dataCenter",
                    "objects": [
                        {"kind": "serverRack", "x": 0.5, "y": 0.36, "size": 0.4, "at": 0},
                        {"kind": "coolingFan", "x": 0.26, "y": 0.66, "size": 0.22, "at": 12},
                    ],
                    "callouts": [],
                    "flows": [{"from": 1, "to": 0, "at": 30}],
                },
            },
            {
                "sceneId": "sc2",
                "template": "ObjectExplainer",
                "segment": "s2",
                "startFrame": 100,
                "durationInFrames": 100,
                "assetRefs": [],
                "text": [{"id": "t2", "text": "Dua", "role": "body", "atFrame": 0}],
                "camera": {"shot": "medium", "move": "static", "amplitude": 0.12},
                "motion": {"energy": 0.6, "continuity": "cut", "beats": []},
                "transition": {"kind": "cut", "frames": 0},
                "data": {
                    "environment": "circuit",
                    "objects": [
                        {"kind": "gpu", "x": 0.5, "y": 0.36, "size": 0.4, "at": 0},
                        {"kind": "coolingFan", "x": 0.26, "y": 0.66, "size": 0.22, "at": 12},
                    ],
                    "callouts": [],
                    "flows": [{"from": 1, "to": 0, "at": 30}],
                },
            },
            {
                "sceneId": "sc3",
                "template": "ObjectExplainer",
                "segment": "s3",
                "startFrame": 200,
                "durationInFrames": 100,
                "assetRefs": [],
                "text": [{"id": "t3", "text": "Tiga", "role": "title", "atFrame": 0}],
                "camera": {"shot": "close", "move": "static", "amplitude": 0.12},
                "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
                "transition": {"kind": "cut", "frames": 0},
                "data": {
                    "environment": "grid",
                    "objects": [
                        {"kind": "database", "x": 0.5, "y": 0.36, "size": 0.4, "at": 0},
                        {"kind": "coolingFan", "x": 0.26, "y": 0.66, "size": 0.22, "at": 12},
                    ],
                    "callouts": [],
                    "flows": [{"from": 1, "to": 0, "at": 30}],
                },
            },
        ],
        "subtitles": [
            {"startMs": 0, "endMs": 2000, "text": "Satu"},
            {"startMs": 2000, "endMs": 5000, "text": "Dua"},
            {"startMs": 5000, "endMs": 10_000, "text": "Tiga"},
        ],
    }
}

AUDIO = {
    "narration": {"src": "narration.wav", "durationMs": 10_000, "voice": "system-default"},
    "scenes": [
        {"sceneId": "sc1", "startMs": 0, "endMs": 3333},
        {"sceneId": "sc2", "startMs": 3333, "endMs": 6666},
        {"sceneId": "sc3", "startMs": 6666, "endMs": 10_000},
    ],
    "subtitles": PROPS["storyboard"]["subtitles"],
    "mix": {"music": None, "music_gain_db": None, "ducking": False, "loudness_lufs": -16},
}

ASSETS = {
    "characters": [
        {
            "id": "maya",
            "rig_hash": "b" * 64,
            "palette_hash": "c" * 64,
            "poses": ["stand", "point", "reach"],
            "expressions": ["neutral"],
        }
    ],
    "backgrounds": [],
    "audio": [],
    "manifest_sha256": "d" * 64,
}

REVIEW = {
    "verdict": "accept",
    "scores": {"hook": 4, "coherence": 4, "pacing": 4, "originality": 4, "payoff": 4},
    "findings": [],
    "attempt": 0,
}

SCRIPT = {
    "hook": "Satu",
    "segments": [
        {"id": "s1", "text": "Satu", "purpose": "hook"},
        {"id": "s2", "text": "Dua", "purpose": "build"},
        {"id": "s3", "text": "Tiga", "purpose": "payoff"},
    ],
    "cta": "",
    "content_kind": "fictional",
}


def _probe(**overrides):
    video = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1080,
        "height": 1920,
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "avg_frame_rate": "30/1",
        "r_frame_rate": "30/1",
        "nb_read_frames": "300",
    }
    audio = {
        "codec_type": "audio",
        "codec_name": "aac",
        "duration": "10.0",
    }
    payload = {
        "streams": [video, audio],
        "format": {"duration": "10.0"},
    }
    payload.update(overrides)
    return payload


def _clean_detectors(**overrides):
    base = {
        "blackdetect": DetectorResult(ran=True, count=0, detail=""),
        "silencedetect": DetectorResult(ran=True, count=0, detail=""),
        "freezedetect": DetectorResult(ran=True, count=0, detail=""),
    }
    base.update(overrides)
    return base


def _tech(**kwargs):
    params = {
        "probe": _probe(),
        "props": PROPS,
        "audio": AUDIO,
        "detectors": _clean_detectors(),
        "loudness": {"input_i": -16.0, "input_tp": -1.5},
        "sha256": "e" * 64,
        "render": {"sha256": "e" * 64, "scene_hashes": {"sc1": "1", "sc2": "2", "sc3": "3"}},
    }
    params.update(kwargs)
    return evaluate_technical(**params)


# -- technical: the happy path -----------------------------------------------------------------


def test_a_clean_render_passes_every_technical_check():
    result = _tech()
    assert result.passed is True, result.failed
    assert result.failed == []
    assert set(result.checks) == {
        "resolution",
        "frame_rate",
        "video_codec",
        "pix_fmt",
        "color_range",
        "video_stream_count",
        "audio_stream_count",
        "audio_codec",
        "frame_count",
        "duration",
        "black_frames",
        "unexpected_silence",
        "frozen_frames",
        "subtitle_bounds",
        "loudness",
        "true_peak",
        "checksum",
        "scene_hashes",
    }


def test_every_check_reports_the_value_and_the_threshold():
    result = _tech()
    assert result.observed["width"] == 1080
    assert result.observed["fps"] == pytest.approx(30.0)
    assert result.observed["frames"] == 300
    assert result.observed["duration_ms"] == pytest.approx(10_000, abs=1)
    assert result.thresholds["resolution"] == "1080x1920"
    assert "0.4" in result.thresholds["black_frames"]


# -- technical: the expectations do not come from render.json ---------------------------------


def test_frame_count_is_expected_from_the_timed_props_not_the_render():
    """A render that under-delivers must be caught even if it reports its own frame count."""
    result = _tech(probe=_probe(streams=[dict(_probe()["streams"][0], nb_read_frames="150"), _probe()["streams"][1]]))
    assert "frame_count" in result.failed
    assert result.observed["expected_frames"] == 300


def test_duration_is_expected_from_the_narration_not_the_frame_math():
    result = _tech(audio={**AUDIO, "narration": {"src": "n.wav", "durationMs": 12_000, "voice": "v"}})
    assert "duration" in result.failed
    assert result.observed["expected_duration_ms"] == pytest.approx(12_000)


def test_resolution_is_expected_from_the_props():
    props = json.loads(json.dumps(PROPS))
    props["storyboard"]["width"] = 720
    props["storyboard"]["height"] = 1280
    result = _tech(props=props)
    assert "resolution" in result.failed


def test_a_720p_render_fails_resolution():
    streams = [dict(_probe()["streams"][0], width=720, height=1280), _probe()["streams"][1]]
    assert "resolution" in _tech(probe=_probe(streams=streams)).failed


def test_a_25fps_render_fails_frame_rate():
    streams = [dict(_probe()["streams"][0], avg_frame_rate="25/1", r_frame_rate="25/1"), _probe()["streams"][1]]
    assert "frame_rate" in _tech(probe=_probe(streams=streams)).failed


def test_yuvj420p_fails_the_pixel_format_check():
    streams = [dict(_probe()["streams"][0], pix_fmt="yuvj420p"), _probe()["streams"][1]]
    assert "pix_fmt" in _tech(probe=_probe(streams=streams)).failed


def test_a_full_range_tag_fails_the_color_range_check():
    streams = [dict(_probe()["streams"][0], color_range="pc"), _probe()["streams"][1]]
    result = _tech(probe=_probe(streams=streams))
    assert "color_range" in result.failed
    assert result.observed["color_range"] == "pc"


def test_a_missing_color_range_tag_fails_because_it_cannot_be_proven_limited():
    streams = [dict(_probe()["streams"][0], color_range=None), _probe()["streams"][1]]
    assert "color_range" in _tech(probe=_probe(streams=streams)).failed


def test_a_render_without_audio_fails_the_stream_and_codec_checks():
    result = _tech(probe=_probe(streams=[_probe()["streams"][0]]))
    assert "audio_stream_count" in result.failed
    assert "audio_codec" in result.failed


def test_two_audio_streams_fail_the_stream_count():
    audio = _probe()["streams"][1]
    result = _tech(probe=_probe(streams=[_probe()["streams"][0], audio, dict(audio)]))
    assert "audio_stream_count" in result.failed


def test_two_video_streams_fail_the_stream_count():
    video = _probe()["streams"][0]
    result = _tech(probe=_probe(streams=[video, dict(video), _probe()["streams"][1]]))
    assert "video_stream_count" in result.failed


# -- technical: detectors ----------------------------------------------------------------------


def test_a_black_interval_fails_black_frames():
    result = _tech(detectors=_clean_detectors(blackdetect=DetectorResult(ran=True, count=1, detail="black_start:1")))
    assert "black_frames" in result.failed


def test_a_silence_interval_fails_unexpected_silence():
    result = _tech(detectors=_clean_detectors(silencedetect=DetectorResult(ran=True, count=2, detail="x")))
    assert "unexpected_silence" in result.failed


def test_a_freeze_interval_fails_frozen_frames():
    result = _tech(detectors=_clean_detectors(freezedetect=DetectorResult(ran=True, count=1, detail="x")))
    assert "frozen_frames" in result.failed


def test_a_detector_that_did_not_run_is_a_hard_failure_not_a_warning():
    """The pipeline cannot treat an unmeasured file as clean. This is the difference from the
    standalone script, whose WARN is honest for a human and useless as a gate."""
    result = _tech(detectors=_clean_detectors(blackdetect=DetectorResult(ran=False, count=0, detail="ffmpeg missing")))
    assert "black_frames" in result.failed
    assert result.detectors["blackdetect"]["ran"] is False


def test_a_missing_detector_key_fails_rather_than_defaulting_clean():
    result = _tech(detectors={"blackdetect": DetectorResult(ran=True, count=0), "silencedetect": DetectorResult(ran=True, count=0)})
    assert "frozen_frames" in result.failed


# -- technical: loudness, checksum, scene hashes ------------------------------------------------


def test_loudness_outside_minus_16_plus_minus_2_fails():
    assert "loudness" in _tech(loudness={"input_i": -12.5, "input_tp": -1.5}).failed
    assert "loudness" in _tech(loudness={"input_i": -19.0, "input_tp": -1.5}).failed


def test_loudness_inside_the_window_passes():
    assert "loudness" not in _tech(loudness={"input_i": -14.2, "input_tp": -1.5}).failed
    assert "loudness" not in _tech(loudness={"input_i": -17.9, "input_tp": -1.5}).failed


def test_a_true_peak_above_minus_one_db_fails():
    assert "true_peak" in _tech(loudness={"input_i": -16.0, "input_tp": -0.2}).failed


def test_a_checksum_that_does_not_match_the_render_fails():
    assert "checksum" in _tech(sha256="f" * 64).failed


def test_scene_hash_keys_must_equal_the_storyboard_scene_ids():
    render = {"sha256": "e" * 64, "scene_hashes": {"sc1": "1", "sc2": "2"}}
    result = _tech(render=render)
    assert "scene_hashes" in result.failed
    assert result.observed["missing_scene_hashes"] == ["sc3"]


def test_an_extra_scene_hash_is_also_a_mismatch():
    render = {"sha256": "e" * 64, "scene_hashes": {"sc1": "1", "sc2": "2", "sc3": "3", "sc4": "4"}}
    assert "scene_hashes" in _tech(render=render).failed


# -- technical: subtitles ----------------------------------------------------------------------


def _with_subs(cues):
    props = json.loads(json.dumps(PROPS))
    props["storyboard"]["subtitles"] = cues
    return props


def test_a_subtitle_cue_past_the_narration_fails():
    props = _with_subs([{"startMs": 0, "endMs": 12_000, "text": "lama"}])
    assert "subtitle_bounds" in _tech(props=props).failed


def test_overlapping_subtitle_cues_fail():
    props = _with_subs(
        [
            {"startMs": 0, "endMs": 3000, "text": "satu"},
            {"startMs": 2000, "endMs": 5000, "text": "dua"},
        ]
    )
    result = _tech(props=props)
    assert "subtitle_bounds" in result.failed
    assert result.observed["subtitle_overlaps"] == 1


def test_an_unordered_subtitle_pair_fails():
    props = _with_subs(
        [
            {"startMs": 5000, "endMs": 6000, "text": "dua"},
            {"startMs": 1000, "endMs": 2000, "text": "satu"},
        ]
    )
    assert "subtitle_bounds" in _tech(props=props).failed


def test_a_subtitle_cue_over_42_characters_fails():
    props = _with_subs([{"startMs": 0, "endMs": 2000, "text": "x" * 43}])
    result = _tech(props=props)
    assert "subtitle_bounds" in result.failed
    assert result.observed["subtitle_max_chars"] == 43


def test_an_empty_subtitle_list_is_a_failure_when_the_script_has_segments():
    """A video whose narration is subtitled nowhere is not deliverable."""
    props = _with_subs([])
    assert "subtitle_bounds" in _tech(props=props).failed


# -- creative ----------------------------------------------------------------------------------


def _creative(**kwargs):
    params = {
        "props": PROPS,
        "audio": AUDIO,
        "review": REVIEW,
        "script": SCRIPT,
        "assets": ASSETS,
        "static_seconds": 1.0,
        "history": [],
    }
    params.update(kwargs)
    return evaluate_creative(**params)


def test_the_reference_storyboard_passes_every_creative_check():
    result = _creative()
    assert result.passed is True, result.failed
    assert result.metrics["static_ratio"] == pytest.approx(0.1)
    assert result.metrics["fade_ratio"] == 0.0
    assert result.metrics["shot_variety"] == pytest.approx(1.0)
    assert result.metrics["repeated_world"] == pytest.approx(1.0)


def test_static_ratio_above_0_45_fails():
    result = _creative(static_seconds=4.6)
    assert "static_ratio" in result.failed
    assert result.metrics["static_ratio"] == pytest.approx(0.46)


def test_static_ratio_at_the_threshold_passes():
    assert "static_ratio" not in _creative(static_seconds=4.5).failed


def test_fade_ratio_above_0_35_fails():
    props = json.loads(json.dumps(PROPS))
    for scene in props["storyboard"]["scenes"]:
        scene["transition"] = {"kind": "fade", "frames": 40}
    result = _creative(props=props)
    assert "fade_ratio" in result.failed
    assert result.metrics["fade_ratio"] == pytest.approx(0.4)


def test_a_cut_heavy_storyboard_has_zero_fade_ratio():
    assert _creative().metrics["fade_ratio"] == 0.0


def test_text_density_above_42_chars_per_second_fails():
    props = json.loads(json.dumps(PROPS))
    props["storyboard"]["scenes"][0]["text"] = [{"id": "t1", "text": "x" * 120, "role": "body", "atFrame": 0}]
    props["storyboard"]["scenes"][0]["durationInFrames"] = 60  # 2 s -> 60 chars/s
    result = _creative(props=props)
    assert "text_density" in result.failed
    assert result.metrics["text_density_max"] == pytest.approx(60.0)


def test_a_single_text_element_over_120_characters_fails():
    props = json.loads(json.dumps(PROPS))
    props["storyboard"]["scenes"][0]["text"] = [{"id": "t1", "text": "x" * 121, "role": "body", "atFrame": 0}]
    props["storyboard"]["scenes"][0]["durationInFrames"] = 300
    assert "text_density" in _creative(props=props).failed


def test_shot_variety_is_read_from_rendered_data_shots():
    """The adapter forwards ``data.shots[]`` and nothing else; a score from ``camera`` would be
    a number no pixel can contradict."""
    props = json.loads(json.dumps(PROPS))
    for scene in props["storyboard"]["scenes"]:
        scene["data"]["shots"] = [{"framing": "wide", "camera": "static", "weight": 1}]
        scene["camera"] = {"shot": "close", "move": "pan", "target": "t1"}
    result = _creative(props=props)
    assert "shot_variety" in result.failed
    assert result.metrics["shot_variety"] == pytest.approx(1 / 3)


def test_one_world_across_three_scenes_fails_repeated_world():
    props = json.loads(json.dumps(PROPS))
    for scene in props["storyboard"]["scenes"]:
        scene["data"]["environment"] = "dataCenter"
        scene["data"]["objects"] = [{"kind": "serverRack", "x": 0.5, "y": 0.4, "size": 0.4}]
    result = _creative(props=props)
    assert "repeated_world" in result.failed
    assert result.metrics["repeated_world"] == pytest.approx(1 / 3)


def test_a_revise_verdict_fails_the_hook_and_coherence_checks():
    review = {**REVIEW, "verdict": "revise", "findings": [{"severity": "major", "issue": "x"}]}
    result = _creative(review=review)
    assert "hook" in result.failed
    assert "coherence" in result.failed


def test_a_review_score_below_three_fails_the_named_check():
    review = {**REVIEW, "scores": {**REVIEW["scores"], "hook": 2}}
    result = _creative(review=review)
    assert "hook" in result.failed
    assert "coherence" not in result.failed


def test_a_missing_review_score_is_a_failure_not_a_default():
    review = {**REVIEW, "scores": {"hook": 4}}
    assert "coherence" in _creative(review=review).failed


def test_a_storyboard_scene_without_a_script_segment_fails_mapping():
    props = json.loads(json.dumps(PROPS))
    props["storyboard"]["scenes"][0]["segment"] = "missing"
    result = _creative(props=props)
    assert "segment_mapping" in result.failed
    assert result.metrics["mapped_segments"] == 2


def test_an_unmapped_script_segment_also_fails_mapping():
    script = json.loads(json.dumps(SCRIPT))
    script["segments"].append({"id": "s4", "text": "Empat", "purpose": "build"})
    assert "segment_mapping" in _creative(script=script).failed


def test_object_consistency_requires_a_drawn_object():
    """A scene with nothing on its stage is the blank-frame failure this gate exists to catch."""
    props = json.loads(json.dumps(PROPS))
    for scene in props["storyboard"]["scenes"]:
        scene["data"]["objects"] = []
    result = _creative(props=props)
    assert "object_consistency" in result.failed
    assert result.metrics["object_kinds"] == []


def test_an_unknown_object_kind_fails_consistency():
    """The storyboard cannot ask for a drawing the renderer does not ship."""
    props = json.loads(json.dumps(PROPS))
    props["storyboard"]["scenes"][0]["data"]["objects"][0]["kind"] = "hologram"
    result = _creative(props=props)
    assert "object_consistency" in result.failed
    assert "hologram" in result.metrics["unknown_objects"]


def test_every_shipped_object_kind_passes_consistency():
    """The mirror list and the renderer's library agree, kind by kind."""
    from packages.core.media.qc import SHIPPED_OBJECT_KINDS

    props = json.loads(json.dumps(PROPS))
    kinds = sorted(SHIPPED_OBJECT_KINDS)
    for index, scene in enumerate(props["storyboard"]["scenes"]):
        scene["data"]["objects"][0]["kind"] = kinds[index]
    result = _creative(props=props)
    assert "object_consistency" not in result.failed
    assert result.metrics["unknown_objects"] == []


def test_pacing_fails_when_one_scene_dominates_the_timeline():
    audio = json.loads(json.dumps(AUDIO))
    audio["scenes"][0]["endMs"] = 9000
    audio["scenes"][1].update({"startMs": 9000, "endMs": 9500})
    audio["scenes"][2].update({"startMs": 9500, "endMs": 10_000})
    result = _creative(audio=audio)
    assert "pacing" in result.failed
    assert result.metrics["pacing_max_scene_share"] > 0.6
    assert "0.6" in CREATIVE_THRESHOLDS["pacing_max_scene_share"]


def test_pacing_reports_cue_durations_too():
    result = _creative()
    assert result.metrics["pacing_median_cue_ms"] == pytest.approx(3000, abs=1)


def test_repetition_fails_above_0_8_jaccard_against_history():
    """The prior job is the same video with different words: same worlds, same shots."""
    same = {
        "scenes": [
            {"template": "ObjectExplainer", "environment": "dataCenter", "hero": "serverRack", "shot": "wide/static"},
            {"template": "ObjectExplainer", "environment": "circuit", "hero": "gpu", "shot": "medium/static"},
            {"template": "ObjectExplainer", "environment": "grid", "hero": "database", "shot": "close/static"},
        ]
    }
    result = _creative(history=[same])
    assert "repetition" in result.failed
    assert result.metrics["repetition"] == pytest.approx(1.0)


def test_a_partially_shared_style_stays_below_the_repetition_threshold():
    """One shared world out of three is 1/5 Jaccard, not a repetition verdict."""
    partial = {
        "scenes": [
            {"template": "ObjectExplainer", "environment": "dataCenter", "hero": "serverRack", "shot": "wide/static"},
        ]
    }
    result = _creative(history=[partial])
    assert "repetition" not in result.failed
    assert result.metrics["repetition"] < 0.8


def test_repetition_passes_against_a_different_world():
    other = {
        "scenes": [
            {"template": "KineticTypography", "environment": "space", "hero": "", "shot": "close/pushIn"}
        ]
    }
    result = _creative(history=[other])
    assert "repetition" not in result.failed
    assert result.metrics["repetition"] == pytest.approx(0.0)


def test_history_is_capped_at_ten_jobs():
    other = {
        "scenes": [
            {"template": "KineticTypography", "environment": "space", "hero": "", "shot": "close/pushIn"}
        ]
    }
    result = _creative(history=[other] * 25)
    assert result.metrics["history_compared"] == 10


def test_every_creative_metric_and_threshold_is_returned():
    result = _creative()
    assert set(CREATIVE_THRESHOLDS) <= set(result.thresholds)
    assert set(result.metrics) >= {
        "static_ratio",
        "fade_ratio",
        "text_density_max",
        "shot_variety",
        "repeated_world",
        "mapped_segments",
        "object_kinds",
        "unknown_objects",
        "pacing_max_scene_share",
        "repetition",
    }


# -- detector parsing --------------------------------------------------------------------------


def test_parse_blackdetect_counts_intervals():
    log = "black_start:1 black_end:2.03 black_duration:1.03\nblack_start:5 black_end:5.5 black_duration:0.5"
    result = parse_detector_output("blackdetect", log, returncode=0)
    assert result.ran is True
    assert result.count == 2
    assert "1.03" in result.detail


def test_parse_silencedetect_counts_intervals():
    log = "silence_start: 1.2\nsilence_end: 3.4 | silence_duration: 2.2"
    assert parse_detector_output("silencedetect", log, returncode=0).count == 1


def test_parse_freezedetect_counts_intervals():
    log = "freeze_start: 0.7\nfreeze_duration: 0.63\nfreeze_end: 1.36"
    assert parse_detector_output("freezedetect", log, returncode=0).count == 1


def test_a_nonzero_exit_means_the_detector_did_not_run():
    result = parse_detector_output("silencedetect", "Filtergraph has a audio output", returncode=1)
    assert result.ran is False
    assert result.count == 0


def test_a_filter_banner_is_not_a_detection():
    """The bug in ``scripts/verify_video.py``: ``name in log`` matches the filter's own name."""
    log = "Parsed_blackdetect_0 @ 0x1 [info] nothing here"
    assert parse_detector_output("blackdetect", log, returncode=0).count == 0


def test_measure_static_time_sums_freeze_intervals():
    log = "freeze_start: 0.5\nfreeze_end: 1.0\nfreeze_start: 2.0\nfreeze_end: 3.25"
    assert measure_static_time(log) == pytest.approx(1.75)


def test_an_unterminated_freeze_is_closed_at_the_media_duration():
    """A still looped to the last frame emits freeze_start and no freeze_end."""
    log = "freeze_start: 0"
    assert measure_static_time(log, duration_s=8.0) == pytest.approx(8.0)


def test_an_unterminated_freeze_without_a_duration_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="unterminated"):
        measure_static_time("freeze_start: 0")


def test_measure_static_time_ignores_the_filter_name():
    assert measure_static_time("Parsed_freezedetect_0 @ 0x1") == 0.0


# -- thresholds are named constants -------------------------------------------------------------


def test_technical_thresholds_are_declared_constants():
    assert TECHNICAL_THRESHOLDS["black_frames"] == "blackdetect=d=0.4:pix_th=0.02:pic_th=0.98"
    assert TECHNICAL_THRESHOLDS["unexpected_silence"] == "silencedetect=n=-45dB:d=2.5"
    assert TECHNICAL_THRESHOLDS["frozen_frames"] == "freezedetect=n=-60dB:d=2.0"
    assert TECHNICAL_THRESHOLDS["loudness"] == "-16 +/- 2 LUFS"
    assert TECHNICAL_THRESHOLDS["true_peak"] == "<= -1.0 dBTP"
    assert TECHNICAL_THRESHOLDS["duration"] == "within 120 ms of narration"


def test_qc_flags_missing_concrete_subject():
    script = {
        "segments": [
            {"id": "s1", "text": "Lihat struktur mesh dan wireframe poligon 3D."},
            {"id": "s2", "text": "Dua"},
            {"id": "s3", "text": "Tiga"},
        ]
    }
    # PROPS uses serverRack, gpu, database — missing meshTopology
    result = _creative(script=script)
    assert result.checks["concrete_subjects"] is False
    assert "meshTopology" in result.metrics["missing_concrete_subjects"]


def test_qc_passes_when_concrete_subject_present():
    import copy
    props_with_mesh = copy.deepcopy(PROPS)
    props_with_mesh["storyboard"]["scenes"][0]["data"]["objects"][0]["kind"] = "meshTopology"
    script = {
        "segments": [
            {"id": "s1", "text": "Lihat struktur mesh dan wireframe poligon 3D."},
            {"id": "s2", "text": "Dua"},
            {"id": "s3", "text": "Tiga"},
        ]
    }
    result = _creative(props=props_with_mesh, script=script)
    assert result.checks["concrete_subjects"] is True
    assert len(result.metrics["missing_concrete_subjects"]) == 0


def test_qc_flags_safe_zone_violation():
    import copy
    props_bad_pos = copy.deepcopy(PROPS)
    props_bad_pos["storyboard"]["scenes"][0]["data"]["objects"][0]["y"] = 0.95
    result = _creative(props=props_bad_pos)
    assert result.checks["safe_zones"] is False
    assert result.metrics["safe_zone_violations"] > 0


# -- creative quality, beyond frame differences -------------------------------------------------


def test_a_scene_whose_narration_names_a_subject_it_does_not_draw_fails_relevance():
    """The script-wide check passes when *some* scene draws the subject; this one asks for the
    scene whose own words name it. Ramen narrated over a GPU is the failure this catches."""
    import copy

    props = copy.deepcopy(PROPS)
    script = {
        "segments": [
            {"id": "s1", "text": "Satu"},
            {"id": "s2", "text": "Ramen digulung jadi mie keriting."},  # sc2 draws a gpu
            {"id": "s3", "text": "Tiga"},
        ]
    }
    # The film as a whole still draws ramen, so the script-wide gate is satisfied.
    props["storyboard"]["scenes"][2]["data"]["objects"][0]["kind"] = "ramenBowl"
    result = _creative(props=props, script=script)
    assert result.checks["concrete_subjects"] is True, "the subject is drawn somewhere"
    assert result.checks["narration_visual_relevance"] is False
    assert result.metrics["narration_relevance_missing"] == ["sc2"]


def test_a_scene_that_illustrates_its_own_narration_passes_relevance():
    import copy

    props = copy.deepcopy(PROPS)
    props["storyboard"]["scenes"][1]["data"]["objects"][0]["kind"] = "ramenBowl"
    props["storyboard"]["scenes"][1]["data"]["objects"][1]["kind"] = "cookingPot"
    script = {
        "segments": [
            {"id": "s1", "text": "Satu"},
            {"id": "s2", "text": "Ramen digulung jadi mie keriting."},
            {"id": "s3", "text": "Tiga"},
        ]
    }
    result = _creative(props=props, script=script)
    assert result.checks["narration_visual_relevance"] is True
    assert result.metrics["narration_relevance_checked"] == 1


def _with_causal(index, **fields):
    import copy

    props = copy.deepcopy(PROPS)
    scene = props["storyboard"]["scenes"][index]
    scene["causal_state"] = {
        "initial_state": "Awal",
        "causal_action": "Sesuatu terjadi",
        "resulting_state": "Akhir",
        "transition": "potong ke berikutnya",
        **fields,
    }
    return props


def test_an_incomplete_causal_cycle_fails_cause_and_effect():
    """A storyboard that claims a transformation but omits the mechanics has not shown one."""
    result = _creative(props=_with_causal(0, causal_action=""))
    assert result.checks["cause_effect"] is False
    assert result.metrics["causal_scenes_incomplete"] == ["sc1"]


def test_a_causal_cycle_that_ends_where_it_started_fails_cause_and_effect():
    result = _creative(props=_with_causal(0, resulting_state="Awal"))
    assert result.checks["cause_effect"] is False
    assert result.metrics["causal_scenes_unchanged"] == ["sc1"]


def test_a_complete_causal_cycle_passes_cause_and_effect():
    result = _creative(props=_with_causal(0))
    assert result.checks["cause_effect"] is True
    assert result.metrics["causal_scenes_declared"] == 1


def test_a_scene_with_no_causal_state_is_not_penalised_for_the_optional_field():
    """``SceneSpec.causal_state`` is optional in the contract; the gate must not require what the
    contract does not, or the contract's own optionality becomes a lie."""
    result = _creative()
    assert result.checks["cause_effect"] is True
    assert result.metrics["causal_scenes_declared"] == 0


def test_declaring_carry_while_changing_every_object_fails_continuity():
    import copy

    props = copy.deepcopy(PROPS)
    props["storyboard"]["scenes"][1]["motion"]["continuity"] = "carry"
    # sc1 draws serverRack + coolingFan; sc2 draws gpu + coolingFan. A carry claim over a shared
    # fan is still a claim the storyboard makes, so break the shared object to prove the check.
    props["storyboard"]["scenes"][1]["data"]["objects"][1]["kind"] = "wafer"
    result = _creative(props=props)
    assert result.checks["transition_continuity"] is False
    assert result.metrics["continuity_violations"] == ["sc2"]


def test_declaring_carry_over_a_shared_object_passes_continuity():
    result = _creative(props=_carry_fixture())
    assert result.checks["transition_continuity"] is True
    assert result.metrics["continuity_declared"] == 1


def _carry_fixture():
    import copy

    props = copy.deepcopy(PROPS)
    props["storyboard"]["scenes"][1]["motion"]["continuity"] = "carry"
    return props


def test_a_final_scene_that_draws_nothing_fails_visual_payoff():
    import copy

    props = copy.deepcopy(PROPS)
    props["storyboard"]["scenes"][2]["data"]["objects"] = []
    result = _creative(props=props)
    assert result.checks["visual_payoff"] is False
    assert "final scene draws nothing" in result.metrics["visual_payoff_problems"]


def test_a_final_scene_that_records_no_resulting_state_fails_visual_payoff():
    props = _with_causal(2, resulting_state="")
    result = _creative(props=props)
    assert result.checks["visual_payoff"] is False
    assert any(
        "resulting state" in problem for problem in result.metrics["visual_payoff_problems"]
    )


def test_the_reference_film_passes_every_creative_quality_check():
    result = _creative()
    for name in (
        "narration_visual_relevance",
        "cause_effect",
        "transition_continuity",
        "visual_payoff",
    ):
        assert result.checks[name] is True, name
