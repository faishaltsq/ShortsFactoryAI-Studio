"""The render boundary: one Remotion subprocess in, one ffprobe-validated MP4 out.

Everything here is deliberately dull. The interesting rules live in the callers:

- ``render.json`` is written only after ffprobe has described the actual file, so a stage can
  never claim a render it did not produce (AGENTS §3 rule 1).
- Technical QC never invents an audio track. A silent MP4 fails the ``audio_streams`` check and
  the job is blocked; fabricating silence to make the gate green would be a false artifact.
- The subprocess is the only place ``packages/video`` is touched, per AGENTS §4.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..contracts.artifacts import RenderArtifact
from ..contracts.base import validate_artifact
from ..contracts.state import JobState
from ..security.redact import redact

if TYPE_CHECKING:
    from ..orchestration.runner import Stage

#: The Remotion entry point inside ``packages/video``.
CLI_RELATIVE = Path("node_modules/@remotion/cli/remotion-cli.js")
COMPOSITION_ID = "Short"
#: The compositions this build is allowed to render. Both are registered in
#: ``packages/video/src/Root.tsx``; the list is closed so a typo cannot silently render the
#: default composition and record a different name.
COMPOSITIONS = frozenset({COMPOSITION_ID, "Thumbnail"})
PROPS_NAME = "render-props.json"
RENDER_NAME = "render.json"
VIDEO_NAME = "output.mp4"
RAW_VIDEO_NAME = "video-only.mp4"

#: Rendering is attributed to EditorAgent: it exists in AGENT_IDS, and its documented role is
#: "composes the final timeline". Technical and editorial QC live in ``orchestration/editorial.py``
#: and are attributed to QualityAgent there.
RENDER_AGENT = "EditorAgent"


def free_tcp_port() -> int:
    """Return a loopback port that is currently free.

    Binding ``:0`` and closing is not enough on Windows: a wildcard listener elsewhere can still
    answer a connect, and Remotion would then serve its bundle on a port Chrome cannot reach. So
    the socket is bound with ``SO_EXCLUSIVEADDRUSE`` where available and the port is verified by
    a refused connect before it is returned.
    """
    last_error: Exception | None = None
    for _ in range(40):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        except OSError as exc:  # pragma: no cover - only on a machine with no ports left
            last_error = exc
            continue
        finally:
            sock.close()
        if 1024 <= port <= 65535 and not _accepts_connection(port):
            return port
    raise RuntimeError(f"no free loopback port available for the Remotion preview server: {last_error}")


def _accepts_connection(port: int) -> bool:
    """True when something answers on ``port``. A refused connect is the proof we want."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.25)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


def render_argv(
    *,
    video_dir: Path,
    props_path: Path,
    out_path: Path,
    port: int,
    frames: tuple[int, int] | None = None,
    composition: str = COMPOSITION_ID,
) -> list[str]:
    """Build the Remotion argv array. Never a shell string; both paths must be absolute.

    ``composition`` defaults to the video composition. It is a parameter rather than the module
    constant because the thumbnail is a different composition in the same Remotion project, and a
    constant pinned to ``"Short"`` made it unreachable from any Python code path.
    ``frames`` is an inclusive ``(start, end)`` range for the per-scene cache misses; ``None``
    renders the whole composition.
    """
    if composition not in COMPOSITIONS:
        raise ValueError(
            f"unknown composition {composition!r}; expected one of {sorted(COMPOSITIONS)}"
        )
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is not on PATH; the renderer needs it to run packages/video")
    cli = Path(video_dir) / CLI_RELATIVE
    if not Path(props_path).is_absolute() or not Path(out_path).is_absolute():
        raise ValueError("props_path and out_path must be absolute; a relative path renders empty")
    argv = [
        node,
        str(cli),
        "render",
        "src/index.ts",
        composition,
        str(out_path),
        f"--props={props_path}",
        "--overwrite",
        "--log=error",
        # Remotion's config only sets the *image* format (jpeg). Two flags are needed for a
        # limited-range yuv420p file: `--pixel-format` asks for the format, but Remotion's default
        # color space emits no `-color_range`, so libx264 tags the output full range and ffprobe
        # reports yuvj420p. `--color-space=bt709` is what emits `-color_range tv` plus the zscale
        # conversion, and a full-range file is a real colour difference, not a cosmetic label.
        "--pixel-format=yuv420p",
        "--color-space=bt709",
        f"--port={port}",
        "--concurrency=1",
    ]
    if frames is not None:
        start, end = frames
        argv.append(f"--frames={start}-{end}")
    return argv


