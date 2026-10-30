"""The runner's four promises: reuse, marker-last, lease-guard, no unverified success."""

from __future__ import annotations

import pytest

from packages.core.contracts.state import JobState
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.leases import LeaseKeeper
from packages.core.orchestration.runner import Stage, StageError, StageOutcome, run_stages


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "f.db", tmp_path / "jobs")


def _stage(name, state, *, produces=("out.json",), behaviour=None, contract=None,
           contract_artifact="", done_when=None):
    calls = {"n": 0}

    def run(ctx):
        job_id = ctx.job_id
        calls["n"] += 1
        if behaviour is not None:
            return behaviour(ctx, job_id, calls["n"])
        ctx.write_artifact("out.json", {"ok": True, "n": calls["n"]})
        return StageOutcome(ok=True, artifacts=["out.json"])

    stage = Stage(
        name=name,
        state=state,
        produces=produces,
        run=run,
        contract=contract,
        contract_artifact=contract_artifact,
        done_when=done_when,
    )
    return stage, calls


def test_a_successful_stage_advances_the_state(store):
    job = store.create(title="x")
    stage, calls = _stage("one", JobState.TOPIC_SELECTED)
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is True
    assert calls["n"] == 1
    assert store.get(job.id).state is JobState.TOPIC_SELECTED


def test_a_completed_stage_is_reused_not_rerun(store):
    job = store.create(title="x")
    stage, calls = _stage("one", JobState.TOPIC_SELECTED)
    run_stages(store=store, job_id=job.id, stages=[stage])
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert calls["n"] == 1, "a second run must not call the stage again"
    assert report["stages"][0]["reused"] is True


def test_a_stage_claiming_success_without_its_artifact_fails(store):
    job = store.create(title="x")

    def lies(ctx, job_id, _n):
        return StageOutcome(ok=True, detail="trust me")

    stage, _ = _stage("liar", JobState.TOPIC_SELECTED, behaviour=lies)
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is False
    assert report["stopped"] == "missing_artifact"
    assert store.get(job.id).state is JobState.FAILED


def test_an_invalid_contract_fails_even_when_the_file_exists(store):
    from packages.core.contracts import ScriptArtifact

    job = store.create(title="x")
    for state in (JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE):
        store.transition(job.id, state)

    def bad(ctx, job_id, _n):
        ctx.write_artifact( "script.json", {"hook": "", "segments": []})
        return StageOutcome(ok=True)

    stage = Stage(
        name="script",
        state=JobState.SCRIPT_GENERATED,
        produces=("script.json",),
        run=bad,
        contract=ScriptArtifact,
        contract_artifact="script.json",
    )
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is False
    assert store.get(job.id).state is JobState.FAILED


def test_retryable_failures_are_retried_then_blocked(store):
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)

    def always_fails(ctx, job_id, _n):
        raise StageError("provider_timeout", "upstream timed out", retryable=True)

    stage, calls = _stage("flaky", JobState.RESEARCH_COMPLETE, behaviour=always_fails)
    report = run_stages(store=store, job_id=job.id, stages=[stage], max_attempts=3)
    assert calls["n"] == 3
    assert report["stopped"] == "provider_timeout"
    assert store.get(job.id).state is JobState.BLOCKED, "retry exhaustion needs a decision"


def test_a_retryable_failure_that_then_succeeds(store):
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)

    def fails_once(ctx, job_id, n):
        if n == 1:
            raise StageError("provider_rate_limit", "429", retryable=True)
        ctx.write_artifact( "out.json", {"ok": True})
        return StageOutcome(ok=True)

    stage, calls = _stage("flaky", JobState.RESEARCH_COMPLETE, behaviour=fails_once)
    report = run_stages(store=store, job_id=job.id, stages=[stage], max_attempts=3)
    assert report["ok"] is True
    assert calls["n"] == 2


def test_a_non_retryable_failure_fails_immediately(store):
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)

    def boom(ctx, job_id, _n):
        raise StageError("provider_auth", "401", retryable=False)

    stage, calls = _stage("auth", JobState.RESEARCH_COMPLETE, behaviour=boom)
    report = run_stages(store=store, job_id=job.id, stages=[stage], max_attempts=3)
    assert calls["n"] == 1, "a non-retryable failure must not be retried"
    assert report["stopped"] == "provider_auth"
    assert store.get(job.id).state is JobState.FAILED


