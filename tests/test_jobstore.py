"""Durability: transitions, atomic writes, confinement, and event/state coupling."""

from __future__ import annotations

import json
import os

import pytest

from packages.core.contracts.state import JobState
from packages.core.orchestration.jobstore import (
    ArtifactNotFound,
    IllegalTransition,
    JobStore,
    safe_artifact_name,
)


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def test_create_writes_a_job_and_its_first_event(store):
    job = store.create(title="first", payload={"provider_mode": "mock"})
    assert job.state is JobState.IDEA_DISCOVERY
    assert job.is_mock is True
    events = store.events(job.id)
    assert len(events) == 1
    assert events[0]["to_state"] == JobState.IDEA_DISCOVERY.value


def test_state_change_and_event_commit_together(store):
    job = store.create(title="x")
    before = store.event_count(job.id)
    store.transition(job.id, JobState.TOPIC_SELECTED, detail="picked")
    assert store.event_count(job.id) == before + 1
    assert store.get(job.id).state is JobState.TOPIC_SELECTED


def test_illegal_transition_is_refused_and_changes_nothing(store):
    job = store.create(title="x")
    with pytest.raises(IllegalTransition):
        store.transition(job.id, JobState.PUBLISHED)
    assert store.get(job.id).state is JobState.IDEA_DISCOVERY
    assert store.event_count(job.id) == 1


def test_conditional_transition_protects_against_a_lost_worker(store):
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)
    with pytest.raises(IllegalTransition):
        store.transition(
            job.id, JobState.RESEARCH_COMPLETE, expected=JobState.IDEA_DISCOVERY
        )
    assert store.get(job.id).state is JobState.TOPIC_SELECTED


def test_no_transition_to_approved_from_blocked(store):
    """A blocked job cannot be moved to ``APPROVED`` by any caller, including a future scheduler.

    ``BLOCKED`` does not list ``APPROVED`` in the allow-list, so this edge never existed. It is
    asserted here because a resume or schedule path is exactly the kind of caller that would try
    it, and ``APPROVED -> PRIVATE_UPLOAD`` would then be legal behind it.
    """
    job = store.create(title="x")
    for state in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
    ):
        store.transition(job.id, state)
    # ``READY_FOR_APPROVAL`` has no BLOCKED exit, so a job that is blocked at all is blocked
    # before the gate — which is exactly the state a resume path would try to short-circuit.
    store.transition(job.id, JobState.BLOCKED, detail="qa blocked")
    events_before = store.event_count(job.id)

    with pytest.raises(IllegalTransition) as exc:
        store.transition(job.id, JobState.APPROVED)
    assert "BLOCKED -> APPROVED" in str(exc.value)
    assert store.get(job.id).state is JobState.BLOCKED
    assert store.event_count(job.id) == events_before, "a refused transition writes no event"


def test_an_approved_job_cannot_reenter_approved_after_blocking(store):
    """``APPROVED -> BLOCKED -> APPROVED`` is refused; the gate must be re-run at the gate state.

    The only legal re-entry is ``BLOCKED -> READY_FOR_APPROVAL``, and even there the transition
    needs the gate's artifact — see the evidence tests below.
    """
    job = store.create(title="x")
    for state in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job.id, state)
    store.write_artifact(job.id, "render.json", {"sha256": "d" * 64})
    store.write_artifact(job.id, "approval.json", _approval(job.id, "d" * 64))
    store.transition(job.id, JobState.APPROVED, detail="approved by op")

    store.transition(job.id, JobState.BLOCKED, detail="upload failed")
    with pytest.raises(IllegalTransition) as exc:
        store.transition(job.id, JobState.APPROVED)
    assert "BLOCKED -> APPROVED" in str(exc.value)

    # The long way round is still open, and it passes the gate again.
    store.transition(job.id, JobState.READY_FOR_APPROVAL, detail="re-review")
    store.transition(job.id, JobState.APPROVED, detail="approved again")
    assert store.get(job.id).state is JobState.APPROVED


# -- APPROVED requires recorded evidence, not merely a legal edge -------------------------------


def _walk_to_gate(store, job_id: str) -> None:
    """Advance a job to ``READY_FOR_APPROVAL`` with no approval artifact written."""
    for state in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job_id, state)


def _approval(job_id: str, render_sha256: str | None) -> dict:
    payload = {
        "schema_version": 1,
        "decision": "approved",
        "operator": "op",
        "reason": None,
        "checks": {"publishable": True},
        "decided_at": "2026-01-01T00:00:00+00:00",
    }
    if render_sha256 is not None:
        payload["render_sha256"] = render_sha256
    return payload


