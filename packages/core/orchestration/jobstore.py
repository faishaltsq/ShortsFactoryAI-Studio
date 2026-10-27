"""SQLite-backed job store: atomic writes, explicit transitions, token-owned leases.

Design choices worth defending:

* **Raw ``sqlite3``, no ORM.** The queries are a handful of statements; an ORM would add a mapping
  layer and a dependency to debug at 2 a.m. for no benefit.
* **WAL + busy_timeout.** The API thread reads while the worker writes. Without both, a read during
  a write raises ``database is locked`` under load and never under test.
* **Atomic artifact writes.** Write ``.tmp`` in the same directory, ``fsync``, ``os.replace``. A
  half-written ``storyboard.json`` must never be readable.
* **A state change and its event commit in the same transaction.** A state change without an event
  makes the studio lie; an event without a state change makes the log useless.
* **Path confinement.** Artifact names are validated, not trusted, so a name from a URL cannot walk
  out of the job directory.
"""

from __future__ import annotations

import builtins
import datetime as dt
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts.state import JobState, assert_transition


class IllegalTransition(RuntimeError):
    def __init__(self, job_id: str, source: str, target: str) -> None:
        self.job_id = job_id
        self.source = source
        self.target = target
        super().__init__(f"job {job_id}: illegal transition {source} -> {target}")


class ArtifactNotFound(FileNotFoundError):
    pass


class ApprovalEvidenceMissing(IllegalTransition):
    """``APPROVED`` was requested without the gate's recorded evidence.

    Distinct from a plain illegal edge: the transition is in the allow-list, but the artifact that
    proves the gate ran is absent, unparseable, or about different bytes. The store does not decide
    whether the gate *should* pass — that is ``_approval_checks`` in ``apps/api``, which reads
    artifacts and hashes them. It only refuses to record the outcome without the evidence.
    """

    def __init__(self, job_id: str, source: str, reason: str) -> None:
        self.reason = reason
        IllegalTransition.__init__(self, job_id, source, f"APPROVED ({reason})")


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _utc_now_ms() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


SAFE_NAME = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def safe_artifact_name(name: str) -> str:
    """Reject traversal, separators, and anything that is not a plain file name."""
    if not name or len(name) > 128:
        raise ValueError("artifact name is empty or too long")
    if name in {".", ".."} or name.startswith("."):
        raise ValueError(f"artifact name {name!r} is not allowed")
    if not set(name) <= SAFE_NAME or "/" in name or "\\" in name:
        raise ValueError(f"artifact name {name!r} contains illegal characters")
    return name


@dataclass(frozen=True)
class JobRecord:
    id: str
    title: str
    state: JobState
    attempts: int
    payload: dict[str, Any]
    last_error: str | None
    created_at: str
    updated_at: str
    locked_at: str | None
    #: Queue priority: lower runs first (1 = most urgent; 5 = operator default). Additive.
    priority: int
    #: Earliest production start (ISO-8601 UTC). ``None`` means "as soon as schedulable".
    #: Schedules *production* only — never approval, never publication (STATE_MACHINE FR-8.4).
    scheduled_for: str | None

    @property
    def provider_mode(self) -> str:
        return str(self.payload.get("provider_mode", "live"))

    @property
    def is_mock(self) -> bool:
        return self.provider_mode == "mock"


