"""Verify one job's rendered video against the media gate in TEST_STRATEGY §3.

    uv run python scripts/verify_video.py <job_id> [--json]

Exit codes are the contract:

    0  every hard check passed
    1  at least one hard check failed
    2  the job directory or output.mp4 does not exist (nothing to verify)

Paths come from ``apps.api.settings.Settings.from_env()``, so ``SHORTS_DATA_DIR`` and
``SHORTS_JOBS_DIR`` work exactly as they do for the API; no path is hardcoded.

This is a script, not a library: the check logic lives in ``evaluate`` so the test can feed it a
hand-built ffprobe dict without spawning anything.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.settings import Settings  # noqa: E402 - after the sys.path fix
from packages.core.media.render import probe_media  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_FILE = 2

EXPECTED_WIDTH = 1080
EXPECTED_HEIGHT = 1920
EXPECTED_FPS = 30.0
EXPECTED_PIX_FMT = "yuv420p"
EXPECTED_VIDEO_CODEC = "h264"
DURATION_TOLERANCE_MS = 120.0

#: Detector filters from TEST_STRATEGY §3 Media. Each is one ffmpeg pass over the file.
DETECTORS = ("blackdetect", "silencedetect", "freezedetect")


@dataclass
class Check:
    """One reported line. ``hard`` false means a warning: it is printed, never fails the gate."""

    name: str
    ok: bool
    observed: str
    expected: str = ""
    reason: str = ""
    hard: bool = True

    @property
    def status(self) -> str:
        if self.ok:
            return "PASS"
        return "FAIL" if self.hard else "WARN"

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "ok": self.ok,
            "hard": self.hard,
            "observed": self.observed,
            "expected": self.expected,
            "reason": self.reason,
        }


@dataclass
class Result:
    checks: list[Check] = field(default_factory=list)
    job_id: str = ""
    video: str = ""
    detectors: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.hard]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.hard]

    @property
    def exit_code(self) -> int:
        return EXIT_FAILED if self.failed else EXIT_OK

    def to_json(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "video": self.video,
            "exit_code": self.exit_code,
            "passed": self.exit_code == EXIT_OK,
            "checks": [c.to_json() for c in self.checks],
            "detectors": self.detectors,
        }


def _streams(probe: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    streams = probe.get("streams")
    if not isinstance(streams, list):
        return []
    return [s for s in streams if isinstance(s, dict) and s.get("codec_type") == kind]


def _fps(stream: dict[str, Any]) -> float | None:
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    if not isinstance(raw, str) or "/" not in raw:
        return None
    num, _, den = raw.partition("/")
    try:
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _frames(stream: dict[str, Any]) -> int | None:
    for key in ("nb_read_frames", "nb_frames"):
        raw = stream.get(key)
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
    return None


def _duration_ms(probe: dict[str, Any]) -> float | None:
    fmt = probe.get("format")
    if not isinstance(fmt, dict):
        return None
    try:
        return float(fmt.get("duration")) * 1000.0
    except (TypeError, ValueError):
        return None


def evaluate(
    probe: dict[str, Any],
    *,
    reference_frames: int | None = None,
    reference_duration_ms: float | None = None,
    require_narration_reference: bool = False,
    detectors: dict[str, Any] | None = None,
) -> Result:
    """Turn an ffprobe dict into the media gate's verdict. Pure; never raises."""
    result = Result()
    video = _streams(probe, "video")
    audio = _streams(probe, "audio")
    first = video[0] if video else {}
    detectors = detectors or {}

    result.checks.append(
        Check(
            name="video_streams",
            ok=len(video) == 1,
            observed=str(len(video)),
            expected="1",
        )
    )
    codec = first.get("codec_name")
    result.checks.append(
        Check(
            name="video_codec",
            ok=codec == EXPECTED_VIDEO_CODEC,
            observed=str(codec),
            expected=EXPECTED_VIDEO_CODEC,
        )
    )
    width, height = first.get("width"), first.get("height")
    result.checks.append(
        Check(
            name="resolution",
            ok=width == EXPECTED_WIDTH and height == EXPECTED_HEIGHT,
            observed=f"{width}x{height}",
            expected=f"{EXPECTED_WIDTH}x{EXPECTED_HEIGHT}",
        )
    )
    fps = _fps(first)
    result.checks.append(
        Check(
            name="fps",
            ok=fps is not None and abs(fps - EXPECTED_FPS) <= 0.01,
            observed=f"{fps:g}" if fps is not None else "unknown",
            expected=f"{EXPECTED_FPS:g}",
        )
    )
    pix_fmt = first.get("pix_fmt")
    result.checks.append(
        Check(
            name="pix_fmt",
            ok=pix_fmt == EXPECTED_PIX_FMT,
            observed=str(pix_fmt),
            expected=EXPECTED_PIX_FMT,
            reason="" if pix_fmt == EXPECTED_PIX_FMT else "yuvj420p is full range; the gate needs yuv420p",
        )
    )

    color_range = first.get("color_range")
    if color_range is None:
        # ffprobe omits the key for untagged streams. That is not a pass and not a failure:
        # it cannot be distinguished from "limited" without decoding, so it is a warning.
        result.checks.append(
            Check(
                name="color_range",
                ok=False,
                observed="unknown",
                expected="tv",
                reason="ffprobe reports no color_range; cannot be proven limited range",
                hard=False,
            )
        )
    else:
        result.checks.append(
            Check(
                name="color_range",
                ok=str(color_range) == "tv",
                observed=str(color_range),
                expected="tv",
            )
        )

    frames = _frames(first)
    if reference_frames is None:
        result.checks.append(
            Check(
                name="frame_count",
                ok=frames is not None,
                observed=str(frames),
                expected="unknown",
                reason="no render.json to compare against; observed count only",
                hard=False,
            )
        )
    else:
        result.checks.append(
            Check(
                name="frame_count",
                ok=frames == reference_frames,
                observed=str(frames),
                expected=str(reference_frames),
            )
        )

    duration_ms = _duration_ms(probe)
    if require_narration_reference and reference_duration_ms is None:
        expected_ms = None
    elif reference_duration_ms is not None:
        expected_ms = reference_duration_ms
    elif frames is not None and fps is not None:
        expected_ms = frames / fps * 1000.0
    else:
        expected_ms = None
    if expected_ms is None:
        result.checks.append(
            Check(
                name="duration",
                ok=False,
                observed=f"{duration_ms:.0f}ms" if duration_ms is not None else "unknown",
                expected="narration duration or frames/fps",
                reason=(
                    "audio.json and narration.wav do not provide a matching narration duration"
                    if require_narration_reference
                    else "cannot compute an expected duration without audio.json or frames and fps"
                ),
            )
        )
    else:
        result.checks.append(
            Check(
                name="duration",
                ok=duration_ms is not None and abs(duration_ms - expected_ms) <= DURATION_TOLERANCE_MS,
                observed=f"{duration_ms:.0f}ms" if duration_ms is not None else "unknown",
                expected=f"{expected_ms:.0f}ms (+/-{DURATION_TOLERANCE_MS:.0f}ms)",
            )
        )

    audio_codec = audio[0].get("codec_name") if audio else None
    result.checks.append(
        Check(
            name="audio_streams",
            ok=len(audio) == 1,
            observed=str(len(audio)),
            expected="1",
            reason="" if len(audio) == 1 else "exactly one narration stream is required",
        )
    )
    result.checks.append(
        Check(
            name="audio_codec",
            ok=audio_codec == "aac",
            observed=str(audio_codec),
            expected="aac",
            reason="" if audio_codec == "aac" else "narration must be encoded as AAC",
        )
    )

    for name in DETECTORS:
        finding = detectors.get(name)
        if finding is None:
            result.checks.append(
                Check(
                    name=name,
                    ok=False,
                    observed="not run",
                    expected="no unexpected detection",
                    reason="detector did not run",
                    hard=False,
                )
            )
            continue
        detected = bool(finding.get("detected"))
        expected = bool(finding.get("expected"))
        ran = finding.get("ran", True)
        observed = str(finding.get("detail") or ("detected" if detected else "nothing"))
        if not ran:
            # The filter did not execute (bad invocation, missing binary). A non-result must never
            # read as "clean", so it is a warning that names the failure.
            result.checks.append(
                Check(
                    name=name,
                    ok=False,
                    observed=observed,
                    expected="detector ran",
                    reason="the detector did not run; this is not evidence of a clean file",
                    hard=False,
                )
            )
        elif detected and expected:
            result.checks.append(
                Check(
                    name=name,
                    ok=False,
                    observed=observed,
                    expected="no unexpected detection",
                    reason="expected detector finding for a media file without that stream",
                    hard=False,
                )
            )
        else:
            result.checks.append(
                Check(
                    name=name,
                    ok=not detected,
                    observed=observed,
                    expected="no unexpected detection",
                )
            )

    return result


