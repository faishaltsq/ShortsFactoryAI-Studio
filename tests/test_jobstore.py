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
    assert versions == [1]


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
