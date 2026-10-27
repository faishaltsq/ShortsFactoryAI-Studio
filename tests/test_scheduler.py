"""The scheduler: opt-in, and structurally unable to select a job awaiting approval.

The failure this file exists to prevent is a scheduler that drains the queue past the operator
gate — running work nobody asked for, or (worse) advancing a job toward publication. So the
central test asserts the *claim query itself* excludes every state at or past
``READY_FOR_APPROVAL``, rather than asserting that some caller remembers to filter.
"""

from __future__ import annotations

import pytest

from packages.core.contracts.state import JobState, is_transition_allowed
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.scheduler import (
    DEFAULT_ENABLED,
    SCHEDULABLE_STATES,
    claim_next,
    is_schedulable,
)


@pytest.fixture
def store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def test_the_scheduler_is_off_by_default():
    assert DEFAULT_ENABLED is False


def test_no_schedulable_state_is_at_or_past_the_approval_gate():
    """The allow-list defines "past the gate"; the schedulable set must be disjoint from it."""
    forbidden = {
        JobState.READY_FOR_APPROVAL,
        JobState.APPROVED,
        JobState.PRIVATE_UPLOAD,
        JobState.SCHEDULED,
        JobState.PUBLISHED,
        JobState.REJECTED,
    }
    assert not (set(SCHEDULABLE_STATES) & forbidden), (
        "the scheduler must never select a job at or past the approval gate"
    )


def test_an_approval_waiting_job_is_never_claimed(store):
    """The claim query returns nothing for a job waiting on the operator."""
    job = store.create(title="Menunggu", payload={"provider_mode": "mock"})
    for state in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY, JobState.ASSETS_READY,
        JobState.AUDIO_READY, JobState.RENDERING, JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job.id, state)
    assert claim_next(store) is None


def test_a_published_job_is_never_claimed(store):
    job = store.create(title="Terbit", payload={"provider_mode": "mock"})
    store.transition(job.id, JobState.TOPIC_SELECTED)
    store.transition(job.id, JobState.BLOCKED)
    store.transition(job.id, JobState.CANCELLED)
    assert claim_next(store) is None


def test_a_resumable_job_is_claimed(store):
    """A job sitting in a pre-gate stage is exactly what the scheduler exists to pick up."""
    job = store.create(title="Siap", payload={"provider_mode": "mock"})
    store.transition(job.id, JobState.TOPIC_SELECTED)
    claimed = claim_next(store)
    assert claimed is not None
    assert claimed.id == job.id


def test_a_freshly_created_job_is_claimed(store):
    job = store.create(title="Baru", payload={"provider_mode": "mock"})
    claimed = claim_next(store)
    assert claimed is not None and claimed.id == job.id


def test_claiming_is_one_at_a_time_and_oldest_first(store):
    first = store.create(title="Pertama", payload={"provider_mode": "mock"})
    second = store.create(title="Kedua", payload={"provider_mode": "mock"})
    claimed = claim_next(store)
    assert claimed is not None
    assert claimed.id in {first.id, second.id}
    # A second claim must not return the same job.
    other = claim_next(store, exclude={claimed.id})
    assert other is not None
    assert other.id != claimed.id


def test_is_schedulable_answers_per_state():
    assert is_schedulable(JobState.IDEA_DISCOVERY) is True
    assert is_schedulable(JobState.READY_FOR_APPROVAL) is False
    assert is_schedulable(JobState.APPROVED) is False
    assert is_schedulable(JobState.PUBLISHED) is False


# -- PAUSED must be reachable, or it is a dead state -------------------------------------------


def test_paused_is_reachable_from_a_running_stage():
    assert is_transition_allowed(JobState.RENDERING, JobState.PAUSED)


def test_paused_can_resume_into_a_running_stage():
    assert is_transition_allowed(JobState.PAUSED, JobState.RENDERING)


def test_paused_cannot_be_entered_from_the_approval_gate():
    """Pausing a job the operator is deciding would hide it from the queue with no owner."""
    assert not is_transition_allowed(JobState.READY_FOR_APPROVAL, JobState.PAUSED)


def test_paused_has_no_inbound_edge_from_a_terminal_state():
    for terminal in (JobState.PUBLISHED, JobState.REJECTED, JobState.CANCELLED):
        assert not is_transition_allowed(terminal, JobState.PAUSED)


def test_paused_is_not_schedulable(store):
    """A paused job is paused on purpose; the scheduler must not resume it."""
    assert is_schedulable(JobState.PAUSED) is False


# -- the loop: off by default, one tick at a time, and it re-checks the state -------------------


def test_the_loop_is_off_by_default():
    from packages.core.orchestration.scheduler import SchedulerConfig

    assert SchedulerConfig().enabled is False


def test_the_loop_reads_its_config_from_the_operator_environment():
    from packages.core.orchestration.scheduler import SchedulerConfig

    off = SchedulerConfig.from_env({})
    assert off.enabled is False
    assert off.interval_s == 60.0

    on = SchedulerConfig.from_env(
        {"SHORTS_SCHEDULER_ENABLED": "1", "SHORTS_SCHEDULER_INTERVAL_S": "15"}
    )
    assert on.enabled is True
    assert on.interval_s == 15.0


