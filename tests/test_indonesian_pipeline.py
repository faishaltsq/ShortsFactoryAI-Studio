"""End-to-end Indonesian voice and anti-slop visual pipeline verification."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from packages.core.agents.concrete import StoryboardAgent
from packages.core.contracts.state import JobState
from packages.core.media.qc import verify_voice_locale
from packages.core.media.render import merge_motion_plan_into_storyboard
from packages.core.media.tts import (
    EdgeTTSProvider,
    resolve_tts,
)
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.pipeline import build_stages
from packages.core.orchestration.runner import _validate_chain
from packages.core.providers.mock import MockProvider


def test_indonesian_pipeline_stages_and_chain():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        store = JobStore(root / "db.sqlite", root / "jobs")
        job = store.create(
            title="Misteri Mimpi REM",
            payload={
                "provider_mode": "mock",
                "render_video": True,
                "topic": "Bagaimana otak memproses mimpi selama fase tidur REM?",
                "language": "id",
                "voice": "id-ID-ArdiNeural",
            },
        )

        class DummyState:
            def __init__(self, s: JobStore) -> None:
                self.store = s
                self.lock = None
                self.provider = MockProvider()

        state = DummyState(store)
        stages = build_stages(state, job.id)

        assert len(stages) == 14
        assert [s.name for s in stages] == [
            "ResearchAgent",
            "TopicSelectionAgent",
            "ScriptAgent",
            "CreativeDirectorAgent",
            "CreativeDirectorAgent",
            "StoryboardAgent",
            "MetadataAgent",
            "AnimationAgent",
            "AssetAgent",
            "AudioAgent",
            "RenderAgent",
            "QualityAgent",
            "QualityAgent",
            "DirectorAgent",
        ]
        _validate_chain(JobState.TOPIC_SELECTED, stages)
        assert stages[-1].state is JobState.READY_FOR_APPROVAL


def test_storyboard_sanitizer_injects_topic_objects():
    agent = StoryboardAgent.__new__(StoryboardAgent)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "text": [{"id": "t1", "text": "Otak memproses mimpi saat tidur REM"}],
                "data": {},
            },
            {
                "sceneId": "sc2",
                "template": "ObjectExplainer",
                "text": [{"id": "t2", "text": "Struktur DNA dan kode genetik manusia"}],
                "data": {},
            },
            {
                "sceneId": "sc3",
                "template": "ObjectExplainer",
                "text": [{"id": "t3", "text": "Reaksi kimia dalam lab laboratorium"}],
                "data": {},
            },
        ],
    }
    sanitized = agent.sanitize_payload(payload)
    scenes = sanitized["scenes"]

    # Brain/memory copy gets the neural objects, not a character standing beside a brain icon.
    objects1 = scenes[0]["data"]["objects"]
    assert len(objects1) > 0
    assert objects1[0]["kind"] in ("neuralNet", "database", "gpu")

    # A topic with no object of its own still gets a real stage rather than a blank frame.
    for scene in scenes:
        assert scene["data"]["objects"], scene["sceneId"]
        assert scene["data"]["environment"] in {
            "dataCenter", "circuit", "space", "lab", "city", "grid", "abstract"
        }, scene["sceneId"]


def test_merge_motion_plan_into_storyboard():
    storyboard: dict[str, Any] = {
        "scenes": [
            {
                "sceneId": "sc1",
                "motion": {"beats": []},
            }
        ]
    }
    motion_plan: dict[str, Any] = {
        "style_brief": {"theme": "neuroscience"},
        "scenes": [
            {
                "sceneId": "sc1",
                "camera_path": {"pan": [0, 0.2], "zoom": [1.0, 1.1]},
                "beats": [{"frame": 15, "type": "pulse"}],
            }
        ],
    }

    merged = merge_motion_plan_into_storyboard(storyboard, motion_plan)
    sc = merged["scenes"][0]
    assert sc["motion"]["beats"] == [{"atFrame": 15, "kind": "emphasis", "subject": "object:0"}]
    # `style_brief` stays on the motion plan. Copying it into `scene.data` put a field the
    # renderer's own validator rejects into the payload it has to render, which failed the render.
    assert sc.get("data", {}) == {}
    assert sc["camera"] == {} or "move" not in sc["camera"]


def test_verify_voice_locale_strict_rejection():
    # Valid Indonesian neural voices
    ok, _ = verify_voice_locale({"narration": {"voice": "id-ID-ArdiNeural", "locale": "id-ID"}}, "id")
    assert ok is True

    ok, _ = verify_voice_locale({"narration": {"voice": "id-ID-GadisNeural", "locale": "id-ID"}}, "id-ID")
    assert ok is True

    # English voice with id language must fail
    ok, err = verify_voice_locale({"narration": {"voice": "Microsoft David Desktop", "locale": "en-US"}}, "id")
    assert ok is False
    assert "does not match Indonesian" in err

    # SAPI default on id job must fail
    ok, _ = verify_voice_locale({"narration": {"voice": "Microsoft Zira Desktop"}}, "id")
    assert ok is False


def test_indonesian_neural_tts_voice_resolution() -> None:
    provider, voice = resolve_tts(language="id", requested_voice=None)
    assert isinstance(provider, EdgeTTSProvider)
    assert voice.id == "id-ID-ArdiNeural"
    assert voice.locale == "id-ID"

    provider, voice = resolve_tts(language="id", requested_voice="id-ID-GadisNeural")
    assert isinstance(provider, EdgeTTSProvider)
    assert voice.id == "id-ID-GadisNeural"


def test_audio_stage_supports_voicestudio_provider() -> None:
    from packages.core.media.tts import VoiceStudioProvider, select_tts_provider

    provider = select_tts_provider("voicestudio")
    assert provider == "voicestudio"
    tts_prov, tts_voice = resolve_tts("id", requested_provider="voicestudio", requested_voice="alloy")
    assert isinstance(tts_prov, VoiceStudioProvider)
    assert tts_voice.provider == "voicestudio"


def test_mux_argv_preserves_audio_sample_rate() -> None:
    from packages.core.media.render import mux_argv

    argv = mux_argv(Path("video.mp4"), Path("audio.wav"), Path("out.mp4"), sample_rate=24000)
    assert "-ar" in argv
    idx = argv.index("-ar")
    assert argv[idx + 1] == "24000"
    assert "-b:a" in argv
    b_idx = argv.index("-b:a")
    assert argv[b_idx + 1] == "128k"


def test_audio_stage_voicestudio_preserves_24khz_sample_rate_and_word_timestamps(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import io
    import math
    import shutil
    import struct
    import wave

    import pytest

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe required for audio stage test")

    from packages.core.contracts.artifacts import AudioArtifact
    from packages.core.contracts.base import validate_artifact
    from packages.core.contracts.scene import WordTimestamp
    from packages.core.media.tts import build_audio_stage, read_pcm_format
    from packages.core.media.voicestudio import VoiceStudioAdapter, VoiceStudioResult
    from packages.core.orchestration.runner import NullCancel, StageContext

    def _tone_wav(sample_rate: int = 24000, duration_s: float = 1.0) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            frames = int(sample_rate * duration_s)
            raw = bytearray()
            for i in range(frames):
                val = int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate))
                raw.extend(struct.pack("<h", val))
            wf.writeframes(bytes(raw))
        return buf.getvalue()

    fake_wav_bytes = _tone_wav(sample_rate=24000, duration_s=1.0)

    def fake_synthesize(self: Any, text: str, **kwargs: Any) -> VoiceStudioResult:
        words = text.split()
        timestamps = []
        curr = 0
        step = int(1000 / len(words)) if words else 1000
        for i, w in enumerate(words):
            end = 1000 if i == len(words) - 1 else curr + step
            timestamps.append({"word": w, "startMs": curr, "endMs": end})
            curr = end
        return VoiceStudioResult(
            audio_bytes=fake_wav_bytes,
            sample_rate=24000,
            duration_s=1.0,
            word_timestamps=timestamps,
        )

    monkeypatch.setattr(VoiceStudioAdapter, "synthesize", fake_synthesize)

    store = JobStore(tmp_path / "db.sqlite", tmp_path / "jobs")
    job = store.create(
        title="Uji VoiceStudio 24kHz",
        payload={
            "provider_mode": "mock",
            "language": "id",
            "tts_provider": "voicestudio",
            "voice": "alloy",
        },
    )
    job_id = job.id
    store.write_artifact(
        job_id,
        "script.json",
        {
            "schema_version": "1.0",
            "hook": "Halo dunia",
            "core_message": "Ini tes",
            "cta": "Penutup",
            "duration_target_seconds": 2,
            "target_word_count": 6,
            "segments": [
                {"id": "sc1", "text": "Halo dunia suara alami"},
                {"id": "sc2", "text": "Kecerdasan buatan lokal"},
            ],
        },
    )
    store.write_artifact(
        job_id,
        "storyboard.json",
        {
            "schema_version": "1.0",
            "totalScenes": 2,
            "scenes": [
                {"sceneId": "sc1", "segment": "sc1"},
                {"sceneId": "sc2", "segment": "sc2"},
            ],
        },
    )

    class _Events:
        def __init__(self) -> None:
            self.rows: list[dict[str, Any]] = []

        def emit(self, **kwargs: Any) -> None:
            self.rows.append(kwargs)

    class _State:
        def __init__(self, s: Any) -> None:
            self.store = s
            self.events = _Events()

    state = _State(store)
    stage = build_audio_stage(state)
    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    ctx = StageContext(store, job_id, staging, cancel=NullCancel())
    outcome = stage.run(ctx)
    assert outcome.ok is True

    # Check narration.wav sample rate is preserved at 24000 Hz
    narration_path = dict(ctx.files_pending)["narration.wav"]
    assert narration_path.is_file()
    fmt = read_pcm_format(narration_path)
    assert fmt.sample_rate == 24000

    # Check audio.json
    audio_json = dict(ctx.json_pending)["audio.json"]
    validate_artifact(AudioArtifact, audio_json)
    assert audio_json["narration"]["provider"] == "voicestudio"
    assert audio_json["narration"]["voice"] == "alloy"

    # Verify word timestamps
    words = audio_json["words"]
    assert len(words) == 7  # 4 words in sc1 + 3 words in sc2
    for w in words:
        WordTimestamp.model_validate(w)
        assert w["endMs"] > w["startMs"]

