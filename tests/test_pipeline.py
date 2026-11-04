"""The Phase 1 pipeline end to end: real stages, real artifacts, no fabricated success."""

from __future__ import annotations

import time
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


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def test_mock_job_runs_to_storyboard_ready(state, client):
    job = client.post(
        "/api/jobs", json={"title": "Uji", "topic": "sejarah", "provider_mode": "mock"}
    ).json()
    assert client.post(f"/api/jobs/{job['id']}/run").status_code == 202

    deadline = time.time() + 60
    while time.time() < deadline:
        record = state.store.get(job["id"])
        if record.state in {JobState.STORYBOARD_READY, JobState.FAILED, JobState.BLOCKED}:
            break
        time.sleep(0.1)

    record = state.store.get(job["id"])
    assert record.state is JobState.STORYBOARD_READY, (
        record.last_error or "job did not reach STORYBOARD_READY"
    )
    artifacts = state.store.list_artifacts(job["id"])
    for name in ("research.json", "topic.json", "script.json", "review.json", "storyboard.json"):
        assert name in artifacts, f"{name} missing from {artifacts}"


def test_every_artifact_validates_against_its_contract(state, client):
    from packages.core.contracts import (
        ResearchArtifact,
        ReviewArtifact,
        ScriptArtifact,
        StoryboardArtifact,
    )
    from packages.core.contracts.base import validate_artifact

    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    client.post(f"/api/jobs/{job['id']}/run")
    deadline = time.time() + 60
    while time.time() < deadline and state.store.get(job["id"]).state not in {
        JobState.STORYBOARD_READY, JobState.FAILED, JobState.BLOCKED
    }:
        time.sleep(0.1)

    pairs = {
        "research.json": ResearchArtifact,
        "topic.json": ResearchArtifact,
        "script.json": ScriptArtifact,
        "review.json": ReviewArtifact,
        "storyboard.json": StoryboardArtifact,
    }
    for name, contract in pairs.items():
        payload = state.store.read_artifact(job["id"], name)
        validate_artifact(contract, payload)


def test_events_describe_the_run(state, client):
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    client.post(f"/api/jobs/{job['id']}/run")
    deadline = time.time() + 60
    while time.time() < deadline and state.store.get(job["id"]).state not in {
        JobState.STORYBOARD_READY, JobState.FAILED, JobState.BLOCKED
    }:
        time.sleep(0.1)

    events = state.events.history(job["id"], limit=200)
    started = [e for e in events if e.event_type == "stage_started"]
    completed = [e for e in events if e.event_type == "stage_completed"]
    assert len(started) >= 5
    assert len(completed) >= 5
    agents = {e.agent_id for e in events}
    assert {"ResearchAgent", "ScriptAgent", "StoryboardAgent"} <= agents


def test_progress_one_only_appears_with_a_completed_stage(state, client):
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    client.post(f"/api/jobs/{job['id']}/run")
    deadline = time.time() + 60
    while time.time() < deadline and state.store.get(job["id"]).state not in {
        JobState.STORYBOARD_READY, JobState.FAILED, JobState.BLOCKED
    }:
        time.sleep(0.1)
    for event in state.events.history(job["id"], limit=200):
        if event.progress == 1.0:
            assert event.event_type in {"stage_completed", "artifact_reused"}


def test_a_second_run_reuses_artifacts_without_repeating_work(state, client):
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    client.post(f"/api/jobs/{job['id']}/run")
    # Wait for the run to finish, not for a state name. ``MetadataAgent`` targets
    # STORYBOARD_READY — the state the job is already in — so polling on that state can observe a
    # run that is still in flight, and the reuse assertions below would race it.
    deadline = time.time() + 60
    while time.time() < deadline and job["id"] in state.running:
        time.sleep(0.05)
    assert job["id"] not in state.running, "the first run did not finish"
    assert state.store.get(job["id"]).state in {
        JobState.STORYBOARD_READY, JobState.FAILED, JobState.BLOCKED
    }
    before = state.store.event_count(job["id"])
    usage_before = len(state.usage.for_job(job["id"]))

    # Simulate a restart: run the same chain again over the same job.
    from packages.core.orchestration.runner import run_stages

    report = run_stages(
        store=state.store, job_id=job["id"], stages=build_stages(state, job["id"])
    )
    assert report["ok"] is True
    assert all(stage.get("reused") for stage in report["stages"]), report["stages"]
    assert len(state.usage.for_job(job["id"])) == usage_before, "no repeat provider calls"
    assert state.store.event_count(job["id"]) == before, "a reuse writes no state transition"


