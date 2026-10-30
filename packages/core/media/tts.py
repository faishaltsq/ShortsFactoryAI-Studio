"""Offline Windows narration, subtitle timing, and ffmpeg audio argv builders."""

from __future__ import annotations

import array
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..contracts.artifacts import AssetsArtifact, AudioArtifact
from ..contracts.base import validate_artifact
from ..contracts.scene import SubtitleCue
from ..contracts.state import JobState
from ..security.redact import redact
from .render import probe_media

if TYPE_CHECKING:
    from ..orchestration.runner import Stage

STDERR_LIMIT = 1200
DEFAULT_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sapi_tts.ps1"
ASSETS_NAME = "assets.json"
AUDIO_NAME = "audio.json"
NARRATION_NAME = "narration.wav"
ASSET_AGENT = "AssetAgent"
AUDIO_AGENT = "AudioAgent"

#: SAPI appends ~750 ms of digital silence after the last word, and every scene WAV inherits it.
#: That tail used to become scene duration, narration duration, and subtitle lifetime, so a
#: caption lingered over pure silence. Speech extent is measured from the PCM instead and each
#: scene is trimmed to a deliberate pad: enough lead-in that the first consonant is not clipped,
#: enough tail that the last one is not either.
SILENCE_FLOOR_DB = -60.0
SCENE_LEAD_IN_MS = 120
SCENE_TAIL_MS = 150

#: The declared narration loudness target. ``DATA_CONTRACTS.md`` §8 says the narration-only mix is
#: loudness-normalised; -16 LUFS with a -1.5 dBTP ceiling is that promise, and the audio stage now
#: proves it on the file it hands to the mux instead of accepting -18 ±2.
NARRATION_TARGET_LUFS = -16.0
NARRATION_LOUDNESS_TOLERANCE = 0.5
NARRATION_TRUE_PEAK_MAX_DBTP = -1.5

#: Raw SAPI speech has a peak-to-loudness ratio near 20 dB. Reaching -16 LUFS under a -1.5 dBTP
#: ceiling needs a PLR of at most 14.5 dB, so plain gain cannot get there without clipping — the
#: crest factor has to come down first. This is a deliberately gentle compressor: 0.3 ms attack
#: and 10 ms release so it only acts on the plosive peaks that would otherwise be the ceiling,
#: with a soft knee so it does not gate the quiet tail of a word.
NARRATION_COMPRESSOR = "acompressor=threshold=-20dB:ratio=12:attack=0.3:release=10:knee=1:makeup=1"
#: Brickwall ceiling at -2 dBFS, i.e. 0.5 dB of headroom under the -1.5 dBTP promise.
NARRATION_LIMITER = "alimiter=limit=0.794328:level=disabled:attack=0.1:release=50"


@dataclass(frozen=True)
class PcmFormat:
    """The parts of a WAV header that decide whether the mux can use the file as-is."""

    channels: int
    sample_width: int
    sample_rate: int
    frames: int

    @property
    def duration_ms(self) -> float:
        return self.frames / self.sample_rate * 1000.0


@dataclass(frozen=True)
class SpeechExtent:
    """Where real audio starts and stops in a WAV, measured at ``SILENCE_FLOOR_DB``."""

    onset_ms: float
    offset_ms: float
    duration_ms: float

    @property
    def speech_ms(self) -> float:
        return self.offset_ms - self.onset_ms


@dataclass(frozen=True)
class SceneTrim:
    """One scene WAV trimmed to its measured speech extent plus the declared pad."""

    path: Path
    start_frame: int
    end_frame: int
    sample_rate: int
    extent: SpeechExtent

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame

    @property
    def duration_ms(self) -> float:
        return self.frames / self.sample_rate * 1000.0

    @property
    def window_start_ms(self) -> float:
        return self.start_frame / self.sample_rate * 1000.0


@dataclass(frozen=True)
class Loudness:
    """One EBU R128 measurement: what the file measures, not what was asked for.

    ``integrated`` is always reported. ``true_peak`` and ``range`` are optional because loudnorm
    omits them from some diagnostics, and inventing a value for a number ffmpeg did not measure is
    exactly the kind of claim this module refuses to make.
    """

    integrated: float
    true_peak: float | None = None
    range: float | None = None


