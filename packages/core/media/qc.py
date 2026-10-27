"""Quality control as measurement, not opinion.

Two evaluators, both pure over data that was actually measured:

``evaluate_technical``
    FR-7.1. Takes an ffprobe dict, the timed props, the audio artifact, three detector results,
    a loudness measurement, the real file hash and ``render.json``. Expected values come from the
    props and the narration — **never** from ``render.json``. A render that reports its own frame
    count can never disagree with itself; the job at ``data/jobs/4145e5b9e03c87d7`` did exactly
    that and passed with a ``qc.json`` that contained no detector result at all.

``evaluate_creative``
    FR-7.2. Every number is derived from what the renderer actually receives: ``data.shots[]`` for
    shot variety (``camera``/``motion`` are dropped by the adapter and cannot be scored), the
    forwarded ``transition`` for fade ratio, the audio scene timings for pacing.

Design constraints that shape this module:

- It imports ``contracts`` and stdlib only. ``media`` may not reach into ``agents``,
  ``providers`` or ``orchestration`` — the evaluators are callable from a test and from a CLI
  without a provider, a database or a job.
- A detector that did not run is a **failure**, not a warning. The standalone
  ``scripts/verify_video.py`` prints WARN, which is honest for a human reading a terminal; a
  pipeline stage that cannot measure must not report success.
- Nothing here invents a score. If a review has no ``hook`` score, the hook check fails; it does
  not default to a passing value.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: FFmpeg filter strings. Thresholds are part of the contract, so they are named once and
#: reported in every artifact that used them.
TECHNICAL_THRESHOLDS: dict[str, str] = {
    "resolution": "1080x1920",
    "frame_rate": "30 +/- 0.01",
    "video_codec": "h264",
    "pix_fmt": "yuv420p",
    "color_range": "tv",
    "video_stream_count": "== 1",
    "audio_stream_count": "== 1",
    "audio_codec": "aac",
    "frame_count": "== sum(render-props scene durationInFrames)",
    "duration": "within 120 ms of narration",
    "black_frames": "blackdetect=d=0.4:pix_th=0.02:pic_th=0.98",
    "unexpected_silence": "silencedetect=n=-45dB:d=2.5",
    "frozen_frames": "freezedetect=n=-60dB:d=2.0",
    "subtitle_bounds": "ordered, non-overlapping, <= 42 chars, inside narration",
    "loudness": "-16 +/- 2 LUFS",
    "true_peak": "<= -1.0 dBTP",
    "checksum": "sha256(output.mp4) == render.json.sha256",
    "scene_hashes": "keys == storyboard scene ids",
}

CREATIVE_THRESHOLDS: dict[str, str] = {
    "static_ratio": "<= 0.45",
    "fade_ratio": "<= 0.35",
    "text_density": "<= 42 chars/s per scene and <= 120 chars per element",
    "shot_variety": ">= 0.5 distinct rendered shots",
    "repeated_world": ">= 0.5 distinct (template, setting, timeOfDay)",
    "pacing": "max scene share <= 0.6 of narration and median cue >= 700 ms",
    "pacing_max_scene_share": "<= 0.6 of total narration",
    "pacing_min_cue_ms": ">= 700 ms median cue",
    "repetition": "<= 0.8 Jaccard against up to 10 prior jobs",
    "hook": "review verdict accept and score >= 3",
    "coherence": "review verdict accept and score >= 3",
    "segment_mapping": "every scene segment in the script and every script segment in a scene",
    "character_consistency": ">= 1 rendered character id, all resolve to one rig/palette",
}

MAX_SUBTITLE_CHARS = 42
MAX_TEXT_ELEMENT_CHARS = 120
DURATION_TOLERANCE_MS = 120.0
FPS_TOLERANCE = 0.01
STATIC_FREEZE_D = 0.5
HISTORY_LIMIT = 10

#: FFmpeg filter names used by the detectors. Kept as one tuple so the stage and the script agree.
DETECTORS = ("blackdetect", "silencedetect", "freezedetect")

_DETECTOR_ARGV: dict[str, list[str]] = {
    "blackdetect": ["-vf", "blackdetect=d=0.4:pix_th=0.02:pic_th=0.98"],
    "silencedetect": ["-af", "silencedetect=n=-45dB:d=2.5"],
    "freezedetect": ["-vf", "freezedetect=n=-60dB:d=2.0"],
}

#: Interval markers. The count of these is the measurement; the filter's own name is not.
_INTERVAL_MARKERS = {
    "blackdetect": re.compile(r"black_start:"),
    "silencedetect": re.compile(r"silence_start:"),
    "freezedetect": re.compile(r"freeze_start:"),
}
_FREEZE_DURATION = re.compile(r"freeze_duration:\s*([0-9.]+)")
_FREEZE_START = re.compile(r"freeze_start:\s*([0-9.]+)")
_FREEZE_END = re.compile(r"freeze_end:\s*([0-9.]+)")


@dataclass(frozen=True)
class DetectorResult:
    """One detector's outcome. ``ran`` is separate from ``count`` on purpose."""

    ran: bool
    count: int
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"ran": self.ran, "count": self.count, "detail": self.detail}


