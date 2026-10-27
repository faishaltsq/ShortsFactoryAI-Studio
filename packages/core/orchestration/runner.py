"""Stage execution: idempotent, cancellable, lease-guarded, honest about success.

A stage is a function that writes artifacts and returns an outcome. The runner does four things a
naive loop does not:

1. **Skips work that is already done**, and says so with ``artifact_reused`` rather than a fake
   ``working`` phase at 100 %.
2. **Writes the completion marker last**, so a crash between data and marker resumes rather than
   treating a partial stage as complete.
3. **Checks lease ownership before and after every stage**, renewing it first, and never writes a
   state transition it does not own. Renewal is what keeps a legitimate long stage (a 70 s render
   against a 120 s TTL, a 900 s render timeout) from aging its own lease out and being projected
   as a dead worker.
4. **Refuses to report success without a validated artifact.** The stage declares what it must
   produce; the runner verifies the file exists and parses before accepting ``ok``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..contracts.base import Artifact, ArtifactValidationError, validate_artifact
from ..contracts.state import JobState, is_transition_allowed
from .jobstore import JobStore
from .leases import LeaseKeeper, LeaseLost


class CancelToken(Protocol):
    def is_cancelled(self) -> bool: ...


class NullCancel:
    def is_cancelled(self) -> bool:
        return False


@dataclass
class StageOutcome:
    """What a stage did. ``ok`` is the stage's claim; the runner verifies it separately."""

    ok: bool
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)
    reused: bool = False
    error_code: str = ""
    retryable: bool = False


class StageChainError(ValueError):
    """The stage list cannot run from the job's current state.

    Raised before any stage executes. A pipeline that jumps states is a programming error, and
    discovering it halfway through a paid run is the expensive way to find out.
    """