def test_live_mode_without_a_provider_fails_rather_than_mocking(state, client, monkeypatch):
    monkeypatch.setattr(state.secrets, "resolve", lambda name: None)
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "live"}).json()
    client.post(f"/api/jobs/{job['id']}/run")
    deadline = time.time() + 60
    while time.time() < deadline and state.store.get(job["id"]).state not in {
        JobState.FAILED, JobState.BLOCKED
    }:
        time.sleep(0.1)
    record = state.store.get(job["id"])
    assert record.state in {JobState.FAILED, JobState.BLOCKED}
    assert not state.store.has_artifact(job["id"], "research.json")


def test_stages_target_reachable_states(state, client):
    """The chain must be walkable; the runner refuses to start otherwise."""
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    stages = build_stages(state, job["id"])
    assert [stage.state for stage in stages] == [
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.CREATIVE_REVIEW,
        # The creative brief is a director decision on the same review state as the visual plan.
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        # MetadataAgent has no state of its own in the allow-list; it targets the state the job is
        # already in, which ``run_stages`` treats as a no-op rather than an illegal edge.
        JobState.STORYBOARD_READY,
    ]


def test_render_stages_are_absent_unless_the_job_asks_for_video(state, client):
    """A default job must never depend on Node being installed.

    Asserting on stage names rather than mocking the renderer is deliberate: the guarantee is
    that the chain does not contain the render stage at all, so nothing can reach a subprocess.
    """
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    stages = build_stages(state, job["id"])
    names = [stage.name for stage in stages]
    assert "EditorAgent" not in names, "no render stage without render_video"
    assert "QualityAgent" not in names, "no technical QC without render_video"
    assert names == [
        "ResearchAgent",
        "TopicSelectionAgent",
        "ScriptAgent",
        "CreativeDirectorAgent",
        "CreativeDirectorAgent",
        # The film's creative identity, decided after the visual plan and before the shots.
        "CreativeDirectorAgent",
        "StoryboardAgent",
        # Metadata is a provider call, not a render: it belongs in the agent-only chain, and the
        # publish stage reads it. It is last because it is derived from the script.
        "MetadataAgent",
    ]


def test_render_stages_walk_through_assets_audio_and_both_qc_gates(state, client):
    """The real chain: assets, audio, motion, render, technical QC, editorial QC.

    Motion code is generated after the narration it has to sync to and before the renderer that
    reads it, so the motion stage sits between audio and render rather than before assets.

    Exactly one technical stage exists. The old one in ``media/render.py`` wrote ``qc.json``
    before any detector ran; it is gone, so ``QualityAgent`` appears once per gate and the
    artifacts are ``technical-qc.json`` then ``qc.json`` + ``readiness.json``.
    """
    job = client.post(
        "/api/jobs",
        json={
            "title": "Uji",
            "provider_mode": "mock",
            "render_video": True,
            "voice": "system-default",
        },
    ).json()
    stages = build_stages(state, job["id"])
    assert [stage.name for stage in stages][-7:] == [
        "AssetAgent",
        "AudioAgent",
        "AnimationAgent",
        "RenderAgent",
        "QualityAgent",
        "QualityAgent",
        "DirectorAgent",
    ]
    assert [stage.state for stage in stages][-7:] == [
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.MOTION_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ]
    assert stages[-3].produces == ("technical-qc.json",)
    assert stages[-2].produces == ("qc.json",)
    assert stages[-1].produces == ("readiness.json",)


def test_the_render_chain_is_reachable_without_an_illegal_transition(state, client):
    """The runner refuses a chain whose targets are not reachable; this proves the wiring."""
    from packages.core.orchestration.runner import _validate_chain

    job = client.post(
        "/api/jobs",
        json={"title": "Uji", "provider_mode": "mock", "render_video": True,
              "voice": "system-default"},
    ).json()
    stages = build_stages(state, job["id"])
    # From the storyboard on: an index would silently test the wrong stages the next time a stage
    # is added before it, which is exactly what happened when the brief stage appeared.
    storyboard_at = next(
        index for index, stage in enumerate(stages) if stage.name == "StoryboardAgent"
    )
    _validate_chain(JobState.STORYBOARD_READY, stages[storyboard_at:])
    assert stages[-1].state is JobState.READY_FOR_APPROVAL


