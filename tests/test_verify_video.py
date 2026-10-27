"""The media gate's pure logic and its exit-code contract.

No ffmpeg and no ffprobe: ``evaluate`` takes a hand-built probe dict, and ``main`` is exercised
only on the paths that stop before probing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_video.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_video", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module through sys.modules, so register it first.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify = _load()


def _probe(*, audio: bool = True, pix_fmt: str = "yuv420p", color_range: str | None = "tv",
           frames: int = 900, width: int = 1080, height: int = 1920) -> dict:
    video = {
        "codec_type": "video",
        "codec_name": "h264",
        "pix_fmt": pix_fmt,
        "width": width,
        "height": height,
        "avg_frame_rate": "30/1",
        "nb_read_frames": str(frames),
    }
    if color_range is not None:
        video["color_range"] = color_range
    streams = [video]
    if audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return {"streams": streams, "format": {"duration": str(frames / 30)}}


def _clean_detectors() -> dict:
    return {name: {"detected": False, "expected": False, "detail": ""} for name in verify.DETECTORS}


def test_a_perfect_probe_passes_every_check():
    result = verify.evaluate(_probe(), reference_frames=900, detectors=_clean_detectors())
    assert result.exit_code == verify.EXIT_OK
    assert result.failed == []

def test_duration_uses_audio_artifact_when_available():
    probe = _probe(frames=416)
    probe["format"]["duration"] = "13.990"

    result = verify.evaluate(
        probe,
        reference_frames=416,
        reference_duration_ms=13_990,
        detectors=_clean_detectors(),
    )

    assert "duration" not in {check.name for check in result.failed}



def test_duration_reference_is_ignored_when_audio_source_is_not_narration():
    assert verify.read_reference_duration_ms_from_payload(
        {"narration": {"src": "other.wav", "durationMs": 13_990}}
    ) is None


def test_duration_reference_requires_audio_contract_fields():
    assert verify.read_reference_duration_ms_from_payload(
        {"narration": {"src": "narration.wav", "durationMs": 13_990}}
    ) is None


def test_duration_reference_accepts_matching_narration_contract():
    assert verify.read_reference_duration_ms_from_payload(
        {
            "narration": {
                "src": "narration.wav",
                "durationMs": 13_990,
                "voice": "system-default",
            },
            "scenes": [{"sceneId": "sc1", "startMs": 0, "endMs": 13_990}],
            "subtitles": [{"startMs": 100, "endMs": 13_990, "text": "hello."}],
            "mix": {"loudness_lufs": -16},
        }
    ) == 13_990


def test_missing_narration_reference_cannot_pass_duration_gate():
    result = verify.evaluate(
        _probe(),
        reference_frames=900,
        reference_duration_ms=None,
        require_narration_reference=True,
        detectors=_clean_detectors(),
    )

    duration = next(check for check in result.checks if check.name == "duration")
    assert duration.status == "FAIL"
    assert "audio.json" in duration.reason

def test_yuvj420p_fails_with_the_observed_value():
    result = verify.evaluate(_probe(pix_fmt="yuvj420p"), reference_frames=900,
                             detectors=_clean_detectors())
    assert result.exit_code == verify.EXIT_FAILED
    failed = {c.name for c in result.failed}
    assert failed == {"pix_fmt"}
    pix = next(c for c in result.checks if c.name == "pix_fmt")
    assert pix.observed == "yuvj420p"
    assert "full range" in pix.reason


def test_zero_audio_fails_with_a_narration_requirement():
    result = verify.evaluate(_probe(audio=False), reference_frames=900,
                             detectors=_clean_detectors())
    assert result.exit_code == verify.EXIT_FAILED
    failed = {c.name for c in result.failed}
    assert {"audio_streams", "audio_codec"} <= failed
    audio = next(c for c in result.checks if c.name == "audio_streams")
    assert audio.observed == "0"
    assert "one narration stream" in audio.reason


def test_a_missing_color_range_is_a_warning_not_a_failure():
    result = verify.evaluate(_probe(color_range=None), reference_frames=900,
                             detectors=_clean_detectors())
    assert result.exit_code == verify.EXIT_OK
    check = next(c for c in result.checks if c.name == "color_range")
    assert check.observed == "unknown"
    assert check.hard is False
    assert check.status == "WARN"


def test_a_full_range_tag_fails_the_gate():
    result = verify.evaluate(_probe(color_range="pc"), reference_frames=900,
                             detectors=_clean_detectors())
    assert "color_range" in {c.name for c in result.failed}


def test_frame_count_without_a_reference_is_a_warning():
    result = verify.evaluate(_probe(), reference_frames=None, detectors=_clean_detectors())
    check = next(c for c in result.checks if c.name == "frame_count")
    assert check.hard is False
    assert "no render.json" in check.reason


def test_a_frame_count_mismatch_fails():
    result = verify.evaluate(_probe(frames=450), reference_frames=900,
                             detectors=_clean_detectors())
    assert "frame_count" in {c.name for c in result.failed}


def test_silencedetect_on_a_file_without_audio_is_expected_not_passed():
    detectors = _clean_detectors()
    detectors["silencedetect"] = {"detected": True, "expected": True,
                                  "detail": "silence_start: 0"}
    result = verify.evaluate(_probe(audio=False), reference_frames=900, detectors=detectors)
    check = next(c for c in result.checks if c.name == "silencedetect")
    assert check.status == "WARN"
    assert check.ok is False
    assert "without that stream" in check.reason
    # The audio failure is what fails the gate, not the detector.
    assert "silencedetect" not in {c.name for c in result.failed}


def test_a_real_black_frame_fails():
    detectors = _clean_detectors()
    detectors["blackdetect"] = {"detected": True, "expected": False,
                                "detail": "black_start:1 black_end:2"}
    result = verify.evaluate(_probe(), reference_frames=900, detectors=detectors)
    assert "blackdetect" in {c.name for c in result.failed}


def test_a_detector_that_did_not_run_is_a_warning():
    result = verify.evaluate(_probe(), reference_frames=900, detectors={})
    for name in verify.DETECTORS:
        check = next(c for c in result.checks if c.name == name)
        assert check.hard is False
        assert check.observed == "not run"


def test_json_output_carries_the_exit_code():
    result = verify.evaluate(_probe(audio=False), reference_frames=900,
                             detectors=_clean_detectors())
    payload = json.loads(json.dumps(result.to_json()))
    assert payload["exit_code"] == verify.EXIT_FAILED
    assert payload["passed"] is False
    assert {c["name"] for c in payload["checks"] if c["status"] == "FAIL"} == {
        "audio_streams",
        "audio_codec",
    }


def test_a_missing_job_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHORTS_JOBS_DIR", str(tmp_path / "jobs"))
    code = verify.main(["no-such-job"])
    assert code == verify.EXIT_NO_FILE
    assert "does not exist" in capsys.readouterr().err


def test_a_job_without_output_mp4_exits_two(tmp_path, monkeypatch, capsys):
    jobs = tmp_path / "jobs"
    (jobs / "abc").mkdir(parents=True)
    monkeypatch.setenv("SHORTS_JOBS_DIR", str(jobs))
    code = verify.main(["abc"])
    assert code == verify.EXIT_NO_FILE
    assert "no output.mp4" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--json"])
def test_a_missing_job_still_emits_json_when_asked(tmp_path, monkeypatch, capsys, flag):
    monkeypatch.setenv("SHORTS_JOBS_DIR", str(tmp_path / "jobs"))
    code = verify.main(["nope", flag])
    assert code == verify.EXIT_NO_FILE
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == verify.EXIT_NO_FILE


def test_a_detector_that_failed_to_run_is_a_warning_not_a_pass():
    """silencedetect with -vf exits non-zero; that must never read as a clean file."""
    detectors = _clean_detectors()
    detectors["silencedetect"] = {
        "detected": False,
        "expected": False,
        "detail": "Filtergraph has a audio output, cannot connect it to video output stream",
        "ran": False,
    }
    result = verify.evaluate(_probe(), reference_frames=900, detectors=detectors)
    check = next(c for c in result.checks if c.name == "silencedetect")
    assert check.status == "WARN"
    assert check.ok is False
    assert "did not run" in check.reason
    assert result.exit_code == verify.EXIT_OK


# -- detector parsing must read event markers, not the filter banner ----------------------------


def _banner(name: str) -> str:
    """The line every ffmpeg invocation prints for a filter, with no detection in it."""
    return (
        f"Stream mapping:\n  Stream #0:0 -> #0:0 ({name})\n"
        f"[Parsed_{name}_0 @ 0x000001] lavfi.{name}.{name}: nothing to report\n"
        "frame=   90 fps=0.0 q=-0.0 Lsize=N/A time=00:00:03.00 bitrate=N/A speed=74.2x"
    )


def test_a_banner_with_no_marker_is_clean():
    """The defect: ``name in log`` matched the filter's own name in its own banner, so every
    invocation looked like a detection. This log has the banner and no interval."""
    log = _banner("blackdetect")
    assert "blackdetect" in log, "the fixture must contain the filter name"
    result = verify.parse_detector_log("blackdetect", log, returncode=0)
    assert result["detected"] is False
    assert result["ran"] is True


def test_a_real_black_marker_is_detected():
    log = _banner("blackdetect") + "\n[blackdetect @ 0x1] black_start:1.0 black_end:2.03 black_duration:1.03"
    result = verify.parse_detector_log("blackdetect", log, returncode=0)
    assert result["detected"] is True
    assert result["ran"] is True


def test_a_real_freeze_marker_is_detected():
    log = _banner("freezedetect") + "\n[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 0.7"
    assert verify.parse_detector_log("freezedetect", log, returncode=0)["detected"] is True


def test_a_freeze_duration_marker_alone_is_detected():
    """Some ffmpeg builds report only the duration when the interval closes at EOF."""
    log = _banner("freezedetect") + "\n[freezedetect @ 0x1] lavfi.freezedetect.freeze_duration: 0.63"
    assert verify.parse_detector_log("freezedetect", log, returncode=0)["detected"] is True


def test_a_real_silence_marker_is_detected():
    log = _banner("silencedetect") + "\n[silencedetect @ 0x1] silence_start: 1.2"
    assert verify.parse_detector_log("silencedetect", log, returncode=0)["detected"] is True


def test_a_silence_end_marker_alone_is_detected():
    log = _banner("silencedetect") + "\n[silencedetect @ 0x1] silence_end: 3.4 | silence_duration: 2.2"
    assert verify.parse_detector_log("silencedetect", log, returncode=0)["detected"] is True


def test_a_filter_that_did_not_run_is_not_clean():
    log = "Filtergraph has a audio output, cannot connect it to video output stream"
    result = verify.parse_detector_log("silencedetect", log, returncode=1)
    assert result["ran"] is False
    assert result["detected"] is False


def test_the_clean_detector_map_reports_ran_true():
    findings = verify.parse_detector_log("blackdetect", _banner("blackdetect"), returncode=0)
    assert findings == {"detected": False, "expected": False, "detail": "", "ran": True}


def test_a_clean_file_still_passes_the_gate():
    detectors = {name: {"detected": False, "expected": False, "detail": "", "ran": True}
                 for name in verify.DETECTORS}
    result = verify.evaluate(_probe(), reference_frames=900, detectors=detectors)
    assert result.exit_code == verify.EXIT_OK


def test_a_detected_interval_still_fails_the_gate():
    detectors = {name: {"detected": False, "expected": False, "detail": "", "ran": True}
                 for name in verify.DETECTORS}
    detectors["blackdetect"] = {"detected": True, "expected": False,
                                "detail": "black_start:1.0", "ran": True}
    result = verify.evaluate(_probe(), reference_frames=900, detectors=detectors)
    assert "blackdetect" in {check.name for check in result.failed}
