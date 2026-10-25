"""Usage accounting and pre-call budget enforcement.

Cost is an estimate and is labelled as one. The budget check is pre-call and uses a worst-case
completion size, because a budget that is enforced after the money is spent is not a budget.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from .base import Health, Provider, ProviderResult, ResolvedCall, Usage


def _utc_day() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Budget:
    max_daily_tokens: int | None = None
    max_daily_cost_usd: float | None = None
    unlimited: bool = False

    @property
    def enforced(self) -> bool:
        return not self.unlimited and (
            self.max_daily_tokens is not None or self.max_daily_cost_usd is not None
        )


class BudgetExceeded(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"budget exceeded: {reason}")


class UsageTracker:
    """Records every call and answers "may I spend more today?"."""

    def __init__(self, db_path: Path, budget: Budget | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.budget = budget or Budget()
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    agent TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    est_cost_usd REAL NOT NULL DEFAULT 0,
                    elapsed_ms INTEGER NOT NULL DEFAULT 0,
                    day TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_log(day)")

    def record(
        self,
        *,
        job_id: str | None,
        agent: str,
        provider: str,
        model: str,
        usage: Usage,
        est_cost_usd: float,
        elapsed_ms: int,
    ) -> None:
        now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO usage_log(job_id, agent, provider, model, prompt_tokens,"
                " completion_tokens, est_cost_usd, elapsed_ms, day, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    agent,
                    provider,
                    model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    est_cost_usd,
                    elapsed_ms,
                    _utc_day(),
                    now,
                ),
            )

    def today(self) -> dict[str, float]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(prompt_tokens + completion_tokens),0) AS tokens,"
                " COALESCE(SUM(est_cost_usd),0) AS cost, COUNT(*) AS calls"
                " FROM usage_log WHERE day = ?",
                (_utc_day(),),
            ).fetchone()
        return {"tokens": float(row["tokens"]), "cost_usd": float(row["cost"]), "calls": float(row["calls"])}

    def for_job(self, job_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT agent, provider, model, prompt_tokens, completion_tokens, est_cost_usd,"
                " elapsed_ms, created_at FROM usage_log WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def assert_can_spend(self, *, worst_case_tokens: int, worst_case_cost_usd: float) -> None:
        if not self.budget.enforced:
            return
        spent = self.today()
        if self.budget.max_daily_tokens is not None:
            if spent["tokens"] + worst_case_tokens > self.budget.max_daily_tokens:
                raise BudgetExceeded(
                    f"daily tokens {int(spent['tokens'])} + worst case {worst_case_tokens}"
                    f" > cap {self.budget.max_daily_tokens}"
                )
        if self.budget.max_daily_cost_usd is not None:
            if spent["cost_usd"] + worst_case_cost_usd > self.budget.max_daily_cost_usd:
                raise BudgetExceeded(
                    f"daily cost ${spent['cost_usd']:.4f} + worst case ${worst_case_cost_usd:.4f}"
                    f" > cap ${self.budget.max_daily_cost_usd:.2f}"
                )


def estimate_cost(
    usage: Usage, *, price_in: float | None, price_out: float | None
) -> float:
    """Rough USD. Returns 0.0 when no price is configured rather than inventing one."""
    if price_in is None and price_out is None:
        return 0.0
    return (
        usage.prompt_tokens / 1_000_000 * (price_in or 0.0)
        + usage.completion_tokens / 1_000_000 * (price_out or 0.0)
    )


class RecordingProvider:
    """Wraps a transport so every completion is recorded, without the agent knowing.

    The point is that usage attribution cannot be forgotten: an agent that calls ``complete`` is
    recorded because the recording happens at the boundary, not in the agent. That is what makes
    "which provider and model actually served this agent" answerable from the database rather than
    from a config file.
    """

    def __init__(
        self,
        inner: Provider,
        *,
        tracker: UsageTracker,
        agent: str,
        job_id: str | None,
        price_in: float | None = None,
        price_out: float | None = None,
        worst_case_tokens: int = 8000,
    ) -> None:
        self.inner = inner
        self.tracker = tracker
        self.agent = agent
        self.job_id = job_id
        self.price_in = price_in
        self.price_out = price_out
        self.worst_case_tokens = worst_case_tokens
        self.transport = inner.transport
        self.name = inner.name

    def health(self, call: ResolvedCall) -> Health:
        return self.inner.health(call)

    def list_models(self, call: ResolvedCall) -> list[str] | None:
        return self.inner.list_models(call)

    def complete(
        self, call: ResolvedCall, *, system: str, user: str, task: str
    ) -> ProviderResult:
        # Pre-call budget check: a budget enforced after the money is spent is not a budget.
        worst_cost = estimate_cost(
            Usage(prompt_tokens=len(user) // 3, completion_tokens=self.worst_case_tokens),
            price_in=self.price_in,
            price_out=self.price_out,
        )
        self.tracker.assert_can_spend(
            worst_case_tokens=self.worst_case_tokens, worst_case_cost_usd=worst_cost
        )
        result = self.inner.complete(call, system=system, user=user, task=task)
        cost = estimate_cost(result.usage, price_in=self.price_in, price_out=self.price_out)
        self.tracker.record(
            job_id=self.job_id,
            agent=self.agent,
            provider=result.provider,
            model=result.model,
            usage=result.usage,
            est_cost_usd=cost,
            elapsed_ms=result.elapsed_ms,
        )
        return result