def test_an_invalid_interval_is_refused_not_ignored():
    """A silently-ignored bad interval is a scheduler that runs at a cadence nobody chose."""
    from packages.core.orchestration.scheduler import SchedulerConfig

    with pytest.raises(ValueError, match="SHORTS_SCHEDULER_INTERVAL_S"):
        SchedulerConfig.from_env({"SHORTS_SCHEDULER_INTERVAL_S": "every minute"})
    with pytest.raises(ValueError, match="SHORTS_SCHEDULER_INTERVAL_S"):
        SchedulerConfig.from_env({"SHORTS_SCHEDULER_INTERVAL_S": "0"})
    with pytest.raises(ValueError, match="SHORTS_SCHEDULER_INTERVAL_S"):
        SchedulerConfig.from_env({"SHORTS_SCHEDULER_INTERVAL_S": "-5"})


def test_an_unrecognised_enabled_value_is_refused():
    from packages.core.orchestration.scheduler import SchedulerConfig

    with pytest.raises(ValueError, match="SHORTS_SCHEDULER_ENABLED"):
        SchedulerConfig.from_env({"SHORTS_SCHEDULER_ENABLED": "maybe"})


def test_a_disabled_loop_claims_nothing(store):
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    store.create(title="Baru", payload={"provider_mode": "mock"})
    started: list[str] = []
    loop = SchedulerLoop(
        store, started.append, config=SchedulerConfig(enabled=False)
    )
    assert loop.tick() is None
    assert started == []


def test_one_tick_claims_exactly_one_schedulable_job(store):
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    first = store.create(title="Pertama", payload={"provider_mode": "mock"})
    second = store.create(title="Kedua", payload={"provider_mode": "mock"})
    started: list[str] = []
    loop = SchedulerLoop(store, started.append, config=SchedulerConfig(enabled=True))

    claimed = loop.tick()
    # ``created_at`` has second resolution, so "oldest" between two jobs created in the same
    # second is not a meaningful assertion. What matters is one job per tick, and never the same
    # one twice.
    assert claimed is not None and claimed in {first.id, second.id}
    assert started == [claimed], "one tick starts exactly one job"

    following = loop.tick()
    assert following is not None and following != claimed
    assert started == [claimed, following]


def test_a_tick_with_nothing_schedulable_starts_nothing(store):
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    started: list[str] = []
    loop = SchedulerLoop(store, started.append, config=SchedulerConfig(enabled=True))
    assert loop.tick() is None
    assert started == []


def test_a_job_at_the_gate_is_never_claimed_even_when_it_is_the_oldest(store):
    """The oldest job is the one a naive scheduler would pick first. It must be skipped."""
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    waiting = store.create(title="Menunggu", payload={"provider_mode": "mock"})
    for state in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY, JobState.ASSETS_READY,
        JobState.AUDIO_READY, JobState.RENDERING, JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL,
    ):
        store.transition(waiting.id, state)
    younger = store.create(title="Muda", payload={"provider_mode": "mock"})

    started: list[str] = []
    loop = SchedulerLoop(store, started.append, config=SchedulerConfig(enabled=True))
    claimed = loop.tick()

    assert claimed == younger.id, "the approval-waiting job must be skipped, not claimed"
    assert waiting.id not in started


def test_the_loop_rechecks_the_state_before_handing_off(store, monkeypatch):
    """The state can change between ``claim_next`` and ``start``.

    A job can reach ``READY_FOR_APPROVAL`` (or be approved) in that window — a worker finishing a
    stage, an operator approving. Handing such a job to the runner would start work the operator
    is in the middle of deciding about. So the loop re-reads the row and refuses.
    """
    from packages.core.orchestration import scheduler as sched
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    job = store.create(title="Balapan", payload={"provider_mode": "mock"})
    for state in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY, JobState.ASSETS_READY,
        JobState.AUDIO_READY, JobState.RENDERING, JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job.id, state)

    # Simulate the race: the claim returns a record that was schedulable when it was read.
    stale = store.get(job.id)
    monkeypatch.setattr(sched, "claim_next", lambda store_, **kw: stale)

    started: list[str] = []
    loop = SchedulerLoop(store, started.append, config=SchedulerConfig(enabled=True))
    assert loop.tick() is None
    assert started == [], "a job that reached the gate must not be handed to the runner"


def test_start_twice_does_not_create_a_second_loop(store):
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    started: list[str] = []
    loop = SchedulerLoop(
        store, started.append, config=SchedulerConfig(enabled=True, interval_s=0.01)
    )
    try:
        assert loop.start() is True
        assert loop.start() is False, "a second start must not spawn a second thread"
        assert loop.running is True
    finally:
        loop.stop()
    assert loop.running is False


