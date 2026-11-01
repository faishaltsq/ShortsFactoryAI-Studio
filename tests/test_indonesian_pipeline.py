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

        assert len(stages) == 13
        assert [s.name for s in stages] == [
            "ResearchAgent",
            "TopicSelectionAgent",
            "ScriptAgent",
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
    ok, err = verify_voice_locale({"narration": {"voice": "Microsoft Zira Desktop"}}, "id")
    assert ok is False


def test_indonesian_neural_tts_voice_resolution():
    provider, voice = resolve_tts(language="id", requested_voice=None)
    assert isinstance(provider, EdgeTTSProvider)
    assert voice.id == "id-ID-ArdiNeural"
    assert voice.locale == "id-ID"

    provider, voice = resolve_tts(language="id", requested_voice="id-ID-GadisNeural")
    assert isinstance(provider, EdgeTTSProvider)
    assert voice.id == "id-ID-GadisNeural"
