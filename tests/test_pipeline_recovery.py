"""Durable recovery and bounded script revisions, isolated from operator state."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from packages.core.orchestration.leases import LeaseKeeper
from packages.core.orchestration.pipeline import MAX_REVISIONS, build_stages, run_job
from packages.core.orchestration.runner import run_stages
from packages.core.providers.mock import MockProvider
from packages.core.providers.usage import Budget


class RevisionProvider(MockProvider):
    def __init__(self, *, revisions=1, changed=True):
        super().__init__()
        self.revisions = revisions
        self.changed = changed
        self.sent = []
        self.scripts = []
        self.reviews = 0

    def complete(self, call, *, system, user, task):
        self.sent.append({"task": task, "user": user})
        result = super().complete(call, system=system, user=user, task=task)
        payload = json.loads(result.content)
        if task == "review":
            self.reviews += 1
            payload = {
                "schema_version": 1,
                "verdict": "revise" if self.reviews <= self.revisions else "accept",
                "scores": {"hook": 0.4},
                "findings": [{"segment_id": "s1", "issue": "missing consequence", "fix": "show the consequence"}]
                if self.reviews <= self.revisions else [],
                "attempt": self.reviews - 1,
            }
        elif task == "script":
            if self.scripts:
                payload = dict(self.scripts[-1])
                if self.changed:
                    payload["hook"] = f"Revised consequence {len(self.scripts)}"
            self.scripts.append(payload)
        return replace(result, content=json.dumps(payload))


@pytest.fixture
def state(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data", db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs", secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    return AppState.build(settings, budget=Budget())


def _run(state, job_id):
    keeper = LeaseKeeper(state.store.db_path, owner="recovery-test")
    keeper.acquire(job_id)
    try:
        return run_job(state, job_id, keeper=keeper)
    finally:
        keeper.release()


def _job(state, provider):
    state.transports["mock"] = provider
    return state.store.create(title="recovery", payload={"provider_mode": "mock"})


def test_a_revision_receives_findings_changes_content_and_reaches_storyboard(state):
    provider = RevisionProvider()
    job = _job(state, provider)

    report = _run(state, job.id)

    assert report["ok"] is True, report
    assert state.store.get(job.id).state is JobState.STORYBOARD_READY
    assert len(provider.scripts) == 2
    revision_prompt = [call["user"] for call in provider.sent if call["task"] == "script"][1]
    assert "missing consequence" in revision_prompt
    assert provider.scripts[0]["hook"] in revision_prompt
    ledger = state.store.read_artifact(job.id, "revisions.json")
    attempt = ledger["attempts"][0]
    assert attempt["phase"] == "applied"
    assert attempt["before_script"]["hook"] == provider.scripts[0]["hook"]
    assert attempt["candidate_script"]["hook"] == provider.scripts[1]["hook"]
    assert state.store.read_artifact(job.id, "script.json")["hook"] == provider.scripts[1]["hook"]
    assert not state.store.active_stages([job.id])
    assert not state.store.get(job.id).last_error


def test_an_unchanged_revision_blocks_without_invalidating_existing_outputs(state):
    provider = RevisionProvider(changed=False)
    job = _job(state, provider)
    state.store.write_artifact(job.id, "storyboard.json", {"sentinel": "existing downstream evidence"})

    report = _run(state, job.id)

    assert report["ok"] is False
    assert report["stopped"] == "revision_unchanged"
    assert state.store.get(job.id).state is JobState.BLOCKED
    assert state.store.read_artifact(job.id, "storyboard.json")["sentinel"]
    before = list(provider.sent)
    assert _run(state, job.id)["stopped"] == "revision_unchanged"
    assert provider.sent == before
    assert state.store.read_artifact(job.id, "revisions.json")["attempts"][0]["phase"] == "unchanged"


def test_the_revision_ceiling_survives_a_restart(state):
    provider = RevisionProvider(revisions=99)
    job = _job(state, provider)

    report = _run(state, job.id)

    assert report["stopped"] == "revision_limit"
    assert state.store.get(job.id).state is JobState.BLOCKED
    assert len(provider.scripts) == MAX_REVISIONS + 1
    assert len(state.store.read_artifact(job.id, "revisions.json")["attempts"]) == MAX_REVISIONS
    restarted = AppState.build(state.settings, budget=Budget())
    restarted.transports["mock"] = provider
    calls = list(provider.sent)
    assert _run(restarted, job.id)["stopped"] == "revision_limit"
    assert provider.sent == calls
    assert not state.store.has_artifact(job.id, "storyboard.json")


class ProcessCrash(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["prepared", "generated", "promotion"])
def test_a_revision_recovers_durable_boundaries_without_duplicate_completions(state, monkeypatch, boundary):
    provider = RevisionProvider()
    job = _job(state, provider)
    state.store.write_artifact(job.id, "storyboard.json", {"sentinel": "preserve until decision"})
    commit = state.store.commit_stage
    crashed = False

    def interrupt(*args, **kwargs):
        nonlocal crashed
        pending = dict(kwargs.get("json_artifacts") or [])
        ledger = pending.get("revisions.json")
        phase = ledger["attempts"][-1]["phase"] if ledger and ledger["attempts"] else None
        if not crashed and ((phase == boundary) or (boundary == "promotion" and phase == "applied")):
            crashed = True
            if boundary == "promotion":
                # Simulate promotion interrupted after the new script but before its marker.
                partial = dict(kwargs)
                partial["json_artifacts"] = [("script.json", pending["script.json"])]
                commit(*args, **partial)
                raise ProcessCrash()
            commit(*args, **kwargs)
            raise ProcessCrash()
        return commit(*args, **kwargs)

    monkeypatch.setattr(state.store, "commit_stage", interrupt)
    with pytest.raises(ProcessCrash):
        _run(state, job.id)
    monkeypatch.setattr(state.store, "commit_stage", commit)
    if boundary == "generated":
        recorded = state.store.read_artifact(job.id, "revisions.json")["attempts"][0]
        assert recorded["phase"] == "generated"
        assert recorded["candidate_script"]["hook"] != recorded["before_script"]["hook"]
        assert state.store.read_artifact(job.id, "storyboard.json")["sentinel"]
        assert state.store.read_artifact(job.id, "script.json")["hook"] == recorded["before_script"]["hook"]
    restarted = AppState.build(state.settings, budget=Budget())
    restarted.transports["mock"] = provider

    report = _run(restarted, job.id)

    assert report["ok"] is True, report
    assert len(provider.scripts) == 2
    assert provider.reviews == 2
    assert restarted.store.get(job.id).state is JobState.STORYBOARD_READY
    ledger = restarted.store.read_artifact(job.id, "revisions.json")
    assert len(ledger["attempts"]) == 1
    assert ledger["attempts"][0]["phase"] == "applied"
    assert "sentinel" not in restarted.store.read_artifact(job.id, "storyboard.json")
    for task in ("research", "topic"):
        assert sum(call["task"] == task for call in provider.sent) == 1


def test_a_completed_revision_response_replays_after_artifact_promotion_crashes(state, monkeypatch):
    provider = RevisionProvider()
    job = _job(state, provider)
    commit = state.store.commit_stage
    crashed = False

    def interrupt(*args, **kwargs):
        nonlocal crashed
        if not crashed and "revision-1-script.json" in dict(kwargs.get("json_artifacts") or []):
            crashed = True
            raise ProcessCrash()
        return commit(*args, **kwargs)

    monkeypatch.setattr(state.store, "commit_stage", interrupt)
    with pytest.raises(ProcessCrash):
        _run(state, job.id)
    monkeypatch.setattr(state.store, "commit_stage", commit)
    restarted = AppState.build(state.settings, budget=Budget())
    restarted.transports["mock"] = provider

    assert _run(restarted, job.id)["ok"] is True
    assert len(provider.scripts) == 2
    assert provider.reviews == 2


@pytest.mark.parametrize("current", [JobState.RENDERING, JobState.TECHNICAL_QC, JobState.EDITORIAL_QC])
def test_advanced_pipeline_resume_reuses_valid_upstream_without_provider_calls(state, current):
    provider = RevisionProvider(revisions=0)
    job = _job(state, provider)
    assert _run(state, job.id)["ok"] is True
    # Reuse real agent artifacts, then let the real QC gate reject absent local media inputs.
    for target in (JobState.ASSETS_READY, JobState.AUDIO_READY, JobState.MOTION_READY,
                   JobState.RENDERING, JobState.TECHNICAL_QC, JobState.EDITORIAL_QC):
        state.store.transition(job.id, target)
        if target is current:
            break
    calls = list(provider.sent)
    stages = build_stages(state, job.id)
    from packages.core.orchestration.editorial import (
        build_editorial_qc_stage,
        build_technical_qc_stage,
    )
    stages.append(
        build_editorial_qc_stage(state) if current is JobState.EDITORIAL_QC
        else build_technical_qc_stage(state)
    )

    report = run_stages(store=state.store, job_id=job.id, stages=stages)

    assert report["stopped"] == "qa_blocked"
    assert state.store.get(job.id).state is JobState.BLOCKED
    assert provider.sent == calls
    assert all(row.get("reused") for row in report["stages"][:-1])


def test_revision_contract_rejects_unearned_applied_or_unchanged_decisions():
    from packages.core.contracts.artifacts import RevisionArtifact
    from packages.core.contracts.base import ArtifactValidationError, validate_artifact
    before = {"hook": "before", "segments": [{"id": "s1", "text": "one"}]}
    review = {"verdict": "revise", "findings": [{"issue": "consequence"}]}
    for phase, candidate in (("applied", None), ("applied", before),
                             ("unchanged", {**before, "hook": "after"})):
        with pytest.raises(ArtifactValidationError):
            validate_artifact(RevisionArtifact, {"attempts": [{
                "attempt": 1, "before_script": before, "review": review,
                "candidate_script": candidate, "phase": phase,
            }]})


@pytest.mark.parametrize("gate,artifact,payload", [
    (JobState.TECHNICAL_QC, "technical-qc.json", {
        "passed": False, "thresholds": {"black": "none"}, "failed": ["black"],
        "inputs_sha256": "a" * 64,
    }),
    (JobState.EDITORIAL_QC, "qc.json", {
        "technical": {"passed": True},
        "creative": {"passed": False, "metrics": {"static_ratio": 1}},
        "visual": {"status": "skipped_no_vision_provider", "frames_inspected": 0},
    }),
])
def test_a_persisted_negative_qa_verdict_is_not_reused_as_success(state, gate, artifact, payload):
    job = state.store.create(title="negative QA", payload={"provider_mode": "mock", "render_video": True})
    for target in list(JobState)[1:list(JobState).index(gate) + 1]:
        state.store.transition(job.id, target)
    state.store.write_artifact(job.id, artifact, payload)
    stage = next(stage for stage in build_stages(state, job.id) if stage.state is gate)

    report = run_stages(store=state.store, job_id=job.id, stages=[stage])

    assert report["ok"] is False
    assert report["stopped"] == "qa_blocked"
    assert state.store.get(job.id).state is JobState.BLOCKED
    assert state.store.read_artifact(job.id, artifact) == payload


def test_a_stale_readiness_record_cannot_certify_missing_render_evidence(state):
    job = state.store.create(title="stale readiness", payload={"provider_mode": "mock", "render_video": True})
    for target in list(JobState)[1:list(JobState).index(JobState.EDITORIAL_QC) + 1]:
        state.store.transition(job.id, target)
    state.store.write_artifact(job.id, "readiness.json", {
        "ready": True, "technical_passed": True, "creative_passed": True,
        "visual_status": "skipped_no_vision_provider", "inputs_sha256": "a" * 64,
    })
    stage = next(stage for stage in build_stages(state, job.id) if stage.state is JobState.READY_FOR_APPROVAL)

    report = run_stages(store=state.store, job_id=job.id, stages=[stage])

    assert report["ok"] is False
    assert report["stopped"] == "qa_blocked"
    assert state.store.get(job.id).state is JobState.BLOCKED


def test_a_lost_revision_lease_cannot_invalidate_or_promote_any_output(state):
    from packages.core.orchestration.leases import LeaseLost

    job = state.store.create(title="fenced invalidation", payload={"provider_mode": "mock"})
    state.store.write_artifact(job.id, "storyboard.json", {"sentinel": "owned output"})
    keeper = LeaseKeeper(state.store.db_path, owner="stale-revision")
    keeper.acquire(job.id)
    with keeper._connect() as connection:
        connection.execute("UPDATE job_leases SET token = 'rival' WHERE job_id = ?", (job.id,))
    try:
        with pytest.raises(LeaseLost):
            state.store.commit_stage(
                job.id, token=keeper.token, remove_artifacts=["storyboard.json"],
                json_artifacts=[("script.json", {"hook": "must not appear"})],
            )
    finally:
        keeper.release()
    assert state.store.read_artifact(job.id, "storyboard.json")["sentinel"] == "owned output"
    assert not state.store.has_artifact(job.id, "script.json")


def test_a_recorded_creative_revise_is_not_reused_as_success_or_paid_again(state):
    provider = RevisionProvider()
    job = _job(state, provider)
    for target in (JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED):
        state.store.transition(job.id, target)
    state.store.write_artifact(job.id, "script.json", {
        "hook": "original consequence", "segments": [{"id": "s1", "text": "original text"}],
    })
    state.store.write_artifact(job.id, "review.json", {
        "verdict": "revise", "findings": [{"issue": "missing consequence"}],
    })
    stage = next(stage for stage in build_stages(state, job.id) if stage.name == "CreativeDirectorAgent")

    report = run_stages(store=state.store, job_id=job.id, stages=[stage])

    assert report["stopped"] == "revision_required"
    assert report["ok"] is False
    assert state.store.get(job.id).state is JobState.BLOCKED
    assert provider.sent == []