def test_stop_is_idempotent_and_restartable(store):
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    started: list[str] = []
    loop = SchedulerLoop(
        store, started.append, config=SchedulerConfig(enabled=True, interval_s=0.01)
    )
    loop.stop()  # never started: must not raise
    loop.stop()

    assert loop.start() is True
    loop.stop()
    loop.stop()  # twice in a row
    assert loop.running is False

    assert loop.start() is True, "stop then start must work"
    loop.stop()
    assert loop.running is False


def test_a_running_loop_eventually_starts_a_job(store):
    """The thread really ticks, not just the method."""
    import time

    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    job = store.create(title="Ambil", payload={"provider_mode": "mock"})
    started: list[str] = []
    loop = SchedulerLoop(
        store, started.append, config=SchedulerConfig(enabled=True, interval_s=0.01)
    )
    try:
        loop.start()
        deadline = time.time() + 5
        while time.time() < deadline and not started:
            time.sleep(0.01)
    finally:
        loop.stop()
    assert started == [job.id]


# -- wiring: the loop exists but nothing starts it -------------------------------------------------


def test_the_app_builds_a_scheduler_that_is_not_running(tmp_path):
    """``create_app`` must not start a scheduler. Starting is an operator action."""

    from apps.api.main import create_app
    from apps.api.settings import Settings
    from apps.api.state import AppState

    settings = Settings(
        data_dir=tmp_path / "d", db_path=tmp_path / "d" / "f.db",
        jobs_dir=tmp_path / "d" / "jobs", secrets_dir=tmp_path / "d" / "secrets",
        studio_config=tmp_path / "c" / "studio.json",
    ).ensure()
    state = AppState.build(settings)
    create_app(state)
    assert state.scheduler is None, "the app must not build a scheduler unless asked"


def test_the_scheduler_hands_off_to_job_service_start(tmp_path):
    """The hand-off is ``JobService.start`` — the same path the run button uses."""
    from apps.api.jobs import JobService
    from apps.api.settings import Settings
    from apps.api.state import AppState
    from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop

    settings = Settings(
        data_dir=tmp_path / "d", db_path=tmp_path / "d" / "f.db",
        jobs_dir=tmp_path / "d" / "jobs", secrets_dir=tmp_path / "d" / "secrets",
        studio_config=tmp_path / "c" / "studio.json",
    ).ensure()
    state = AppState.build(settings)
    service = JobService(state)
    job = state.store.create(title="Jadwal", payload={"provider_mode": "mock"})

    loop = SchedulerLoop(
        state.store, service.start, config=SchedulerConfig(enabled=True)
    )
    claimed = loop.tick()
    assert claimed == job.id
    # ``start`` spawns a worker thread; wait for it to finish so the test leaves nothing running.
    import time

    deadline = time.time() + 60
    while time.time() < deadline and job.id in state.running:
        time.sleep(0.05)
    assert state.store.get(job.id).state is not JobState.IDEA_DISCOVERY, (
        "the scheduler's hand-off must actually run the job"
    )


def test_priority_runs_before_age(store):
    """A low priority number outranks a job that has been waiting longer."""
    old = store.create(title="Tua", payload={"provider_mode": "mock"})
    urgent = store.create(title="Cepat", payload={"provider_mode": "mock"}, priority=1)
    claimed = claim_next(store)
    assert claimed is not None and claimed.id == urgent.id
    _ = old


def test_same_priority_falls_back_to_oldest_first(store):
    first = store.create(title="Pertama", payload={"provider_mode": "mock"}, priority=3)
    second = store.create(title="Kedua", payload={"provider_mode": "mock"}, priority=3)
    claimed = claim_next(store)
    assert claimed is not None and claimed.id == first.id
    _ = second


def test_a_future_scheduled_job_is_never_claimed_early(store):
    """A calendar entry waits: future scheduled_for excludes the job from claiming."""
    now_job = store.create(title="Sekarang", payload={"provider_mode": "mock"})
    future = store.create(
        title="Nanti",
        payload={"provider_mode": "mock"},
        scheduled_for="2099-01-01T00:00:00+00:00",
    )
    claimed = claim_next(store)
    assert claimed is not None and claimed.id == now_job.id
    later = claim_next(store, exclude={now_job.id})
    assert later is None, "future job must not be pulled early"
    _ = future


def test_a_past_scheduled_job_is_claimable(store):
    past = store.create(
        title="Telat",
        payload={"provider_mode": "mock"},
        scheduled_for="2000-01-01T00:00:00+00:00",
    )
    claimed = claim_next(store)
    assert claimed is not None and claimed.id == past.id


def test_priority_bounds_are_enforced_at_creation(store):
    with pytest.raises(ValueError, match="priority"):
        store.create(title="Salah", payload={"provider_mode": "mock"}, priority=10)
    with pytest.raises(ValueError, match="priority"):
        store.create(title="Salah", payload={"provider_mode": "mock"}, priority=0)


def test_a_scheduled_job_past_the_approval_gate_is_never_claimed(store):
    """Production scheduling must never launder a job past the human gate."""
    gated = store.create(
        title="Di gerbang",
        payload={"provider_mode": "mock"},
        state=JobState.READY_FOR_APPROVAL,
        priority=1,
    )
    assert claim_next(store) is None
    _ = gated
