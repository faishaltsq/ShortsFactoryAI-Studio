"""Offline Windows narration, subtitle timing, and ffmpeg audio argv builders."""

from __future__ import annotations

import array
import hashlib
import json
import os
import re
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
from ..contracts.scene import SubtitleCue, WordTimestamp
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

#: Speech compressor tuned for vocal transparency: 0.5 ms attack to preserve consonant transients,
#: 30 ms release to avoid LF distortion and pumping, 4:1 ratio with soft knee for natural dynamics.
NARRATION_COMPRESSOR = "acompressor=threshold=-20dB:ratio=4:attack=0.5:release=30:knee=2:makeup=2"
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


@dataclass(frozen=True)
class TTSVoice:
    """A declared voice from a TTS provider."""

    id: str
    name: str
    locale: str
    gender: str
    provider: str
    description: str = ""


def normalize_indonesian_pronunciation(text: str) -> str:
    """Safe normalization for Indonesian scripts without mutating technical terms.

    Expands percentage signs, technical acronyms (AI, GPU, CPU, etc.), and normalizes
    common symbols and punctuation for natural sentence pacing, rhythm and clear pauses.
    """
    normalized = text
    # Strip markdown bold/italic
    normalized = re.sub(r"\*\*([^*]+)\*\*", r"\1", normalized)
    normalized = re.sub(r"\*([^*]+)\*", r"\1", normalized)

    # Honorifics
    normalized = re.sub(r"\bProf\.", "Profesor", normalized)
    normalized = re.sub(r"\bdr\.", "Dokter", normalized)

    # Percentages
    normalized = re.sub(r"(\d+)%", r"\1 persen", normalized)

    # Ampersand
    normalized = re.sub(r"\s*&\s*", " dan ", normalized)

    # Natural pacing: convert em-dashes, double hyphens, and ellipses to commas for breathing pauses
    normalized = re.sub(r"\s*[—–]\s*", ", ", normalized)
    normalized = re.sub(r"\s+--\s+", ", ", normalized)
    normalized = re.sub(r"\.{3,}", ", ", normalized)

    # Dimensions
    normalized = re.sub(r"\b3D\b", "3-D", normalized)
    normalized = re.sub(r"\b2D\b", "2-D", normalized)
    normalized = re.sub(r"\b3d\b", "3-D", normalized)
    normalized = re.sub(r"\b2d\b", "2-D", normalized)

    # Technical acronyms to phonetic hyphenated form so neural voice articulates each letter clearly
    # without slurring into accidental Indonesian syllables (e.g. AI -> A-I, GPU -> G-P-U)
    acronyms = {
        r"\bAI\b": "A-I",
        r"\bGPU\b": "G-P-U",
        r"\bCPU\b": "C-P-U",
        r"\bAPI\b": "A-P-I",
        r"\bLLM\b": "L-L-M",
        r"\bRAM\b": "R-A-M",
        r"\bVRAM\b": "V-R-A-M",
        r"\bFPS\b": "F-P-S",
        r"\bSSD\b": "S-S-D",
        r"\bHDD\b": "H-D-D",
        r"\bUI\b": "U-I",
        r"\bUX\b": "U-X",
        r"\bVPC\b": "V-P-C",
        r"\bURL\b": "U-R-L",
    }
    for pattern, replacement in acronyms.items():
        normalized = re.sub(pattern, replacement, normalized)

    # Clean redundant whitespace
    normalized = re.sub(r"[ \t]+", " ", normalized).strip()
    return normalized


def _fallback_word_boundaries(text: str, duration_ms: int) -> list[WordBoundary]:
    tokens = [t.strip() for t in text.split() if t.strip()]
    if not tokens or duration_ms <= 0:
        return []
    total_chars = sum(len(t) for t in tokens)
    cursor = 0
    words: list[WordBoundary] = []
    for t in tokens:
        word_dur = max(1, round(duration_ms * (len(t) / total_chars)))
        end = min(duration_ms, cursor + word_dur)
        if end > cursor:
            words.append(WordBoundary(t, cursor, end))
        cursor = end
    if words and words[-1].end_ms < duration_ms:
        words[-1] = WordBoundary(words[-1].text, words[-1].start_ms, duration_ms)
    return words