#: The event markers each filter prints when it actually finds something. The filter's own name
#: appears in every invocation's banner, so ``name in log`` matched unconditionally — a file with a
#: real black interval read clean and a clean file read dirty, depending only on which words the
#: banner happened to contain.
DETECTOR_MARKERS: dict[str, tuple[str, ...]] = {
    "blackdetect": ("black_start:", "black_end:"),
    "silencedetect": ("silence_start:", "silence_end:"),
    "freezedetect": ("freeze_start:", "freeze_end:", "freeze_duration:"),
}


def parse_detector_log(name: str, log: str, *, returncode: int) -> dict[str, Any]:
    """Turn one ffmpeg log into a detector finding, using event markers only.

    A filter that ran and printed no marker is clean. A filter that did not run is neither clean
    nor dirty: ``ran`` is false and the caller reports it as a warning, because an unmeasured file
    is not evidence of anything.
    """
    if name not in DETECTOR_MARKERS:
        raise ValueError(f"unknown detector {name!r}")
    if returncode != 0:
        detail = ""
        for line in log.splitlines():
            if "error" in line.lower():
                detail = line.strip()[:200]
                break
        return {
            "detected": False,
            "expected": False,
            "detail": detail or f"ffmpeg exited {returncode}",
            "ran": False,
        }
    markers = DETECTOR_MARKERS[name]
    hits = [line.strip() for line in log.splitlines() if any(marker in line for marker in markers)]
    return {
        "detected": bool(hits),
        "expected": False,
        "detail": hits[0][:200] if hits else "",
        "ran": True,
    }