def test_an_unexpected_exception_never_looks_like_success(store):
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)

    def crash(ctx, job_id, _n):
        raise RuntimeError("index out of range")

    stage, _ = _stage("crash", JobState.RESEARCH_COMPLETE, behaviour=crash)
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is False
    assert report["stopped"] == "stage_exception"
    assert "index out of range" in report["detail"]
    assert store.get(job.id).state is JobState.FAILED


def test_cancellation_between_stages_stops_the_run(store):
    job = store.create(title="x")
    first, _ = _stage("one", JobState.TOPIC_SELECTED)

    class Cancelled:
        def is_cancelled(self):
            return True

    report = run_stages(store=store, job_id=job.id, stages=[first], cancel=Cancelled())
    assert report["stopped"] == "cancelled"
    assert store.get(job.id).state is JobState.CANCELLED


def test_a_lost_lease_stops_without_touching_the_job(store):
    job = store.create(title="x")
    keeper = LeaseKeeper(store.db_path, owner="mine")
    keeper.acquire(job.id)
    stage, calls = _stage("one", JobState.TOPIC_SELECTED)

    with keeper._connect() as conn:
        conn.execute("UPDATE job_leases SET token = 'other' WHERE job_id = ?", (job.id,))

    report = run_stages(store=store, job_id=job.id, stages=[stage], keeper=keeper)
    assert report["stopped"] == "lease_lost"
    assert calls["n"] == 0
    assert store.get(job.id).state is JobState.IDEA_DISCOVERY, "must not write another owner's job"


def test_a_stage_that_loses_the_lease_mid_run_is_not_recorded(store):
    job = store.create(title="x")
    keeper = LeaseKeeper(store.db_path, owner="mine")
    keeper.acquire(job.id)

    def steals_then_writes(ctx, job_id, _n):
        with keeper._connect() as conn:
            conn.execute("UPDATE job_leases SET token = 'rival' WHERE job_id = ?", (job_id,))
        ctx.write_artifact( "out.json", {"ok": True})
        return StageOutcome(ok=True)

    stage, _ = _stage("thief", JobState.TOPIC_SELECTED, behaviour=steals_then_writes)
    report = run_stages(store=store, job_id=job.id, stages=[stage], keeper=keeper)
    assert report["stopped"] == "lease_lost"
    assert store.get(job.id).state is JobState.IDEA_DISCOVERY


def test_resume_after_a_crash_does_not_repeat_paid_work(store):
    """The cost bug this prevents: a paid completion that is repeated on resume."""
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.transition(job.id, JobState.RESEARCH_COMPLETE)
    paid_calls = {"n": 0}

    def paid(ctx, job_id, n):
        paid_calls["n"] += 1
        ctx.write_artifact( "out.json", {"script": "once"})
        return StageOutcome(ok=True)

    stage, _ = _stage("paid", JobState.SCRIPT_GENERATED, behaviour=paid)
    run_stages(store=store, job_id=job.id, stages=[stage])
    run_stages(store=store, job_id=job.id, stages=[stage])  # simulate a restart + resume
    assert paid_calls["n"] == 1


def test_a_failed_stage_is_retried_on_resume(store):
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.transition(job.id, JobState.RESEARCH_COMPLETE)
    state = {"fail": True}

    def maybe(ctx, job_id, _n):
        if state["fail"]:
            raise StageError("provider_timeout", "down", retryable=True)
        ctx.write_artifact( "out.json", {"ok": True})
        return StageOutcome(ok=True)

    stage, _ = _stage("maybe", JobState.SCRIPT_GENERATED, behaviour=maybe)
    run_stages(store=store, job_id=job.id, stages=[stage], max_attempts=1)
    assert store.get(job.id).state is JobState.BLOCKED

    state["fail"] = False
    store.transition(job.id, JobState.SCRIPT_GENERATED, detail="operator retry")
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is True


def test_an_unreachable_stage_chain_is_refused_before_anything_runs(store):
    """A pipeline that jumps states must fail before a paid call, not after."""
    from packages.core.orchestration.runner import StageChainError

    job = store.create(title="x")
    stage, calls = _stage("jump", JobState.SCRIPT_GENERATED)
    with pytest.raises(StageChainError) as exc:
        run_stages(store=store, job_id=job.id, stages=[stage])
    assert "not reachable from IDEA_DISCOVERY" in str(exc.value)
    assert calls["n"] == 0
    assert store.get(job.id).state is JobState.IDEA_DISCOVERY