class BaseTTSProvider:
    provider_id: str

    def list_voices(self, locale: str | None = None) -> list[TTSVoice]:
        raise NotImplementedError

    def validate_voice(self, voice: str, locale: str | None = None) -> TTSVoice:
        raise NotImplementedError

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        rate: str | None = None,
        timeout_s: int = 90,
        **kwargs: Any,
    ) -> tuple[list[WordBoundary], int]:
        raise NotImplementedError


class EdgeTTSProvider(BaseTTSProvider):
    provider_id = "edge-tts"
    _cached_voices: list[TTSVoice] | None = None

    def list_voices(self, locale: str | None = None) -> list[TTSVoice]:
        if self._cached_voices is None:
            self._load_voices()
        voices = self._cached_voices or []
        if locale:
            loc = locale.lower()
            norm = "id-id" if loc in ("id", "id-id", "indonesian") else loc
            return [v for v in voices if v.locale.lower() == norm or v.locale.lower().startswith(norm[:2])]
        return list(voices)

    def _load_voices(self) -> None:
        try:
            import asyncio

            import edge_tts

            async def _fetch() -> list[Any]:
                return list(await edge_tts.list_voices())

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    raw_list = ex.submit(asyncio.run, _fetch()).result(timeout=10)
            else:
                raw_list = asyncio.run(_fetch())

            res = []
            for item in raw_list:
                res.append(
                    TTSVoice(
                        id=str(item.get("ShortName", "")),
                        name=str(item.get("FriendlyName", item.get("ShortName", ""))),
                        locale=str(item.get("Locale", "")),
                        gender=str(item.get("Gender", "Unknown")),
                        provider="edge-tts",
                        description=f"Microsoft Edge Neural ({item.get('Locale', '')})",
                    )
                )
            self._cached_voices = res
        except Exception:
            self._cached_voices = [
                TTSVoice(
                    id="id-ID-ArdiNeural",
                    name="Microsoft Ardi Online (Natural) - Indonesian (Indonesia)",
                    locale="id-ID",
                    gender="Male",
                    provider="edge-tts",
                    description="Indonesian Male Voice",
                ),
                TTSVoice(
                    id="id-ID-GadisNeural",
                    name="Microsoft Gadis Online (Natural) - Indonesian (Indonesia)",
                    locale="id-ID",
                    gender="Female",
                    provider="edge-tts",
                    description="Indonesian Female Voice",
                ),
            ]

    def validate_voice(self, voice: str, locale: str | None = None) -> TTSVoice:
        voices = self.list_voices()
        found = next((v for v in voices if v.id.lower() == voice.lower()), None)
        if not found:
            if "Neural" in voice:
                parts = voice.split("-")
                loc = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else "unknown"
                found = TTSVoice(
                    id=voice,
                    name=voice,
                    locale=loc,
                    gender="Unknown",
                    provider="edge-tts",
                    description=f"Neural Voice ({loc})",
                )
            else:
                raise ValueError(f"Unknown Edge TTS voice {voice!r}")
        if locale:
            loc = locale.lower()
            norm = "id" if loc in ("id", "id-id", "indonesian") else loc[:2]
            if not found.locale.lower().startswith(norm):
                raise ValueError(
                    f"Edge TTS voice {voice!r} (locale {found.locale}) does not match required locale {locale!r}"
                )
        return found

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        rate: str | None = "-3%",
        timeout_s: int = 90,
        **kwargs: Any,
    ) -> tuple[list[WordBoundary], int]:
        import asyncio

        import edge_tts

        normalized = normalize_indonesian_pronunciation(text.strip())
        if not normalized:
            raise ValueError("narration text is empty")

        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_mp3 = output_path.with_suffix(".tmp.mp3")

        comm_kwargs: dict[str, Any] = {"boundary": "WordBoundary"}
        if rate:
            comm_kwargs["rate"] = rate

        async def _run() -> list[Any]:
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    communicate = edge_tts.Communicate(normalized, voice, **comm_kwargs)
                    words_raw: list[Any] = []
                    audio_received = False
                    with open(raw_mp3, "wb") as f:
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                                audio_received = True
                            elif chunk["type"] == "WordBoundary":
                                words_raw.append(chunk)
                    if audio_received and raw_mp3.is_file() and raw_mp3.stat().st_size > 0:
                        return words_raw
                except Exception as exc:
                    last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(0.6 * (attempt + 1))
            if last_exc:
                raise last_exc
            raise RuntimeError("Edge TTS produced empty audio output")
        try:
            try:
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass

                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        words_raw = ex.submit(asyncio.run, _run()).result(timeout=timeout_s)
                else:
                    words_raw = asyncio.run(_run())
            except Exception as exc:
                raise RuntimeError(f"Edge TTS synthesis failed for voice {voice}: {exc}") from exc

            if not raw_mp3.is_file() or raw_mp3.stat().st_size == 0:
                raise RuntimeError("Edge TTS produced empty audio output")

            cmd = [
                "ffmpeg", "-y", "-i", str(raw_mp3),
                "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
                str(output_path),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr[-STDERR_LIMIT:]}")

            duration_ms = _audio_duration_ms(probe_media(output_path))
            words: list[WordBoundary] = []
            for w in words_raw:
                start_ms = round(w["offset"] / 10000)
                end_ms = round((w["offset"] + w["duration"]) / 10000)
                if end_ms > start_ms:
                    words.append(WordBoundary(text=w["text"], start_ms=start_ms, end_ms=end_ms))

            if not words:
                words = _fallback_word_boundaries(normalized, duration_ms)

            words = parse_boundaries([{"text": w.text, "startMs": w.start_ms, "endMs": w.end_ms} for w in words], duration_ms=duration_ms)
            group_subtitles(words, duration_ms=duration_ms)
            return words, duration_ms
        finally:
            raw_mp3.unlink(missing_ok=True)