def probe_media(path: Path) -> dict[str, Any]:
    """Describe a media file with ffprobe. A non-zero exit is an error, not an empty result."""
    argv = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-count_frames",
        str(path),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - argv array, no shell
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is not on PATH") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise RuntimeError(f"ffprobe failed on {path}: {tail}")
    try:
        payload: dict[str, Any] = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc
    return payload


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


def validate_render(
    probe: dict[str, Any],
    *,
    expected_frames: int,
    expected_width: int = 1080,
    expected_height: int = 1920,
    expected_fps: float = 30.0,
    expected_duration_ms: float | None = None,
) -> list[str]:
    """Return the names of failed checks, empty when every check passes.

    A missing key is a failed check. Nothing here raises: QC must be able to report on a file
    that is broken in any of a dozen ways.
    """
    failed: list[str] = []
    video = _streams(probe, "video")
    audio = _streams(probe, "audio")
    first = video[0] if video else {}

    if len(video) != 1:
        failed.append("video_streams")
    if len(audio) != 1:
        failed.append("audio_streams")

    if first.get("width") != expected_width:
        failed.append("width")
    if first.get("height") != expected_height:
        failed.append("height")

    fps = _fps(first)
    if fps is None or abs(fps - expected_fps) > 0.01:
        failed.append("fps")

    if first.get("codec_name") != "h264":
        failed.append("video_codec")
    if first.get("pix_fmt") != "yuv420p":
        failed.append("pix_fmt")

    frames = _frames(first)
    if frames != expected_frames:
        failed.append("frame_count")

    # One authoritative duration check. ``expected_duration_ms`` is the measured narration from
    # ``audio.json``; when it is absent the frame span stands in, because a render with no
    # narration has nothing else to be compared against. A separate ``frame_duration`` check used
    # to ask whether the frame span was shorter than the narration — the same question, answered
    # by a second code path that could disagree with ``TECHNICAL_QC``.
    frame_duration_ms = expected_frames / expected_fps * 1000.0
    expected_ms = expected_duration_ms if expected_duration_ms is not None else frame_duration_ms
    measured_ms = _duration_ms(probe)
    if measured_ms is None or abs(measured_ms - expected_ms) > 120.0:
        failed.append("duration")

    if not audio or audio[0].get("codec_name") != "aac":
        failed.append("audio_codec")

    return failed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()



def update_storyboard_from_audio(storyboard: dict[str, Any], audio: dict[str, Any]) -> dict[str, Any]:
    """Return render props whose scene frames and subtitles follow measured narration."""
    timed: dict[str, Any] = json.loads(json.dumps(storyboard))
    fps = int(timed.get("fps") or 30)
    scenes = timed.get("scenes")
    audio_scenes = audio.get("scenes")
    if not isinstance(scenes, list) or not isinstance(audio_scenes, list) or len(scenes) != len(audio_scenes):
        raise ValueError("audio scene timings must match storyboard scenes")
    cursor = 0
    for index, (scene, timing) in enumerate(zip(scenes, audio_scenes, strict=True)):
        if scene.get("sceneId") != timing.get("sceneId"):
            raise ValueError(f"audio scene {index} does not match storyboard scene")
        end_frame = math.ceil(int(timing["endMs"]) * fps / 1000)
        if end_frame <= cursor:
            raise ValueError(f"audio scene {scene.get('sceneId')!r} has no renderable duration")
        scene["startFrame"] = cursor
        scene["durationInFrames"] = end_frame - cursor
        speech = _speech_windows(timing.get("speech"), duration_ms=int(timing["endMs"]) - int(timing["startMs"]))
        if speech:
            scene["speech"] = speech
        else:
            # An audio artifact from before the boundaries were persisted carries no ``speech``.
            # Dropping the key (rather than writing an empty list or a synthesised clock) is what
            # makes the renderer's "no windows means a closed mouth" rule observable downstream.
            scene.pop("speech", None)
        cursor = end_frame
    timed["subtitles"] = audio.get("subtitles", [])
    return timed


