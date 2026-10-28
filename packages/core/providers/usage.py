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
from typing import Any

from .base import Health, Provider, ProviderResult, ResolvedCall, Usage, VisionImage


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

    def set_limits(
        self,
        *,
        max_daily_tokens: int | None,
        max_daily_cost_usd: float | None,
        unlimited: bool,
    ) -> Budget:
        """Swap the budget object for a new one, atomically.

        ``Budget`` is frozen, so "changing a limit" means replacing the object every call site
        reads. Doing it under the same lock the recorder takes means a call in flight sees either
        the old limit or the new one — never a half-written pair — and a saved setting takes effect
        without a restart, which is the difference between a limit and a suggestion.
        """
        with self._lock:
            self.budget = Budget(
                max_daily_tokens=max_daily_tokens,
                max_daily_cost_usd=max_daily_cost_usd,
                unlimited=unlimited,
            )
            return self.budget

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

    def for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT agent, provider, model, prompt_tokens, completion_tokens, est_cost_usd,"
                " elapsed_ms, created_at FROM usage_log WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        """Per-day, per-agent and per-model totals over the whole log.

        ``cost_usd`` is only meaningful when the operator configured prices. ``estimate_cost``
        returns 0.0 when both prices are ``None`` (usage.py:146-157), so a log filled by
        unpriced providers reports 0.0 for every call. The ``price_configured`` flag says which
        case this is, so a dashboard cannot present an unpriced zero as "free".
        """
        with self._connect() as conn:
            days = conn.execute(
                "SELECT day,"
                " SUM(prompt_tokens + completion_tokens) AS tokens,"
                " COUNT(*) AS calls,"
                " SUM(est_cost_usd) AS cost"
                " FROM usage_log GROUP BY day ORDER BY day"
            ).fetchall()
            by_agent = conn.execute(
                "SELECT day, agent,"
                " SUM(prompt_tokens + completion_tokens) AS tokens,"
                " COUNT(*) AS calls,"
                " SUM(est_cost_usd) AS cost"
                " FROM usage_log GROUP BY day, agent ORDER BY day, agent"
            ).fetchall()
            by_model = conn.execute(
                "SELECT day, provider, model,"
                " SUM(prompt_tokens + completion_tokens) AS tokens,"
                " COUNT(*) AS calls,"
                " SUM(est_cost_usd) AS cost"
                " FROM usage_log GROUP BY day, provider, model ORDER BY day, provider, model"
            ).fetchall()
            priced = conn.execute(
                "SELECT COUNT(*) AS n FROM usage_log WHERE est_cost_usd > 0"
            ).fetchone()

        def row(item: sqlite3.Row) -> dict[str, Any]:
            return {
                **{key: item[key] for key in item.keys()},
                "tokens": int(item["tokens"] or 0),
                "calls": int(item["calls"] or 0),
                "cost_usd": float(item["cost"] or 0.0),
            }

        return {
            "days": [row(item) for item in days],
            "by_agent": [row(item) for item in by_agent],
            "by_model": [row(item) for item in by_model],
            "price_configured": bool(priced["n"]) if priced else False,
        }

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

    def complete_vision(
        self,
        call: ResolvedCall,
        *,
        system: str,
        user: str,
        task: str,
        images: list[VisionImage],
    ) -> ProviderResult:
        """Recorded exactly like a text call, with the image payload counted as prompt tokens.

        A vision call is the one place a per-call cost can jump by an order of magnitude, so it
        must not be the one call that escapes the usage log.
        """
        worst_cost = estimate_cost(
            Usage(
                prompt_tokens=(len(user) + sum(image.byte_size for image in images)) // 3,
                completion_tokens=self.worst_case_tokens,
            ),
            price_in=self.price_in,
            price_out=self.price_out,
        )
        self.tracker.assert_can_spend(
            worst_case_tokens=len(user) // 3 + self.worst_case_tokens,
            worst_case_cost_usd=worst_cost,
        )
        result = self.inner.complete_vision(
            call, system=system, user=user, task=task, images=images
        )
        # ``record`` takes a computed cost, not the price table: the estimate has to be made here,
        # exactly as ``complete`` does. Passing the prices through was a real defect — every vision
        # call raised TypeError *after* a successful round-trip, so the tokens were spent and
        # unrecorded.
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
