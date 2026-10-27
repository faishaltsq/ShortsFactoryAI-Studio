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