@dataclass(frozen=True)
class WordBoundary:
    text: str
    start_ms: int
    end_ms: int

    def __init__(self, text: str, start_ms: int, end_ms: int) -> None:
        if not text or start_ms < 0 or end_ms <= start_ms:
            raise ValueError("word boundary needs text and increasing non-negative times")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "start_ms", start_ms)
        object.__setattr__(self, "end_ms", end_ms)


def _audio_duration_ms(probe: dict[str, Any]) -> int:
    streams = probe.get("streams", [])
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(audio) != 1 or audio[0].get("codec_name") != "pcm_s16le":
        raise RuntimeError("SAPI output must contain exactly one PCM s16le audio stream")
    try:
        return round(float(probe["format"]["duration"]) * 1000)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("ffprobe did not report the SAPI WAV duration") from exc


def read_pcm_format(path: Path) -> PcmFormat:
    """Read a WAV header. A file that is not integer PCM is an error, not something to resample."""
    with wave.open(str(path), "rb") as wav:
        if wav.getcomptype() != "NONE":
            raise RuntimeError(f"{path.name} is compressed; narration must be uncompressed PCM")
        return PcmFormat(
            channels=wav.getnchannels(),
            sample_width=wav.getsampwidth(),
            sample_rate=wav.getframerate(),
            frames=wav.getnframes(),
        )


def _pcm_samples(path: Path) -> tuple[PcmFormat, array.array[int]]:
    with wave.open(str(path), "rb") as wav:
        if wav.getcomptype() != "NONE":
            raise RuntimeError(f"{path.name} is compressed; narration must be uncompressed PCM")
        if wav.getsampwidth() != 2:
            raise RuntimeError(f"{path.name} is not 16-bit PCM; sample measurement needs s16")
        fmt = PcmFormat(
            channels=wav.getnchannels(),
            sample_width=wav.getsampwidth(),
            sample_rate=wav.getframerate(),
            frames=wav.getnframes(),
        )
        samples = array.array("h")
        samples.frombytes(wav.readframes(fmt.frames))
    if sys.byteorder == "big":
        samples.byteswap()
    return fmt, samples


def measure_speech_extent(path: Path, *, floor_db: float = SILENCE_FLOOR_DB) -> SpeechExtent:
    """Measure where real audio starts and stops in one PCM WAV.

    SAPI's ``SpeakProgress`` offsets stop before the trailing silence it appends, so they cannot
    answer this question: the tail is appended by the synthesizer after the last word boundary is
    reported. The samples can. Every channel is reduced to its loudest absolute value so a
    channel that happens to be quiet does not look like silence.
    """
    fmt, samples = _pcm_samples(path)
    if fmt.frames == 0:
        raise RuntimeError(f"{path.name} contains no audio frames")
    threshold = int(round(32767 * 10 ** (floor_db / 20.0)))
    channels = fmt.channels
    onset: int | None = None
    offset: int | None = None
    for frame in range(fmt.frames):
        base = frame * channels
        peak = max(abs(sample) for sample in samples[base : base + channels])
        if peak >= threshold:
            if onset is None:
                onset = frame
            offset = frame
    if onset is None or offset is None:
        raise RuntimeError(f"{path.name} is silent at or below {floor_db:.0f} dBFS")
    return SpeechExtent(
        onset_ms=onset / fmt.sample_rate * 1000.0,
        offset_ms=(offset + 1) / fmt.sample_rate * 1000.0,
        duration_ms=fmt.duration_ms,
    )


def trim_scene_wav(
    source: Path,
    target: Path,
    *,
    lead_ms: float = SCENE_LEAD_IN_MS,
    tail_ms: float = SCENE_TAIL_MS,
    floor_db: float = SILENCE_FLOOR_DB,
) -> SceneTrim:
    """Copy the speech window plus a deliberate pad into ``target``, sample-exact.

    The window is computed in frames from the measured extent, so ``target`` is a whole number of
    frames and its duration is reproducible without re-probing.
    """
    fmt, samples = _pcm_samples(source)
    extent = measure_speech_extent(source, floor_db=floor_db)
    start = max(0, int(round((extent.onset_ms - lead_ms) / 1000.0 * fmt.sample_rate)))
    end = min(fmt.frames, int(round((extent.offset_ms + tail_ms) / 1000.0 * fmt.sample_rate)))
    if end <= start:
        raise RuntimeError(f"{source.name} has no trimmable speech window")
    with wave.open(str(target), "wb") as out:
        out.setnchannels(fmt.channels)
        out.setsampwidth(fmt.sample_width)
        out.setframerate(fmt.sample_rate)
        out.setcomptype("NONE", "not compressed")
        out.writeframes(samples[start * fmt.channels : end * fmt.channels].tobytes())
    return SceneTrim(
        path=target,
        start_frame=start,
        end_frame=end,
        sample_rate=fmt.sample_rate,
        extent=extent,
    )


