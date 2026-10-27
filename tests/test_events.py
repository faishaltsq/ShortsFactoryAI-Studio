"""The studio may never show work that is not happening."""

from __future__ import annotations

import json

import pytest

from packages.core.observability.events import (
    AGENT_IDS,
    StudioEventStore,
    derive_status,
    project_agents,
    snapshot,
)

SENTINEL = "sk-" + "eventsentinel" + "0123456789"


@pytest.fixture
def store(tmp_path):
    return StudioEventStore(tmp_path / "f.db")


def test_emit_and_page(store):
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_started", stage="SCRIPT_GENERATED")
    events = store.page()
    assert len(events) == 1
    assert events[0].status == "working"
    assert events[0].agent_id == "ScriptAgent"


def test_cursor_is_monotonic_and_pageable(store):
    first = store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_started")
    second = store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_completed")
    assert second.event_id > first.event_id
    assert [e.event_id for e in store.page(after=first.event_id)] == [second.event_id]


def test_progress_one_percent_is_reserved_for_a_finished_stage(store):
    with pytest.raises(ValueError):
        store.emit(
            job_id="j1", agent_id="ScriptAgent", event_type="progress", progress=1.0
        )
    # The two legitimate cases are allowed.
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_completed", progress=1.0)
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="artifact_reused", progress=1.0)


def test_progress_must_be_in_range(store):
    with pytest.raises(ValueError):
        store.emit(job_id="j1", agent_id="ScriptAgent", event_type="progress", progress=1.5)


def test_unknown_agent_is_refused(store):
    with pytest.raises(ValueError):
        store.emit(job_id="j1", agent_id="NotAnAgent", event_type="stage_started")


def test_descriptions_are_redacted(store):
    store.emit(
        job_id="j1",
        agent_id="ScriptAgent",
        event_type="failed",
        description=f"call failed with key {SENTINEL}",
    )
    payload = json.dumps([e.to_json() for e in store.page()])
    assert SENTINEL not in payload
    assert "[redacted]" in payload


def test_descriptions_are_bounded(store):
    store.emit(
        job_id="j1", agent_id="ScriptAgent", event_type="failed", description="x" * 2000
    )
    assert len(store.page()[0].description) <= 400


def test_derive_status_maps_every_event_type():
    assert derive_status("stage_started") == "working"
    assert derive_status("progress") == "working"
    assert derive_status("stage_completed") == "completed"
    assert derive_status("artifact_reused") == "completed"
    assert derive_status("failed") == "failed"
    assert derive_status("blocked") == "blocked"
    assert derive_status("cancelled") == "waiting"


def test_a_stale_worker_reads_as_waiting_not_working(store):
    """The phantom-typing case: the process died, the last event said working."""
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_started")
    views = project_agents(store, job_id="j1", live_agents=set())
    script = next(v for v in views if v.agent_id == "ScriptAgent")
    assert script.status == "waiting"
    assert script.stale is True


def test_a_live_worker_reads_as_working(store):
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_started")
    views = project_agents(store, job_id="j1", live_agents={"ScriptAgent"})
    script = next(v for v in views if v.agent_id == "ScriptAgent")
    assert script.status == "working"
    assert script.stale is False


def test_completed_is_not_downgraded_by_staleness(store):
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_completed")
    views = project_agents(store, job_id="j1", live_agents=set())
    script = next(v for v in views if v.agent_id == "ScriptAgent")
    assert script.status == "completed"


def test_every_agent_appears_even_with_no_events(store):
    views = project_agents(store)
    assert {v.agent_id for v in views} == set(AGENT_IDS)
    assert all(v.status == "waiting" for v in views)


def test_two_jobs_do_not_leak_state_into_each_other(store):
    store.emit(job_id="a", agent_id="ScriptAgent", event_type="stage_started", description="job a")
    store.emit(job_id="b", agent_id="ScriptAgent", event_type="stage_completed", description="job b")
    a_views = project_agents(store, job_id="a")
    a_script = next(v for v in a_views if v.agent_id == "ScriptAgent")
    assert a_script.task == "job a"
    assert a_script.status in {"working", "waiting"}


def test_snapshot_cursor_precedes_the_projection(store):
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_started")
    snap = snapshot(store, job_id="j1")
    assert snap["cursor"] >= 1
    # Replaying from the cursor must yield nothing already included in the snapshot.
    assert store.page(after=snap["cursor"]) == []


def test_history_is_bounded_and_ordered(store):
    for i in range(10):
        store.emit(
            job_id="j1", agent_id="ScriptAgent", event_type="progress", progress=i / 20
        )
    history = store.history("j1", limit=4)
    assert len(history) == 4
    assert [e.event_id for e in history] == sorted(e.event_id for e in history)


def test_artifact_reuse_never_emits_working(store):
    """A resumed stage must not claim it is working when it only reused an artifact."""
    store.emit(job_id="j1", agent_id="ScriptAgent", event_type="artifact_reused", progress=1.0)
    event = store.page()[-1]
    assert event.status == "completed"
    assert event.event_type == "artifact_reused"


def test_an_agent_with_an_event_always_carries_its_timestamp(store):
    """`updated_at` is the only thing the studio can age an event by.

    A view whose ``status`` came from an event but whose ``updated_at`` is null would force the
    browser to guess an age, and guessing is how a live character reads as idle.
    """
    store.emit(job_id="j1", agent_id="ResearchAgent", event_type="stage_completed")
    views = project_agents(store, job_id="j1")
    for view in views:
        if view.status == "waiting" and view.updated_at is None:
            continue  # no event at all: nothing to timestamp, and `waiting` is the honest answer
        assert view.updated_at is not None, f"{view.agent_id} reports a status with no timestamp"
        assert view.job_id is not None


def test_a_completed_stage_keeps_its_own_status_and_timestamp(store):
    """Server truth is not decayed: the two-second reaction is the browser's, not the projection's."""
    event = store.emit(job_id="j1", agent_id="ScriptAgent", event_type="stage_completed")
    view = next(v for v in project_agents(store, job_id="j1") if v.agent_id == "ScriptAgent")
    assert view.status == "completed"
    assert view.updated_at == event.created_at
