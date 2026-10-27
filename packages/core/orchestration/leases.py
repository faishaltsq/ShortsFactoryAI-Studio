"""Token-owned leases.

A lease is the only thing that gives a worker the right to write a job's state. It is owned by a
random token, not by a worker id: two processes with the same name must not be able to confuse each
other, and a restarted process must not inherit a dead one's authority.

The failure this prevents is specific and expensive: a worker that stalled (a blocked stage, a
suspended laptop) wakes up after another worker took over, and writes ``FAILED`` over the new
worker's successful run. So every state write is conditional on still owning the token, and losing
it stops the worker without touching the job.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TTL_S = 120
DEFAULT_STALE_S = 1800


class LeaseLost(RuntimeError):
    """This worker no longer owns the job. Stop; do not write anything."""

    def __init__(self, job_id: str, reason: str, *, token: str = "") -> None:
        self.job_id = job_id
        self.reason = reason
        self.token = token
        detail = f"lease for job {job_id}: {reason}"
        if token:
            detail += f" (token {token[:8]})"
        super().__init__(detail)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(moment: dt.datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Lease:
    job_id: str
    token: str
    owner: str
    acquired_at: str
    renewed_at: str
    expires_at: str

    @property
    def expired(self) -> bool:
        return dt.datetime.fromisoformat(self.expires_at) <= _now()

def _read_rows(db_path: Path, job_ids: list[str]) -> list[Lease]:
    """One connection, one statement, for every requested job."""
    if not job_ids:
        return []
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        placeholders = ",".join("?" for _ in job_ids)
        rows = conn.execute(
            f"SELECT * FROM job_leases WHERE job_id IN ({placeholders})", job_ids
        ).fetchall()
    finally:
        conn.close()
    return [
        Lease(
            row["job_id"], row["token"], row["owner"],
            row["acquired_at"], row["renewed_at"], row["expires_at"],
        )
        for row in rows
    ]

def read_lease(db_path: Path, job_id: str) -> Lease | None:
    """The persisted lease row for one job, or ``None``. Reads; never acquires."""
    rows = _read_rows(Path(db_path), [job_id])
    return rows[0] if rows else None

def read_leases(db_path: Path, job_ids: list[str]) -> dict[str, Lease]:
    """Every persisted lease for the given jobs, keyed by job id.

    The studio asks this to decide staleness: a worker that stopped heartbeating may still have a
    live thread, but its lease has expired and that is the authority (ADR-008, FR-9.4).
    """
    return {lease.job_id: lease for lease in _read_rows(Path(db_path), list(job_ids))}

def unexpired_jobs(db_path: Path, job_ids: list[str]) -> set[str]:
    """The subset of ``job_ids`` whose lease row exists and has not expired."""
    now = _now()
    return {
        job_id
        for job_id, lease in read_leases(db_path, job_ids).items()
        if dt.datetime.fromisoformat(lease.expires_at) > now
    }


class LeaseKeeper:
    """Acquire, renew, and release one job's lease, and answer "do I still own this?"."""

    def __init__(
        self,
        db_path: Path,
        *,
        ttl_s: int = DEFAULT_TTL_S,
        owner: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl_s = ttl_s
        self.owner = owner or f"worker-{os.getpid()}"
        self._token = uuid.uuid4().hex
        self._job_id: str | None = None
        self._lock = threading.Lock()

    @property
    def token(self) -> str:
        return self._token

    @property
    def job_id(self) -> str | None:
        return self._job_id

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        # Without this a lease can be written for a job that does not exist, and the orphan row
        # then blocks a real job's id forever.
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def acquire(self, job_id: str) -> Lease:
        """Take the lease, or raise if another live worker holds it."""
        now = _now()
        expires = now + dt.timedelta(seconds=self.ttl_s)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_leases WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is not None:
                holder = Lease(
                    row["job_id"], row["token"], row["owner"],
                    row["acquired_at"], row["renewed_at"], row["expires_at"],
                )
                if not holder.expired:
                    raise LeaseLost(
                        job_id,
                        f"held by {holder.owner} until {holder.expires_at}",
                        token=self._token,
                    )
                conn.execute("DELETE FROM job_leases WHERE job_id = ?", (job_id,))
            conn.execute(
                "INSERT INTO job_leases(job_id, token, owner, acquired_at, renewed_at, expires_at)"
                " VALUES (?,?,?,?,?,?)",
                (job_id, self._token, self.owner, _iso(now), _iso(now), _iso(expires)),
            )
            self._job_id = job_id
        return Lease(job_id, self._token, self.owner, _iso(now), _iso(now), _iso(expires))

    def renew(self) -> bool:
        """Extend the lease and keep ownership alive. False when this token no longer owns it.

        A worker that never renews has an expired row after ``ttl_s``. Staleness is derived from
        that row, so an un-renewed lease makes a live worker read as dead — the 120 s TTL against a
        900 s render. The runner heartbeats through this method, and it is the only thing that
        extends expiry.
        """
        if self._job_id is None:
            return False
        now = _now()
        expires = now + dt.timedelta(seconds=self.ttl_s)
        with self._lock, self._connect() as conn:
            # Renewal extends the row this token owns. Proof of ownership is the token, not the
            # expiry: this call is what repairs an expiry this same worker let lapse.
            cursor = conn.execute(
                "UPDATE job_leases SET renewed_at = ?, expires_at = ?"
                " WHERE job_id = ? AND token = ?",
                (_iso(now), _iso(expires), self._job_id, self._token),
            )
            return cursor.rowcount == 1

    def owns(self) -> bool:
        """Do I still hold an unexpired lease? An expired row is not ownership, whatever the token.

        Token equality alone was a second vote on the question the studio already answers from
        ``expires_at``, and the two disagreed: after the TTL the projection read ``waiting`` while
        ``owns()`` kept letting the worker write state. The lease is expired or it is not; there is
        one answer.
        """
        if self._job_id is None:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token, expires_at FROM job_leases WHERE job_id = ?", (self._job_id,)
            ).fetchone()
        if row is None or row["token"] != self._token:
            return False
        return dt.datetime.fromisoformat(row["expires_at"]) > _now()

    def assert_owned(self) -> None:
        if not self.owns():
            raise LeaseLost(
                self._job_id or "?", "not owned by this worker", token=self._token
            )

    def release(self) -> None:
        """Give up the lease. Only removes the row if this token still owns it."""
        if self._job_id is None:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM job_leases WHERE job_id = ? AND token = ?",
                (self._job_id, self._token),
            )
        self._job_id = None

    def current(self, job_id: str) -> Lease | None:
        return read_lease(self.db_path, job_id)

    def __enter__(self) -> LeaseKeeper:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
