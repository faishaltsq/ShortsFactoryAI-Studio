"""Two-pass timing: motion code is written against the narration it has to sync to.

Pass 1 plans and synthesises; pass 2 generates motion code from the *measured* narration. The
dangerous failure is the quiet one — a job that resumed past the audio stage keeping animation
timed against a provisional estimate, which looks like the two-pass workflow while being the
one-pass one.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from packages.core.orchestration.pipeline import build_stages
from packages.core.providers.usage import Budget


@pytest.fixture
def state(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    return AppState.build(settings, budget=Budget())


def _job(state: Any, *, renderer: str) -> str:
    job = state.store.create(
        title="Timing",
        payload={
            "provider_mode": "mock",
            "render_video": True,
            "renderer": renderer,
            "voice": "system-default",
        },
    )
    return job.id


def _audio(scene_ids: list[str], *, duration_ms: int = 9_000) -> dict[str, Any]:
    """A minimal, contract-valid ``audio.json`` with contiguous scene timings."""
    span = duration_ms // len(scene_ids)
    scenes = []
    cursor = 0
    for index, scene_id in enumerate(scene_ids):
        end = duration_ms if index == len(scene_ids) - 1 else cursor + span
        scenes.append({"sceneId": scene_id, "startMs": cursor, "endMs": end})
        cursor = end
    return {
        "schema_version": 1,
        "narration": {"src": "narration.wav", "durationMs": duration_ms, "voice": "system-default"},
        "scenes": scenes,
        "subtitles": [],
        "words": [],
        "mix": {"music": None, "music_gain_db": None, "ducking": False, "loudness_lufs": -16},
    }


def test_the_motion_stage_runs_between_audio_and_render(state) -> None:
    """The ordering *is* the feature: before audio, the coder has no measured timing to sync to."""
    job_id = _job(state, renderer="custom-motion")
    stages = build_stages(state, job_id)
    names = [stage.name for stage in stages]
    assert names.index("AudioAgent") < names.index("MotionCoderAgent") < names.index("RenderAgent")
    motion = stages[names.index("MotionCoderAgent")]
    assert motion.state is JobState.MOTION_READY
    assert motion.produces == ("motion-code.json",)


def test_the_legacy_motion_stage_moved_with_it(state) -> None:
    """Both renderers take the same hop, so a job cannot skip the measured timing by choosing the
    other motion stage."""
    job_id = _job(state, renderer="remotion")
    stages = build_stages(state, job_id)
    names = [stage.name for stage in stages]
    assert names.index("AudioAgent") < names.index("AnimationAgent") < names.index("RenderAgent")
    assert stages[names.index("AnimationAgent")].state is JobState.MOTION_READY


def _motion_stage(state: Any, job_id: str):
    stages = build_stages(state, job_id)
    return next(stage for stage in stages if stage.name == "MotionCoderAgent")


def _write_motion_code(state: Any, job_id: str, timing_sha: str) -> None:
    state.store.write_artifact(
        job_id,
        "motion-code.json",
        {
            "schema_version": 1,
            "entry_component": "RootComposition",
            "files": {"RootComposition.tsx": "export const RootComposition = () => null;"},
            "dependencies": ["react", "remotion"],
            "skill_hashes": [],
            "validated_by_codeguard": True,
            "issues": [],
            "narration_timing_sha256": timing_sha,
            "timing_source": "measured" if timing_sha else "estimated",
        },
    )


def test_motion_code_timed_against_the_current_narration_is_reused(state) -> None:
    from packages.core.orchestration.pipeline import _narration_timing_digest

    job_id = _job(state, renderer="custom-motion")
    state.store.write_artifact(job_id, "storyboard.json", {
        "schema_version": 1, "fps": 30, "width": 1080, "height": 1920, "theme": "editorialLight",
        "scenes": [{
            "sceneId": "sc1", "template": "ObjectExplainer", "segment": "s1",
            "startFrame": 0, "durationInFrames": 300,
        }],
        "subtitles": [],
    })
    state.store.write_artifact(job_id, "audio.json", _audio(["sc1"]))
    digest = _narration_timing_digest(state.store, job_id)
    assert digest, "a contract-valid audio artifact must produce a digest"
    _write_motion_code(state, job_id, digest)

    stage = _motion_stage(state, job_id)
    assert stage.done_when is not None
    recorded = state.store.read_artifact(job_id, "motion-code.json")
    assert stage.done_when(recorded, job_id) is True


def test_motion_code_timed_against_a_different_narration_is_not_reused(state) -> None:
    """The whole point of the guard: animation timed to a narration that has since changed must be
    regenerated, exactly as a re-render expires a QC verdict."""
    from packages.core.orchestration.pipeline import _narration_timing_digest

    job_id = _job(state, renderer="custom-motion")
    state.store.write_artifact(job_id, "storyboard.json", {
        "schema_version": 1, "fps": 30, "width": 1080, "height": 1920, "theme": "editorialLight",
        "scenes": [{
            "sceneId": "sc1", "template": "ObjectExplainer", "segment": "s1",
            "startFrame": 0, "durationInFrames": 300,
        }],
        "subtitles": [],
    })
    state.store.write_artifact(job_id, "audio.json", _audio(["sc1"], duration_ms=9_000))
    first = _narration_timing_digest(state.store, job_id)

    # Re-voiced: the same scenes, a different measured length.
    state.store.write_artifact(job_id, "audio.json", _audio(["sc1"], duration_ms=12_000))
    second = _narration_timing_digest(state.store, job_id)
    assert first != second

    _write_motion_code(state, job_id, first)
    stage = _motion_stage(state, job_id)
    recorded = state.store.read_artifact(job_id, "motion-code.json")
    assert stage.done_when is not None
    assert stage.done_when(recorded, job_id) is False


def test_motion_code_from_before_any_timing_is_not_reused(state) -> None:
    """An artifact with no digest was written before a measurement existed — the case the field is
    there to make visible rather than silently accept."""
    job_id = _job(state, renderer="custom-motion")
    state.store.write_artifact(job_id, "audio.json", _audio(["sc1"]))
    _write_motion_code(state, job_id, "")
    stage = _motion_stage(state, job_id)
    recorded = state.store.read_artifact(job_id, "motion-code.json")
    assert stage.done_when is not None
    assert stage.done_when(recorded, job_id) is False


def test_the_timing_digest_ignores_what_the_code_does_not_sync_to(state) -> None:
    """A mix or file-name change must not expire correctly timed animation."""
    from packages.core.orchestration.pipeline import _narration_timing_digest

    job_id = _job(state, renderer="custom-motion")
    state.store.write_artifact(job_id, "audio.json", _audio(["sc1", "sc2"]))
    before = _narration_timing_digest(state.store, job_id)

    renamed = _audio(["sc1", "sc2"])
    renamed["narration"]["src"] = "other.wav"
    renamed["mix"]["loudness_lufs"] = -14
    state.store.write_artifact(job_id, "audio.json", renamed)
    assert _narration_timing_digest(state.store, job_id) == before

    moved = _audio(["sc1", "sc2"], duration_ms=10_000)
    state.store.write_artifact(job_id, "audio.json", moved)
    assert _narration_timing_digest(state.store, job_id) != before


def test_the_stamp_is_written_by_code_never_by_the_model(state) -> None:
    """A digest echoed by the model is a claim; the runner's guard compares a fact."""
    from packages.core.orchestration.pipeline import _motion_timing_stamp

    job_id = _job(state, renderer="custom-motion")
    state.store.write_artifact(job_id, "audio.json", _audio(["sc1"]))
    claimed = {"narration_timing_sha256": "f" * 64, "timing_source": "measured"}
    _motion_timing_stamp(state.store, job_id, claimed)
    assert claimed["narration_timing_sha256"] != "f" * 64, "the model's value is overwritten"
    assert len(claimed["narration_timing_sha256"]) == 64

    # And with no audio artifact at all, the stamp records that fact rather than guessing.
    other = _job(state, renderer="custom-motion")
    empty: dict[str, Any] = {}
    _motion_timing_stamp(state.store, other, empty)
    assert empty["narration_timing_sha256"] == ""
    assert empty["timing_source"] == "estimated"


