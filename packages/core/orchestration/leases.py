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
        """Extend the lease. Returns False when the token is no longer the owner."""
        if self._job_id is None:
            return False
        now = _now()
        expires = now + dt.timedelta(seconds=self.ttl_s)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE job_leases SET renewed_at = ?, expires_at = ?"
                " WHERE job_id = ? AND token = ?",
                (_iso(now), _iso(expires), self._job_id, self._token),
            )
            return cursor.rowcount == 1

    def owns(self) -> bool:
        if self._job_id is None:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token FROM job_leases WHERE job_id = ?", (self._job_id,)
            ).fetchone()
        return row is not None and row["token"] == self._token

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
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_leases WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return Lease(
            row["job_id"], row["token"], row["owner"],
            row["acquired_at"], row["renewed_at"], row["expires_at"],
        )

    def __enter__(self) -> LeaseKeeper:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