def _speech_windows(raw: Any, *, duration_ms: int) -> list[dict[str, int]]:
    """Validate one scene's measured word windows, or return [] when there are none.

    The audio stage clamps these to the measured speech offset, so they arrive ordered and inside
    the scene. They are re-checked here because this function is the boundary the renderer trusts:
    a mouth driven by overlapping or out-of-range windows would open at the wrong frame and still
    look plausible in a still, which is exactly the failure this feature exists to avoid.
    """
    if not isinstance(raw, list):
        return []
    windows: list[dict[str, int]] = []
    previous_end = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"speech[{index}] must be an object")
        start, end = item.get("startMs"), item.get("endMs")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError(f"speech[{index}] startMs/endMs must be integers")
        if start < previous_end or end <= start or end > duration_ms:
            raise ValueError(
                f"speech[{index}] {start}..{end} must be ordered, non-empty and inside the "
                f"scene (previous end {previous_end}, scene {duration_ms} ms)"
            )
        windows.append({"startMs": start, "endMs": end})
        previous_end = end
    return windows


def mux_argv(video_path: Path, narration_path: Path, output_path: Path) -> list[str]:
    """Build the fixed ffmpeg argv that adds one AAC narration stream without re-encoding video.

    No ``-shortest``. ``update_storyboard_from_audio`` rounds every scene end *up*, so the picture
    is deliberately up to one frame longer than the narration; ``-shortest`` then cut the output
    back to the audio length and deleted that frame. A 434-frame render against 14450 ms of
    narration muxed to 433 frames, and ``TECHNICAL_QC`` blocked the job on ``frame_count`` — the
    gate was right, the mux was wrong.

    The video is the master timeline: it was rendered to the frames the storyboard asked for, and
    muxing must not change how many of them survive. The audio stream simply ends first and the
    container pads it.

    ``-b:a 64k``, not 192k. AAC-LC allows 6144 bits per 1024-sample frame, so a 16 kHz stream tops
    out near 96 kb/s; requesting 192k made ffmpeg print ``Too many bits 12288 > 6144 per frame
    requested, clamping to max`` and deliver 67 524 b/s on a real render. A constant the encoder
    cannot honour is a lie in the argv. 64k is ample for mono speech and is a rate the format can
    actually reach.

    ``-ar 16000`` is a real resample, not a no-op: ``narration.wav`` measures 192 kHz mono, so this
    is a 12:1 conversion. Stating it keeps the delivered format a decision rather than an ffmpeg
    default that would move if the TTS voice changed rate.
    """
    return [
        "ffmpeg", "-y", "-i", str(video_path), "-i", str(narration_path),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        "-ar", "16000", "-ac", "1", "-b:a", "64k", "-movflags",
        "+faststart", str(output_path),
    ]


def mux_narration(video_path: Path, narration_path: Path, output_path: Path, *, timeout_s: int = 120) -> None:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed ffmpeg argv, no shell
            mux_argv(video_path, narration_path, output_path), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_s, check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg mux timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise RuntimeError(f"ffmpeg mux exited {proc.returncode}: {detail}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg mux produced no file at {output_path}")


