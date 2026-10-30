"""Resume must advance the state of a stage whose artifact already exists.

The reuse path used to ``continue`` before ``store.transition``, so a crash between "artifact
written" and "state advanced" left the job one state behind — and the *next* stage then failed
``_validate_chain`` because it was no longer reachable. That is an unresumable job, which is
exactly what N4 and S4 forbid.

The fix is not a new transition rule: the artifact was verified against its contract before the
skip, so the stage really is done and the state must say so.
"""

from __future__ import annotations

import pytest

from packages.core.contracts.state import JobState
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.runner import Stage, StageChainError, StageContext, StageOutcome, run_stages


@pytest.fixture
def store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _stage(state: JobState, name: str, artifact: str) -> Stage:
    def run(ctx: StageContext) -> StageOutcome:
        ctx.write_artifact(artifact, {"schema_version": 1})
        return StageOutcome(ok=True, artifacts=[artifact])

    return Stage(name=name, state=state, produces=(artifact,), run=run)


def test_a_reused_stage_advances_the_state_it_owns(store):
    job = store.create(title="x", payload={"provider_mode": "mock"})
    store.transition(job.id, JobState.TOPIC_SELECTED)
    # The crash shape: the artifact exists, the transition never happened.
    store.write_artifact(job.id, "a.json", {"schema_version": 1})

    report = run_stages(
        store=store, job_id=job.id, stages=[_stage(JobState.RESEARCH_COMPLETE, "A", "a.json")]
    )

    assert report["stages"][0]["reused"] is True
    assert store.get(job.id).state is JobState.RESEARCH_COMPLETE


def test_a_chain_resumes_past_a_reused_stage_instead_of_refusing_it(store):
    """Without the fix this raises StageChainError: SCRIPT_GENERATED is not reachable from
    TOPIC_SELECTED, because the first stage's transition was skipped."""
    job = store.create(title="x", payload={"provider_mode": "mock"})
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.write_artifact(job.id, "a.json", {"schema_version": 1})

    report = run_stages(
        store=store,
        job_id=job.id,
        stages=[
            _stage(JobState.RESEARCH_COMPLETE, "A", "a.json"),
            _stage(JobState.SCRIPT_GENERATED, "B", "b.json"),
        ],
    )

    assert report["ok"] is True
    assert report["stages"][0]["reused"] is True
    assert "reused" not in report["stages"][1], "the second stage actually ran"
    assert store.get(job.id).state is JobState.SCRIPT_GENERATED


def test_a_finished_job_rerrun_from_the_top_is_not_rewound(store):
    """Every stage is done and the job already sits past them. Reuse must not move it back."""
    job = store.create(title="x", payload={"provider_mode": "mock"})
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.transition(job.id, JobState.RESEARCH_COMPLETE)
    store.transition(job.id, JobState.SCRIPT_GENERATED)
    store.write_artifact(job.id, "a.json", {"schema_version": 1})
    store.write_artifact(job.id, "b.json", {"schema_version": 1})

    report = run_stages(
        store=store,
        job_id=job.id,
        stages=[
            _stage(JobState.RESEARCH_COMPLETE, "A", "a.json"),
            _stage(JobState.SCRIPT_GENERATED, "B", "b.json"),
        ],
    )

    assert report["ok"] is True
    assert all(row.get("reused") for row in report["stages"])
    assert store.get(job.id).state is JobState.SCRIPT_GENERATED


def test_a_reused_stage_that_is_already_current_does_not_transition_again(store):
    job = store.create(title="x", payload={"provider_mode": "mock"})
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.transition(job.id, JobState.RESEARCH_COMPLETE)
    store.write_artifact(job.id, "a.json", {"schema_version": 1})

    report = run_stages(
        store=store, job_id=job.id, stages=[_stage(JobState.RESEARCH_COMPLETE, "A", "a.json")]
    )

    assert report["stages"][0]["reused"] is True
    assert store.get(job.id).state is JobState.RESEARCH_COMPLETE


def test_an_unreachable_chain_is_still_refused(store):
    """The fix must not become a way to skip a state that was never entered."""
    job = store.create(title="x", payload={"provider_mode": "mock"})
    with pytest.raises(StageChainError):
        run_stages(
            store=store,
            job_id=job.id,
            stages=[_stage(JobState.READY_FOR_APPROVAL, "Z", "z.json")],
        )


def test_a_crash_after_several_artifacts_resumes_each_verified_hop(store):
    job = store.create(title="x", payload={"provider_mode": "mock"})
    store.write_artifact(job.id, "a.json", {"schema_version": 1})
    store.write_artifact(job.id, "b.json", {"schema_version": 1})

    report = run_stages(
        store=store,
        job_id=job.id,
        stages=[
            _stage(JobState.TOPIC_SELECTED, "A", "a.json"),
            _stage(JobState.RESEARCH_COMPLETE, "B", "b.json"),
            _stage(JobState.SCRIPT_GENERATED, "C", "c.json"),
        ],
    )

    assert report["ok"] is True
    assert [row.get("reused", False) for row in report["stages"]] == [True, True, False]
    assert store.get(job.id).state is JobState.SCRIPT_GENERATED