def test_approved_without_an_approval_artifact_is_refused(store):
    """A legal edge is not sufficient evidence: ``APPROVED`` requires ``approval.json`` on disk.

    ``READY_FOR_APPROVAL -> APPROVED`` is in the allow-list, so before this check any caller that
    reached the gate state could approve a job by transitioning it — including
    ``BLOCKED -> READY_FOR_APPROVAL -> APPROVED``, which never runs ``_approval_checks``. The store
    does not run the gate; it refuses to record the outcome without the gate's artifact.
    """
    job = store.create(title="x")
    _walk_to_gate(store, job.id)
    events_before = store.event_count(job.id)

    with pytest.raises(IllegalTransition) as exc:
        store.transition(job.id, JobState.APPROVED)
    message = str(exc.value)
    assert "approval.json" in message
    assert "APPROVED requires" in message
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL
    assert store.event_count(job.id) == events_before, "a refused transition writes no event"


def test_a_rejected_approval_artifact_cannot_authorise_approved(store):
    """``decision: "rejected"`` is an approval record, not an approval."""
    job = store.create(title="x")
    _walk_to_gate(store, job.id)
    store.write_artifact(
        job.id,
        "approval.json",
        {
            "schema_version": 1,
            "decision": "rejected",
            "operator": "op",
            "reason": "not good enough",
            "checks": {"publishable": False},
            "decided_at": "2026-01-01T00:00:00+00:00",
            "render_sha256": "a" * 64,
        },
    )

    with pytest.raises(IllegalTransition) as exc:
        store.transition(job.id, JobState.APPROVED)
    assert "decision" in str(exc.value)
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL


def test_an_approval_for_a_different_render_cannot_authorise_approved(store):
    """A stale approval must not authorise a different render.

    The approval records the render hash it was decided against. If ``render.json`` now names a
    different file — a re-render happened after the decision — the approval is evidence about
    bytes that no longer exist, and the transition is refused.
    """
    job = store.create(title="x")
    _walk_to_gate(store, job.id)
    store.write_artifact(job.id, "render.json", {"sha256": "b" * 64})
    store.write_artifact(job.id, "approval.json", _approval(job.id, "a" * 64))

    with pytest.raises(IllegalTransition) as exc:
        store.transition(job.id, JobState.APPROVED)
    message = str(exc.value)
    assert "stale approval" in message
    assert "a" * 64 in message and "b" * 64 in message, "the refusal must name both hashes"
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL


def test_an_approval_recording_no_render_hash_is_refused(store):
    """An approval written before ``render_sha256`` existed cannot prove what it approved."""
    job = store.create(title="x")
    _walk_to_gate(store, job.id)
    store.write_artifact(job.id, "render.json", {"sha256": "b" * 64})
    store.write_artifact(job.id, "approval.json", _approval(job.id, None))

    with pytest.raises(IllegalTransition) as exc:
        store.transition(job.id, JobState.APPROVED)
    assert "render_sha256" in str(exc.value)


def test_a_matching_approval_artifact_permits_approved(store):
    """The positive control: matching evidence is accepted, so the check is not a blanket refusal."""
    job = store.create(title="x")
    _walk_to_gate(store, job.id)
    store.write_artifact(job.id, "render.json", {"sha256": "b" * 64})
    store.write_artifact(job.id, "approval.json", _approval(job.id, "b" * 64))

    store.transition(job.id, JobState.APPROVED, detail="approved by op")
    assert store.get(job.id).state is JobState.APPROVED


def test_the_gate_route_is_the_only_door_after_a_block(store):
    """``BLOCKED -> READY_FOR_APPROVAL`` is legal, but it does not itself authorise ``APPROVED``.

    This is the residual the allow-list alone could not close: reaching the gate state is not the
    same as passing the gate. A job blocked before the gate (a provider failure, a QA block) can
    be resumed into ``READY_FOR_APPROVAL`` — and only the artifact written by the gate authorises
    the next step.
    """
    job = store.create(title="x")
    for state in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
    ):
        store.transition(job.id, state)
    store.transition(job.id, JobState.BLOCKED, detail="provider fixed")

    # The operator's resume path: legal, and it does not run the gate.
    store.transition(job.id, JobState.READY_FOR_APPROVAL, detail="re-review")
    with pytest.raises(IllegalTransition) as exc:
        store.transition(job.id, JobState.APPROVED)
    assert "approval.json" in str(exc.value)
    assert store.get(job.id).state is JobState.READY_FOR_APPROVAL

    # Only now, with the gate's artifact present, does it open.
    store.write_artifact(job.id, "render.json", {"sha256": "c" * 64})
    store.write_artifact(job.id, "approval.json", _approval(job.id, "c" * 64))
    store.transition(job.id, JobState.APPROVED, detail="approved by op")
    assert store.get(job.id).state is JobState.APPROVED


