"""The Phase 1 pipeline end to end: real stages, real artifacts, no fabricated success."""

from __future__ import annotations

import time

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


def test_live_mode_without_a_provider_fails_rather_than_mocking(state, client):
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
        "StoryboardAgent",
        # Metadata is a provider call, not a render: it belongs in the agent-only chain, and the
        # publish stage reads it. It is last because it is derived from the script.
        "MetadataAgent",
    ]


def test_render_stages_walk_through_assets_audio_and_both_qc_gates(state, client):
    """The real chain: assets, audio, render, technical QC, editorial QC.

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
    assert [stage.name for stage in stages][-6:] == [
        "AssetAgent",
        "AudioAgent",
        "RenderAgent",
        "QualityAgent",
        "QualityAgent",
        "DirectorAgent",
    ]
    assert [stage.state for stage in stages][-6:] == [
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
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
    _validate_chain(JobState.STORYBOARD_READY, stages[5:])
    assert stages[-1].state is JobState.READY_FOR_APPROVAL