def test_the_timing_context_reports_measured_frames_and_keeps_the_estimate(state) -> None:
    """Two numbers with different provenance beat one number whose origin is unstated."""
    from packages.core.orchestration.pipeline import _narration_timing_context

    job_id = _job(state, renderer="custom-motion")
    storyboard = {
        "fps": 30,
        "scenes": [
            {"sceneId": "sc1", "startFrame": 0, "durationInFrames": 300},
            {"sceneId": "sc2", "startFrame": 300, "durationInFrames": 240},
        ],
    }
    state.store.write_artifact(job_id, "audio.json", _audio(["sc1", "sc2"], duration_ms=18_000))
    context = _narration_timing_context(state.store, job_id, storyboard)
    assert context["source"] == "measured"
    assert [slot["sceneId"] for slot in context["scenes"]] == ["sc1", "sc2"]
    assert context["scenes"][0]["durationFrames"] == 270  # 9000 ms at 30 fps
    assert context["scenes"][0]["estimatedDurationFrames"] == 300, "the estimate is kept"
    assert context["durationMs"] == 18_000

    # A job with no audio yet reports the estimate and says so.
    bare = _job(state, renderer="custom-motion")
    unmeasured = _narration_timing_context(state.store, bare, storyboard)
    assert unmeasured["source"] == "estimated"
    assert "provisional" in unmeasured["note"]


def test_the_two_pass_order_is_reachable_without_an_illegal_transition(state) -> None:
    """``AUDIO_READY -> MOTION_READY -> RENDERING``, not a jump the allow-list would refuse."""
    from packages.core.contracts.state import assert_transition

    job_id = _job(state, renderer="custom-motion")
    stages = build_stages(state, job_id)
    from packages.core.orchestration.runner import _validate_chain

    _validate_chain(JobState.IDEA_DISCOVERY, stages)
    assert_transition(JobState.AUDIO_READY, JobState.MOTION_READY)
    assert_transition(JobState.MOTION_READY, JobState.RENDERING)


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def test_a_mock_motion_job_records_the_timing_source_it_used(state, client) -> None:
    """No audio artifact exists yet in this job, so the stamp must say ``estimated`` rather than
    claim a measurement nobody took."""
    job = client.post(
        "/api/jobs",
        json={
            "title": "Uji",
            "provider_mode": "mock",
            "render_video": True,
            "renderer": "custom-motion",
            "voice": "system-default",
        },
    ).json()
    storyboard = {"scenes": [{"sceneId": "sc1", "durationInFrames": 300}]}
    from packages.core.orchestration.pipeline import _motion_timing_stamp

    payload: dict[str, Any] = {}
    _motion_timing_stamp(state.store, job["id"], payload)
    assert payload["timing_source"] == "estimated"
    assert storyboard["scenes"][0]["durationInFrames"] == 300