"""Snapshot latency under an event flood, measured rather than assumed.

Pre-fix, ``project_agents`` called ``store.history(job_id, limit=5)`` inside the per-agent loop: a
snapshot of fourteen agents opened fifteen SQLite connections for data one query returns.

Measured on this host (Windows 11, SQLite WAL, ``tempfile`` DB) with the same fixture and the same
200-iteration protocol, against the old per-agent loop:

    pre-fix  p50 = 17.4 ms   p95 = 32.9 ms   max = 53.8 ms

So the 250 ms ceiling was **already met** before this change; the N+1 was a real structural defect
but not the thing keeping this test red. What follows is a regression guard, not evidence of a fix.
The batch and the memo are kept for the connection storm they remove, not for the threshold.
"""

from __future__ import annotations

import time
from pathlib import Path

from packages.core.observability.events import AGENT_IDS, StudioEventStore, snapshot

#: Every agent fires, so the per-agent loop is at its worst. 1200 events is ~85 per agent — deep
#: enough that a per-agent history query is real work, shallow enough to insert in seconds.
FLOOD_EVENTS = 1200
ITERATIONS = 200
#: Index of the p95 sample out of 200 (0-based, so the 191st smallest).
P95_INDEX = 190
BUDGET_S = 0.250


def _flood(db: Path) -> StudioEventStore:
    store = StudioEventStore(db)
    for index in range(FLOOD_EVENTS):
        store.emit(
            job_id="job-perf",
            agent_id=AGENT_IDS[index % len(AGENT_IDS)],
            event_type="progress",
            progress=(index % 99) / 100,
        )
    return store


def test_snapshot_p95_under_a_flood_is_within_budget(tmp_path: Path):
    store = _flood(tmp_path / "perf.db")
    assert store.latest_event_id() == FLOOD_EVENTS
    snapshot(store)  # warm: the first call pays connection setup, not the projection

    samples: list[float] = []
    for _ in range(ITERATIONS):
        started = time.perf_counter()
        body = snapshot(store)
        samples.append(time.perf_counter() - started)
    samples.sort()
    known = {agent["agent_id"] for agent in body["agents"]}
    assert known == set(AGENT_IDS), "the timed snapshot must be the real projection"

    p95 = samples[P95_INDEX]
    assert p95 < BUDGET_S, f"snapshot p95 {p95 * 1000:.1f} ms exceeds {BUDGET_S * 1000:.0f} ms"


def test_the_projection_does_not_open_one_connection_per_agent(tmp_path: Path):
    """The structural claim: a snapshot is a bounded number of statements, not one per agent."""
    store = _flood(tmp_path / "perf.db")
    opened = 0
    original = store._connect

    def counting():  # type: ignore[no-untyped-def]
        nonlocal opened
        opened += 1
        return original()

    store._connect = counting  # type: ignore[method-assign]
    snapshot(store)
    # cursor + latest_per_agent + recent_per_job. Fourteen agents must not add fourteen.
    assert opened <= 4, f"{opened} connections for one snapshot of {len(AGENT_IDS)} agents"