@dataclass
class QcVerdict:
    """A check set plus the numbers behind it. ``passed`` is derived, never assigned."""

    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    observed: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, str] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    detectors: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def as_technical(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "observed": self.observed,
            "thresholds": self.thresholds,
            "failed": self.failed,
            "detectors": self.detectors,
            "reason": self.reason,
        }

    def as_creative(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "failed": self.failed,
            "reason": self.reason,
        }


def _finish(
    checks: dict[str, bool],
    *,
    observed: dict[str, Any],
    thresholds: dict[str, str],
    metrics: dict[str, Any] | None = None,
    detectors: dict[str, dict[str, Any]] | None = None,
) -> QcVerdict:
    failed = sorted(name for name, ok in checks.items() if not ok)
    reason = "all checks passed" if not failed else "failed: " + ", ".join(failed)
    return QcVerdict(
        passed=not failed,
        checks=checks,
        observed=observed,
        thresholds=dict(thresholds),
        failed=failed,
        detectors=detectors or {},
        metrics=metrics or {},
        reason=reason,
    )


# -- small helpers -----------------------------------------------------------------------------


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
    raw = fmt.get("duration")
    if not isinstance(raw, (str, int, float)):
        return None
    try:
        return float(raw) * 1000.0
    except (TypeError, ValueError):
        return None


def _scenes(props: dict[str, Any]) -> list[dict[str, Any]]:
    storyboard = props.get("storyboard")
    if not isinstance(storyboard, dict):
        return []
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list):
        return []
    return [scene for scene in scenes if isinstance(scene, dict)]


def _timed_frames(props: dict[str, Any]) -> int:
    total = 0
    for scene in _scenes(props):
        value = scene.get("durationInFrames")
        if isinstance(value, int) and value > 0:
            total += value
    return total


def _props_fps(props: dict[str, Any]) -> float:
    storyboard = props.get("storyboard")
    value = storyboard.get("fps") if isinstance(storyboard, dict) else None
    return float(value) if isinstance(value, (int, float)) and value > 0 else 30.0


def _props_size(props: dict[str, Any]) -> tuple[int, int]:
    storyboard = props.get("storyboard")
    if not isinstance(storyboard, dict):
        return 1080, 1920
    width = storyboard.get("width")
    height = storyboard.get("height")
    return (
        int(width) if isinstance(width, int) and width > 0 else 1080,
        int(height) if isinstance(height, int) and height > 0 else 1920,
    )


def content_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# -- detector parsing --------------------------------------------------------------------------


def parse_detector_output(name: str, log: str, *, returncode: int) -> DetectorResult:
    """Count real intervals. A non-zero exit means the filter did not run.

    ``scripts/verify_video.py`` decides ``detected`` with ``name in log``, which matches the
    filter's own banner line. Counting the interval marker is the measurement.
    """
    if returncode != 0:
        detail = ""
        for line in log.splitlines():
            if "error" in line.lower():
                detail = line.strip()[:200]
                break
        return DetectorResult(ran=False, count=0, detail=detail or f"ffmpeg exited {returncode}")
    marker = _INTERVAL_MARKERS.get(name)
    if marker is None:
        raise ValueError(f"unknown detector {name!r}; expected one of {list(_INTERVAL_MARKERS)}")
    lines = [line.strip() for line in log.splitlines() if marker.search(line)]
    return DetectorResult(ran=True, count=len(lines), detail=lines[0][:200] if lines else "")


