"""Usage accounting and pre-call budget enforcement.

Cost is an estimate and is labelled as one. The budget check is pre-call and uses a worst-case
completion size, because a budget that is enforced after the money is spent is not a budget.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import Health, Provider, ProviderError, ProviderResult, ResolvedCall, Usage, VisionImage
from .journal import RequestJournal


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
        self.configured_rates: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._init()

    def set_configured_rates(self, rates: dict[str, tuple[float, float]]) -> None:
        """Record which providers currently have both rates configured (a zero rate counts).

        The registry is in-memory, so the log cannot answer this itself. Passing the fact in keeps
        ``price_configured`` about today's configuration rather than about historical rows.
        """
        with self._lock:
            self.configured_rates = dict(rates)

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
                    created_at TEXT NOT NULL,
                    price_in_per_mtok REAL,
                    price_out_per_mtok REAL,
                    pricing_status TEXT NOT NULL DEFAULT 'priced'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_log(day)")
            # Historical rows predate the price snapshot: they are "legacy_unknown", never
            # re-priced from today's rates and never inferred "free" from a zero cost.
            for statement in (
                "ALTER TABLE usage_log ADD COLUMN price_in_per_mtok REAL",
                "ALTER TABLE usage_log ADD COLUMN price_out_per_mtok REAL",
                "ALTER TABLE usage_log ADD COLUMN pricing_status TEXT NOT NULL DEFAULT 'priced'",
            ):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(statement)
            conn.execute(
                "UPDATE usage_log SET pricing_status = 'legacy_unknown'"
                " WHERE pricing_status = 'priced' AND price_in_per_mtok IS NULL"
                " AND price_out_per_mtok IS NULL"
            )

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
        price_in_per_mtok: float | None = None,
        price_out_per_mtok: float | None = None,
    ) -> None:
        """Record one call with the price snapshot that produced its cost.

        The snapshot is the point: a cost computed from today's rates cannot be compared against a
        cost computed after the operator changed the price, and a zero with no rates is not a zero
        cost. ``pricing_status`` says which of the three cases this row is, so a summary can report
        what it does not know instead of presenting an incomplete total as a complete one.
        """
        now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
        if price_in_per_mtok is None and price_out_per_mtok is None:
            status = "unpriced"
        elif price_in_per_mtok is None or price_out_per_mtok is None:
            status = "partial"
        else:
            status = "priced"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO usage_log(job_id, agent, provider, model, prompt_tokens,"
                " completion_tokens, est_cost_usd, elapsed_ms, day, created_at,"
                " price_in_per_mtok, price_out_per_mtok, pricing_status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    price_in_per_mtok,
                    price_out_per_mtok,
                    status,
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
        # One predicate for "this total knows what it cost": a fully-priced row is one whose
        # snapshot carried both rates. Anything else — partial, unpriced, or a legacy row from
        # before snapshots existed — is explicitly incomplete, and the counts below say so rather
        # than letting a smaller total look like a smaller spend.
        priced_calls = "COUNT(*) FILTER (WHERE pricing_status = 'priced')"
        unknown_calls = "COUNT(*) FILTER (WHERE pricing_status <> 'priced')"
        with self._connect() as conn:
            days = conn.execute(
                f"SELECT day,"
                f" SUM(prompt_tokens + completion_tokens) AS tokens,"
                f" COUNT(*) AS calls,"
                f" SUM(est_cost_usd) AS cost,"
                f" {priced_calls} AS priced_calls,"
                f" {unknown_calls} AS unknown_price_calls"
                " FROM usage_log GROUP BY day ORDER BY day"
            ).fetchall()
            by_agent = conn.execute(
                "SELECT day, agent,"
                " SUM(prompt_tokens + completion_tokens) AS tokens,"
                " COUNT(*) AS calls,"
                " SUM(est_cost_usd) AS cost,"
                " COUNT(*) FILTER (WHERE pricing_status = 'priced') AS priced_calls,"
                " COUNT(*) FILTER (WHERE pricing_status <> 'priced') AS unknown_price_calls"
                " FROM usage_log GROUP BY day, agent ORDER BY day, agent"
            ).fetchall()
            by_model = conn.execute(
                "SELECT day, provider, model,"
                " SUM(prompt_tokens + completion_tokens) AS tokens,"
                " COUNT(*) AS calls,"
                " SUM(est_cost_usd) AS cost,"
                " COUNT(*) FILTER (WHERE pricing_status = 'priced') AS priced_calls,"
                " COUNT(*) FILTER (WHERE pricing_status <> 'priced') AS unknown_price_calls"
                " FROM usage_log GROUP BY day, provider, model ORDER BY day, provider, model"
            ).fetchall()
            # ``price_configured`` describes the *rates the operator configured now*, not whether
            # any row happens to have a nonzero cost: a zero rate is a real price, and a nonzero
            # cost from a rate that has since been removed is not a configured price today. The
            # configured rates are a registry fact, so the caller passes them in; this module only
            # reads its own log.
            configured = self.configured_rates

        def row(item: sqlite3.Row) -> dict[str, Any]:
            return {
                **{key: item[key] for key in item.keys()},
                "tokens": int(item["tokens"] or 0),
                "calls": int(item["calls"] or 0),
                "cost_usd": float(item["cost"] or 0.0),
                # "is this total complete?" belongs next to the total itself: a group whose cost
                # covers every call in it is fully priced; anything else is a partial number.
                "fully_priced": int(item["priced_calls"] or 0) == int(item["calls"] or 0),
                "unknown_price_calls": int(item["unknown_price_calls"] or 0),
            }

        return {
            "days": [row(item) for item in days],
            "by_agent": [row(item) for item in by_agent],
            "by_model": [row(item) for item in by_model],
            "price_configured": bool(configured),
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
        journal: RequestJournal | None = None,
        request_identity: dict[str, Any] | None = None,
    ) -> None:
        self.inner = inner
        self.tracker = tracker
        self.agent = agent
        self.job_id = job_id
        self.price_in = price_in
        self.price_out = price_out
        self.worst_case_tokens = worst_case_tokens
        # The journal is what makes a crash between "sent" and "recorded" recoverable. Without it
        # the call either gets retried (double spend) or dropped (lost work); with it, the restart
        # blocks until the operator acknowledges the uncertainty.
        self.journal = journal
        self.request_identity = request_identity or {}
        self.transport = inner.transport
        self.name = inner.name

    # -- journal boundary --------------------------------------------------------------------
    def _identity(self, *, user: str, system: str, task: str) -> tuple[str, int]:
        """The journal key for this call, and the attempt number to use.

        Semantic inputs only: the prompt text, the task, and the effective call configuration.
        A timeout or a price change does not change the identity, so a recorded result stays
        replayable across an operator's settings edit.
        """
        from .journal import hash_inputs, request_key

        identity = self.request_identity
        inputs = hash_inputs(
            {
                "system": system,
                "user": user,
                "task": task,
                "model": identity.get("model"),
                "temperature": identity.get("temperature"),
                "max_tokens": identity.get("max_tokens"),
                "provider": identity.get("provider"),
                "transport": identity.get("transport"),
            }
        )
        key = request_key(
            job_id=self.job_id,
            agent=self.agent,
            ordinal=int(identity.get("ordinal", 0)),
            inputs_sha256=inputs,
            prompt_sha256=identity.get("prompt_sha256", ""),
            call_config_sha256=identity.get("call_config_sha256", ""),
        )
        attempt = self.journal.next_attempt(key) if self.journal is not None else 1
        return key, attempt

    def _recorded_result(self, key: str) -> Any | None:
        """A previously completed response for this exact request, if the journal has one."""
        if self.journal is None:
            return None
        return self.journal.completed(key)

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
            price_in_per_mtok=self.price_in,
            price_out_per_mtok=self.price_out,
        )
        return result

    def complete(
        self, call: ResolvedCall, *, system: str, user: str, task: str
    ) -> ProviderResult:
        key, attempt = self._identity(user=user, system=system, task=task)
        recorded = self._recorded_result(key)
        if recorded is not None:
            # A completed response replays locally: zero new transport calls, and the usage is
            # already in the log from the attempt that produced it.
            from .base import ProviderResult

            return ProviderResult(
                content=str(recorded["result"].get("text", "")),
                usage=Usage(
                    prompt_tokens=int(recorded["usage"].get("prompt_tokens", 0)),
                    completion_tokens=int(recorded["usage"].get("completion_tokens", 0)),
                ),
                provider=recorded["provider"],
                model=recorded["model"],
                elapsed_ms=0,
            )
        # Pre-call budget check: a budget enforced after the money is spent is not a budget.
        worst_cost = estimate_cost(
            Usage(prompt_tokens=len(user) // 3, completion_tokens=self.worst_case_tokens),
            price_in=self.price_in,
            price_out=self.price_out,
        )
        self.tracker.assert_can_spend(
            worst_case_tokens=self.worst_case_tokens, worst_case_cost_usd=worst_cost
        )
        if self.journal is not None:
            try:
                attempt = self.journal.claim_attempt(
                    request_key=key, job_id=self.job_id, agent=self.agent,
                    provider=call.provider, model=call.model,
                )
            except ValueError as exc:
                raise ProviderError(
                    "provider_outcome_unknown", str(exc), provider=call.provider
                ) from exc
            self.journal.reserve(
                request_key=key, attempt=attempt, job_id=self.job_id, agent=self.agent,
                tokens=len(user) // 3 + self.worst_case_tokens, cost_usd=worst_cost,
            )
            self.journal.mark_sent(
                request_key=key, attempt=attempt, provider=call.provider, model=call.model
            )
        try:
            result = self.inner.complete(call, system=system, user=user, task=task)
        except Exception as exc:  # noqa: BLE001 - the journal must survive the transport's errors
            if self.journal is not None:
                # The call left this process. Nobody knows whether the provider accepted it, so
                # the attempt is uncertain and the reservation stays held: retrying here is the
                # duplicate-spend bug this whole mechanism exists to prevent.
                self.journal.mark_uncertain(request_key=key, attempt=attempt, error=f"{type(exc).__name__}: {exc}")
                self.journal.retained(request_key=key, attempt=attempt)
            raise
        cost = estimate_cost(result.usage, price_in=self.price_in, price_out=self.price_out)
        self.tracker.record(
            job_id=self.job_id,
            agent=self.agent,
            provider=result.provider,
            model=result.model,
            usage=result.usage,
            est_cost_usd=cost,
            elapsed_ms=result.elapsed_ms,
            price_in_per_mtok=self.price_in,
            price_out_per_mtok=self.price_out,
        )
        if self.journal is not None:
            self.journal.mark_completed(
                request_key=key, attempt=attempt,
                usage={"prompt_tokens": result.usage.prompt_tokens,
                       "completion_tokens": result.usage.completion_tokens},
                result={"text": result.content},
            )
            self.journal.settle(
                request_key=key, attempt=attempt,
                tokens=result.usage.prompt_tokens + result.usage.completion_tokens,
                cost_usd=cost,
            )
        return result