class StageError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        self.code = code
        self.detail = detail
        self.retryable = retryable
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class Stage:
    """One unit of pipeline work.

    ``produces`` is the contract: the artifact names this stage must leave on disk. ``contract`` is
    the model used to validate the primary artifact. A stage that returns ``ok`` without producing
    its artifacts is a bug in the stage, and the runner treats it as a failure rather than passing
    it on.
    """

    name: str
    state: JobState
    produces: tuple[str, ...]
    run: Callable[[JobStore, str], StageOutcome]
    contract: type[Artifact] | None = None
    contract_artifact: str = ""
    #: Optional predicate ``(artifact, job_id) -> bool`` answering "does this artifact mean the
    #: stage is done?". Defaults to ``None``, which keeps the original rule: a valid artifact is a
    #: finished stage. It exists for stages whose artifact can record a *non-success* — a
    #: publication that is ``uncertain`` validates, but reusing it would claim an upload that may
    #: not have happened. The job id is passed because the predicate may need to recompute
    #: something job-specific (an idempotency key) rather than read a flag.
    done_when: Callable[[dict[str, Any], str], bool] | None = None


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def run_stages(
    *,
    store: JobStore,
    job_id: str,
    stages: list[Stage],
    keeper: LeaseKeeper | None = None,
    cancel: CancelToken | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Execute ``stages`` in order and return a report.

    A stage failure does not silently become a success. A retryable failure increments the attempt
    counter and retries; exhaustion moves the job to ``BLOCKED`` because that needs an operator
    decision, not a louder error.
    """
    cancel = cancel or NullCancel()
    report: dict[str, Any] = {"job_id": job_id, "stages": [], "ok": True, "stopped": None}

    # A resume over a finished job must be a no-op, not an illegal transition. Stages whose
    # artifacts already validate are dropped from chain validation (they will report ``reused``),
    # and only the remaining work has to be reachable from the current state.
    #
    # The starting point is the last reused stage's state, not the stored state: reuse now
    # advances the state, so a crash between "artifact written" and "transition" leaves the job
    # behind its own artifacts. Validating from the stored state would refuse a chain that the
    # loop is about to make legal.
    stored = store.get(job_id).state
    done = [stage for stage in stages if _is_done(store, job_id, stage)]
    pending = [stage for stage in stages if not _is_done(store, job_id, stage)]
    # Only move the starting point forward. A finished job re-run from the top has every stage
    # done and must stay where it is; a crashed job whose last artifact outran its transition
    # must be validated from that artifact's stage.
    start = stored
    if done and is_transition_allowed(stored, done[-1].state):
        start = done[-1].state
    _validate_chain(start, pending)

    for stage in stages:
        if cancel.is_cancelled():
            report["ok"] = False
            report["stopped"] = "cancelled"
            store.transition(job_id, JobState.CANCELLED, detail="cancelled before " + stage.name)
            return report

        if keeper is not None:
            if not keeper.renew():
                report["ok"] = False
                report["stopped"] = "lease_lost"
                report["detail"] = f"lease lost before {stage.name}"
                return report

        # Reuse: every declared artifact exists, the contract validates, and the artifact says the
        # stage actually succeeded (``done_when``).
        if stage.produces and all(store.has_artifact(job_id, name) for name in stage.produces):
            if _validate_produced(store, job_id, stage) is None and _artifact_says_done(
                store, job_id, stage
            ):
                # The artifact was verified, so the stage really is done — the state must say so.
                # Skipping the transition here left a crash between "artifact written" and
                # "state advanced" unresumable: the next stage was no longer reachable.
                #
                # Only ever forward. A finished job re-run from the top has every stage done and
                # already sits past all of them; transitioning to an earlier stage would be a
                # rewind, and the allow-list refuses it — so it must not be attempted.
                current = store.get(job_id).state
                if current != stage.state and is_transition_allowed(current, stage.state):
                    store.transition(job_id, stage.state, detail=f"{stage.name} reused")
                report["stages"].append(
                    {"name": stage.name, "ok": True, "reused": True, "detail": "artifacts present"}
                )
                continue

        attempts = 0
        while True:
            attempts += 1
            try:
                outcome = stage.run(store, job_id)
            except LeaseLost:
                report["ok"] = False
                report["stopped"] = "lease_lost"
                report["detail"] = f"lease lost during {stage.name}"
                return report
            except StageError as exc:
                outcome = StageOutcome(
                    ok=False, detail=exc.detail, error_code=exc.code, retryable=exc.retryable
                )
            except Exception as exc:  # noqa: BLE001 - a stage bug must not look like success
                outcome = StageOutcome(
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}",
                    error_code="stage_exception",
                    retryable=False,
                )

            if outcome.ok:
                problem = _validate_produced(store, job_id, stage)
                if problem is None:
                    break
                outcome = StageOutcome(
                    ok=False,
                    detail=problem,
                    error_code="missing_artifact",
                    retryable=False,
                )

            if keeper is not None and not keeper.renew():
                report["ok"] = False
                report["stopped"] = "lease_lost"
                return report

            if outcome.retryable and attempts < max_attempts:
                continue

            # Terminal for this run.
            if outcome.retryable:
                store.set_error(job_id, f"{stage.name}: {outcome.detail}")
                store.bump_attempts(job_id)
                store.transition(
                    job_id,
                    JobState.BLOCKED,
                    detail=f"retry cap reached at {stage.name}: {outcome.detail}",
                )
            else:
                store.set_error(job_id, f"{stage.name}: {outcome.detail}")
                # ``capability`` and ``qa_blocked`` both need an operator decision, not a louder
                # error: a configuration fix and a failed technical gate are not crashes.
                # ``publication_uncertain`` and ``publication_key_mismatch`` are the same kind of
                # thing: an upload whose outcome is unknown, or a record for different bytes,
                # needs a human to reconcile it. ``FAILED`` would invite a retry, and a retry is
                # the duplicate upload.
                store.transition(
                    job_id,
                    JobState.BLOCKED
                    if outcome.error_code
                    in {"capability", "qa_blocked", "publication_uncertain", "publication_key_mismatch"}
                    else JobState.FAILED,
                    detail=f"{stage.name} failed: {outcome.error_code} {outcome.detail}".strip(),
                )
            report["ok"] = False
            report["stopped"] = outcome.error_code or "failed"
            report["detail"] = outcome.detail
            report["stages"].append({"name": stage.name, "ok": False, "detail": outcome.detail})
            return report

        report["stages"].append(
            {"name": stage.name, "ok": True, "attempts": attempts, "detail": outcome.detail}
        )
        if keeper is not None and not keeper.renew():
            report["ok"] = False
            report["stopped"] = "lease_lost"
            return report
        current = store.get(job_id).state
        if current != stage.state:
            store.transition(job_id, stage.state, detail=f"{stage.name} completed")

    report["finished_at"] = _now()
    return report


def _is_done(store: JobStore, job_id: str, stage: Stage) -> bool:
    """A stage is done when every declared artifact exists and its contract validates.

    ``stage.done_when`` narrows that: an artifact can validate and still not mean the stage
    succeeded (a publication in ``uncertain`` phase is a valid artifact describing an unknown
    outcome). Without the predicate such a stage would be reported ``reused``/``ok`` on the next
    run, claiming work that may not have happened.
    """
    if not stage.produces:
        return False
    if not all(store.has_artifact(job_id, name) for name in stage.produces):
        return False
    if _validate_produced(store, job_id, stage) is not None:
        return False
    return _artifact_says_done(store, job_id, stage)


def _artifact_says_done(store: JobStore, job_id: str, stage: Stage) -> bool:
    """Apply ``done_when`` to the validated primary artifact. Default: any valid artifact is done."""
    if stage.done_when is None:
        return True
    if not stage.contract_artifact:
        return True
    try:
        payload = store.read_artifact(job_id, stage.contract_artifact)
    except Exception:  # noqa: BLE001 - unreadable is not done
        return False
    try:
        return bool(stage.done_when(payload, job_id))
    except Exception:  # noqa: BLE001 - a predicate that cannot decide is not a completion
        return False


def _validate_chain(start: JobState, stages: list[Stage]) -> None:
    """Every stage's target must be reachable from the previous one, starting at ``start``."""
    cursor = start
    for stage in stages:
        if stage.state == cursor:
            continue
        if not is_transition_allowed(cursor, stage.state):
            raise StageChainError(
                f"stage {stage.name!r} targets {stage.state.value}, which is not reachable "
                f"from {cursor.value}"
            )
        cursor = stage.state


def _validate_produced(store: JobStore, job_id: str, stage: Stage) -> str | None:
    """Return ``None`` when every declared artifact exists (and the contract validates)."""
    for name in stage.produces:
        if not store.has_artifact(job_id, name):
            return f"{stage.name} reported success but {name} is missing"
    if stage.contract is not None and stage.contract_artifact:
        try:
            payload = store.read_artifact(job_id, stage.contract_artifact)
        except Exception as exc:  # noqa: BLE001 - unreadable artifact is a failure, not a crash
            return f"{stage.name}: cannot read {stage.contract_artifact}: {exc}"
        try:
            validate_artifact(stage.contract, payload)
        except ArtifactValidationError as exc:
            return f"{stage.name}: {exc}"
    return None


def artifact_path(store: JobStore, job_id: str, name: str) -> Path:
    return store.job_dir(job_id) / name