def _list_sapi_installed_voices() -> list[TTSVoice]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return []
    ps_code = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "foreach ($v in $s.GetInstalledVoices()) { "
        'Write-Output ($v.VoiceInfo.Name + "|" + $v.VoiceInfo.Culture.Name + "|" + [string]$v.VoiceInfo.Gender) '
        "}"
    )
    try:
        proc = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return []
        voices = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            name = parts[0]
            culture = parts[1] if len(parts) > 1 else "unknown"
            gender = parts[2] if len(parts) > 2 else "Unknown"
            voices.append(
                TTSVoice(
                    id=name,
                    name=name,
                    locale=culture,
                    gender=gender,
                    provider="sapi",
                    description=f"Windows Desktop SAPI Voice ({culture})",
                )
            )
        return voices
    except Exception:
        return []


class SapiTTSProvider(BaseTTSProvider):
    provider_id = "sapi"
    _cached_voices: list[TTSVoice] | None = None

    def list_voices(self, locale: str | None = None) -> list[TTSVoice]:
        if self._cached_voices is None:
            self._cached_voices = _list_sapi_installed_voices()
        voices = self._cached_voices or []
        if locale:
            loc = locale.lower()
            norm = "id" if loc in ("id", "id-id", "indonesian") else loc[:2]
            return [v for v in voices if v.locale.lower().startswith(norm)]
        return list(voices)

    def validate_voice(self, voice: str, locale: str | None = None) -> TTSVoice:
        _validate_voice(voice)
        installed = self.list_voices()
        v: TTSVoice | None
        if voice == "system-default":
            v = installed[0] if installed else TTSVoice("system-default", "System Default", "en-US", "Unknown", "sapi")
        else:
            v = next((item for item in installed if item.id.lower() == voice.lower()), None)
        if v is None:
            raise ValueError(f"Requested voice {voice!r} is not installed in Windows SAPI")
        if locale:
            loc = locale.lower()
            norm = "id" if loc in ("id", "id-id", "indonesian") else loc[:2]
            if not v.locale.lower().startswith(norm):
                raise ValueError(
                    f"Requested SAPI voice {v.id!r} has culture {v.locale!r}, which does not match requested "
                    f"locale {locale!r}. Windows SAPI has no Indonesian voice. Use Edge TTS (e.g. 'id-ID-ArdiNeural')."
                )
        return v

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        rate: str | None = None,
        timeout_s: int = 90,
        **kwargs: Any,
    ) -> tuple[list[WordBoundary], int]:
        return synthesize_sapi(text, output_path, voice=voice, timeout_s=timeout_s)


