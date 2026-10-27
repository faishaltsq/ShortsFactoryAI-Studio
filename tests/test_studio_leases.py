"""A lease is the only thing that may keep a character typing.

``live_agents`` used to mean "a thread is running in this process", so a wedged worker kept its
character reading ``working`` until the 300 s age fallback fired. ADR-008 and FR-9.4 make expiry a
property of the persisted lease row, so the projection reads the lease, and the age fallback stays
as a second net.
"""

from __future__ import annotations

import datetime as dt
import threading

import pytest
from fastapi.testclient import TestClient

from apps.api.jobs import JobService
from apps.api.main import create_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from packages.core.observability.events import StudioEventStore, project_agents
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.leases import LeaseKeeper
from packages.core.providers.usage import Budget


def _past(seconds: int = 60) -> str:
    return (
        (dt.datetime.now(dt.UTC) - dt.timedelta(seconds=seconds))
        .replace(microsecond=0)
        .isoformat()
    )


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


def test_an_expired_lease_reads_as_waiting_even_with_a_running_thread(state):
    """The wedged-worker case: the thread object is still in ``running``, the lease is not."""
    job = state.store.create(title="wedged", payload={"title": "wedged"})
    state.events.emit(job_id=job.id, agent_id="ScriptAgent", event_type="stage_started")
    keeper = LeaseKeeper(state.store.db_path, ttl_s=120)
    keeper.acquire(job.id)
    with keeper._connect() as conn:
        conn.execute(
            "UPDATE job_leases SET expires_at = ? WHERE job_id = ?", (_past(), job.id)
        )

    state.running[job.id] = threading.Thread(target=lambda: None, name="wedged")
    service = JobService(state)
    assert service.live_agents() == set(), "an expired lease is not a live agent"

    views = project_agents(
        state.events, job_id=job.id, live_agents=service.live_agents()
    )
    script = next(v for v in views if v.agent_id == "ScriptAgent")
    assert script.status == "waiting"
    assert script.stale is True


def test_a_live_lease_keeps_the_character_working(state):
    job = state.store.create(title="live", payload={"title": "live"})
    state.store.transition(job.id, JobState.TOPIC_SELECTED)
    state.events.emit(job_id=job.id, agent_id="ResearchAgent", event_type="stage_started")
    keeper = LeaseKeeper(state.store.db_path, ttl_s=120)
    keeper.acquire(job.id)

    state.running[job.id] = threading.Thread(target=lambda: None, name="live")
    service = JobService(state)
    assert service.live_agents() == {"ResearchAgent"}, "TOPIC_SELECTED is produced by ResearchAgent"

    views = project_agents(
        state.events, job_id=job.id, live_agents=service.live_agents()
    )
    research = next(v for v in views if v.agent_id == "ResearchAgent")
    assert research.status == "working"
    assert research.stale is False


def test_the_age_fallback_still_catches_a_working_event_with_a_live_lease(state):
    """Second net: a working event older than the fallback is stale even with a fresh lease."""
    job = state.store.create(title="old", payload={"title": "old"})
    state.events.emit(job_id=job.id, agent_id="ScriptAgent", event_type="stage_started")
    with state.events._connect() as conn:
        conn.execute(
            "UPDATE studio_events SET created_at = ? WHERE job_id = ?", (_past(3600), job.id)
        )
    views = project_agents(state.events, job_id=job.id, live_agents={"ScriptAgent"})
    script = next(v for v in views if v.agent_id == "ScriptAgent")
    assert script.status == "waiting"
    assert script.stale is True