def run_detectors(path: Path, *, has_audio: bool) -> dict[str, Any]:
    """Run each detector filter once. Absent ffmpeg is reported, not crashed on.

    ``silencedetect`` is an audio filter: applied with ``-vf`` it aborts with "Filtergraph has a
    audio output, cannot connect it to video output stream", which would otherwise look like a
    clean result. It uses ``-af`` and is skipped entirely when the file has no audio stream.
    """
    findings: dict[str, Any] = {}
    for name in DETECTORS:
        if name == "silencedetect" and not has_audio:
            findings[name] = {
                "detected": False,
                "expected": False,
                "detail": "not applicable: the file has no audio stream",
            }
            continue
        argv = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af" if name == "silencedetect" else "-vf",
            name,
            "-f",
            "null",
            "-",
        ]
        try:
            proc = subprocess.run(  # noqa: S603 - argv array, no shell
                argv, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
            )
        except FileNotFoundError:
            findings[name] = {
                "detected": False,
                "expected": False,
                "detail": "ffmpeg not on PATH",
                "ran": False,
            }
            continue
        log = f"{proc.stderr or ''}{proc.stdout or ''}"
        findings[name] = parse_detector_log(name, log, returncode=proc.returncode)
    return findings


def read_reference_frames(job_dir: Path) -> int | None:
    render = job_dir / "render.json"
    if not render.is_file():
        return None
    try:
        payload = json.loads(render.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("frames")
    return value if isinstance(value, int) and value > 0 else None


def read_reference_duration_ms_from_payload(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    narration = payload.get("narration")
    scenes = payload.get("scenes")
    subtitles = payload.get("subtitles")
    mix = payload.get("mix")
    if not isinstance(narration, dict) or narration.get("src") != "narration.wav":
        return None
    if not isinstance(narration.get("voice"), str) or not narration["voice"]:
        return None
    if not isinstance(scenes, list) or not scenes or not isinstance(subtitles, list) or not isinstance(mix, dict):
        return None
    try:
        duration = float(narration["durationMs"])
    except (KeyError, TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def read_reference_duration_ms(job_dir: Path) -> float | None:
    audio = job_dir / "audio.json"
    narration = job_dir / "narration.wav"
    if not audio.is_file() or not narration.is_file():
        return None
    try:
        payload = json.loads(audio.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = read_reference_duration_ms_from_payload(payload)
    if expected is None:
        return None
    measured = _duration_ms(probe_media(narration))
    return expected if measured is not None and abs(measured - expected) <= 1.0 else None


def print_result(result: Result) -> None:
    width = max((len(c.name) for c in result.checks), default=10)
    print(f"job {result.job_id}")
    print(f"video {result.video}")
    for check in result.checks:
        expected = f" (expected {check.expected})" if check.expected else ""
        reason = f" — {check.reason}" if check.reason else ""
        print(
            f"{check.status:<4} {check.name:<{width}} {check.observed}{expected}{reason}"
        )
    passed = len(result.checks) - len(result.failed) - len(result.warnings)
    print(
        f"\n{passed} passed, {len(result.failed)} failed, "
        f"{len(result.warnings)} warning(s) — exit {result.exit_code}"
    )
    if result.failed:
        print("failed: " + ", ".join(c.name for c in result.failed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify one job's rendered video against the media gate."
    )
    parser.add_argument("job_id", help="job id, as returned by POST /api/jobs")
    parser.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    job_dir = Path(settings.jobs_dir) / args.job_id
    video = job_dir / "output.mp4"

    if not job_dir.is_dir():
        message = f"job directory does not exist: {job_dir}"
        if args.json:
            print(json.dumps({"job_id": args.job_id, "error": message, "exit_code": EXIT_NO_FILE}))
        else:
            print(f"ERROR {message}", file=sys.stderr)
        return EXIT_NO_FILE
    if not video.is_file():
        message = f"no output.mp4 for job {args.job_id}: {video}"
        if args.json:
            print(json.dumps({"job_id": args.job_id, "error": message, "exit_code": EXIT_NO_FILE}))
        else:
            print(f"ERROR {message}", file=sys.stderr)
        return EXIT_NO_FILE

    probe = probe_media(video)
    has_audio = bool(_streams(probe, "audio"))
    detectors = run_detectors(video, has_audio=has_audio)
    result = evaluate(
        probe,
        reference_frames=read_reference_frames(job_dir),
        reference_duration_ms=read_reference_duration_ms(job_dir),
        require_narration_reference=(job_dir / "render.json").is_file(),
        detectors=detectors,
    )
    result.job_id = args.job_id
    result.video = str(video)
    result.detectors = detectors

    if args.json:
        print(json.dumps(result.to_json(), indent=2, sort_keys=True))
    else:
        print_result(result)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
