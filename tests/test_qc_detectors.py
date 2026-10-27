"""Detectors and probes against real files, generated at test time.

No committed binaries: every fixture is a few hundred kilobytes of ffmpeg output built in
``tmp_path``. The point is that the *wiring* is exercised — the pure evaluator tests prove the
decision table, and these prove that the decision table is fed by a command that actually runs.

Durations are deliberately tiny (1-3 s) so the whole file stays under a few seconds.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from packages.core.media.qc import (
    DETECTORS,
    DetectorResult,
    measure_loudness,
    measure_static,
    parse_detector_output,
    run_detector,
    run_detectors,
    sha256_file,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe are required for the detector integration tests",
)

W, H, FPS = 270, 480, 30


def _ffmpeg(*args: str) -> None:
    proc = subprocess.run(  # noqa: S603 - argv array, no shell
        ["ffmpeg", "-v", "error", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-600:]


def _silent_clip(path: Path, *, seconds: float = 3.0) -> Path:
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d={seconds}",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate=48000:d={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    )
    return path


@pytest.fixture(scope="module")
def clean_clip(tmp_path_factory) -> Path:
    return _silent_clip(tmp_path_factory.mktemp("qc") / "clean.mp4")


# -- black -------------------------------------------------------------------------------------


def test_a_black_interval_is_detected_by_the_real_filter(tmp_path):
    path = tmp_path / "black.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=gray:s={W}x{H}:r={FPS}:d=2",
        "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,0.5,1.5)'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )
    result = run_detector("blackdetect", path)
    assert result.ran is True
    assert result.count >= 1, "a 1 s black span must be caught by d=0.4"


def test_a_clean_clip_reports_no_black_interval(clean_clip):
    result = run_detector("blackdetect", clean_clip)
    assert result.ran is True
    assert result.count == 0


def test_bare_blackdetect_would_miss_a_one_second_span(tmp_path):
    """Why the threshold is pinned rather than left at ffmpeg's default d=2."""
    path = tmp_path / "black1s.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=gray:s={W}x{H}:r={FPS}:d=2",
        "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,0.5,1.5)'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )
    proc = subprocess.run(  # noqa: S603
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", "blackdetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    log = f"{proc.stderr}{proc.stdout}"
    assert parse_detector_output("blackdetect", log, returncode=proc.returncode).count == 0


# -- frozen ------------------------------------------------------------------------------------


def test_a_still_loop_is_detected_as_frozen(tmp_path):
    path = tmp_path / "frozen.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=3",
        "-vf", "trim=end_frame=1,loop=loop=89:size=1:start=0,setpts=N/30/TB",
        "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )
    result = run_detector("freezedetect", path)
    assert result.ran is True
    assert result.count >= 1


def test_a_clip_with_real_motion_is_not_frozen(tmp_path):
    path = tmp_path / "motion.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=#223344:s={W}x{H}:r={FPS}:d=2",
        "-f", "lavfi", "-i", f"color=c=red:s=150x150:r={FPS}:d=2",
        "-filter_complex", "[0:v][1:v]overlay=x='t*120':y=200",
        "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )
    assert run_detector("freezedetect", path).count == 0


def test_measure_static_sums_freeze_time(clean_clip, tmp_path):
    still = tmp_path / "still.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=2",
        "-vf", "trim=end_frame=1,loop=loop=59:size=1:start=0,setpts=N/30/TB",
        "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(still),
    )
    seconds, parsed = measure_static(still)
    assert parsed.ran is True
    # The freeze runs to the last frame, so freezedetect emits freeze_start and no freeze_end.
    assert seconds >= 1.5, "an unterminated freeze must be closed at the media duration"


def test_measure_static_on_a_clean_clip_is_zero(clean_clip):
    seconds, parsed = measure_static(clean_clip)
    assert parsed.ran is True
    assert seconds == 0.0


# -- silence -----------------------------------------------------------------------------------


def test_a_silent_audio_stream_is_detected(clean_clip):
    """anullsrc is digital silence, which is exactly the failure a TTS gap produces."""
    result = run_detector("silencedetect", clean_clip)
    assert result.ran is True
    assert result.count >= 1


def test_a_tone_is_not_silence(tmp_path):
    path = tmp_path / "tone.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    )
    assert run_detector("silencedetect", path).count == 0


def test_silencedetect_applied_as_a_video_filter_fails_instead_of_reading_clean(clean_clip):
    """The exact bug ``scripts/verify_video.py`` documents: -vf aborts, and an aborted filter
    must never be reported as 'nothing detected'."""
    proc = subprocess.run(  # noqa: S603
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(clean_clip), "-vf", "silencedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    log = f"{proc.stderr}{proc.stdout}"
    result = parse_detector_output("silencedetect", log, returncode=proc.returncode)
    assert proc.returncode != 0
    assert result.ran is False


# -- loudness ----------------------------------------------------------------------------------


def test_loudness_is_measured_from_a_real_file(tmp_path):
    path = tmp_path / "loud.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", str(path))
    measured = measure_loudness(path)
    assert measured is not None
    assert -40.0 < measured["input_i"] < 0.0
    assert measured["input_tp"] <= 0.0


def test_loudness_returns_none_for_a_file_with_no_audio(tmp_path):
    path = tmp_path / "video_only.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )
    assert measure_loudness(path) is None


# -- runner-level behaviour --------------------------------------------------------------------


def test_run_detectors_returns_every_detector(clean_clip):
    results = run_detectors(clean_clip)
    assert set(results) == set(DETECTORS)
    assert all(isinstance(value, DetectorResult) for value in results.values())
    assert all(value.ran for value in results.values())


def test_a_missing_file_does_not_run_the_detector(tmp_path):
    result = run_detector("blackdetect", tmp_path / "absent.mp4")
    assert result.ran is False
    assert result.count == 0


def test_an_unknown_detector_is_a_programming_error(tmp_path):
    with pytest.raises(ValueError, match="unknown detector"):
        run_detector("sharpen", tmp_path / "x.mp4")


def test_sha256_matches_a_known_digest(tmp_path):
    path = tmp_path / "bytes.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