def test_artifacts_are_written_atomically(store):
    job = store.create(title="x")
    path = store.write_artifact(job.id, "script.json", {"hook": "h"})
    assert path.is_file()
    assert not list(path.parent.glob(".*.tmp")), "no temp file may survive a write"
    assert json.loads(path.read_text(encoding="utf-8"))["hook"] == "h"


def test_missing_artifact_raises_a_specific_error(store):
    job = store.create(title="x")
    with pytest.raises(ArtifactNotFound):
        store.read_artifact(job.id, "nope.json")


@pytest.mark.parametrize("name", ["../escape.json", "a/b.json", "a\\b.json", ".hidden", "", "x" * 200])
def test_artifact_names_are_confined(name):
    with pytest.raises(ValueError):
        safe_artifact_name(name)


def test_artifact_name_cannot_escape_the_job_directory(store):
    job = store.create(title="x")
    with pytest.raises(ValueError):
        store.write_artifact(job.id, "../outside.json", {"x": 1})
    assert not (store.jobs_dir / "outside.json").exists()


def test_job_id_cannot_escape_either(store):
    with pytest.raises(ValueError):
        store.job_dir("../evil")


def test_listing_artifacts_hides_temp_files(store):
    job = store.create(title="x")
    store.write_artifact(job.id, "a.json", {})
    (store.job_dir(job.id) / ".a.json.tmp").write_text("{}", encoding="utf-8")
    assert store.list_artifacts(job.id) == ["a.json"]


def test_events_are_ordered_and_pageable(store):
    job = store.create(title="x")
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.transition(job.id, JobState.RESEARCH_COMPLETE)
    all_events = store.events(job.id)
    assert [e["to_state"] for e in all_events] == [
        JobState.IDEA_DISCOVERY.value,
        JobState.TOPIC_SELECTED.value,
        JobState.RESEARCH_COMPLETE.value,
    ]
    tail = store.events(job.id, after_id=all_events[0]["id"])
    assert len(tail) == 2


def test_migrations_are_idempotent(tmp_path):
    db = tmp_path / "f.db"
    jobs = tmp_path / "jobs"
    first = JobStore(db, jobs)
    job = first.create(title="x")
    second = JobStore(db, jobs)  # reopening must not wipe or duplicate
    assert second.get(job.id).title == "x"
    with second._connect() as conn:
        versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations")]
    assert versions == [1, 2, 3], "each migration applies exactly once, never re-running an earlier one"


def test_wal_is_enabled(store):
    with store._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_error_and_attempts_are_recorded(store):
    job = store.create(title="x")
    store.set_error(job.id, "boom")
    assert store.bump_attempts(job.id) == 1
    assert store.bump_attempts(job.id) == 2
    refreshed = store.get(job.id)
    assert refreshed.last_error == "boom"
    assert refreshed.attempts == 2


def test_list_filters_by_state(store):
    a = store.create(title="a")
    b = store.create(title="b")
    store.transition(b.id, JobState.TOPIC_SELECTED)
    assert {job.id for job in store.list(states=[JobState.IDEA_DISCOVERY])} == {a.id}
    assert {job.id for job in store.list(states=[JobState.TOPIC_SELECTED])} == {b.id}


def test_delete_removes_the_row_and_its_events(store):
    job = store.create(title="x")
    store.delete(job.id)
    with pytest.raises(KeyError):
        store.get(job.id)
    assert store.event_count(job.id) == 0


def test_concurrent_writes_do_not_deadlock(store):
    """WAL + busy_timeout is what makes the API thread and worker thread coexist."""
    import threading

    job = store.create(title="x")
    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            for i in range(10):
                store.write_artifact(job.id, f"f{n}-{i}.json", {"n": n, "i": i})
                store.events(job.id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert len(store.list_artifacts(job.id)) == 40


def test_store_does_not_hold_a_connection_open(store):
    """A leaked connection blocks WAL checkpointing and hides lock bugs."""
    job = store.create(title="x")
    del job
    before = len(os.listdir(store.db_path.parent))
    store.create(title="y")
    after = len(os.listdir(store.db_path.parent))
    assert after - before <= 1