def measure_static_time(log: str, *, duration_s: float | None = None) -> float:
    """Total seconds reported as frozen.

    ``freezedetect`` emits ``freeze_duration`` only when an interval *ends*. A freeze that runs to
    the last frame emits ``freeze_start`` alone, so summing durations reports 0.0 for the most
    extreme case there is — a single still looped for the whole video. An unterminated interval is
    therefore closed at the media duration, and asking for one without a duration is an error
    rather than a silent zero.
    """
    starts = [float(value) for value in _FREEZE_START.findall(log)]
    ends = [float(value) for value in _FREEZE_END.findall(log)]
    if not starts:
        return 0.0
    if len(starts) == len(ends):
        return round(sum(max(0.0, end - start) for start, end in zip(starts, ends, strict=True)), 3)
    if duration_s is None:
        raise ValueError(
            "freezedetect reported an unterminated interval; pass duration_s so it can be closed"
        )
    # Every start that has no matching end runs to the end of the file.
    total = 0.0
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration_s
        total += max(0.0, end - start)
    return round(total, 3)


def parse_loudnorm(log: str) -> dict[str, float] | None:
    """The last JSON object ffmpeg's ``loudnorm`` prints. ``None`` when it did not print one."""
    candidates = re.findall(r"\{[^{}]+\}", log, re.DOTALL)
    for blob in reversed(candidates):
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            continue
        try:
            return {
                "input_i": float(payload["input_i"]),
                "input_tp": float(payload["input_tp"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return None


def run_detector(name: str, path: Path, *, timeout_s: int = 180) -> DetectorResult:
    """One bounded ffmpeg pass. Argv array only, never a shell string."""
    if name not in _DETECTOR_ARGV:
        raise ValueError(f"unknown detector {name!r}")
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        *_DETECTOR_ARGV[name],
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv array, no shell
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return DetectorResult(ran=False, count=0, detail="ffmpeg not on PATH")
    except subprocess.TimeoutExpired:
        return DetectorResult(ran=False, count=0, detail=f"ffmpeg timed out after {timeout_s}s")
    log = f"{proc.stderr or ''}{proc.stdout or ''}"
    return parse_detector_output(name, log, returncode=proc.returncode)


def run_detectors(path: Path, *, timeout_s: int = 180) -> dict[str, DetectorResult]:
    return {name: run_detector(name, path, timeout_s=timeout_s) for name in DETECTORS}


def probe_duration_s(path: Path) -> float | None:
    """Media duration in seconds, or ``None`` when ffprobe cannot say."""
    argv = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv array, no shell
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        value = float((proc.stdout or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def measure_static(path: Path, *, timeout_s: int = 180) -> tuple[float, DetectorResult]:
    """Freeze time at ``d=0.5``, which is what ``static_ratio`` is defined against."""
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-vf",
        f"freezedetect=d={STATIC_FREEZE_D}",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv array, no shell
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return 0.0, DetectorResult(ran=False, count=0, detail="ffmpeg not on PATH")
    except subprocess.TimeoutExpired:
        return 0.0, DetectorResult(ran=False, count=0, detail=f"ffmpeg timed out after {timeout_s}s")
    log = f"{proc.stderr or ''}{proc.stdout or ''}"
    parsed = parse_detector_output("freezedetect", log, returncode=proc.returncode)
    duration_s = probe_duration_s(path)
    try:
        seconds = measure_static_time(log, duration_s=duration_s)
    except ValueError:
        return 0.0, DetectorResult(ran=False, count=parsed.count, detail="duration unknown")
    return seconds, parsed


def measure_loudness(path: Path, *, timeout_s: int = 180) -> dict[str, float] | None:
    """One loudnorm pass over the muxed file. ``None`` when ffmpeg could not measure it."""
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv array, no shell
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return parse_loudnorm(f"{proc.stderr or ''}{proc.stdout or ''}")


# -- keyframes ---------------------------------------------------------------------------------

#: Contact-sheet geometry. 1080 wide matches the output width; three tiles per row keeps a 6-tile
#: sheet around 1080x1280, which is readable at "high" detail and under the vision size cap.
SHEET_WIDTH = 1080
SHEET_TILE_HEIGHT = 620
#: Colour of the tile that carries the "no frame" label. ``tile``'s default is black, and a black
#: tile is indistinguishable from a black frame in the video — the vision prompt would correctly
#: report it as a finding, blaming the render for our layout.
SHEET_PAD_COLOR = "0x2b2b2b"
#: Grid shapes that leave no empty cell. ``len(frames)`` picks one, so padding only exists where
#: the shape is forced: 5 frames in 3x2 leaves one cell, which gets a label instead of black.
SHEET_GRIDS: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (2, 1),
    3: (3, 1),
    4: (2, 2),
    5: (3, 2),
    6: (3, 2),
}
MAX_KEYFRAMES = 6
BOUNDARY_OFFSET_S = 0.5


def scene_midpoints(
    props: dict[str, Any], *, include_boundaries: bool = False, limit: int = MAX_KEYFRAMES
) -> list[dict[str, Any]]:
    """Frames worth looking at: one per scene centre, optionally one after each cut.

    A midpoint alone can miss a scene that starts broken and settles, and a boundary alone can
    catch only the transition. Both, capped, is the smallest set that can see either.
    """
    fps = _props_fps(props)
    scenes = _scenes(props)
    points: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes):
        start = scene.get("startFrame")
        duration = scene.get("durationInFrames")
        if not isinstance(start, int) or not isinstance(duration, int) or duration <= 0:
            continue
        points.append(
            {
                "sceneId": str(scene.get("sceneId") or f"sc{index}"),
                "frame": start + duration // 2,
                "boundary": False,
            }
        )
        if include_boundaries and index + 1 < len(scenes):
            offset = round(BOUNDARY_OFFSET_S * fps)
            after = start + duration + offset
            following = scenes[index + 1]
            next_start = following.get("startFrame")
            next_duration = following.get("durationInFrames")
            if isinstance(next_start, int) and isinstance(next_duration, int):
                points.append(
                    {
                        "sceneId": str(following.get("sceneId") or f"sc{index + 1}"),
                        "frame": min(after, next_start + max(0, next_duration - 1)),
                        "boundary": True,
                    }
                )
    return points[: max(0, limit)]


def sheet_grid(count: int) -> tuple[int, int]:
    """The (columns, rows) shape for ``count`` frames. Raises rather than inventing a shape."""
    if count < 1:
        raise ValueError("a contact sheet needs at least one frame")
    return SHEET_GRIDS[count]


def _sheet_filter(count: int, tile_height: int) -> str:
    """Scale each still, tile it into a grid sized to the count, then label any empty cell.

    The label must come **after** ``tile``. Placed before it, ``drawtext`` is part of the per-frame
    chain and stamps every tile — which is what an earlier version did: five frames each captioned
    "no frame 6" while the actual empty cell stayed blank. After ``tile`` the text is drawn once,
    positioned inside the one cell that has no frame.

    Black is never used for the empty cell: a black tile is a plausible black frame, and the vision
    prompt is instructed to report an unreadable tile as a finding.
    """
    columns, rows = sheet_grid(count)
    tile_width = SHEET_WIDTH // columns
    chain = (
        f"scale={tile_width}:{tile_height}:force_original_aspect_ratio=decrease,"
        f"pad={tile_width}:{tile_height}:(ow-iw)/2:(oh-ih)/2:color={SHEET_PAD_COLOR},"
        f"tile={columns}x{rows}:color={SHEET_PAD_COLOR}:padding=0:margin=0"
    )
    unused = columns * rows - count
    if not unused:
        return chain
    # The empty cell is always the last one in reading order.
    column, row = count % columns, count // columns
    x = column * tile_width
    y = row * tile_height
    return (
        f"{chain},drawtext=text='no frame {count + 1}':fontcolor=white@0.8:fontsize=26:"
        f"x={x}+({tile_width}-text_w)/2:y={y}+({tile_height}-text_h)/2"
    )


def extract_contact_sheet(
    video: Path, props: dict[str, Any], target: Path, *, timeout_s: int = 120
) -> tuple[Path, int]:
    """One JPEG holding every keyframe. Returns the path and the number actually extracted.

    One image leaves the machine per job: six separate uploads would be six times the cost and six
    times the exposure for the same information. The count returned is the number of stills the
    sheet was built from, which is what the provider's answer is checked against.
    """
    points = scene_midpoints(props, include_boundaries=True, limit=MAX_KEYFRAMES * 2)
    if not points:
        return target, 0
    video = Path(video)
    if not video.is_file():
        raise RuntimeError(f"ffmpeg cannot read a missing clip: {video}")

    # A scene shorter than one second has its midpoint exactly where "0.5 s after the cut" lands,
    # so the two points are the same frame. Extracting it twice would inflate the count the
    # provider is checked against; the cap therefore applies to distinct frames, not to points.
    frames = sorted({int(point["frame"]) for point in points})[:MAX_KEYFRAMES]
    select = "+".join(f"eq(n\\,{frame})" for frame in frames)
    count = len(frames)
    target.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(video),
        "-vf",
        f"select='{select}',{_sheet_filter(count, SHEET_TILE_HEIGHT)}",
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(target),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv array, no shell
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not on PATH; cannot extract a contact sheet") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"contact sheet timed out after {timeout_s}s") from exc
    if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-600:]
        raise RuntimeError(f"ffmpeg could not build a contact sheet: {detail}")
    return target, count


# -- technical ---------------------------------------------------------------------------------


def evaluate_technical(
    *,
    probe: dict[str, Any],
    props: dict[str, Any],
    audio: dict[str, Any],
    detectors: dict[str, DetectorResult],
    loudness: dict[str, float] | None,
    sha256: str,
    render: dict[str, Any],
) -> QcVerdict:
    """FR-7.1 over measured facts. Every expected value comes from props/audio, not the render."""
    video = _streams(probe, "video")
    audios = _streams(probe, "audio")
    first = video[0] if video else {}

    expected_width, expected_height = _props_size(props)
    expected_fps = _props_fps(props)
    expected_frames = _timed_frames(props)
    narration = audio.get("narration")
    narration_ms = float(narration.get("durationMs") or 0) if isinstance(narration, dict) else 0.0

    measured_fps = _fps(first)
    measured_frames = _frames(first)
    measured_ms = _duration_ms(probe)

    observed: dict[str, Any] = {
        "width": first.get("width"),
        "height": first.get("height"),
        "fps": measured_fps,
        "pix_fmt": first.get("pix_fmt"),
        "color_range": first.get("color_range"),
        "video_codec": first.get("codec_name"),
        "audio_codec": audios[0].get("codec_name") if audios else None,
        "video_streams": len(video),
        "audio_streams": len(audios),
        "frames": measured_frames,
        "duration_ms": round(measured_ms, 3) if measured_ms is not None else None,
        "expected_frames": expected_frames,
        "expected_duration_ms": narration_ms,
        "expected_width": expected_width,
        "expected_height": expected_height,
        "expected_fps": expected_fps,
    }

    checks: dict[str, bool] = {}
    checks["resolution"] = (
        first.get("width") == expected_width and first.get("height") == expected_height
    )
    checks["frame_rate"] = (
        measured_fps is not None and abs(measured_fps - expected_fps) <= FPS_TOLERANCE
    )
    checks["video_codec"] = first.get("codec_name") == "h264"
    checks["pix_fmt"] = first.get("pix_fmt") == "yuv420p"
    # ffprobe omits color_range for an untagged stream. That cannot be proven limited, so it
    # fails here even though the standalone script reports it as a warning for a human.
    checks["color_range"] = first.get("color_range") == "tv"
    checks["video_stream_count"] = len(video) == 1
    checks["audio_stream_count"] = len(audios) == 1
    checks["audio_codec"] = bool(audios) and audios[0].get("codec_name") == "aac"
    checks["frame_count"] = (
        expected_frames > 0 and measured_frames == expected_frames
    )
    checks["duration"] = (
        narration_ms > 0
        and measured_ms is not None
        and abs(measured_ms - narration_ms) <= DURATION_TOLERANCE_MS
    )

    detector_json: dict[str, dict[str, Any]] = {}
    for name in DETECTORS:
        result = detectors.get(name)
        if result is None:
            detector_json[name] = {"ran": False, "count": 0, "detail": "not run"}
            checks[_detector_check(name)] = False
            continue
        detector_json[name] = result.to_json()
        # A detector that did not run is a failure: an unmeasured file is not a clean file.
        checks[_detector_check(name)] = result.ran and result.count == 0

    subtitle = _subtitle_metrics(props, audio, narration_ms)
    observed.update(subtitle["observed"])
    checks["subtitle_bounds"] = subtitle["ok"]

    loudness = loudness or {}
    integrated = loudness.get("input_i")
    peak = loudness.get("input_tp")
    observed["integrated_lufs"] = integrated
    observed["true_peak_dbtp"] = peak
    checks["loudness"] = integrated is not None and -18.0 <= float(integrated) <= -14.0
    checks["true_peak"] = peak is not None and float(peak) <= -1.0

    expected_sha = render.get("sha256")
    observed["sha256"] = sha256
    observed["render_sha256"] = expected_sha
    checks["checksum"] = bool(expected_sha) and sha256 == expected_sha

    scene_ids = sorted(
        str(scene.get("sceneId"))
        for scene in _scenes(props)
        if isinstance(scene.get("sceneId"), str) and scene.get("sceneId")
    )
    hashes = render.get("scene_hashes")
    hashed = sorted(hashes) if isinstance(hashes, dict) else []
    observed["scene_ids"] = scene_ids
    observed["hashed_scene_ids"] = hashed
    observed["missing_scene_hashes"] = [sid for sid in scene_ids if sid not in hashed]
    observed["extra_scene_hashes"] = [sid for sid in hashed if sid not in scene_ids]
    checks["scene_hashes"] = scene_ids == hashed

    return _finish(checks, observed=observed, thresholds=TECHNICAL_THRESHOLDS, detectors=detector_json)


def _detector_check(name: str) -> str:
    return {
        "blackdetect": "black_frames",
        "silencedetect": "unexpected_silence",
        "freezedetect": "frozen_frames",
    }[name]


def _subtitle_metrics(
    props: dict[str, Any], audio: dict[str, Any], narration_ms: float
) -> dict[str, Any]:
    storyboard = props.get("storyboard")
    raw = storyboard.get("subtitles") if isinstance(storyboard, dict) else None
    if not isinstance(raw, list):
        fallback = audio.get("subtitles")
        raw = fallback if isinstance(fallback, list) else []
    cues = [cue for cue in raw if isinstance(cue, dict)]

    overlaps = 0
    unordered = 0
    outside = 0
    max_chars = 0
    previous_end = -1
    previous_start = -1
    for cue in cues:
        start = cue.get("startMs")
        end = cue.get("endMs")
        text = cue.get("text")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            unordered += 1
            continue
        if start < previous_end:
            overlaps += 1
        if start < previous_start:
            unordered += 1
        if narration_ms > 0 and end > narration_ms:
            outside += 1
        previous_end = max(previous_end, end)
        previous_start = max(previous_start, start)
        if isinstance(text, str):
            max_chars = max(max_chars, len(text))

    segments = 0
    storyboard = props.get("storyboard")
    if isinstance(storyboard, dict) and isinstance(storyboard.get("scenes"), list):
        segments = len(storyboard["scenes"])

    observed = {
        "subtitle_cues": len(cues),
        "subtitle_overlaps": overlaps,
        "subtitle_unordered": unordered,
        "subtitle_outside_narration": outside,
        "subtitle_max_chars": max_chars,
    }
    ok = (
        bool(cues)
        and overlaps == 0
        and unordered == 0
        and outside == 0
        and max_chars <= MAX_SUBTITLE_CHARS
        and segments > 0
    )
    return {"ok": ok, "observed": observed}


# -- creative ----------------------------------------------------------------------------------


def _rendered_shots(scene: dict[str, Any]) -> list[tuple[str, str]]:
    """The shots the renderer will actually cut to.

    ``product-adapter.ts`` forwards ``data`` untouched and drops ``camera``/``motion``, and
    ``IllustratedStory`` reads ``data.shots[]``. Scoring ``camera.move`` would produce a number no
    pixel can contradict, which is exactly the false confidence this file exists to prevent.
    """
    data = scene.get("data")
    if not isinstance(data, dict):
        return []
    shots = data.get("shots")
    if not isinstance(shots, list):
        return []
    out: list[tuple[str, str]] = []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        framing = shot.get("framing")
        camera = shot.get("camera")
        if isinstance(framing, str) and isinstance(camera, str):
            out.append((framing, camera))
    return out


def _world(scene: dict[str, Any]) -> tuple[str, str, str]:
    raw_data = scene.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    template = scene.get("template")
    setting = data.get("setting")
    time_of_day = data.get("timeOfDay")
    return (
        template if isinstance(template, str) else "",
        setting if isinstance(setting, str) else "",
        time_of_day if isinstance(time_of_day, str) else "",
    )


def _character_ids(props: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for scene in _scenes(props):
        data = scene.get("data")
        if not isinstance(data, dict):
            continue
        actors = data.get("actors")
        if not isinstance(actors, list):
            continue
        for actor in actors:
            if isinstance(actor, dict) and isinstance(actor.get("character"), str):
                ids.append(actor["character"])
    return ids


def _distinct_ratio(values: Iterable[Any], total: int) -> float:
    if total <= 0:
        return 0.0
    return len(set(values)) / total


def _style_signature(props: dict[str, Any]) -> dict[str, Any]:
    """Content-independent signature for cross-job repetition.

    Text, narration and timings are excluded on purpose: two jobs about different topics can be
    the same video visually, and that is the repetition worth catching.
    """
    scenes = []
    for scene in _scenes(props):
        shots = _rendered_shots(scene)
        template, setting, time_of_day = _world(scene)
        scenes.append(
            {
                "template": template,
                "setting": setting,
                "timeOfDay": time_of_day,
                "shot": "/".join(shots[0]) if shots else "",
            }
        )
    return {"scenes": scenes}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def _signature_tokens(signature: dict[str, Any]) -> set[str]:
    scenes = signature.get("scenes")
    if not isinstance(scenes, list):
        return set()
    tokens = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        tokens.add(
            "|".join(
                str(scene.get(key) or "")
                for key in ("template", "setting", "timeOfDay", "shot")
            )
        )
    return tokens


def evaluate_creative(
    *,
    props: dict[str, Any],
    audio: dict[str, Any],
    review: dict[str, Any] | None,
    script: dict[str, Any] | None,
    assets: dict[str, Any] | None,
    static_seconds: float,
    history: list[dict[str, Any]] | None = None,
) -> QcVerdict:
    """FR-7.2 over the props the renderer received and the timings it was given."""
    scenes = _scenes(props)
    scene_count = len(scenes)
    total_frames = _timed_frames(props)
    fps = _props_fps(props)
    total_seconds = total_frames / fps if fps else 0.0

    observed: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    checks: dict[str, bool] = {}

    # static_ratio -- measured, never inferred from a declared camera move.
    static_ratio = static_seconds / total_seconds if total_seconds > 0 else 1.0
    metrics["static_ratio"] = static_ratio
    metrics["static_seconds"] = round(static_seconds, 3)
    metrics["duration_seconds"] = round(total_seconds, 3)
    checks["static_ratio"] = static_ratio <= 0.45

    # fade_ratio -- from the transitions the adapter forwards to the renderer.
    fade_frames = 0
    for scene in scenes:
        transition = scene.get("transition")
        if isinstance(transition, dict) and transition.get("kind") == "fade":
            frames = transition.get("frames")
            if isinstance(frames, int) and frames > 0:
                fade_frames += frames
    fade_ratio = fade_frames / total_frames if total_frames else 0.0
    metrics["fade_ratio"] = fade_ratio
    metrics["fade_frames"] = fade_frames
    checks["fade_ratio"] = fade_ratio <= 0.35

    # text_density -- per scene chars/second plus the longest single element.
    worst_density = 0.0
    longest_element = 0
    for scene in scenes:
        duration = scene.get("durationInFrames")
        seconds = (duration / fps) if isinstance(duration, int) and duration > 0 and fps else 0.0
        chars = 0
        texts = scene.get("text")
        if isinstance(texts, list):
            for element in texts:
                if not isinstance(element, dict):
                    continue
                text = element.get("text")
                if isinstance(text, str):
                    chars += len(text)
                    longest_element = max(longest_element, len(text))
        if seconds > 0:
            worst_density = max(worst_density, chars / seconds)
    metrics["text_density_max"] = round(worst_density, 3)
    metrics["text_element_max_chars"] = longest_element
    checks["text_density"] = worst_density <= 42.0 and longest_element <= MAX_TEXT_ELEMENT_CHARS

    # shot_variety -- rendered data.shots[] only.
    shots: list[tuple[str, str]] = []
    for scene in scenes:
        shots.extend(_rendered_shots(scene))
    shot_variety = _distinct_ratio(shots, len(shots))
    metrics["shot_variety"] = shot_variety
    metrics["rendered_shots"] = len(shots)
    metrics["distinct_rendered_shots"] = len(set(shots))
    checks["shot_variety"] = bool(shots) and shot_variety >= 0.5

    # repeated_world -- one template/setting/timeOfDay for the whole video is the failure.
    worlds = [_world(scene) for scene in scenes]
    repeated_world = _distinct_ratio(worlds, scene_count)
    metrics["repeated_world"] = repeated_world
    metrics["distinct_worlds"] = len(set(worlds))
    checks["repeated_world"] = scene_count > 0 and repeated_world >= 0.5

    # hook / coherence -- bound to the accepted review, never re-scored by a model here.
    scores = review.get("scores") if isinstance(review, dict) else None
    scores = scores if isinstance(scores, dict) else {}
    verdict = review.get("verdict") if isinstance(review, dict) else None
    accepted = verdict == "accept"
    for name in ("hook", "coherence"):
        value = scores.get(name)
        numeric = float(value) if isinstance(value, (int, float)) else None
        metrics[f"{name}_score"] = numeric
        checks[name] = accepted and numeric is not None and numeric >= 3.0
    metrics["review_verdict"] = verdict
    metrics["review_findings"] = len(review.get("findings") or []) if isinstance(review, dict) else 0

    # segment_mapping -- every scene names a script segment and every segment is rendered.
    script_segments = []
    if isinstance(script, dict) and isinstance(script.get("segments"), list):
        script_segments = [
            item.get("id")
            for item in script["segments"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
    scene_segments = [
        scene.get("segment") for scene in scenes if isinstance(scene.get("segment"), str)
    ]
    missing_in_script = [sid for sid in scene_segments if sid not in script_segments]
    unrendered = [sid for sid in script_segments if sid not in scene_segments]
    mapped = len([sid for sid in scene_segments if sid in script_segments])
    metrics["mapped_segments"] = mapped
    metrics["missing_segments_in_script"] = missing_in_script
    metrics["unrendered_segments"] = unrendered
    checks["segment_mapping"] = (
        bool(script_segments)
        and not missing_in_script
        and not unrendered
        and len(scene_segments) == len(scenes)
    )

    # character_consistency -- at least one rendered actor, all resolving to one rig/palette.
    ids = _character_ids(props)
    records = {}
    if isinstance(assets, dict) and isinstance(assets.get("characters"), list):
        for record in assets["characters"]:
            if isinstance(record, dict) and isinstance(record.get("id"), str):
                records[record["id"]] = record
    unresolved = sorted({cid for cid in ids if cid not in records})
    pairs = {
        (records[cid].get("rig_hash"), records[cid].get("palette_hash"))
        for cid in ids
        if cid in records
    }
    metrics["character_ids"] = sorted(set(ids))
    metrics["unresolved_characters"] = unresolved
    metrics["character_rig_palette_pairs"] = len(pairs)
    checks["character_consistency"] = bool(ids) and not unresolved and len(pairs) == 1

    # pacing -- from measured scene timings and cue durations.
    raw_audio_scenes = audio.get("scenes")
    audio_scenes: list[Any] = raw_audio_scenes if isinstance(raw_audio_scenes, list) else []
    durations = []
    for timing in audio_scenes:
        if not isinstance(timing, dict):
            continue
        start, end = timing.get("startMs"), timing.get("endMs")
        if isinstance(start, int) and isinstance(end, int) and end > start:
            durations.append(end - start)
    narration = audio.get("narration")
    narration_ms = float(narration.get("durationMs") or 0) if isinstance(narration, dict) else 0.0
    max_share = max(durations) / narration_ms if durations and narration_ms else 1.0
    raw_cues = audio.get("subtitles")
    cues: list[Any] = raw_cues if isinstance(raw_cues, list) else []
    cue_lengths = sorted(
        cue["endMs"] - cue["startMs"]
        for cue in cues
        if isinstance(cue, dict)
        and isinstance(cue.get("startMs"), int)
        and isinstance(cue.get("endMs"), int)
        and cue["endMs"] > cue["startMs"]
    )
    median_cue = float(cue_lengths[len(cue_lengths) // 2]) if cue_lengths else 0.0
    metrics["pacing_max_scene_share"] = max_share
    metrics["pacing_median_cue_ms"] = median_cue
    metrics["pacing_scene_count"] = len(durations)
    checks["pacing"] = (
        bool(durations) and max_share <= 0.6 and median_cue >= 700.0
    )

    # repetition -- style signature against up to ten prior rendered jobs.
    signature = _style_signature(props)
    prior = [item for item in (history or []) if isinstance(item, dict)][:HISTORY_LIMIT]
    tokens = _signature_tokens(signature)
    worst = 0.0
    for other in prior:
        worst = max(worst, _jaccard(tokens, _signature_tokens(other)))
    metrics["repetition"] = worst
    metrics["history_compared"] = len(prior)
    checks["repetition"] = worst <= 0.8

    observed["signature"] = signature
    observed["scenes"] = scene_count
    return _finish(
        checks,
        observed=observed,
        thresholds=CREATIVE_THRESHOLDS,
        metrics=metrics,
    )


__all__ = [
    "CREATIVE_THRESHOLDS",
    "DETECTORS",
    "DetectorResult",
    "MAX_KEYFRAMES",
    "SHEET_GRIDS",
    "MAX_SUBTITLE_CHARS",
    "MAX_TEXT_ELEMENT_CHARS",
    "QcVerdict",
    "TECHNICAL_THRESHOLDS",
    "content_hash",
    "evaluate_creative",
    "evaluate_technical",
    "extract_contact_sheet",
    "scene_midpoints",
    "sheet_grid",
    "measure_loudness",
    "measure_static",
    "measure_static_time",
    "parse_detector_output",
    "parse_loudnorm",
    "probe_duration_s",
    "run_detector",
    "run_detectors",
    "sha256_file",
]