class JobStore:
    """One SQLite file holds jobs, events, leases, and usage."""

    def __init__(self, db_path: Path, jobs_dir: Path) -> None:
        self.db_path = Path(db_path)
        self.jobs_dir = Path(jobs_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migrate()

    # -- plumbing ---------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _migrate(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for version, statements in MIGRATIONS:
                if version in applied:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?,?)",
                    (version, _utc_now()),
                )

    # -- jobs -------------------------------------------------------------------------------
    def create(
        self,
        *,
        title: str,
        payload: dict[str, Any] | None = None,
        state: JobState = JobState.IDEA_DISCOVERY,
        job_id: str | None = None,
        priority: int = 5,
        scheduled_for: str | None = None,
    ) -> JobRecord:
        """Create a job. ``priority``: lower runs first. ``scheduled_for``: earliest
        production start, UTC ISO-8601 — production scheduling only, never publish."""
        if not 1 <= int(priority) <= 9:
            raise ValueError(f"priority must be 1..9, got {priority}")
        now = _utc_now()
        identifier = job_id or os.urandom(8).hex()
        body = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs(id, title, state, attempts, payload, created_at, updated_at,"
                " priority, scheduled_for) VALUES (?,?,?,0,?,?,?,?,?)",
                (identifier, title, state.value, body, now, now, int(priority), scheduled_for),
            )
            self._insert_event(
                conn, identifier, None, state.value, "job created", now
            )
        (self.jobs_dir / identifier).mkdir(parents=True, exist_ok=True)
        return self.get(identifier)

    def get(self, job_id: str) -> JobRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown job {job_id!r}")
        return _record(row)

    def list(self, *, states: builtins.list[JobState] | None = None, limit: int = 200) -> builtins.list[JobRecord]:
        query = "SELECT * FROM jobs"
        params: list[Any] = []
        if states:
            placeholders = ",".join("?" for _ in states)
            query += f" WHERE state IN ({placeholders})"
            params.extend(state.value for state in states)
        # ``rowid`` breaks created_at ties deterministically: two jobs created in the same
        # second keep a stable insertion order everywhere this ordering is trusted.
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_record(row) for row in rows]

    def transition(
        self,
        job_id: str,
        target: JobState,
        *,
        detail: str = "",
        expected: JobState | None = None,
    ) -> JobRecord:
        """Move a job to ``target``, writing the event in the same transaction.

        ``expected`` makes the transition conditional: a worker that lost its lease must not
        overwrite the state another worker already set.
        """
        now = _utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown job {job_id!r}")
            current = JobState(row["state"])
            if expected is not None and current != expected:
                raise IllegalTransition(job_id, current.value, f"{target.value} (expected {expected.value})")
            try:
                assert_transition(current, target)
            except Exception as exc:  # noqa: BLE001 - re-raised with job context
                raise IllegalTransition(job_id, current.value, target.value) from exc
            if target is JobState.APPROVED:
                # A legal edge is not evidence. ``_approval_checks`` runs in ``apps/api`` and only
                # on the approve route, so any other caller that reaches the gate state — a resume
                # path, a scheduler, a maintenance script — would otherwise approve a job by
                # transitioning it. Require the artifact the gate writes.
                problem = self._approval_evidence_problem(job_id)
                if problem is not None:
                    raise ApprovalEvidenceMissing(job_id, current.value, problem)
            conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
                (target.value, now, job_id),
            )
            self._insert_event(conn, job_id, current.value, target.value, detail, now)
            updated = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _record(updated)

    def _approval_evidence_problem(self, job_id: str) -> str | None:
        """Return why ``approval.json`` does not authorise ``APPROVED``, or ``None`` when it does.

        Existence and minimal shape only. The store does not know what a valid gate result looks
        like beyond "it says approved, an operator signed it, the gate marked it publishable, and
        it names the render it judged" — deciding more would put policy in the persistence layer.
        """
        try:
            approval = self.read_artifact(job_id, "approval.json")
        except ArtifactNotFound:
            return "APPROVED requires approval.json, which does not exist for this job"
        except (OSError, ValueError) as exc:
            return f"approval.json cannot be read: {type(exc).__name__}"

        decision = approval.get("decision")
        if decision != "approved":
            return f"approval.json decision is {decision!r}, not 'approved'"
        if not str(approval.get("operator") or "").strip():
            return "approval.json records no operator"
        checks = approval.get("checks")
        if not isinstance(checks, dict) or checks.get("publishable") is not True:
            return "approval.json does not record checks.publishable == true"

        recorded = approval.get("render_sha256")
        if not recorded:
            return "approval.json records no render_sha256, so it cannot prove which render it approved"
        try:
            render = self.read_artifact(job_id, "render.json")
        except (ArtifactNotFound, OSError, ValueError):
            return "approval.json names a render_sha256 but render.json is missing or unreadable"
        current = render.get("sha256")
        if current != recorded:
            return (
                f"stale approval: approval.json was decided against render_sha256 {recorded}, "
                f"but render.json.sha256 is {current}"
            )
        return None

    def set_error(self, job_id: str, message: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET last_error = ?, updated_at = ? WHERE id = ?",
                (message, _utc_now(), job_id),
            )

    def bump_attempts(self, job_id: str) -> int:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (_utc_now(), job_id),
            )
            row = conn.execute("SELECT attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return int(row["attempts"]) if row else 0

    def delete(self, job_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # -- events -----------------------------------------------------------------------------
    def _insert_event(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        from_state: str | None,
        to_state: str,
        detail: str,
        created_at: str,
    ) -> None:
        conn.execute(
            "INSERT INTO job_events(job_id, from_state, to_state, detail, created_at)"
            " VALUES (?,?,?,?,?)",
            (job_id, from_state, to_state, detail, created_at),
        )

    def events(self, job_id: str, *, after_id: int = 0, limit: int = 500) -> builtins.list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, job_id, from_state, to_state, detail, created_at FROM job_events"
                " WHERE job_id = ? AND id > ? ORDER BY id LIMIT ?",
                (job_id, after_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def event_count(self, job_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM job_events WHERE job_id = ?", (job_id,)
            ).fetchone()
        return int(row["n"])

    # -- artifacts --------------------------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        safe = safe_artifact_name(job_id)
        path = self.jobs_dir / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_artifact(self, job_id: str, name: str, payload: dict[str, Any]) -> Path:
        """Atomic JSON write: temp file in the same directory, fsync, replace."""
        safe = safe_artifact_name(name)
        directory = self.job_dir(job_id)
        target = directory / safe
        tmp = directory / f".{safe}.tmp"
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        return target

    def read_artifact(self, job_id: str, name: str) -> dict[str, Any]:
        safe = safe_artifact_name(name)
        path = self.job_dir(job_id) / safe
        if not path.is_file():
            raise ArtifactNotFound(f"artifact {name} does not exist for job {job_id}")
        artifact: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return artifact

    def has_artifact(self, job_id: str, name: str) -> bool:
        try:
            safe = safe_artifact_name(name)
        except ValueError:
            return False
        return (self.job_dir(job_id) / safe).is_file()

    def list_artifacts(self, job_id: str) -> builtins.list[str]:
        directory = self.job_dir(job_id)
        return sorted(
            path.name
            for path in directory.iterdir()
            if path.is_file() and not path.name.startswith(".")
        )

    # -- topic discoveries ------------------------------------------------------------------
    def record_topic_discovery(
        self, *, discovery_id: str, payload: dict[str, Any], titles: builtins.list[str]
    ) -> None:
        """Persist one discovery run. ``titles`` seeds the next run's avoid list."""
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO topic_discoveries (id, payload, candidates_json, created_at)
                VALUES (?,?,?,?)
                """,
                (
                    discovery_id,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(titles, ensure_ascii=False),
                    now,
                ),
            )

    def topic_discovery(self, discovery_id: str) -> dict[str, Any] | None:
        row = self._connect().execute(
            "SELECT payload FROM topic_discoveries WHERE id = ?", (discovery_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def topic_avoid_list(self, *, limit: int = 10) -> builtins.list[str]:
        """Candidate titles from the last ``limit`` discoveries, newest first.

        Seeded initially from job titles (the plan's rule); once discoveries exist they dominate,
        because repeating a *proposed* title is as bad as repeating a produced one.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT candidates_json FROM topic_discoveries ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        if rows:
            out: list[str] = []
            for row in rows:
                titles = json.loads(row["candidates_json"])
                if isinstance(titles, list):
                    out.extend(str(t) for t in titles if str(t).strip())
            return out
        return [
            job.title
            for job in reversed(self.list(limit=limit))
            if job.title.strip()
        ]


def _record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        title=row["title"],
        state=JobState(row["state"]),
        attempts=int(row["attempts"]),
        payload=json.loads(row["payload"] or "{}"),
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        locked_at=row["locked_at"],
        priority=int(row["priority"]),
        scheduled_for=row["scheduled_for"],
    )


MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL DEFAULT '{}',
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                locked_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                from_state TEXT,
                to_state TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state)",
            "CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id)",
            """
            CREATE TABLE IF NOT EXISTS job_leases (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                token TEXT NOT NULL,
                owner TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                renewed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_leases_expiry ON job_leases(expires_at)",
        ],
    ),
    (
        2,
        [
            """
            CREATE TABLE IF NOT EXISTS topic_discoveries (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL DEFAULT '{}',
                candidates_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_discoveries_time ON topic_discoveries(created_at)",
        ],
    ),
    (
        3,
        [
            # Additive per DATA_CONTRACTS rule 0: new columns with defaults, no renames.
            "ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 5",
            "ALTER TABLE jobs ADD COLUMN scheduled_for TEXT",
            "CREATE INDEX IF NOT EXISTS idx_jobs_sched ON jobs(scheduled_for)",
        ],
    ),
]