def test_a_reused_middle_stage_still_connects_the_pending_chain(store):
    job = store.create(title="x", payload={"provider_mode": "mock"})
    store.write_artifact(job.id, "b.json", {"schema_version": 1})

    report = run_stages(
        store=store,
        job_id=job.id,
        stages=[
            _stage(JobState.TOPIC_SELECTED, "A", "a.json"),
            _stage(JobState.RESEARCH_COMPLETE, "B", "b.json"),
            _stage(JobState.SCRIPT_GENERATED, "C", "c.json"),
        ],
    )

    assert report["ok"] is True
    assert report["stages"][1]["reused"] is True
    assert store.get(job.id).state is JobState.SCRIPT_GENERATED


@pytest.mark.parametrize("current", [JobState.CREATIVE_REVIEW, JobState.TECHNICAL_QC])
def test_reuse_does_not_take_a_legal_revision_or_repair_edge(store, current):
    path = list(JobState)[:list(JobState).index(current) + 1]
    job = store.create(title="x", payload={"provider_mode": "mock"})
    stages = []
    for state in path[1:]:
        store.transition(job.id, state)
        artifact = state.value.lower() + ".json"
        store.write_artifact(job.id, artifact, {"schema_version": 1})
        stages.append(_stage(state, state.value, artifact))
    before = store.event_count(job.id)

    report = run_stages(store=store, job_id=job.id, stages=stages)

    assert report["ok"] is True
    assert all(row.get("reused") for row in report["stages"])
    assert store.get(job.id).state is current
    assert store.event_count(job.id) == before


@pytest.mark.parametrize("current", [
    JobState.RENDERING, JobState.TECHNICAL_QC, JobState.EDITORIAL_QC,
])
@pytest.mark.parametrize("damage", ["missing", "unreadable", "invalid"])
def test_advanced_resume_blocks_damaged_upstream_evidence_before_any_call(store, current, damage):
    from dataclasses import replace

    from packages.core.contracts import ScriptArtifact

    path = list(JobState)[1:list(JobState).index(current) + 1]
    job = store.create(title="x", payload={"provider_mode": "mock"})
    stages = []
    calls = []
    for state in path:
        store.transition(job.id, state)
        artifact = "script.json" if state is JobState.SCRIPT_GENERATED else state.value + ".json"
        store.write_artifact(job.id, artifact, {"schema_version": 1})

        def unexpected_call(ctx):
            calls.append(ctx.job_id)
            return StageOutcome(ok=False, detail="historical work must not run")

        stage = replace(_stage(state, state.value, artifact), run=unexpected_call)
        if state is JobState.SCRIPT_GENERATED:
            stage = replace(
                stage, name="ScriptAgent", contract=ScriptArtifact, contract_artifact=artifact,
            )
        stages.append(stage)
    script = store.job_dir(job.id) / "script.json"
    if damage == "missing":
        script.unlink()
    elif damage == "unreadable":
        script.write_text("{broken", encoding="utf-8")
    before = store.event_count(job.id)

    report = run_stages(store=store, job_id=job.id, stages=stages)

    assert report["ok"] is False
    assert report["stopped"] == "resume_evidence_missing"
    assert "ScriptAgent" in report["detail"]
    assert "script.json" in report["detail"]
    assert calls == []
    assert store.get(job.id).state is JobState.BLOCKED
    assert store.event_count(job.id) == before + 1
    again = run_stages(store=store, job_id=job.id, stages=stages)
    assert again["stopped"] == "resume_evidence_missing"
    assert calls == []
    assert store.event_count(job.id) == before + 1


def test_upstream_evidence_disappearing_after_preflight_never_restarts_paid_work(store, monkeypatch):
    from dataclasses import replace

    from packages.core.orchestration.leases import LeaseKeeper

    job = store.create(title="race", payload={"provider_mode": "mock"})
    stages = []
    calls = []
    for state in list(JobState)[1:list(JobState).index(JobState.RENDERING) + 1]:
        store.transition(job.id, state)
        name = state.value + ".json"
        store.write_artifact(job.id, name, {"schema_version": 1})

        def unexpected_call(ctx):
            calls.append(ctx.job_id)
            return StageOutcome(ok=False)

        stages.append(replace(_stage(state, state.value, name), run=unexpected_call))
    keeper = LeaseKeeper(store.db_path, owner="resume-race")
    keeper.acquire(job.id)
    renew = keeper.renew
    removed = False

    def remove_after_preflight():
        nonlocal removed
        if not removed:
            removed = True
            (store.job_dir(job.id) / "SCRIPT_GENERATED.json").unlink()
        return renew()

    monkeypatch.setattr(keeper, "renew", remove_after_preflight)
    try:
        report = run_stages(store=store, job_id=job.id, stages=stages, keeper=keeper)
    finally:
        keeper.release()
    assert report["stopped"] == "resume_evidence_missing"
    assert calls == []