def test_a_qa_blocked_failure_needs_an_operator_decision(store):
    """A failed technical gate is not a crash; it is a decision the operator must make."""
    job = store.create(title="x")
    stage, _calls = _stage(
        "qc",
        JobState.TOPIC_SELECTED,
        behaviour=lambda *_a: StageOutcome(
            ok=False, detail="technical QC failed: audio_streams", error_code="qa_blocked"
        ),
    )
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is False
    assert report["stopped"] == "qa_blocked"
    assert store.get(job.id).state is JobState.BLOCKED


def test_a_generic_non_retryable_failure_still_fails(store):
    job = store.create(title="x")
    stage, _calls = _stage(
        "boom",
        JobState.TOPIC_SELECTED,
        behaviour=lambda *_a: StageOutcome(
            ok=False, detail="unexpected", error_code="stage_exception"
        ),
    )
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["stopped"] == "stage_exception"
    assert store.get(job.id).state is JobState.FAILED


def test_a_control_outcome_commits_evidence_and_stops_without_success(store):
    """``control`` is a decision, not a result.

    A review that says ``revision_required`` has produced evidence the operator must be able to
    read (``review.json``), but the stage did not succeed and must not be reused as if it had.
    The runner commits the staged artifact, moves the job to ``BLOCKED`` (the rework controller's
    entry point), and stops the chain — it does not advance to the stage's target state and it
    does not retry.
    """
    job = store.create(title="x")

    def behaviour(ctx, _job_id, _n):
        ctx.write_artifact("out.json", {"verdict": "revise", "findings": ["hook too slow"]})
        return StageOutcome(
            ok=True, detail="revise the hook", control="revision_required",
            artifacts=["out.json"],
        )

    # The review's own completion predicate: an accept verdict is a finished review, a revise
    # verdict is evidence plus a decision. Without it the second run would reuse the committed
    # revise verdict as if it were an accepted one.
    stage, calls = _stage(
        "review",
        JobState.TOPIC_SELECTED,
        behaviour=behaviour,
        contract_artifact="out.json",
        done_when=lambda payload, _job_id: payload.get("verdict") == "accept",
    )
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is False
    assert report["stopped"] == "revision_required"
    assert calls["n"] == 1, "a control outcome is not a retryable failure"
    assert store.get(job.id).state is JobState.BLOCKED
    # The evidence is committed, so the operator can read why the chain stopped.
    assert store.has_artifact(job.id, "out.json")
    payload = store.read_artifact(job.id, "out.json")
    assert payload["verdict"] == "revise"
    # ...and it does not authorize reuse as a success on the next run.
    report2 = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report2["stopped"] == "revision_required"
    assert calls["n"] == 2


def test_waiting_resources_control_blocks_without_failing(store):
    """A resource wait is the operator-visible waiting state, not a failure."""
    job = store.create(title="x")

    def behaviour(ctx, _job_id, _n):
        ctx.write_artifact("out.json", {"waiting": "vram"})
        return StageOutcome(
            ok=True, detail="GPU telemetry unavailable", control="waiting_resources",
            artifacts=["out.json"],
        )

    stage, _calls = _stage("render", JobState.TOPIC_SELECTED, behaviour=behaviour)
    report = run_stages(store=store, job_id=job.id, stages=[stage])
    assert report["ok"] is False
    assert report["stopped"] == "waiting_resources"
    assert store.get(job.id).state is JobState.BLOCKED
    assert "GPU telemetry unavailable" in (store.get(job.id).last_error or "")


@pytest.mark.parametrize("staged", [False, True])
def test_resource_refusal_needs_no_render_outputs_and_promotes_nothing(store, staged):
    job = store.create(title="resource wait")

    def refusal(ctx, _job_id, _n):
        if staged:
            ctx.write_artifact("out.json", {"partial": True})
        return StageOutcome(ok=True, control="waiting_resources", detail="render slot occupied")

    stage, calls = _stage("render", JobState.TOPIC_SELECTED, behaviour=refusal)
    report = run_stages(store=store, job_id=job.id, stages=[stage])

    assert report["stopped"] == "waiting_resources"
    assert report["ok"] is False
    assert calls["n"] == 1
    assert not store.has_artifact(job.id, "out.json")
    assert store.get(job.id).state is JobState.BLOCKED
