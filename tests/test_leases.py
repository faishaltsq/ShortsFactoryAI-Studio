"""Leases: one owner at a time, and a lost lease never writes."""

from __future__ import annotations

import datetime as dt

import pytest

from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.leases import LeaseKeeper, LeaseLost


@pytest.fixture
def db(tmp_path):
    store = JobStore(tmp_path / "f.db", tmp_path / "jobs")
    job = store.create(title="x")
    return store, job.id


def test_acquire_gives_exclusive_ownership(db):
    store, job_id = db
    first = LeaseKeeper(store.db_path, owner="a")
    second = LeaseKeeper(store.db_path, owner="b")
    first.acquire(job_id)
    with pytest.raises(LeaseLost) as exc:
        second.acquire(job_id)
    assert "held by a" in str(exc.value)
    first.release()


def test_release_allows_reacquisition(db):
    store, job_id = db
    first = LeaseKeeper(store.db_path, owner="a")
    first.acquire(job_id)
    first.release()
    second = LeaseKeeper(store.db_path, owner="b")
    assert second.acquire(job_id).owner == "b"


def test_renew_extends_the_expiry(db):
    store, job_id = db
    keeper = LeaseKeeper(store.db_path, ttl_s=60)
    lease = keeper.acquire(job_id)
    assert keeper.renew() is True
    refreshed = keeper.current(job_id)
    assert dt.datetime.fromisoformat(refreshed.expires_at) >= dt.datetime.fromisoformat(
        lease.expires_at
    )


def test_an_expired_lease_can_be_taken_over(db):
    store, job_id = db
    keeper = LeaseKeeper(store.db_path, ttl_s=1)
    keeper.acquire(job_id)
    # Force expiry rather than sleeping.
    with keeper._connect() as conn:
        past = (dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)).replace(microsecond=0).isoformat()
        conn.execute("UPDATE job_leases SET expires_at = ? WHERE job_id = ?", (past, job_id))
    rival = LeaseKeeper(store.db_path, owner="rival")
    assert rival.acquire(job_id).owner == "rival"


def test_a_stale_worker_that_lost_its_lease_reports_it(db):
    store, job_id = db
    stale = LeaseKeeper(store.db_path, ttl_s=1, owner="stale")
    stale.acquire(job_id)
    with stale._connect() as conn:
        past = (dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)).replace(microsecond=0).isoformat()
        conn.execute("UPDATE job_leases SET expires_at = ? WHERE job_id = ?", (past, job_id))
    rival = LeaseKeeper(store.db_path, owner="rival")
    rival.acquire(job_id)

    assert stale.owns() is False
    with pytest.raises(LeaseLost):
        stale.assert_owned()
    # The stale worker must not be able to release the rival's lease either.
    stale.release()
    assert rival.owns() is True


def test_release_only_removes_our_own_row(db):
    store, job_id = db
    keeper = LeaseKeeper(store.db_path, owner="mine")
    keeper.acquire(job_id)
    with keeper._connect() as conn:
        conn.execute("UPDATE job_leases SET token = 'someone-else' WHERE job_id = ?", (job_id,))
    keeper.release()
    assert keeper.current(job_id) is not None, "must not delete another worker's lease"


def test_renew_after_losing_returns_false(db):
    store, job_id = db
    keeper = LeaseKeeper(store.db_path, owner="mine")
    keeper.acquire(job_id)
    with keeper._connect() as conn:
        conn.execute("UPDATE job_leases SET token = 'other' WHERE job_id = ?", (job_id,))
    assert keeper.renew() is False


def test_context_manager_releases(db):
    store, job_id = db
    with LeaseKeeper(store.db_path) as keeper:
        keeper.acquire(job_id)
        assert keeper.owns() is True
    assert keeper.current(job_id) is None


def test_acquire_on_unknown_job_is_refused_by_the_foreign_key(db):
    import sqlite3

    store, _ = db
    with pytest.raises(sqlite3.IntegrityError):
        LeaseKeeper(store.db_path).acquire("does-not-exist")