def render_storyboard(
    *,
    video_dir: Path,
    props_path: Path,
    out_path: Path,
    timeout_s: int = 900,
    frames: tuple[int, int] | None = None,
    composition: str = COMPOSITION_ID,
) -> dict[str, Any]:
    """Run exactly one Remotion subprocess. This is the packages/video boundary."""
    cli = Path(video_dir) / CLI_RELATIVE
    if not cli.is_file():
        raise RuntimeError(f"Remotion CLI missing at {cli}; run npm install in packages/video")
    port = free_tcp_port()
    argv = render_argv(
        video_dir=video_dir,
        props_path=props_path,
        out_path=out_path,
        port=port,
        frames=frames,
        composition=composition,
    )
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - argv array, no shell
            argv,
            cwd=str(video_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"render timed out after {timeout_s}s (port {port})") from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise RuntimeError(f"remotion exited {proc.returncode}: {tail}")
    return {
        "port": port,
        "elapsed_ms": elapsed_ms,
        "stdout_tail": (proc.stdout or "").strip()[-1200:],
    }


def write_render_props(store: Any, job_id: str) -> Path:
    """Persist storyboard props with measured audio timings and real subtitle cues."""
    storyboard = store.read_artifact(job_id, "storyboard.json")
    audio = store.read_artifact(job_id, "audio.json")
    timed = update_storyboard_from_audio(storyboard, audio)
    target = Path(store.job_dir(job_id)) / PROPS_NAME
    tmp = target.with_name(f".{PROPS_NAME}.tmp")
    data = json.dumps({"storyboard": timed}, ensure_ascii=False, indent=2, sort_keys=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    return target.resolve()


def renderer_version(video_dir: Path) -> str:
    """The pinned remotion version from packages/video/package.json, or '' when unreadable."""
    package = Path(video_dir) / "package.json"
    try:
        payload = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    deps = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(deps, dict):
        return ""
    value = deps.get("remotion")
    return value if isinstance(value, str) else ""


def _scene_hashes(storyboard: dict[str, Any]) -> dict[str, str]:
    """Content hash per scene.

    The hash covers the whole timed scene dict. ``update_storyboard_from_audio`` bakes the
    measured narration timings and subtitle cues into each scene *before* this runs (the stage
    hashes the timed props, not the raw storyboard), so a scene's hash changes when its
    narration, speech windows, or cues change — bytes the per-scene cache keys on.
    """
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list):
        return {}
    hashes: dict[str, str] = {}
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = scene.get("sceneId")
        if not isinstance(scene_id, str) or not scene_id:
            continue
        canonical = json.dumps(scene, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        hashes[scene_id] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return hashes


def _cache_key(
    *,
    scene_hash: str,
    renderer: str,
    renderer_version_value: str,
    theme: str,
    total_frames: int,
    watermark: str,
    width: int,
    height: int,
    fps: int,
) -> str:
    """One cache filename stem: every input the rendered picture of a scene depends on.

    The scene dict hash carries frames, speech windows, subtitle-side timing. The rest are the
    render environment plus the two global pixel inputs that live outside any scene: the total
    length (progress bar) and the watermark text. ``renderer_version`` is inside so a Remotion
    upgrade cannot serve stale pixels under fresh pixels' name.
    """
    material = "|".join(
        (
            scene_hash,
            renderer,
            renderer_version_value,
            theme,
            str(total_frames),
            watermark,
            str(width),
            str(height),
            str(fps),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


#: The two renderers this repository can drive. Order is deliberate: the primary first.
RENDERERS: tuple[str, ...] = ("remotion", "bang-motion")

#: ``packages/video``'s Node capture driver for the secondary renderer.
BANG_SCRIPT_RELATIVE = Path("scripts/bang-render.mjs")


class SceneCache:
    """Per-scene picture cache under ``<data>/render-cache/``.

    One MP4 part per scene, named by :func:`_cache_key`. A part is content-addressed: a hit is
    trusted because the key covers every input to the picture (scene bytes, renderer + version,
    theme, geometry, fps). Parts are written atomically — render to a temp name in the same
    directory, then rename — so a crashed run never leaves a half-written file that a later job
    would splice in. The cache never holds audio: parts are picture-only by construction (the
    narration mux happens later, on the merged file), so a hit cannot carry a stale voice.
    """

    EXT = ".mp4"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, key_prefix: str) -> Path:
        # Shard by the first two key chars: one flat directory of thousands of parts makes
        # listings (and some filesystems) slow; a 256-entry fan-out stays cheap.
        return self.root / key_prefix[:2]

    def hit(
        self, key: str, *, width: int, height: int, fps: int, frames: int
    ) -> Path | None:
        """A validated hit, or ``None``.

        Existence is not enough: a truncated or half-written part must be a miss, not pixels
        spliced into a job's video. ffprobe decides — stream geometry must match the storyboard
        and the frame count must match the scene's window (probe counts real frames because
        ``probe_media`` runs with ``-count_frames``). Any probe failure is a miss; the caller
        re-renders and the store overwrites the bad file.
        """
        candidate = self._dir(key) / f"{key}{self.EXT}"
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return None
        try:
            probe = probe_media(candidate)
        except Exception:  # noqa: BLE001 - unreadable part == miss, never a crash
            return None
        videos = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
        if not videos:
            return None
        video = videos[0]
        if int(video.get("width") or 0) != width or int(video.get("height") or 0) != height:
            return None
        raw_frames = video.get("nb_read_frames")
        if raw_frames is not None:
            if int(raw_frames) != frames:
                return None
        else:
            # Frame count unavailable (some builds): duration within one frame is the fallback.
            duration = float((probe.get("format") or {}).get("duration") or 0.0)
            if abs(duration - frames / fps) > 1.0 / fps:
                return None
        return candidate

    def store(self, key: str, src: Path) -> Path:
        """Copy a freshly rendered single-scene file into the cache, atomically."""
        target_dir = self._dir(key)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{key}{self.EXT}"
        tmp = target.with_name(f".{key}{self.EXT}.tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)
        return target


def _concat_list_file(staging: Path, parts: list[Path]) -> Path:
    """The concat demuxer's playlist: `file` directives, absolute paths, single quotes escaped."""
    lines = []
    for part in parts:
        escaped = str(part.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    target = staging / "concat-list.txt"
    target.write_text("\n".join(lines) + "\n", encoding="ascii")
    return target


def concat_parts(parts: list[Path], out_path: Path, *, timeout_s: int = 120) -> None:
    """Stream-copy concatenate same-encoding MP4 parts into one file. One ffmpeg pass."""
    if len(parts) == 1:
        shutil.copyfile(parts[0], out_path)
        return
    playlist = _concat_list_file(out_path.parent, parts)
    argv = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(playlist), "-c", "copy", str(out_path),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed ffmpeg argv, no shell
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg concat timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise RuntimeError(f"ffmpeg concat exited {proc.returncode}: {detail}")
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg concat produced no file at {out_path}")

#: Chrome for Testing, already vendored by Remotion. No second browser on the machine.
CHROME_RELATIVE = (
    Path("node_modules")
    / ".remotion"
    / "chrome-headless-shell"
    / "win64"
    / "chrome-headless-shell-win64"
    / "chrome-headless-shell.exe"
)

#: Skill version recorded in ``RenderArtifact.renderer_version`` for the secondary renderer.
BANG_MOTION_VERSION = "1.19.0+c1aa65e"


def renderer_kind(payload: dict[str, Any]) -> str:
    """Which renderer this job asked for. An unknown value is an error, never a fallback.

    A typo must not silently render with the primary and record a different name: the operator
    would be comparing a video against itself and calling it parity.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"job payload must be an object, got {type(payload).__name__}")
    value = payload.get("renderer", "remotion")
    if not isinstance(value, str) or value not in RENDERERS:
        raise ValueError(
            f"unknown renderer {value!r}; expected one of {', '.join(RENDERERS)}"
        )
    return value


def bang_render_argv(
    *,
    video_dir: Path,
    props_path: Path,
    out_path: Path,
    staging: Path,
    frames: int,
    fps: int,
    timeout_s: int = 900,
) -> list[str]:
    """Build the Node capture argv for the secondary renderer.

    Delegates to ``packages/core/motion/emit.py``, which owns the document and the argument
    contract. The chrome binary and the script are resolved relative to ``packages/video`` so no
    absolute path is hardcoded here.
    """
    from ..motion.emit import build_render_argv as build_motion_argv

    return build_motion_argv(
        props_path=props_path,
        out_path=out_path,
        staging=staging,
        chrome=Path(video_dir) / CHROME_RELATIVE,
        script=Path(video_dir) / BANG_SCRIPT_RELATIVE,
        frames=frames,
        fps=fps,
        wall_clock_s=timeout_s,
    )


def render_bang_motion(
    *,
    video_dir: Path,
    props_path: Path,
    out_path: Path,
    staging: Path,
    frames: int,
    fps: int,
    timeout_s: int = 900,
) -> dict[str, Any]:
    """Run exactly one Node capture subprocess. The second, independent ``packages/video`` edge."""
    argv = bang_render_argv(
        video_dir=video_dir,
        props_path=props_path,
        out_path=out_path,
        staging=staging,
        frames=frames,
        fps=fps,
        timeout_s=timeout_s,
    )
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - argv array, no shell
            argv,
            cwd=str(video_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"bang-motion capture timed out after {timeout_s}s") from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise RuntimeError(f"bang-motion capture exited {proc.returncode}: {tail}")
    return {"elapsed_ms": elapsed_ms, "stdout_tail": (proc.stdout or "").strip()[-1200:]}


def _finalize_render(
    *,
    ctx: Any,
    video_dir: Path,
    out_path: Path,
    renderer: str,
    renderer_version_value: str,
) -> dict[str, Any]:
    """Probe the finished file and stage ``render.json``. Shared by both renderers.

    ``render.json`` is written here and nowhere else, and only after ffprobe has described the
    actual bytes on disk (AGENTS §3 rule 1). A renderer that produces nothing never reaches this
    function, so it cannot produce an artifact either. The payload is staged; the runner
    promotes it together with the video after validation.
    """
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError(f"renderer produced no file at {out_path}")
    probe = probe_media(out_path)
    video_streams = _streams(probe, "video")
    if not video_streams:
        raise RuntimeError("rendered file has no video stream")
    audio_streams = _streams(probe, "audio")
    if len(audio_streams) != 1:
        raise RuntimeError("rendered file must have exactly one narration stream")

    video = video_streams[0]
    storyboard = ctx.store.read_artifact(ctx.job_id, PROPS_NAME)["storyboard"]
    duration_ms = _duration_ms(probe)
    artifact = RenderArtifact(
        src=VIDEO_NAME,
        sha256=sha256_file(out_path),
        bytes=out_path.stat().st_size,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=int(round(_fps(video) or 0)),
        frames=int(_frames(video) or 0),
        duration_ms=int(round(duration_ms or 0)),
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=(str(audio_streams[0].get("codec_name")) if audio_streams else None),
        pix_fmt=str(video.get("pix_fmt") or ""),
        renderer=renderer,  # type: ignore[arg-type]
        renderer_version=renderer_version_value,
        scene_hashes=_scene_hashes(storyboard),
    )
    payload = artifact.model_dump()
    validate_artifact(RenderArtifact, payload)
    ctx.write_artifact(RENDER_NAME, payload)
    ctx.stage_file(VIDEO_NAME, out_path)
    return payload


def _render_remotion(
    *,
    video_dir: Path,
    props_path: Path,
    raw_path: Path,
    timeout_s: int,
) -> None:
    cli = Path(video_dir) / CLI_RELATIVE
    if not cli.is_file():
        raise RuntimeError(f"Remotion CLI missing at {cli}; run npm install --prefix packages/video")
    render_storyboard(
        video_dir=Path(video_dir),
        props_path=props_path,
        out_path=raw_path,
        timeout_s=timeout_s,
    )


def _render_bang(
    *,
    video_dir: Path,
    props_path: Path,
    raw_path: Path,
    staging: Path,
    frames: int,
    fps: int,
    timeout_s: int,
) -> None:
    script = Path(video_dir) / BANG_SCRIPT_RELATIVE
    if not script.is_file():
        raise RuntimeError(f"bang-motion driver missing at {script}")
    chrome = Path(video_dir) / CHROME_RELATIVE
    if not chrome.is_file():
        raise RuntimeError(
            f"chrome-headless-shell missing at {chrome}; run `npx remotion browser ensure`"
        )
    render_bang_motion(
        video_dir=Path(video_dir),
        props_path=props_path,
        out_path=raw_path,
        staging=staging,
        frames=frames,
        fps=fps,
        timeout_s=timeout_s,
    )


def build_render_stage(
    state: Any, *, video_dir: Path, renderer: str = "remotion", timeout_s: int = 900
) -> Stage:
    """The RENDERING stage: render, prove it with ffprobe, then and only then write render.json.

    The renderer is passed in from the job payload (``remotion`` by default, ``bang-motion``
    optional). An unknown value is refused before any subprocess is reachable, so a typo cannot
    quietly render with the primary and record a different name. Both paths converge on
    ``_finalize_render``: same probe, same artifact, same gate.
    """
    renderer = renderer_kind({"renderer": renderer})
    from ..orchestration.runner import Stage, StageContext, StageError, StageOutcome

    store = state.store

    def run(ctx: StageContext) -> StageOutcome:
        job_id = ctx.job_id
        from ..orchestration.pipeline import _emit  # local import: pipeline imports runner

        _emit(state, job_id, JobState.RENDERING.value, "stage_started", "RenderAgent mulai",
              agent=RENDER_AGENT)
        job_dir = Path(store.job_dir(job_id))
        # The finished video and its raw intermediate are run-owned staging: canonical
        # output.mp4 appears only when the runner promotes after validation.
        out_path = ctx.alloc(VIDEO_NAME).resolve()
        raw_video_path = ctx.alloc(RAW_VIDEO_NAME).resolve()
        staging = (job_dir / ".motion-staging").resolve()
        narration_path = (job_dir / "narration.wav").resolve()

        try:
            props_path = write_render_props(store, job_id)
            storyboard = store.read_artifact(job_id, PROPS_NAME)["storyboard"]
            frames = sum(int(scene["durationInFrames"]) for scene in storyboard["scenes"])
            fps = int(storyboard.get("fps") or 30)

            renderer_version_value = (
                renderer_version(Path(video_dir)) if renderer == "remotion" else BANG_MOTION_VERSION
            )
            # `storyboard` IS the timed doc (props_path is update_storyboard_from_audio's
            # output), so hashes over it change when narration timing moves and a cache key can
            # never serve a stale-timing picture.
            hashes = _scene_hashes(storyboard)
            # Cache applies to the remotion path only: bang-motion captures from frame 0 for N
            # frames (no start offset), so it cannot render one scene's window. bang keeps the
            # legacy whole-document render, unchanged.
            cacheable = renderer == "remotion"
            # The cache lives beside the jobs tree (jobs_dir = <root>/jobs), so test stores and
            # real installs both get it with zero configuration: no settings object required.
            cache = SceneCache(state.store.jobs_dir.parent / "render-cache")
            # One key per scene: env tail is spelled out because a `**dict` unpack is opaque
            # to mypy --strict, and the key's inputs are exactly this function's contract.
            keys = {
                scene_id: _cache_key(
                    scene_hash=scene_hash,
                    renderer=renderer,
                    renderer_version_value=renderer_version_value,
                    theme=json.dumps(
                        storyboard.get("theme") or {},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    total_frames=frames,
                    watermark=str((storyboard.get("watermark") or {}).get("text") or ""),
                    width=int(storyboard.get("width") or 0),
                    height=int(storyboard.get("height") or 0),
                    fps=fps,
                )
                for scene_id, scene_hash in hashes.items()
            }

            if not cacheable:
                # bang-motion: single full-render pass, exactly as before the cache existed.
                _render_bang(
                    video_dir=Path(video_dir),
                    props_path=props_path,
                    raw_path=raw_video_path,
                    staging=staging,
                    frames=frames,
                    fps=fps,
                    timeout_s=timeout_s,
                )
            else:
                parts: list[Path] = []
                misses: list[dict[str, Any]] = []
                for scene in storyboard["scenes"]:
                    scene_id = str(scene["sceneId"])
                    hit = cache.hit(
                        keys[scene_id],
                        width=int(storyboard.get("width") or 0),
                        height=int(storyboard.get("height") or 0),
                        fps=fps,
                        frames=int(scene["durationInFrames"]),
                    )
                    if hit is not None:
                        parts.append(hit)
                        continue
                    misses.append(scene)

                if misses:
                    # One picture-only run per missing scene: same full props, a `--frames=s-e`
                    # window on the scene's own range. Pixel-identical to those frames of a full
                    # render (same composition, same props), and no sliced-props surgery to get
                    # wrong. Each fresh part is stored in the cache; its stored copy is what gets
                    # spliced, so hits and misses splice from one identical source.
                    staging.mkdir(parents=True, exist_ok=True)
                    for scene in misses:
                        scene_id = str(scene["sceneId"])
                        start = int(scene["startFrame"])
                        scene_frames = int(scene["durationInFrames"])
                        scene_raw = staging / f"scene-{scene_id}.mp4"
                        render_storyboard(
                            video_dir=Path(video_dir),
                            props_path=props_path,
                            out_path=scene_raw,
                            frames=(start, start + scene_frames - 1),
                            timeout_s=timeout_s,
                        )
                        if not scene_raw.is_file() or scene_raw.stat().st_size == 0:
                            raise RuntimeError(f"renderer produced no scene file for {scene_id}")
                        parts.append(cache.store(keys[scene_id], scene_raw))
                        scene_raw.unlink(missing_ok=True)
                # Hits and fresh parts are both in `parts`, scene order; one concat pass
                # (single part = straight copy) rebuilds the timeline.
                concat_parts(list(parts), raw_video_path)

            if not raw_video_path.is_file() or raw_video_path.stat().st_size == 0:
                raise RuntimeError(f"renderer produced no file at {raw_video_path}")
            if not narration_path.is_file() or narration_path.stat().st_size == 0:
                raise RuntimeError(f"audio stage produced no narration at {narration_path}")
            mux_narration(raw_video_path, narration_path, out_path, timeout_s=min(timeout_s, 120))

            payload_out = _finalize_render(
                ctx=ctx,
                video_dir=Path(video_dir),
                out_path=out_path,
                renderer=renderer,
                renderer_version_value=(
                    renderer_version(Path(video_dir))
                    if renderer == "remotion"
                    else BANG_MOTION_VERSION
                ),
            )
        except Exception as exc:  # noqa: BLE001 - any render failure is a stage failure
            raw_video_path.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)
            detail = redact(f"{type(exc).__name__}: {exc}", limit=400)
            _emit(state, job_id, JobState.RENDERING.value, "failed", detail, agent=RENDER_AGENT)
            raise StageError("render_failed", detail, retryable=True) from exc
        finally:
            raw_video_path.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)

        _emit(
            state,
            job_id,
            JobState.RENDERING.value,
            "stage_completed",
            f"RenderAgent selesai ({payload_out['renderer']})",
            agent=RENDER_AGENT,
            progress=1.0,
        )
        return StageOutcome(ok=True, artifacts=[VIDEO_NAME, RENDER_NAME])

    return Stage(
        name="RenderAgent",
        state=JobState.RENDERING,
        produces=(VIDEO_NAME, RENDER_NAME),
        run=run,
    )


__all__ = [
    "BANG_MOTION_VERSION",
    "RENDERERS",
    "bang_render_argv",
    "build_render_stage",
    "free_tcp_port",
    "mux_argv",
    "mux_narration",
    "probe_media",
    "render_argv",
    "render_bang_motion",
    "render_storyboard",
    "renderer_kind",
    "renderer_version",
    "sha256_file",
    "update_storyboard_from_audio",
    "validate_render",
    "write_render_props",
]
