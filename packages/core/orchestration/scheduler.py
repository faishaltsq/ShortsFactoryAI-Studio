"""The scheduler: which job, if any, the system may pick up on its own.

Two properties, and the second is the one that matters:

1. **Off by default.** ``DEFAULT_ENABLED`` is false. Enabling it is an operator action, not a
   default, because a scheduler that starts work nobody asked for is the opposite of the product's
   premise.

2. **It cannot select a job at or past the approval gate.** The schedulable set is disjoint from
   ``READY_FOR_APPROVAL`` and everything after it, and ``claim_next`` filters on that set in SQL
   rather than trusting a caller to remember. A job waiting for the operator is waiting for the
   operator; a job that has been approved is waiting for a *human* decision about publishing.

``PAUSED`` is deliberately not schedulable: a paused job is paused on purpose, and resuming it
automatically would make the pause meaningless.

``claim_next`` answers "which job" and nothing else, so the selection rule is testable without a
thread, a clock, or a sleep. :class:`SchedulerLoop` is the smallest honest loop around it: one tick
at a time, off by default, no cron, no dependency, and a re-check of the job's state between the
claim and the hand-off because that state can change in the window between them.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..contracts.state import JobState
from .jobstore import JobRecord, JobStore, _utc_now

#: Off unless an operator turns it on. A scheduler that runs by default would start spending
#: money on the first launch after a reboot.
DEFAULT_ENABLED = False

#: The operator's switch and cadence. ``SHORTS_SCHEDULER_ENABLED`` accepts 0/1/true/false/yes/no;
#: anything else is a configuration error, not a silent "off".
ENABLED_ENV = "SHORTS_SCHEDULER_ENABLED"
INTERVAL_ENV = "SHORTS_SCHEDULER_INTERVAL_S"
DEFAULT_INTERVAL_S = 60.0
#: Below this a loop is a busy-wait wearing a scheduler's clothes.
MIN_INTERVAL_S = 1.0

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})

#: States the scheduler may pick up: pre-gate work that is incomplete. Everything at or past
#: ``READY_FOR_APPROVAL`` is excluded, and a test asserts that against the allow-list rather than
#: against this comment.
SCHEDULABLE_STATES: tuple[JobState, ...] = (
    JobState.IDEA_DISCOVERY,
    JobState.TOPIC_SELECTED,
    JobState.RESEARCH_COMPLETE,
    JobState.SCRIPT_GENERATED,
    JobState.CREATIVE_REVIEW,
    JobState.STORYBOARD_READY,
    JobState.ASSETS_READY,
    JobState.AUDIO_READY,
    JobState.MOTION_READY,
    JobState.RENDERING,
    JobState.TECHNICAL_QC,
    JobState.EDITORIAL_QC,
)


def is_schedulable(state: JobState) -> bool:
    return state in SCHEDULABLE_STATES


@dataclass(frozen=True)
class SchedulerConfig:
    """Operator configuration. Invalid input raises; it is never coerced to a default.

    A silently-ignored bad interval is a scheduler running at a cadence nobody chose, which is
    worse than refusing to start.
    """

    enabled: bool = DEFAULT_ENABLED
    interval_s: float = DEFAULT_INTERVAL_S

    def __post_init__(self) -> None:
        if not isinstance(self.interval_s, (int, float)) or isinstance(self.interval_s, bool):
            raise ValueError(f"{INTERVAL_ENV} must be a number of seconds, got {self.interval_s!r}")
        if not self.interval_s > 0:
            raise ValueError(f"{INTERVAL_ENV} must be positive, got {self.interval_s:g}")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SchedulerConfig:
        env = os.environ if environ is None else environ
        raw_enabled = str(env.get(ENABLED_ENV, "")).strip().lower()
        if raw_enabled in _TRUE:
            enabled = True
        elif raw_enabled in _FALSE:
            enabled = False
        else:
            raise ValueError(
                f"{ENABLED_ENV} must be one of {sorted(_TRUE | _FALSE)} or unset, "
                f"got {raw_enabled!r}"
            )

        raw_interval = str(env.get(INTERVAL_ENV, "")).strip()
        if not raw_interval:
            return cls(enabled=enabled, interval_s=DEFAULT_INTERVAL_S)
        try:
            interval = float(raw_interval)
        except ValueError as exc:
            raise ValueError(
                f"{INTERVAL_ENV} must be a number of seconds, got {raw_interval!r}"
            ) from exc
        # The minimum applies to what an operator may configure. It is not a property of the
        # dataclass, because a test needs a fast loop and a test is not an operator.
        if interval < MIN_INTERVAL_S:
            raise ValueError(
                f"{INTERVAL_ENV} must be at least {MIN_INTERVAL_S:g}s, got {interval:g}"
            )
        return cls(enabled=enabled, interval_s=interval)


def claim_next(store: JobStore, *, exclude: set[str] | None = None) -> JobRecord | None:
    """The job the scheduler may pick up next, or ``None``.

    Selection rule: schedulable states, ``scheduled_for`` not in the future (a calendar entry
    waits — production scheduling never pulls work early), then lowest ``priority`` number,
    then oldest ``created_at``. ``exclude`` lets a caller skip jobs it already holds, so two
    callers cannot be handed the same row by this function alone. Real mutual exclusion is the
    lease (``leases.py``); this is only the selection rule.
    """
    excluded = exclude or set()
    now = _utc_now()
    candidates = [
        job
        for job in store.list(states=list(SCHEDULABLE_STATES), limit=500)
        if job.id not in excluded and (job.scheduled_for is None or job.scheduled_for <= now)
    ]
    # ``store.list`` is newest-first; invert, then sort by (priority, created_at) oldest-first.
    candidates.reverse()
    candidates.sort(key=lambda job: (job.priority, job.created_at))
    return candidates[0] if candidates else None


class SchedulerLoop:
    """One tick at a time, off by default, stoppable.

    ``on_claim`` is the hand-off — in the app it is ``JobService.start``. Injecting it keeps this
    class free of ``apps/`` imports and lets a test observe exactly what was started without
    spawning a worker.

    The loop is deliberately not clever: it claims at most one job per tick, sleeps, and repeats.
    There is no cron and no retry logic — retries belong to the runner, which
    already has a bounded cap.
    """

    def __init__(
        self,
        store: JobStore,
        on_claim: Callable[[str], object],
        *,
        config: SchedulerConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.on_claim = on_claim
        self.config = config or SchedulerConfig()
        self._clock = clock
        self._sleep = sleep
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        #: Jobs this loop already handed off, so one tick cannot re-claim the same row.
        self._handed: set[str] = set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def tick(self) -> str | None:
        """Claim and hand off at most one job. Returns the job id, or ``None``.

        The state is re-read after the claim because it can change in the window between
        ``claim_next`` and the hand-off: a worker may finish a stage, or an operator may approve the
        job. Handing an approval-waiting job to the runner would start work the operator is in the
        middle of deciding about, so the re-check is a refusal, not a warning.
        """
        if not self.config.enabled:
            return None
        claimed = claim_next(self.store, exclude=self._handed)
        if claimed is None:
            return None

        current = self.store.get(claimed.id)
        if not is_schedulable(current.state):
            # Re-checked at claim time, not merely at selection time. Not added to ``_handed``: a
            # job that came back to a schedulable state later should be eligible again.
            return None

        self._handed.add(claimed.id)
        self.on_claim(claimed.id)
        return claimed.id

    def start(self) -> bool:
        """Start the loop. Returns ``False`` when it is already running.

        A second ``start`` must not create a second thread: two loops over one store would race the
        same rows, and the lease would turn that race into a stream of "lease unavailable" events.
        """
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="job-scheduler", daemon=True
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        """Stop the loop. Idempotent, and safe to call when never started."""
        with self._lock:
            thread = self._thread
            self._stop.set()
            self._thread = None
        if thread is not None:
            thread.join(timeout=max(5.0, self.config.interval_s * 2))

    def _run(self) -> None:
        # Tick first, then sleep: a loop that sleeps before its first claim makes an operator wait
        # a full interval to see whether enabling it did anything.
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - one bad tick must not kill the loop
                pass
            self._stop.wait(self.config.interval_s)