def test_pipeline_stops_or_revises_on_static_scene_qc_failure(state: Any) -> None:
    from packages.core.contracts.artifacts import StoryboardArtifact
    from packages.core.orchestration.leases import LeaseKeeper
    from packages.core.orchestration.pipeline import (
        MAX_SCENE_REPAIRS,
        apply_scene_repairs,
        run_job,
    )

    storyboard = {
        "schema_version": "1.0",
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 60,
                "text": [{"id": "t1", "text": "Intro", "role": "title", "atFrame": 0}],
                "camera": {"shot": "wide", "move": "static", "amplitude": 0.12},
                "motion": {"energy": 0.2, "continuity": "cut", "beats": []},
                "transition": {"kind": "cut", "frames": 0},
                "data": {"layout_mode": "DefaultHero", "objects": []},
            }
        ],
    }

    # Verify apply_scene_repairs upgrades failing scene and validates against contract
    revised = apply_scene_repairs(storyboard, ["sc1"], attempt=1)
    validated = StoryboardArtifact.model_validate(revised)
    assert validated is not None
    repaired_sc1 = revised["scenes"][0]
    assert repaired_sc1["camera"]["move"] in ("pan", "push")
    assert repaired_sc1["camera"]["target"] == "t1"
    assert repaired_sc1["motion"]["energy"] > 0.3
    assert repaired_sc1["motion"]["continuity"] in ("carry", "cut")
    assert len(repaired_sc1["motion"]["beats"]) >= 2
    assert repaired_sc1["data"]["layout_mode"] != "DefaultHero"
    assert "causal_action" in repaired_sc1["data"]

    # Verify run_job bounded loop stops after MAX_SCENE_REPAIRS attempts
    job = state.store.create(title="Uji Bounded Revision", payload={"provider_mode": "mock"}, state=JobState.BLOCKED)
    job_id = job.id
    state.store.write_artifact(job_id, "storyboard.json", storyboard)
    state.store.write_artifact(
        job_id,
        "qc.json",
        {
            "schema_version": 1,
            "technical": {"passed": True},
            "creative": {
                "passed": False,
                "metrics": {
                    "bme_dynamics": {
                        "passed": False,
                        "static_scenes": ["sc1"],
                        "scene_metrics": [{"sceneId": "sc1", "delta_bm": 0.0, "delta_me": 0.0, "static": True}],
                    }
                },
            },
            "visual": {"status": "passed", "frames_inspected": 1},
            "repairs": [],
        },
    )
    keeper = LeaseKeeper(state.settings.db_path, owner="test-worker")
    keeper.acquire(job_id)

    # 1. First attempt: qa_repair_required applies repair and resets to STORYBOARD_READY
    import packages.core.orchestration.pipeline as pipeline_mod

    call_count = 0

    def fake_run_stages(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"ok": False, "stopped": "qa_repair_required", "stages": []}
        # Second call returns ok=True to finish
        return {"ok": True, "stages": []}

    orig_run_stages = pipeline_mod.run_stages
    pipeline_mod.run_stages = fake_run_stages
    try:
        report = run_job(state, job_id, keeper=keeper)
        assert report["ok"] is True
        assert call_count == 2
        # Check scene_repairs.json recorded attempt 1
        repairs_art = state.store.read_artifact(job_id, "scene_repairs.json")
        assert repairs_art["attempts"]["sc1"] == 1
    finally:
        pipeline_mod.run_stages = orig_run_stages

    # 2. Exceeded attempts: stops at qa_repair_limit
    job2 = state.store.create(title="Uji Cap", payload={"provider_mode": "mock"}, state=JobState.BLOCKED)
    job2_id = job2.id
    state.store.write_artifact(job2_id, "storyboard.json", storyboard)
    state.store.write_artifact(
        job2_id,
        "qc.json",
        {
            "schema_version": 1,
            "technical": {"passed": True},
            "creative": {
                "passed": False,
                "metrics": {
                    "bme_dynamics": {
                        "passed": False,
                        "static_scenes": ["sc1"],
                        "scene_metrics": [{"sceneId": "sc1", "delta_bm": 0.0, "delta_me": 0.0, "static": True}],
                    }
                },
            },
            "visual": {"status": "passed", "frames_inspected": 1},
            "repairs": [],
        },
    )
    state.store.write_artifact(
        job2_id,
        "scene_repairs.json",
        {"attempts": {"sc1": MAX_SCENE_REPAIRS}, "history": []},
    )
    keeper2 = LeaseKeeper(state.settings.db_path, owner="test-worker")
    keeper2.acquire(job2_id)

    pipeline_mod.run_stages = lambda *args, **kwargs: {"ok": False, "stopped": "qa_repair_required", "stages": []}
    try:
        report2 = run_job(state, job2_id, keeper=keeper2)
        assert report2["ok"] is False
        assert report2["stopped"] == "qa_repair_limit"
        assert "repair limit" in (state.store.get(job2_id).last_error or "").lower()
    finally:
        pipeline_mod.run_stages = orig_run_stages

