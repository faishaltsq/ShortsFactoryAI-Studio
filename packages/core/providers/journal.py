"""The provider request journal: no duplicate paid call after an unknown outcome.

What this buys, concretely: when a process dies between "the request was sent" and "the response
was recorded", the next run cannot know whether the provider charged for that call. Retrying it
might spend the money twice; ignoring it might drop work that was already paid for. So the journal
records the transition to ``sent`` *before* the transport call, records the response after it, and
treats "sent without a response" as ``uncertain`` — which blocks the job until an operator
acknowledges it, rather than silently retrying.

It also gives restarts their deduplication for free: a ``completed`` result replays locally with
zero new transport calls.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

#: Request lifecycle. ``prepared`` and ``sent`` are the only states a crash can interrupt; both
#: are recoverable (release, or block-and-acknowledge).
PREPARED = "prepared"
SENT = "sent"
REFUSED = "refused"
COMPLETED = "completed"
UNCERTAIN = "uncertain"


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def request_key(
    *,
    job_id: str | None,
    agent: str,
    ordinal: int,
    inputs_sha256: str,
    prompt_sha256: str,
    call_config_sha256: str,
) -> str:
    """The identity of one *logical* request, independent of how many times it is attempted.

    Deliberately excluded: credentials, timeouts, retry counts, budget and price configuration.
    Changing a timeout must not turn a retry into a different request, and changing a price must
    not make a recorded response unreplayable. Included: the job, the agent, which call within the
    stage this is, the canonical inputs, the effective prompt and the semantic call fields.
    """
    payload = "|".join(
        [
            job_id or "-",
            agent,
            str(ordinal),
            inputs_sha256,
            prompt_sha256,
            call_config_sha256,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_inputs(payload: dict[str, Any]) -> str:
    """Canonical SHA-256 of the semantic inputs. Key order and whitespace never matter."""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


class RequestJournal:
    """SQLite-backed record of every paid call attempt, and the only source of "may I call?"."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_requests (
                    request_key TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    job_id TEXT,
                    agent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    request_id TEXT,
                    prepared_at TEXT NOT NULL,
                    sent_at TEXT,
                    settled_at TEXT,
                    usage_json TEXT,
                    result_json TEXT,
                    error TEXT,
                    PRIMARY KEY (request_key, attempt)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_job ON provider_requests(job_id, agent)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_status ON provider_requests(status)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budget_reservations (
                    request_key TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    job_id TEXT,
                    agent TEXT NOT NULL,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    settled_at TEXT,
                    PRIMARY KEY (request_key, attempt)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reservations_status"
                " ON budget_reservations(status)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS provider_retry_authorizations ("
                " request_key TEXT NOT NULL, attempt INTEGER NOT NULL,"
                " operator TEXT NOT NULL, authorized_at TEXT NOT NULL,"
                " consumed_at TEXT, PRIMARY KEY(request_key, attempt))"
            )

    # -- lifecycle ---------------------------------------------------------------------------
    def prepare(
        self,
        *,
        request_key: str,
        job_id: str | None,
        agent: str,
        attempt: int,
        provider: str,
        model: str,
    ) -> None:
        """Record the intent to call, before any transport work happens."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO provider_requests(request_key, attempt, job_id, agent,"
                " status, provider, model, request_id, prepared_at, sent_at, settled_at,"
                " usage_json, result_json, error)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request_key,
                    attempt,
                    job_id,
                    agent,
                    PREPARED,
                    provider,
                    model,
                    None,
                    _utc_now(),
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )

    def mark_sent(self, *, request_key: str, attempt: int, provider: str, model: str) -> None:
        """Record that the request left this process. This is the point of no easy return."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE provider_requests SET status = ?, sent_at = ?, provider = ?, model = ?"
                " WHERE request_key = ? AND attempt = ?",
                (SENT, _utc_now(), provider, model, request_key, attempt),
            )

    def mark_refused(self, *, request_key: str, attempt: int, error: str) -> None:
        """A refusal that never reached the provider (budget, capability, netguard)."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE provider_requests SET status = ?, settled_at = ?, error = ?"
                " WHERE request_key = ? AND attempt = ?",
                (REFUSED, _utc_now(), error, request_key, attempt),
            )

    def mark_completed(
        self,
        *,
        request_key: str,
        attempt: int,
        usage: dict[str, Any],
        result: dict[str, Any],
        request_id: str | None = None,
    ) -> None:
        """The durable response. Once this lands, the call is never made again."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE provider_requests SET status = ?, settled_at = ?, usage_json = ?,"
                " result_json = ?, request_id = ? WHERE request_key = ? AND attempt = ?",
                (
                    COMPLETED,
                    _utc_now(),
                    json.dumps(usage, ensure_ascii=False, sort_keys=True),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    request_id,
                    request_key,
                    attempt,
                ),
            )

    def mark_uncertain(self, *, request_key: str, attempt: int, error: str) -> None:
        """The call may have been accepted; nobody knows. Only an operator may move on."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE provider_requests SET status = ?, settled_at = ?, error = ?"
                " WHERE request_key = ? AND attempt = ?",
                (UNCERTAIN, _utc_now(), error, request_key, attempt),
            )

    # -- reservations ------------------------------------------------------------------------
    def reserve(
        self,
        *,
        request_key: str,
        attempt: int,
        job_id: str | None,
        agent: str,
        tokens: int,
        cost_usd: float,
    ) -> None:
        """Hold the worst-case spend for one attempt before the call is made.

        The reservation is deliberately conservative — bytes/3 for prompt tokens, image bytes,
        1024 tokens of protocol allowance, and the effective completion limit — because an
        underestimate is how a budget gets overspent by the time anyone notices. It is an estimate,
        not tokenizer arithmetic.
        """
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO budget_reservations(request_key, attempt, job_id, agent,"
                " tokens, cost_usd, status, created_at, settled_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    request_key,
                    attempt,
                    job_id,
                    agent,
                    tokens,
                    cost_usd,
                    "held",
                    _utc_now(),
                    None,
                ),
            )

    def settle(self, *, request_key: str, attempt: int, tokens: int, cost_usd: float) -> None:
        """Replace the reservation with the observed spend."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE budget_reservations SET tokens = ?, cost_usd = ?, status = ?,"
                " settled_at = ? WHERE request_key = ? AND attempt = ?",
                (tokens, cost_usd, "settled", _utc_now(), request_key, attempt),
            )

    def release(self, *, request_key: str, attempt: int) -> None:
        """Give back a reservation for a call that was never sent (refused, or abandoned)."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE budget_reservations SET status = ?, settled_at = ?"
                " WHERE request_key = ? AND attempt = ?",
                ("released", _utc_now(), request_key, attempt),
            )

    def retained(self, *, request_key: str, attempt: int) -> None:
        """Keep the reservation for an uncertain call: the money may already be spent."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE budget_reservations SET status = ?, settled_at = ?"
                " WHERE request_key = ? AND attempt = ?",
                ("retained", _utc_now(), request_key, attempt),
            )

    def outstanding(self, job_id: str | None = None) -> dict[str, float]:
        """Spend that is held or retained — the number the budget must be checked against.

        Counting only recorded usage would let two in-flight calls each believe it has the whole
        remaining allowance. Counting released reservations would let a refused call keep
        blocking spend forever.
        """
        query = (
            "SELECT COALESCE(SUM(tokens),0) AS tokens, COALESCE(SUM(cost_usd),0) AS cost"
            " FROM budget_reservations WHERE status IN ('held','retained')"
        )
        params: list[Any] = []
        if job_id is not None:
            query += " AND job_id = ?"
            params.append(job_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return {"tokens": float(row["tokens"]), "cost_usd": float(row["cost"])}

    def reconcile(self) -> int:
        """At startup: an attempt stuck in ``prepared`` was never sent, so release it.

        Returns the number released. ``sent`` rows are left alone — their outcome is genuinely
        unknown and must be acknowledged, not tidied away.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE budget_reservations SET status = 'released', settled_at = ?"
                " WHERE status = 'held' AND (request_key, attempt) IN"
                " (SELECT request_key, attempt FROM provider_requests WHERE status = ?)",
                (_utc_now(), PREPARED),
            )
            sent = conn.execute(
                "UPDATE provider_requests SET status = ?, settled_at = ?,"
                " error = 'outcome unknown after restart'"
                " WHERE status = ? AND sent_at IS NOT NULL AND settled_at IS NULL",
                (UNCERTAIN, _utc_now(), SENT),
            )
            return int(cursor.rowcount) + int(sent.rowcount)

    # -- queries ------------------------------------------------------------------------------
    def completed(self, request_key: str) -> dict[str, Any] | None:
        """The recorded result for this logical request, if any attempt completed it."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM provider_requests WHERE request_key = ? AND status = ?"
                " ORDER BY attempt DESC LIMIT 1",
                (request_key, COMPLETED),
            ).fetchone()
        if row is None:
            return None
        return {
            "attempt": int(row["attempt"]),
            "provider": row["provider"],
            "model": row["model"],
            "usage": json.loads(row["usage_json"] or "{}"),
            "result": json.loads(row["result_json"] or "{}"),
            "request_id": row["request_id"],
        }

    def has_unresolved(self, request_key: str) -> bool:
        """Whether an attempt may already have reached the provider."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM provider_requests WHERE request_key = ?"
                " AND status IN (?, ?) LIMIT 1",
                (request_key, SENT, UNCERTAIN),
            ).fetchone()
        return row is not None

    def uncertain(self, job_id: str) -> list[dict[str, Any]]:
        """Attempts whose outcome is unknown, for the operator's acknowledgement queue."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT request_key, attempt, agent, status, provider, model, sent_at, error"
                " FROM provider_requests WHERE job_id = ? AND status = ? ORDER BY sent_at",
                (job_id, UNCERTAIN),
            ).fetchall()
        return [dict(row) for row in rows]

    def next_attempt(self, request_key: str) -> int:
        """The attempt number for a fresh call: one past the highest recorded for this key."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(attempt) AS highest FROM provider_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
        return int(row["highest"] or 0) + 1

    def acknowledge(self, *, request_key: str, attempt: int, operator: str) -> None:
        """Authorize one retry, preserving the uncertain attempt as evidence."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT status FROM provider_requests WHERE request_key = ? AND attempt = ?",
                    (request_key, attempt),
                ).fetchone()
                if row is None or row["status"] != UNCERTAIN:
                    raise ValueError("request is not uncertain")
                conn.execute(
                    "INSERT INTO provider_retry_authorizations"
                    "(request_key, attempt, operator, authorized_at) VALUES (?, ?, ?, ?)",
                    (request_key, attempt, operator, _utc_now()),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def claim_attempt(
        self, *, request_key: str, job_id: str | None, agent: str, provider: str, model: str
    ) -> int:
        """Atomically claim a request, consuming authorization for an uncertain attempt."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT attempt, status FROM provider_requests WHERE request_key = ?"
                    " ORDER BY attempt DESC LIMIT 1", (request_key,),
                ).fetchone()
                attempt = 1 if row is None else int(row["attempt"]) + 1
                if row is not None:
                    if row["status"] == UNCERTAIN:
                        cursor = conn.execute(
                            "UPDATE provider_retry_authorizations SET consumed_at = ?"
                            " WHERE request_key = ? AND attempt = ? AND consumed_at IS NULL",
                            (_utc_now(), request_key, row["attempt"]),
                        )
                        if cursor.rowcount != 1:
                            raise ValueError("uncertain request requires explicit authorization")
                    elif row["status"] != REFUSED:
                        raise ValueError("request already active or completed")
                conn.execute(
                    "INSERT INTO provider_requests"
                    "(request_key, attempt, job_id, agent, status, provider, model, prepared_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (request_key, attempt, job_id, agent, PREPARED, provider, model, _utc_now()),
                )
                conn.commit()
                return attempt
            except BaseException:
                conn.rollback()
                raise

    def statuses(self, job_id: str) -> list[dict[str, Any]]:
        """Safe per-request summaries for the job detail view. No payload content."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT request_key, attempt, agent, status, provider, model, prepared_at,"
                " sent_at, settled_at, error FROM provider_requests WHERE job_id = ?"
                " ORDER BY prepared_at, attempt",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]
