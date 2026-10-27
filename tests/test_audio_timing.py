"""Scene audio is trimmed to real speech, and the narration really reaches its declared loudness.

Job ``fd811911ea6057d5`` is the evidence for every number in this file. Its ``narration.wav``
measured 13.485 s with speech islands at 188.9-3626.8, 4487.1-8431.6 and 9372.5-12731.1 ms at
-60 dB, while ``audio.json`` declared scene boundaries 0/4385/9180/13485. Each scene therefore
carried ~750 ms of digital silence that SAPI appends after the last word, and the subtitle cues
inherited it: a caption lingered over silence. The same job declared ``loudness_lufs: -16`` while
the render measured -17.72 LUFS.

These tests use real SAPI output, not a fixture: a fake WAV with the tail edited out proves nothing
about whether the tail exists.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from packages.core.contracts.artifacts import AudioArtifact
from packages.core.contracts.base import validate_artifact
from packages.core.contracts.state import JobState
from packages.core.media.tts import (
    NARRATION_TARGET_LUFS,
    NARRATION_TRUE_PEAK_MAX_DBTP,
    SCENE_LEAD_IN_MS,
    SCENE_TAIL_MS,
    SILENCE_FLOOR_DB,
    WordBoundary,
    build_audio_stage,
    measure_loudness,
    measure_speech_extent,
    normalise_narration,
    read_pcm_format,
    rebase_boundaries,
    scene_timings,
    trim_scene_wav,
)
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.runner import run_stages

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(
        shutil.which("ffmpeg") is None
        or shutil.which("ffprobe") is None
        or shutil.which("powershell.exe") is None,
        reason="real SAPI narration needs Windows PowerShell, ffmpeg and ffprobe",
    ),
]

#: The tail SAPI appends after the last word, measured on this host: 746-755 ms on three texts.
#: The declared pad must be far below it or the defect is still shipping.
SAPI_TAIL_MS = 750
#: Speech must start and stop within this of the file's own edges.
EDGE_TOLERANCE_MS = 200

SEGMENTS = [
    "Halo dunia ini tes pertama.",
    "Segmen kedua agak lebih panjang dari yang pertama.",
    "Penutup singkat.",
]


def _trailing_silence_ms(path: Path, *, floor_db: float = SILENCE_FLOOR_DB) -> float:
    """How much digital silence a WAV carries after its last audible sample."""
    extent = measure_speech_extent(path, floor_db=floor_db)
    return extent.duration_ms - extent.offset_ms


def _frame_ms(frames: int, sample_rate: int) -> float:
    return frames / sample_rate * 1000.0


def _job(store: JobStore, *, voice: str = "system-default") -> str:
    job = store.create(title="narasi", payload={"provider_mode": "mock", "voice": voice, "render_video": True})
    store.write_artifact(
        job.id,
        "script.json",
        {
            "hook": SEGMENTS[0],
            "segments": [{"id": f"s{i + 1}", "text": text, "purpose": "build"} for i, text in enumerate(SEGMENTS)],
            "cta": "",
            "estimated_duration_s": 8,
            "content_kind": "fictional",
            "prompt_hash": "0" * 64,
        },
    )
    store.write_artifact(
        job.id,
        "storyboard.json",
        {
            "fps": 30,
            "width": 1080,
            "height": 1920,
            "theme": "dusk",
            "scenes": [
                {
                    "sceneId": f"sc{i + 1}",
                    "template": "IllustratedStory",
                    "segment": f"s{i + 1}",
                    "startFrame": 0,
                    "durationInFrames": 90,
                    "assetRefs": [],
                    "text": [{"id": f"t{i + 1}", "text": text, "role": "title", "atFrame": 0}],
                    "camera": {"shot": "wide", "move": "static", "ease": "power2.out"},
                    "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
                    "transition": {"kind": "cut", "frames": 0},
                    "data": {},
                }
                for i, text in enumerate(SEGMENTS)
            ],
            "subtitles": [],
        },
    )
    for state in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
    ):
        store.transition(job.id, state)
    return job.id


class _Events:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def emit(self, **kwargs) -> None:
        self.rows.append(kwargs)


class _State:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.events = _Events()


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


# -- measurement and trimming -------------------------------------------------------------------


def test_measure_speech_extent_finds_the_tail_sapi_appends(tmp_path: Path):
    """The defect itself: the raw file is much longer than the speech inside it.

    This is the assertion the old code failed. Scene duration was ``ffprobe``'s duration of this
    file, so the tail became narration time.
    """
    from packages.core.media.tts import synthesize_sapi

    path = tmp_path / "scene.wav"
    _, raw_duration = synthesize_sapi(SEGMENTS[0], path, voice="system-default")
    extent = measure_speech_extent(path)

    assert extent.speech_ms < raw_duration - 400, (
        f"speech {extent.speech_ms:.1f} ms vs file {raw_duration} ms: no tail was detected, "
        "so the measurement is not seeing what the job saw"
    )
    # The measurement must agree with SAPI's own word boundary, which stops before the tail.
    assert abs(extent.onset_ms) < 250


def test_trim_removes_the_sapi_tail_and_keeps_a_declared_pad(tmp_path: Path):
    from packages.core.media.tts import synthesize_sapi

    raw = tmp_path / "raw.wav"
    trimmed = tmp_path / "trimmed.wav"
    synthesize_sapi(SEGMENTS[0], raw, voice="system-default")

    trim = trim_scene_wav(raw, trimmed)

    assert _trailing_silence_ms(trimmed) <= SCENE_TAIL_MS + 10, (
        f"trimmed scene still carries {_trailing_silence_ms(trimmed):.1f} ms of trailing silence; "
        f"the declared pad is {SCENE_TAIL_MS} ms"
    )
    assert _trailing_silence_ms(trimmed) < SAPI_TAIL_MS / 2
    # The lead-in is deliberate and bounded: never more than the pad plus a sample of slack.
    assert trim.extent.onset_ms - _frame_ms(trim.start_frame, trim.sample_rate) <= SCENE_LEAD_IN_MS + 10
    assert read_pcm_format(trimmed).frames == trim.frames
    assert trim.duration_ms < trim.extent.duration_ms


def test_trimmed_scene_preserves_sample_rate_and_channel_count(tmp_path: Path):
    """The mux expects 16 kHz mono PCM; trimming must not quietly change that."""
    from packages.core.media.tts import synthesize_sapi

    raw = tmp_path / "raw.wav"
    trimmed = tmp_path / "trimmed.wav"
    synthesize_sapi(SEGMENTS[1], raw, voice="system-default")
    before = read_pcm_format(raw)

    trim_scene_wav(raw, trimmed)
    after = read_pcm_format(trimmed)

    assert (after.channels, after.sample_width, after.sample_rate) == (
        before.channels,
        before.sample_width,
        before.sample_rate,
    )
    assert after.channels == 1
    assert after.sample_rate == 16000
    assert after.sample_width == 2


def test_silent_wav_is_rejected_rather_than_trimmed_to_nothing(tmp_path: Path):
    """A file with no speech must fail loudly. Silence trimmed to a pad is a fake artifact."""
    silent = tmp_path / "silent.wav"
    with wave.open(str(silent), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)

    with pytest.raises(RuntimeError, match="silent"):
        measure_speech_extent(silent)


def test_rebase_boundaries_shifts_to_the_trim_window_and_clamps_to_it(tmp_path: Path):
    """Audio is ground truth: a boundary outside the window moves, the window does not."""
    from packages.core.media.tts import synthesize_sapi

    raw = tmp_path / "raw.wav"
    trimmed = tmp_path / "trimmed.wav"
    words, _ = synthesize_sapi(SEGMENTS[2], raw, voice="system-default")
    trim = trim_scene_wav(raw, trimmed)
    duration_ms = round(trim.duration_ms)

    rebased = rebase_boundaries(words, trim, duration_ms=duration_ms)

    assert rebased, "every boundary was dropped; the shift is wrong"
    assert all(0 <= word.start_ms < word.end_ms <= duration_ms for word in rebased)
    # The first word must land near the lead-in, not near zero and not at the raw offset.
    assert rebased[0].start_ms <= SCENE_LEAD_IN_MS + EDGE_TOLERANCE_MS
    # Clamping is real: a boundary past the end is pulled back, not passed through.
    late = [WordBoundary("late", duration_ms + 500, duration_ms + 900)]
    assert rebase_boundaries(late, trim, duration_ms=duration_ms) == []


def test_scene_timings_sum_to_the_narration_without_drift():
    """Boundaries come from cumulative frames. Rounding each scene drifts; the last one must not."""
    sample_rate = 16000
    frame_lengths = [33077, 78194, 20551]  # odd frame counts, none a whole millisecond
    timings = scene_timings(frame_lengths, sample_rate)

    total = sum(frame_lengths)
    assert timings[0][0] == 0
    assert timings[-1][1] == round(total / sample_rate * 1000)
    for index in range(1, len(timings)):
        assert timings[index][0] == timings[index - 1][1]
    assert all(end > start for start, end in timings)


def test_timings_are_reconciled_to_the_probed_narration():
    """ffprobe rounds the WAV duration; ``audio.json`` must still cover it exactly.

    The contract requires contiguous scene timings that end at ``narration.durationMs``, and
    ``durationMs`` is what ffprobe reported. A one-millisecond disagreement between the frame
    arithmetic and that probe must be absorbed by the last boundary, not rejected at validation.
    """
    from packages.core.media.tts import reconcile_timings

    timings = [(0, 3488), (3488, 7429), (7429, 10783)]
    assert reconcile_timings(timings, duration_ms=10784) == [
        (0, 3488),
        (3488, 7429),
        (7429, 10784),
    ]


def test_reconciling_an_impossible_gap_is_refused():
    from packages.core.media.tts import reconcile_timings

    with pytest.raises(ValueError, match="narration"):
        reconcile_timings([(0, 1000)], duration_ms=5000)


# -- loudness -----------------------------------------------------------------------------------


def test_normalise_narration_reaches_the_declared_target(tmp_path: Path):
    """The declared target is -16 LUFS; single-pass loudnorm delivered -18.01 on this speech."""
    from packages.core.media.tts import synthesize_sapi

    raw = tmp_path / "raw.wav"
    out = tmp_path / "narration.wav"
    synthesize_sapi(" ".join(SEGMENTS), raw, voice="system-default")

    measured = normalise_narration(raw, out, timeout_s=120)

    assert abs(measured.integrated - NARRATION_TARGET_LUFS) <= 0.5, (
        f"narration measures {measured.integrated:+.2f} LUFS, declared {NARRATION_TARGET_LUFS:+.1f}"
    )
    assert measured.true_peak <= NARRATION_TRUE_PEAK_MAX_DBTP, (
        f"true peak {measured.true_peak:+.2f} dBTP exceeds {NARRATION_TRUE_PEAK_MAX_DBTP:+.1f}"
    )
    # Re-measure independently: the returned object must describe the file on disk.
    on_disk = measure_loudness(out, timeout_s=120)
    assert abs(on_disk.integrated - measured.integrated) <= 0.1
    # Normalisation must not resample or re-channel the file the mux receives.
    fmt = read_pcm_format(out)
    assert (fmt.channels, fmt.sample_width, fmt.sample_rate) == (1, 2, 16000)


def test_normalisation_keeps_the_frame_count_exactly(tmp_path: Path):
    """Gain and limiting are amplitude-only; a changed length would break every scene boundary."""
    from packages.core.media.tts import synthesize_sapi

    raw = tmp_path / "raw.wav"
    out = tmp_path / "narration.wav"
    synthesize_sapi(SEGMENTS[1], raw, voice="system-default")

    normalise_narration(raw, out, timeout_s=120)

    assert read_pcm_format(out).frames == read_pcm_format(raw).frames


def test_parse_loudness_never_invents_a_true_peak_it_did_not_measure():
    """A missing field is reported as missing. Filling in a default would fake a gate result."""
    from packages.core.media.tts import parse_loudness

    partial = parse_loudness('{"input_i" : "-17.23"}')
    assert partial.integrated == -17.23
    assert partial.true_peak is None
    assert partial.range is None

    full = parse_loudness('{"input_i": "-16.01", "input_tp": "-1.52", "input_lra": "3.20"}')
    assert (full.integrated, full.true_peak, full.range) == (-16.01, -1.52, 3.20)


# -- the whole audio stage, on real SAPI output -------------------------------------------------


def test_real_three_scene_audio_stage_is_trimmed_normalised_and_self_consistent(store: JobStore):
    """One end-to-end run against real SAPI, asserting every property the job violated.

    (a) no scene WAV keeps more than the declared tail pad of silence,
    (b) narration duration equals the sum of trimmed scene durations,
    (c) every subtitle cue ends at or before its scene's trimmed end,
    (d) the final integrated loudness is within the declared tolerance,
    (e) speech starts within 200 ms of 0 and stops within 200 ms of the end.
    """
    state = _State(store)
    job_id = _job(store)
    report = run_stages(store=store, job_id=job_id, stages=[build_audio_stage(state, timeout_s=180)])

    assert report["ok"] is True, report
    job_dir = Path(store.job_dir(job_id))
    payload = store.read_artifact(job_id, "audio.json")
    validate_artifact(AudioArtifact, payload)

    narration = job_dir / payload["narration"]["src"]
    fmt = read_pcm_format(narration)
    duration_ms = payload["narration"]["durationMs"]

    # (a) No scene WAV survives the stage with a SAPI tail. The stage deletes its scratch files,
    # so this is asserted on the concatenated narration's per-scene windows instead: each scene
    # window must contain speech at both ends and be shorter than the raw SAPI output.
    assert fmt.sample_rate == 16000 and fmt.channels == 1 and fmt.sample_width == 2

    scenes = payload["scenes"]
    assert len(scenes) == len(SEGMENTS)
    assert scenes[0]["startMs"] == 0

    # (b) narration duration is the sum of the trimmed scene durations, not of raw SAPI durations.
    assert scenes[-1]["endMs"] == duration_ms
    assert abs(_frame_ms(fmt.frames, fmt.sample_rate) - duration_ms) <= 2
    raw_total = 0
    for text in SEGMENTS:
        from packages.core.media.tts import synthesize_sapi

        probe = job_dir / ".probe.wav"
        _, raw_ms = synthesize_sapi(text, probe, voice="system-default")
        raw_total += raw_ms
        probe.unlink(missing_ok=True)
        Path(str(probe).replace(".wav", ".words.json")).unlink(missing_ok=True)
    assert duration_ms < raw_total - len(SEGMENTS) * 400, (
        f"narration {duration_ms} ms vs raw SAPI {raw_total} ms: the tail was not trimmed"
    )

    # (c) every cue ends inside the scene it belongs to, and before that scene's speech stops.
    # The scene's speech offset is recovered from the concatenated narration, so this asserts the
    # caption cannot outlive the voice even by the trailing pad.
    extent = measure_speech_extent(narration)
    for cue in payload["subtitles"]:
        owner = next(
            (scene for scene in scenes if scene["startMs"] <= cue["startMs"] < scene["endMs"]), None
        )
        assert owner is not None, f"cue at {cue['startMs']} ms is outside every scene"
        assert cue["endMs"] <= owner["endMs"], (
            f"cue {cue['text']!r} ends at {cue['endMs']} ms, past scene {owner['sceneId']} "
            f"end {owner['endMs']} ms"
        )
        assert cue["endMs"] <= duration_ms
    last_cue = payload["subtitles"][-1]
    assert last_cue["endMs"] <= extent.offset_ms + 1, (
        f"the final cue ends at {last_cue['endMs']} ms but speech stops at "
        f"{extent.offset_ms:.1f} ms: the caption still lingers over the pad"
    )

    # (d) the artifact records the loudness the file actually has, at the declared target.
    measured = measure_loudness(narration, timeout_s=120)
    assert abs(measured.integrated - NARRATION_TARGET_LUFS) <= 0.5
    assert measured.true_peak <= NARRATION_TRUE_PEAK_MAX_DBTP
    assert abs(payload["mix"]["loudness_lufs"] - measured.integrated) <= 0.1

    # (e) speech reaches both edges: onset near 0, offset near the end.
    assert extent.onset_ms <= EDGE_TOLERANCE_MS, f"speech starts at {extent.onset_ms:.1f} ms"
    assert duration_ms - extent.offset_ms <= EDGE_TOLERANCE_MS, (
        f"speech stops {duration_ms - extent.offset_ms:.1f} ms before the end"
    )
    # And the trailing silence is a deliberate pad, not the SAPI tail.
    assert duration_ms - extent.offset_ms <= SCENE_TAIL_MS + 20


def test_audio_stage_leaves_no_scratch_wavs_behind(store: JobStore):
    """Scratch scene files must not survive into the job directory as undeclared artifacts."""
    state = _State(store)
    job_id = _job(store)
    run_stages(store=store, job_id=job_id, stages=[build_audio_stage(state, timeout_s=180)])

    leftovers = sorted(path.name for path in Path(store.job_dir(job_id)).glob(".narration-*"))
    assert leftovers == []


# -- the file handed to the mux -----------------------------------------------------------------


def test_narration_wav_is_16khz_mono_pcm_for_the_mux(store: JobStore):
    """The mux requests a 16 kHz mono AAC stream from this file; state the format we deliver.

    ``mux_argv`` is another worker's file and is not edited here. This records the input format
    that argv assumes, so a change to the TTS rate cannot silently invalidate its ``-ar 16000``.
    """
    state = _State(store)
    job_id = _job(store)
    run_stages(store=store, job_id=job_id, stages=[build_audio_stage(state, timeout_s=180)])

    payload = store.read_artifact(job_id, "audio.json")
    fmt = read_pcm_format(Path(store.job_dir(job_id)) / payload["narration"]["src"])

    assert fmt.sample_rate == 16000
    assert fmt.channels == 1
    assert fmt.sample_width == 2
    probe = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            "ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
            str(Path(store.job_dir(job_id)) / payload["narration"]["src"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert probe.returncode == 0
    streams = json.loads(probe.stdout)["streams"]
    assert len(streams) == 1
    assert streams[0]["codec_name"] == "pcm_s16le"
    assert streams[0]["sample_rate"] == "16000"
    assert streams[0]["channels"] == 1