class VoiceStudioProvider(BaseTTSProvider):
    name = "voicestudio"
    provider_id = "voicestudio"

    _standard_voices: tuple[TTSVoice, ...] = (
        TTSVoice(id="alloy", name="VoiceStudio Alloy", locale="id-ID", gender="Neutral", provider="voicestudio", description="VoiceStudio Alloy"),
        TTSVoice(id="echo", name="VoiceStudio Echo", locale="id-ID", gender="Male", provider="voicestudio", description="VoiceStudio Echo"),
        TTSVoice(id="fable", name="VoiceStudio Fable", locale="id-ID", gender="Neutral", provider="voicestudio", description="VoiceStudio Fable"),
        TTSVoice(id="onyx", name="VoiceStudio Onyx", locale="id-ID", gender="Male", provider="voicestudio", description="VoiceStudio Onyx"),
        TTSVoice(id="nova", name="VoiceStudio Nova", locale="id-ID", gender="Female", provider="voicestudio", description="VoiceStudio Nova"),
        TTSVoice(id="shimmer", name="VoiceStudio Shimmer", locale="id-ID", gender="Female", provider="voicestudio", description="VoiceStudio Shimmer"),
    )

    def __init__(self, adapter: Any = None) -> None:
        self.adapter = adapter
        self.last_metadata: dict[str, Any] = {}

    def list_voices(self, locale: str | None = None) -> list[TTSVoice]:
        voices = list(self._standard_voices)
        if locale:
            loc = locale.lower()
            norm = "id" if loc in ("id", "id-id", "indonesian") else loc[:2]
            return [v for v in voices if v.locale.lower().startswith(norm)]
        return voices

    def validate_voice(self, voice: str, locale: str | None = None) -> TTSVoice:
        clean = (voice or "").strip().lower()
        if not clean or clean in ("system-default", "default", "auto"):
            clean = "alloy"
        voices = self.list_voices()
        found = next((v for v in voices if v.id.lower() == clean), None)
        if not found:
            found = TTSVoice(
                id=voice,
                name=f"VoiceStudio {voice}",
                locale="id-ID",
                gender="Unknown",
                provider="voicestudio",
                description=f"VoiceStudio {voice}",
            )
        if locale:
            loc = locale.lower()
            norm = "id" if loc in ("id", "id-id", "indonesian") else loc[:2]
            if not found.locale.lower().startswith(norm):
                raise ValueError(
                    f"VoiceStudio voice {voice!r} (locale {found.locale}) does not match required locale {locale!r}"
                )
        return found

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        rate: str | None = None,
        timeout_s: int = 90,
        return_metadata: bool = False,
        **kwargs: Any,
    ) -> tuple[list[WordBoundary], int] | tuple[list[WordBoundary], int, dict[str, Any]]:
        from .voicestudio import VoiceStudioAdapter

        adapter = self.adapter or VoiceStudioAdapter(timeout_s=float(timeout_s))
        synth_kwargs: dict[str, Any] = {"voice": voice}
        if "model" in kwargs:
            synth_kwargs["model"] = kwargs["model"]
        if "language" in kwargs:
            synth_kwargs["language"] = kwargs["language"]
        if "speed" in kwargs:
            synth_kwargs["speed"] = float(kwargs["speed"])
        elif rate is not None:
            if isinstance(rate, (int, float)):
                synth_kwargs["speed"] = float(rate)
            elif isinstance(rate, str) and rate.endswith("%"):
                try:
                    pct = float(rate.rstrip("%"))
                    synth_kwargs["speed"] = max(0.25, min(4.0, 1.0 + pct / 100.0))
                except ValueError:
                    pass

        res = adapter.synthesize(text, **synth_kwargs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(res.audio_bytes)
        duration_ms = int(round(res.duration_s * 1000.0))
        boundaries = [
            WordBoundary(text=w["word"], start_ms=w["startMs"], end_ms=w["endMs"])
            for w in res.word_timestamps
        ]
        self.last_metadata = {
            "alignment_mode": res.alignment_mode,
            "sample_rate": res.sample_rate,
            "duration_s": res.duration_s,
        }
        if return_metadata:
            return boundaries, duration_ms, dict(self.last_metadata)
        return boundaries, duration_ms


def select_tts_provider(provider_name: str | None) -> str:
    """Normalize TTS provider name.

    Returns "voicestudio" for VoiceStudio/local, "sapi" for Windows SAPI, else "edge-tts".
    """
    prov = (provider_name or "").strip().lower()
    if prov in ("voicestudio", "voice-studio", "omnivioce", "omnivoice", "local"):
        return "voicestudio"
    if prov in ("sapi", "windows"):
        return "sapi"
    return "edge-tts"


def get_tts_provider(name: str) -> BaseTTSProvider:
    selected = select_tts_provider(name)
    if selected == "sapi":
        return SapiTTSProvider()
    if selected == "voicestudio":
        return VoiceStudioProvider()
    return EdgeTTSProvider()


def list_available_voices(locale: str | None = None, provider: str | None = None) -> list[TTSVoice]:
    prov = (provider or "").strip().lower()
    voices: list[TTSVoice] = []
    if not prov or prov in ("edge-tts", "edge"):
        voices.extend(EdgeTTSProvider().list_voices(locale=locale))
    if not prov or prov in ("sapi", "windows"):
        voices.extend(SapiTTSProvider().list_voices(locale=locale))
    if not prov or prov in ("voicestudio", "voice-studio", "omnivioce", "omnivoice", "local"):
        voices.extend(VoiceStudioProvider().list_voices(locale=locale))
    return voices


def resolve_tts(
    language: str = "id",
    requested_voice: str | None = None,
    requested_provider: str | None = None,
) -> tuple[BaseTTSProvider, TTSVoice]:
    lang_clean = (language or "id").strip().lower()
    is_id = lang_clean in ("id", "id-id", "indonesian")
    req_voice = (requested_voice or "").strip()
    req_provider = (requested_provider or "").strip().lower()

    if req_provider in ("voicestudio", "voice-studio", "omnivioce", "omnivoice", "local"):
        vs = VoiceStudioProvider()
        target_locale = "id-ID" if is_id else ("en-US" if lang_clean in ("en", "en-us") else lang_clean)
        target_voice = req_voice if req_voice and req_voice not in ("system-default", "default", "auto") else "alloy"
        voice_obj = vs.validate_voice(target_voice, locale=target_locale if is_id else None)
        return vs, voice_obj

    if is_id:
        target_locale = "id-ID"
        if req_provider in ("sapi", "windows"):
            sapi = SapiTTSProvider()
            voice_obj = sapi.validate_voice(req_voice or "system-default", locale=target_locale)
            return sapi, voice_obj

        edge = EdgeTTSProvider()
        if not req_voice or req_voice in ("system-default", "default", "auto"):
            target_voice = "id-ID-ArdiNeural"
        elif "gadis" in req_voice.lower():
            target_voice = "id-ID-GadisNeural"
        elif "ardi" in req_voice.lower():
            target_voice = "id-ID-ArdiNeural"
        else:
            target_voice = req_voice
        voice_obj = edge.validate_voice(target_voice, locale=target_locale)
        return edge, voice_obj

    # Non-Indonesian
    target_locale = "en-US" if lang_clean in ("en", "en-us") else lang_clean
    if req_provider in ("sapi", "windows") or (req_voice and not req_voice.endswith("Neural")):
        sapi = SapiTTSProvider()
        voice_obj = sapi.validate_voice(req_voice or "system-default", locale=target_locale)
        return sapi, voice_obj

    edge = EdgeTTSProvider()
    target_voice = req_voice if req_voice and req_voice != "system-default" else "en-US-GuyNeural"
    voice_obj = edge.validate_voice(target_voice, locale=target_locale)
    return edge, voice_obj

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
    sample_rate: int = 16000,
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
    if not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError(f"sample_rate must be a positive integer, got {sample_rate!r}")
    filters = ",".join(
        (NARRATION_COMPRESSOR, f"volume={gain_db:.2f}dB", NARRATION_LIMITER)
    )
    return [
        "ffmpeg", "-y", "-i", str(narration_path),
        "-af", filters,
        "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le",
        str(output_path),
    ]


def build_mix_argv(
    narration_path: Path,
    output_path: Path,
    *,
    music_path: Path | None = None,
    music_gain_db: float = -18.0,
    gain_db: float = 0.0,
    sample_rate: int = 16000,
) -> list[str]:
    """Build the narration-only normalisation or a real music ducking mix.

    ``gain_db`` is the measured gain from :func:`normalise_narration`; with music present it is
    applied to the narration leg before the duck, so the music is not lifted with it.
    """
    if not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError(f"sample_rate must be a positive integer, got {sample_rate!r}")
    if music_path is None:
        return build_normalise_argv(narration_path, output_path, gain_db=gain_db, sample_rate=sample_rate)
    narration_chain = f"[0:a]{NARRATION_COMPRESSOR},volume={gain_db:.2f}dB[voice]"
    music_chain = f"[1:a]volume={music_gain_db}dB[music]"
    duck = "[music][voice]sidechaincompress=threshold=0.03:ratio=10[ducked]"
    mix = f"[voice][ducked]amix=inputs=2:duration=first,{NARRATION_LIMITER}[out]"
    return [
        "ffmpeg", "-y", "-i", str(narration_path), "-i", str(music_path),
        "-filter_complex", f"{narration_chain};{music_chain};{duck};{mix}",
        "-map", "[out]",
        "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le",
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
    sample_rate: int | None = None,
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
    target_sample_rate = sample_rate
    if target_sample_rate is None:
        try:
            with wave.open(str(source), "rb") as wf:
                sr = wf.getframerate()
                if sr > 0:
                    target_sample_rate = sr
        except Exception:
            pass
    if target_sample_rate is None or target_sample_rate <= 0:
        target_sample_rate = 16000

    gain_db = 0.0
    measured = Loudness(integrated=0.0, true_peak=None, range=None)
    for _ in range(max_passes):
        _run_audio_argv(
            build_normalise_argv(source, target, gain_db=gain_db, sample_rate=target_sample_rate),
            timeout_s=timeout_s,
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
    """Record the verified visual sources a job's storyboard actually asks the renderer to draw.

    The renderer draws objects, not characters, so this stage hashes the object library, the
    palette and the backdrop module, and lists one entry per object kind and per environment the
    storyboard names. A storyboard that names a kind with no source file fails here rather than
    rendering an empty box.
    """
    from ..orchestration.runner import Stage, StageContext, StageError, StageOutcome

    source = Path(video_dir) / "src"
    kinds_path = source / "art" / "object-kinds.ts"
    library_path = source / "art" / "objects.tsx"
    palette_path = source / "art" / "palette.ts"
    env_path = source / "art" / "Environment.tsx"

    def run(ctx: StageContext) -> StageOutcome:
        job_id = ctx.job_id
        from ..orchestration.pipeline import _emit

        _emit(state, job_id, JobState.ASSETS_READY.value, "stage_started", "AssetAgent mulai", agent=ASSET_AGENT)
        try:
            missing = [str(path) for path in (kinds_path, library_path, palette_path, env_path) if not path.is_file()]
            if missing:
                raise RuntimeError("informative renderer source missing: " + ", ".join(missing))

            storyboard = None
            try:
                storyboard = ctx.store.read_artifact(job_id, "storyboard.json")
            except Exception:
                pass
            # Validate against semantic visual plan if present
            visual_plan = None
            try:
                visual_plan = ctx.store.read_artifact(job_id, "visual-plan.json")
            except Exception:
                pass
            if visual_plan and isinstance(visual_plan, dict):
                from ..agents.asset_registry import AssetResolver
                script = None
                try:
                    script = ctx.store.read_artifact(job_id, "script.json")
                except Exception:
                    pass
                _assets_payload, missing_reports = AssetResolver.resolve_visual_plan(visual_plan, script)
                if missing_reports:
                    unresolved: list[str] = [
                        str(m.get("concept") or m.get("subject") or "unknown") for m in missing_reports
                    ]
                    raise RuntimeError(
                        f"AssetAgent blocked: missing mandatory visual assets for concepts: {unresolved}. "
                        "Cannot proceed without concrete visual representation."
                    )


            kinds: set[str] = set()
            environments: set[str] = set()
            scenes = storyboard.get("scenes") if isinstance(storyboard, dict) else None
            if isinstance(scenes, list):
                for sc in scenes:
                    if not isinstance(sc, dict):
                        continue
                    raw = sc.get("data")
                    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
                    env = data.get("environment")
                    if isinstance(env, str) and env:
                        environments.add(env)
                    for item in data.get("objects") or []:
                        if isinstance(item, dict) and isinstance(item.get("kind"), str):
                            kinds.add(item["kind"])

            from ..contracts.scene import OBJECT_KINDS
            unknown_kinds = sorted({k for k in kinds if k not in OBJECT_KINDS})
            if unknown_kinds:
                raise RuntimeError(
                    f"Storyboard names unresolvable visual objects {unknown_kinds}. "
                    f"Supported drawable library assets: {sorted(OBJECT_KINDS)}"
                )

            library_hash = _sha256_paths([kinds_path, library_path])
            palette_hash = _sha256_paths([palette_path])
            objects = [
                {
                    "id": kind,
                    "library_hash": library_hash,
                    "palette_hash": palette_hash,
                    "source": "packages/video/src/art/objects.tsx",
                    "license": "project-original",
                }
                for kind in sorted(kinds)
            ]

            env_hash = _sha256_paths([env_path])
            backgrounds = [
                {
                    "id": f"env:{environment}",
                    "environment": environment,
                    "source": "packages/video/src/art/Environment.tsx",
                    "sha256": env_hash,
                    "license": "project-original",
                }
                for environment in sorted(environments or {"abstract"})
            ]

            artifact = AssetsArtifact(objects=objects, backgrounds=backgrounds, audio=[])
            payload = artifact.model_dump()
            manifest_bytes = json.dumps(
                [payload["objects"], payload["backgrounds"], payload["audio"]],
                sort_keys=True,
                separators=(",", ":")
            ).encode()
            payload["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
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


def _clamp_words(words: list[WordTimestamp], *, duration_ms: int) -> list[WordTimestamp]:
    """Drop words that fall outside the narration and pull the rest back inside it."""
    clamped: list[WordTimestamp] = []
    for w in words:
        start = min(w.startMs, duration_ms)
        end = min(w.endMs, duration_ms)
        if end <= start:
            continue
        clamped.append(WordTimestamp(word=w.word, startMs=start, endMs=end))
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
            raw_lang = job.payload.get("language")
            req_voice = str(job.payload.get("voice") or "")
            req_provider = str(job.payload.get("tts_provider") or "")
            if raw_lang:
                lang = str(raw_lang)
            elif req_voice == "system-default" or req_provider in ("sapi", "windows"):
                lang = "en"
            else:
                lang = "id"
            tts_provider, tts_voice = resolve_tts(lang, requested_voice=req_voice, requested_provider=req_provider)
            voice = tts_voice.id
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
                rate = str(job.payload.get("speech_rate") or "-3%")
                words, _ = tts_provider.synthesize(text, raw_scene, voice=voice, rate=rate, timeout_s=timeout_s)
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
            measured = normalise_narration(raw_path, narration_path, sample_rate=sample_rate, timeout_s=timeout_s)
            duration_ms = _audio_duration_ms(probe_media(narration_path))
            expected_ms = boundaries[-1][1]
            if abs(duration_ms - expected_ms) > 2:
                raise RuntimeError(
                    f"narration is {duration_ms} ms but the trimmed scenes total {expected_ms} ms"
                )
            boundaries = reconcile_timings(boundaries, duration_ms=duration_ms)

            timings: list[dict[str, Any]] = []
            subtitles: list[SubtitleCue] = []
            all_words: list[WordTimestamp] = []
            for scene_id, trim, raw_words, (start_ms, end_ms) in zip(
                scene_ids, trims, scene_words, boundaries, strict=True
            ):
                scene_duration = end_ms - start_ms
                rebased = rebase_boundaries(raw_words, trim, duration_ms=scene_duration)
                for word in rebased:
                    all_words.append(
                        WordTimestamp(
                            word=word.text,
                            startMs=word.start_ms + start_ms,
                            endMs=word.end_ms + start_ms,
                        )
                    )
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
            word_timestamps = _clamp_words(all_words, duration_ms=duration_ms)
            tts_metadata = {
                "voice": voice,
                "provider": tts_provider.provider_id,
                "locale": tts_voice.locale,
                "gender": tts_voice.gender,
                "rate": str(job.payload.get("speech_rate") or "-3%"),
                "description": tts_voice.description,
            }
            if hasattr(tts_provider, "last_metadata"):
                meta = getattr(tts_provider, "last_metadata", {})
                if "alignment_mode" in meta:
                    tts_metadata["alignment_mode"] = meta["alignment_mode"]
                if "sample_rate" in meta:
                    tts_metadata["sample_rate"] = meta["sample_rate"]
            narration_dict = {
                "src": NARRATION_NAME,
                "durationMs": duration_ms,
                "voice": voice,
                "provider": tts_provider.provider_id,
                "locale": tts_voice.locale,
                "rate": str(job.payload.get("speech_rate") or "-3%"),
                "gender": tts_voice.gender,
            }
            if "alignment_mode" in tts_metadata:
                narration_dict["alignment_mode"] = tts_metadata["alignment_mode"]
            artifact = AudioArtifact(
                narration=narration_dict,
                scenes=timings,
                subtitles=subtitles,
                words=word_timestamps,
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
            ctx.write_artifact("tts_metadata.json", tts_metadata)
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
    "BaseTTSProvider",
    "EdgeTTSProvider",
    "Loudness",
    "PcmFormat",
    "SapiTTSProvider",
    "SceneTrim",
    "SpeechExtent",
    "TTSVoice",
    "VoiceStudioProvider",
    "WordBoundary",
    "build_asset_stage",
    "build_audio_stage",
    "build_mix_argv",
    "build_normalise_argv",
    "get_tts_provider",
    "group_subtitles",
    "list_available_voices",
    "measure_loudness",
    "measure_loudness_lufs",
    "measure_speech_extent",
    "normalise_narration",
    "normalize_indonesian_pronunciation",
    "parse_loudness",
    "parse_loudness_lufs",
    "read_pcm_format",
    "rebase_boundaries",
    "reconcile_timings",
    "resolve_tts",
    "scene_timings",
    "select_tts_provider",
    "synthesize_sapi",
    "trim_scene_wav",
]