def rebase_boundaries(
    words: list[WordBoundary],
    trim: SceneTrim,
    *,
    duration_ms: int,
) -> list[WordBoundary]:
    """Shift SAPI word boundaries onto the trimmed timeline, then clamp them to the speech.

    The audio is ground truth. SAPI reports the last word's end as the raw file duration, which
    includes the tail it appended, so a cue built from that boundary would linger over silence even
    after the trim. Boundaries are therefore clamped to the *measured speech offset*, not to the
    trim window: the trailing pad exists for the listener's ear, not for a caption. Boundaries that
    collapse to nothing are dropped rather than emitted as zero-length cues.
    """
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    shift = trim.window_start_ms
    speech_end_ms = min(duration_ms, int(round(trim.extent.offset_ms - shift)))
    if speech_end_ms <= 0:
        raise RuntimeError(f"{trim.path.name} has no speech inside its trimmed window")
    shifted: list[WordBoundary] = []
    for word in words:
        start = min(max(int(round(word.start_ms - shift)), 0), speech_end_ms)
        end = min(max(int(round(word.end_ms - shift)), 0), speech_end_ms)
        if end <= start:
            continue
        if shifted and start < shifted[-1].end_ms:
            start = shifted[-1].end_ms
            if end <= start:
                continue
        shifted.append(WordBoundary(word.text, start, end))
    return shifted


VOICE_MAX_LENGTH = 100


def _validate_voice(voice: str) -> str:
    """Reject a selector PowerShell could read as an option or a second argument."""
    if not voice or voice != voice.strip() or len(voice) > VOICE_MAX_LENGTH:
        raise ValueError("voice must be a non-empty trimmed selector of at most 100 characters")
    if voice.startswith("-") or any(character in voice for character in '"\'\r\n\t'):
        raise ValueError("voice must be an installed voice name or 'system-default'")
    return voice


def parse_boundaries(raw: Any, *, duration_ms: int) -> list[WordBoundary]:
    """Type the SAPI boundaries, dropping the ones narration cannot contain."""
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise RuntimeError("SAPI boundaries must be a JSON list")
    words: list[WordBoundary] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item["startMs"])
            end = min(int(item["endMs"]), duration_ms)
        except (KeyError, TypeError, ValueError):
            continue
        text = str(item.get("text") or "")
        if not text or start < 0 or end <= start:
            continue
        words.append(WordBoundary(text, start, end))
    if not words:
        raise RuntimeError("SAPI returned no usable word boundaries")
    return words


def synthesize_sapi(
    text: str,
    output_path: Path,
    *,
    voice: str,
    timeout_s: int = 90,
    script_path: Path = DEFAULT_SCRIPT,
) -> tuple[list[WordBoundary], int]:
    """Write one PCM WAV with SAPI's own boundaries. Narration travels through a UTF-8 file.

    The returned duration is the raw file length, which includes the trailing silence SAPI appends
    after the last word — roughly 750 ms, measured on this host. It is returned so a caller can see
    the discrepancy, not so a caller can trust it: scene timing must come from
    :func:`measure_speech_extent`, because SAPI reports no boundary for audio it has not spoken yet.
    """
    if not text.strip():
        raise ValueError("narration text is empty")
    _validate_voice(voice)
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("Windows PowerShell is not on PATH")
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    boundary_path = output_path.with_suffix(".words.json")
    text_fd, raw_text_path = tempfile.mkstemp(prefix="narration-", suffix=".txt", dir=output_path.parent)
    os.close(text_fd)
    text_path = Path(raw_text_path)
    text_path.write_text(text, encoding="utf-8")
    argv = [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(Path(script_path).resolve()),
        str(text_path),
        str(output_path),
        str(boundary_path),
        voice,
    ]
    try:
        try:
            proc = subprocess.run(  # noqa: S603 - fixed script and argv array, no shell
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"SAPI synthesis timed out after {timeout_s}s") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "SAPI synthesis failed").strip()[-STDERR_LIMIT:]
            raise RuntimeError(f"SAPI synthesis exited {proc.returncode}: {detail}")
        if not output_path.is_file() or output_path.stat().st_size == 0 or not boundary_path.is_file():
            raise RuntimeError("SAPI synthesis produced incomplete outputs")
        duration_ms = _audio_duration_ms(probe_media(output_path))
        raw = json.loads(boundary_path.read_text(encoding="utf-8-sig"))
        words = parse_boundaries(raw, duration_ms=duration_ms)
        group_subtitles(words, duration_ms=duration_ms)
        return words, duration_ms
    except Exception:
        output_path.unlink(missing_ok=True)
        boundary_path.unlink(missing_ok=True)
        raise
    finally:
        text_path.unlink(missing_ok=True)