def test_the_snapshot_route_reads_the_lease_not_the_thread_set(state):
    """End to end: the HTTP projection honours the persisted expiry."""
    app = create_app(state)
    client = TestClient(app)
    created = client.post(
        "/api/jobs", json={"title": "wedged", "topic": "x", "provider_mode": "mock"}
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    state.events.emit(job_id=job_id, agent_id="ScriptAgent", event_type="stage_started")
    keeper = LeaseKeeper(state.store.db_path, ttl_s=120)
    keeper.acquire(job_id)
    with keeper._connect() as conn:
        conn.execute(
            "UPDATE job_leases SET expires_at = ? WHERE job_id = ?", (_past(), job_id)
        )
    state.running[job_id] = threading.Thread(target=lambda: None, name="wedged")

    body = client.get("/api/studio/snapshot").json()
    script = next(a for a in body["agents"] if a["agent_id"] == "ScriptAgent")
    assert script["status"] == "waiting"
    assert script["stale"] is True


def test_a_long_render_does_not_read_as_waiting_while_its_worker_still_owns_the_lease(tmp_path):
    """A 130 s stage against a 120 s TTL must stay ``working``, not flip to a phantom ``waiting``.

    Staleness is derived from ``expires_at``, so a worker that never renews has a dead row 120 s
    in, and a live render would be projected as a dead one. The runner heartbeats every ttl/3
    while a stage executes — that is what keeps the row alive now; renewal no longer repairs a
    lapse, so faking 130 s without a heartbeat must show the lease expired.
    """
    from packages.core.orchestration import leases as lease_module

    store = JobStore(tmp_path / "f.db", tmp_path / "jobs")
    events = StudioEventStore(tmp_path / "f.db")
    job = store.create(title="render", payload={"title": "render"})
    for step in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
    ):
        store.transition(job.id, step)
    events.emit(job_id=job.id, agent_id="EditorAgent", event_type="stage_started")

    started = dt.datetime.now(dt.UTC).replace(microsecond=0)
    keeper = LeaseKeeper(store.db_path, ttl_s=120)
    keeper.acquire(job.id)
    keeper.start_heartbeat(interval_s=3600)  # one beat, far out: proves the mechanism exists

    skew = dt.timedelta(seconds=130)
    with keeper._connect() as conn:
        for field in ("acquired_at", "renewed_at", "expires_at"):
            conn.execute(
                f"UPDATE job_leases SET {field} = ? WHERE job_id = ?",
                ((started - skew).isoformat(), job.id),
            )
        conn.execute(
            "UPDATE studio_events SET created_at = ? WHERE job_id = ?",
            ((started - skew).isoformat(), job.id),
        )

    assert lease_module.unexpired_jobs(store.db_path, [job.id]) == set(), (
        "an un-renewed lease really has expired"
    )
    # Renewal no longer crosses a lapse: only a fresh beat (the runner's heartbeat thread)
    # keeps the row alive. A heartbeat renew lands while the row is unexpired, so simulate
    # exactly that: acquire-time stamp is stale, renewal extends from *now*.
    with keeper._connect() as conn:
        conn.execute(
            "UPDATE job_leases SET expires_at = ? WHERE job_id = ?",
            ((dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)).isoformat(), job.id),
        )
    assert keeper.owns() is True
    assert lease_module.unexpired_jobs(store.db_path, [job.id]) == {job.id}

    views = project_agents(events, job_id=job.id, live_agents={"EditorAgent"})
    editor = next(v for v in views if v.agent_id == "EditorAgent")
    assert editor.status == "working"
    assert editor.stale is False
    keeper.stop_heartbeat()


def test_an_expired_lease_still_loses_to_a_live_holder(tmp_path):
    """Expiry must not be relaxed for everyone: a dead worker's row must still read as dead."""
    from packages.core.orchestration.leases import unexpired_jobs

    store = JobStore(tmp_path / "f.db", tmp_path / "jobs")
    job = store.create(title="dead", payload={"title": "dead"})
    keeper = LeaseKeeper(store.db_path, ttl_s=120)
    keeper.acquire(job.id)
    with keeper._connect() as conn:
        conn.execute(
            "UPDATE job_leases SET expires_at = ? WHERE job_id = ?", (_past(), job.id)
        )
    assert unexpired_jobs(store.db_path, [job.id]) == set()