def group_subtitles(
    words: list[WordBoundary], *, duration_ms: int, max_chars: int = 42
) -> list[SubtitleCue]:
    """Group ordered word timings into readable punctuation-aware subtitle cues."""
    if duration_ms < 0 or max_chars < 1:
        raise ValueError("duration_ms and max_chars must be positive")
    previous_end = -1
    for word in words:
        if word.start_ms < previous_end or word.end_ms > duration_ms:
            raise ValueError("word boundaries must be ordered and inside narration duration")
        previous_end = word.end_ms

    cues: list[SubtitleCue] = []
    group: list[WordBoundary] = []
    for word in words:
        candidate = " ".join([*(item.text for item in group), word.text])
        if group and len(candidate) > max_chars:
            cues.append(_cue(group))
            group = []
        group.append(word)
        if word.text.rstrip().endswith((".", "!", "?", ";", ":")):
            cues.append(_cue(group))
            group = []
    if group:
        cues.append(_cue(group))
    return cues


def _cue(words: list[WordBoundary]) -> SubtitleCue:
    return SubtitleCue(startMs=words[0].start_ms, endMs=words[-1].end_ms, text=" ".join(word.text for word in words))


def build_normalise_argv(
    narration_path: Path,
    output_path: Path,
    *,
    gain_db: float,
) -> list[str]:
    """Build the narration-only argv that lands the file on ``NARRATION_TARGET_LUFS``.

    A fixed ``loudnorm`` pass is not enough. Measured on real SAPI output, single-pass loudnorm
    with ``I=-16:TP=-1.5`` delivered -18.0 LUFS: the true-peak ceiling, not the loudness target,
    is what binds, because raw speech has a peak-to-loudness ratio near 20 dB and -16 LUFS under a
    -1.5 dBTP ceiling needs at most 14.5 dB. Two-pass loudnorm with the measured values made no
    difference — it selects the same dynamic mode. The chain therefore reduces the crest factor
    first, then applies a gain the caller measured from the actual output of this exact chain, then
    brickwalls at -2 dBFS. Every element is an argv entry; nothing is a shell string.
    """
    filters = ",".join(
        (NARRATION_COMPRESSOR, f"volume={gain_db:.2f}dB", NARRATION_LIMITER)
    )
    return [
        "ffmpeg", "-y", "-i", str(narration_path),
        "-af", filters,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(output_path),
    ]


def build_mix_argv(
    narration_path: Path,
    output_path: Path,
    *,
    music_path: Path | None = None,
    music_gain_db: float = -18.0,
    gain_db: float = 0.0,
) -> list[str]:
    """Build the narration-only normalisation or a real music ducking mix.

    ``gain_db`` is the measured gain from :func:`normalise_narration`; with music present it is
    applied to the narration leg before the duck, so the music is not lifted with it.
    """
    if music_path is None:
        return build_normalise_argv(narration_path, output_path, gain_db=gain_db)
    narration_chain = f"[0:a]{NARRATION_COMPRESSOR},volume={gain_db:.2f}dB[voice]"
    music_chain = f"[1:a]volume={music_gain_db}dB[music]"
    duck = "[music][voice]sidechaincompress=threshold=0.03:ratio=10[ducked]"
    mix = f"[voice][ducked]amix=inputs=2:duration=first,{NARRATION_LIMITER}[out]"
    return [
        "ffmpeg", "-y", "-i", str(narration_path), "-i", str(music_path),
        "-filter_complex", f"{narration_chain};{music_chain};{duck};{mix}",
        "-map", "[out]",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(output_path),
    ]


def parse_loudness_lufs(log: str) -> float:
    """Extract loudnorm's measured integrated loudness from its JSON diagnostic."""
    return parse_loudness(log).integrated


def _optional_float(value: Any) -> float | None:
    """``float(value)`` or ``None``. loudnorm writes numbers as strings and sometimes omits them."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_loudness(log: str) -> Loudness:
    """Extract every measured value loudnorm reports. The last block wins.

    ``loudnorm`` prints one diagnostic per run; a chain that contains it twice would otherwise let
    the first block's numbers masquerade as the result.
    """
    decoder = json.JSONDecoder()
    measured: Loudness | None = None
    for index, character in enumerate(log):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(log[index:])
            measured = Loudness(
                integrated=float(payload["input_i"]),
                true_peak=_optional_float(payload.get("input_tp")),
                range=_optional_float(payload.get("input_lra")),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    if measured is None:
        raise RuntimeError("ffmpeg loudnorm did not report input_i")
    return measured


def measure_loudness(path: Path, *, timeout_s: int = 90) -> Loudness:
    """Measure one file with EBU R128. Reports what the file is, not what was requested."""
    argv = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed ffmpeg argv, no shell
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg loudness measurement timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-STDERR_LIMIT:]
        raise RuntimeError(f"ffmpeg loudness measurement exited {proc.returncode}: {detail}")
    return parse_loudness(f"{proc.stderr or ''}\n{proc.stdout or ''}")


def measure_loudness_lufs(path: Path, *, timeout_s: int = 90) -> float:
    return measure_loudness(path, timeout_s=timeout_s).integrated


def normalise_narration(
    source: Path,
    target: Path,
    *,
    timeout_s: int = 90,
    max_passes: int = 4,
) -> Loudness:
    """Drive ``source`` to ``NARRATION_TARGET_LUFS`` and return the measured result.

    The gain is not guessed from the input: it is closed over the output of the exact chain that
    ships. A compressor whose makeup gain is not flat means input loudness does not predict output
    loudness, so each pass renders, measures, and corrects. The loop stops when the measurement is
    inside tolerance, and the caller still re-measures the file it hands to the mux.
    """
    if not source.is_file():
        raise RuntimeError(f"normalisation source {source} does not exist")
    gain_db = 0.0
    measured = Loudness(integrated=0.0, true_peak=None, range=None)
    for _ in range(max_passes):
        _run_audio_argv(
            build_normalise_argv(source, target, gain_db=gain_db), timeout_s=timeout_s
        )
        measured = measure_loudness(target, timeout_s=timeout_s)
        error = NARRATION_TARGET_LUFS - measured.integrated
        peak = measured.true_peak
        if peak is None:
            raise RuntimeError("ffmpeg did not report a true peak, so the ceiling cannot be proven")
        if abs(error) <= NARRATION_LOUDNESS_TOLERANCE / 2 and peak <= NARRATION_TRUE_PEAK_MAX_DBTP:
            return measured
        # Never buy loudness with true peak: the correction is capped by the headroom that is left.
        gain_db += min(error, NARRATION_TRUE_PEAK_MAX_DBTP - 0.1 - peak)
    peak = measured.true_peak
    detail = "no true peak reported" if peak is None else f"{peak:+.2f} dBTP"
    raise RuntimeError(
        f"narration normalisation did not reach {NARRATION_TARGET_LUFS:+.1f} ± "
        f"{NARRATION_LOUDNESS_TOLERANCE:.1f} LUFS: measured {measured.integrated:+.2f} LUFS "
        f"at {detail} after {max_passes} passes"
    )


def _sha256_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_asset_stage(state: Any, *, video_dir: Path) -> Stage:
    """Record only built-in Maya source bytes that really exist in packages/video."""
    from ..orchestration.runner import Stage, StageContext, StageError, StageOutcome

    source = Path(video_dir) / "src"
    rig_paths = [
        source / "character" / "rig.ts",
        source / "character" / "assets" / "maya" / "manifest.ts",
        source / "character" / "assets" / "maya" / "art.ts",
    ]
    palette_path = source / "art" / "palette.ts"

    def run(ctx: StageContext) -> StageOutcome:
        job_id = ctx.job_id
        from ..orchestration.pipeline import _emit

        _emit(state, job_id, JobState.ASSETS_READY.value, "stage_started", "AssetAgent mulai", agent=ASSET_AGENT)
        try:
            missing = [str(path) for path in [*rig_paths, palette_path] if not path.is_file()]
            if missing:
                raise RuntimeError("built-in Maya source missing: " + ", ".join(missing))
            artifact = AssetsArtifact(
                characters=[{
                    "id": "maya",
                    "rig_hash": _sha256_paths(rig_paths),
                    "palette_hash": _sha256_paths([palette_path]),
                    "poses": [],
                    "expressions": [],
                }],
                backgrounds=[],
                audio=[],
            )
            payload = artifact.model_dump()
            payload["manifest_sha256"] = hashlib.sha256(
                json.dumps(payload["characters"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            validate_artifact(AssetsArtifact, payload)
            ctx.write_artifact(ASSETS_NAME, payload)
        except Exception as exc:
            detail = redact(f"{type(exc).__name__}: {exc}", limit=400)
            _emit(state, job_id, JobState.ASSETS_READY.value, "failed", detail, agent=ASSET_AGENT)
            raise StageError("asset_failed", detail, retryable=False) from exc
        _emit(state, job_id, JobState.ASSETS_READY.value, "stage_completed", "AssetAgent selesai", agent=ASSET_AGENT, progress=1.0)
        return StageOutcome(ok=True, artifacts=[ASSETS_NAME])

    return Stage(name=ASSET_AGENT, state=JobState.ASSETS_READY, produces=(ASSETS_NAME,), run=run, contract=AssetsArtifact, contract_artifact=ASSETS_NAME)


def _concat_pcm_wavs(inputs: list[Path], output: Path) -> None:
    if not inputs:
        raise ValueError("at least one scene WAV is required")
    with wave.open(str(inputs[0]), "rb") as first:
        params = first.getparams()
        audio_format = (first.getnchannels(), first.getsampwidth(), first.getframerate(), first.getcomptype())
    with wave.open(str(output), "wb") as target:
        target.setparams(params)
        for path in inputs:
            with wave.open(str(path), "rb") as source:
                source_format = (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype())
                if source_format != audio_format:
                    raise RuntimeError("scene WAV formats do not match")
                while chunk := source.readframes(8192):
                    target.writeframesraw(chunk)


def _run_audio_argv(argv: list[str], *, timeout_s: int) -> None:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed ffmpeg argv, no shell
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s, check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg audio operation timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-STDERR_LIMIT:]
        raise RuntimeError(f"ffmpeg audio operation exited {proc.returncode}: {detail}")


def _clamp_cues(cues: list[SubtitleCue], *, duration_ms: int) -> list[SubtitleCue]:
    """Drop cues that fall outside the narration and pull the rest back inside it."""
    clamped: list[SubtitleCue] = []
    for cue in cues:
        start = min(cue.startMs, duration_ms)
        end = min(cue.endMs, duration_ms)
        if end <= start:
            continue
        clamped.append(SubtitleCue(startMs=start, endMs=end, text=cue.text))
    return clamped


def scene_timings(frame_lengths: list[int], sample_rate: int) -> list[tuple[int, int]]:
    """Turn trimmed scene frame counts into integer millisecond boundaries.

    Boundaries come from the cumulative frame position, not from a running sum of rounded
    durations: rounding each scene independently drifts, and after three scenes the last boundary
    no longer matches the concatenated file. The final ``endMs`` is exactly the narration length
    the frames say it is.
    """
    if not frame_lengths or sample_rate <= 0:
        raise ValueError("scene frame lengths and a positive sample rate are required")
    boundaries: list[tuple[int, int]] = []
    cursor = 0
    for frames in frame_lengths:
        if frames <= 0:
            raise ValueError("a scene trimmed to zero frames")
        start_ms = round(cursor / sample_rate * 1000)
        cursor += frames
        end_ms = round(cursor / sample_rate * 1000)
        if end_ms <= start_ms:
            raise ValueError("a scene is shorter than one millisecond")
        boundaries.append((start_ms, end_ms))
    return boundaries


def reconcile_timings(
    timings: list[tuple[int, int]], *, duration_ms: int, tolerance_ms: int = 2
) -> list[tuple[int, int]]:
    """Make the last scene boundary equal the probed narration length.

    ``scene_timings`` derives boundaries from frame counts; ``narration.durationMs`` is what
    ffprobe measured on the encoded file. Those disagree by a millisecond or two because ffprobe
    reports a rounded duration, and the contract requires the timings to end exactly at the
    declared length. A disagreement inside ``tolerance_ms`` is absorbed by the final boundary; a
    larger one means the arithmetic and the audio describe different files, so it raises.
    """
    if not timings:
        raise ValueError("at least one scene timing is required")
    if duration_ms <= 0:
        raise ValueError("narration duration must be positive")
    start, end = timings[-1]
    drift = duration_ms - end
    if abs(drift) > tolerance_ms:
        raise ValueError(
            f"scene timings end at {end} ms but narration duration is {duration_ms} ms"
        )
    adjusted_end = end + drift
    if adjusted_end <= start:
        raise ValueError("reconciled last scene would have no duration")
    return [*timings[:-1], (start, adjusted_end)]


def build_audio_stage(state: Any, *, timeout_s: int = 90) -> Stage:
    """Synthesize each segment, trim it to its measured speech, then mux a true -16 LUFS track.

    The order matters. SAPI's word boundaries describe where words start, and they stop before the
    ~750 ms of silence the synthesizer appends, so they cannot be used to decide how long a scene
    is. Each scene WAV is measured from its samples, trimmed to ``SCENE_LEAD_IN_MS`` +
    speech + ``SCENE_TAIL_MS``, and only then concatenated. Scene boundaries, narration duration
    and subtitle cue ends all come from those trimmed frame counts, so no caption can outlive the
    speech it belongs to.
    """
    from ..orchestration.runner import Stage, StageContext, StageError, StageOutcome

    def run(ctx: StageContext) -> StageOutcome:
        store, job_id = ctx.store, ctx.job_id
        from ..orchestration.pipeline import _emit

        _emit(state, job_id, JobState.AUDIO_READY.value, "stage_started", "AudioAgent mulai", agent=AUDIO_AGENT)
        job_dir = Path(store.job_dir(job_id))
        raw_path = job_dir / ".narration.raw.wav"
        narration_path = ctx.alloc(NARRATION_NAME)
        scratch: list[Path] = []
        try:
            job = store.get(job_id)
            voice = str(job.payload.get("voice") or "")
            if not voice or "Neural" in voice:
                voice = "system-default"
            script = store.read_artifact(job_id, "script.json")
            storyboard = store.read_artifact(job_id, "storyboard.json")
            script_segs = [item for item in script.get("segments", []) if isinstance(item, dict)]
            segments: dict[Any, str] = {}
            for i, item in enumerate(script_segs):
                sid = item.get("id")
                t = str(item.get("text") or "")
                if sid is not None:
                    segments[sid] = t
                    segments[str(sid)] = t
                    if str(sid).isdigit():
                        segments[f"s{sid}"] = t
                segments[f"s{i + 1}"] = t
                segments[str(i + 1)] = t
                segments[i] = t
            scene_ids: list[str] = []
            trims: list[SceneTrim] = []
            scene_words: list[list[WordBoundary]] = []
            for index, scene in enumerate(storyboard.get("scenes", [])):
                scene_id = str(scene.get("sceneId") or "")
                segment_id = scene.get("segment")
                text = segments.get(segment_id)
                if (not text or not str(text).strip()) and index < len(script_segs):
                    text = script_segs[index].get("text")
                if not scene_id or not isinstance(text, str) or not text.strip():
                    raise RuntimeError(f"scene {scene_id or index!r} has no script text for segment {segment_id!r}")
                raw_scene = job_dir / f".narration-scene-{index + 1}.raw.wav"
                trimmed_scene = job_dir / f".narration-scene-{index + 1}.wav"
                scratch.extend((raw_scene, trimmed_scene, raw_scene.with_suffix(".words.json")))
                words, _ = synthesize_sapi(text, raw_scene, voice=voice, timeout_s=timeout_s)
                trim = trim_scene_wav(raw_scene, trimmed_scene)
                scene_ids.append(scene_id)
                trims.append(trim)
                scene_words.append(words)
            if not trims:
                raise RuntimeError("storyboard has no scenes to narrate")
            sample_rates = {trim.sample_rate for trim in trims}
            if len(sample_rates) != 1:
                raise RuntimeError("scene WAVs were synthesized at different sample rates")
            sample_rate = sample_rates.pop()
            boundaries = scene_timings([trim.frames for trim in trims], sample_rate)

            _concat_pcm_wavs([trim.path for trim in trims], raw_path)
            measured = normalise_narration(raw_path, narration_path, timeout_s=timeout_s)
            duration_ms = _audio_duration_ms(probe_media(narration_path))
            expected_ms = boundaries[-1][1]
            if abs(duration_ms - expected_ms) > 2:
                raise RuntimeError(
                    f"narration is {duration_ms} ms but the trimmed scenes total {expected_ms} ms"
                )
            boundaries = reconcile_timings(boundaries, duration_ms=duration_ms)

            timings: list[dict[str, Any]] = []
            subtitles: list[SubtitleCue] = []
            for scene_id, trim, raw_words, (start_ms, end_ms) in zip(
                scene_ids, trims, scene_words, boundaries, strict=True
            ):
                scene_duration = end_ms - start_ms
                rebased = rebase_boundaries(raw_words, trim, duration_ms=scene_duration)
                # Grouped per scene, never across a boundary: a cue that spans two scenes would
                # outlive the picture it was written for.
                for cue in group_subtitles(rebased, duration_ms=scene_duration):
                    subtitles.append(
                        SubtitleCue(startMs=cue.startMs + start_ms, endMs=cue.endMs + start_ms, text=cue.text)
                    )
                # The measured word windows, scene-local like the subtitles above. `rebased` is
                # already clamped to the measured speech offset, so these are ordered,
                # non-overlapping and inside the scene by construction. They are what lets the
                # renderer open the mouth on the voice instead of on a synthetic clock; before this
                # key existed the boundaries were computed and thrown away.
                timings.append(
                    {
                        "sceneId": scene_id,
                        "startMs": start_ms,
                        "endMs": end_ms,
                        "speech": [{"startMs": word.start_ms, "endMs": word.end_ms} for word in rebased],
                    }
                )

            if abs(measured.integrated - NARRATION_TARGET_LUFS) > NARRATION_LOUDNESS_TOLERANCE:
                raise RuntimeError(
                    f"narration loudness {measured.integrated:+.2f} LUFS is outside "
                    f"{NARRATION_TARGET_LUFS:+.1f} ±{NARRATION_LOUDNESS_TOLERANCE:.1f} LUFS"
                )
            peak = measured.true_peak
            if peak is None or peak > NARRATION_TRUE_PEAK_MAX_DBTP:
                observed = "unreported" if peak is None else f"{peak:+.2f} dBTP"
                raise RuntimeError(
                    f"narration true peak {observed} exceeds {NARRATION_TRUE_PEAK_MAX_DBTP:+.1f} dBTP"
                )
            subtitles = _clamp_cues(subtitles, duration_ms=duration_ms)
            artifact = AudioArtifact(
                narration={"src": NARRATION_NAME, "durationMs": duration_ms, "voice": voice},
                scenes=timings,
                subtitles=subtitles,
                mix={
                    "music": None,
                    "music_gain_db": None,
                    "ducking": False,
                    "loudness_lufs": round(measured.integrated, 2),
                },
            )
            payload = artifact.model_dump()
            validate_artifact(AudioArtifact, payload)
            ctx.write_artifact(AUDIO_NAME, payload)
            ctx.stage_file(NARRATION_NAME, narration_path)
        except Exception as exc:
            narration_path.unlink(missing_ok=True)
            detail = redact(f"{type(exc).__name__}: {exc}", limit=400)
            _emit(state, job_id, JobState.AUDIO_READY.value, "failed", detail, agent=AUDIO_AGENT)
            raise StageError("audio_failed", detail, retryable=False) from exc
        finally:
            raw_path.unlink(missing_ok=True)
            for path in scratch:
                path.unlink(missing_ok=True)
        _emit(state, job_id, JobState.AUDIO_READY.value, "stage_completed", "AudioAgent selesai", agent=AUDIO_AGENT, progress=1.0)
        return StageOutcome(ok=True, artifacts=[NARRATION_NAME, AUDIO_NAME])

    return Stage(name=AUDIO_AGENT, state=JobState.AUDIO_READY, produces=(NARRATION_NAME, AUDIO_NAME), run=run, contract=AudioArtifact, contract_artifact=AUDIO_NAME)


__all__ = [
    "NARRATION_TARGET_LUFS",
    "NARRATION_TRUE_PEAK_MAX_DBTP",
    "SCENE_LEAD_IN_MS",
    "SCENE_TAIL_MS",
    "SILENCE_FLOOR_DB",
    "Loudness",
    "PcmFormat",
    "SceneTrim",
    "SpeechExtent",
    "WordBoundary",
    "build_asset_stage",
    "build_audio_stage",
    "build_mix_argv",
    "build_normalise_argv",
    "group_subtitles",
    "measure_loudness",
    "measure_loudness_lufs",
    "measure_speech_extent",
    "normalise_narration",
    "parse_loudness",
    "parse_loudness_lufs",
    "read_pcm_format",
    "rebase_boundaries",
    "reconcile_timings",
    "scene_timings",
    "synthesize_sapi",
    "trim_scene_wav",
]
