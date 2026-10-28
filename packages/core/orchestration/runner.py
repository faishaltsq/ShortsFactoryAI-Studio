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
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from ..contracts.base import Artifact, ArtifactValidationError, validate_artifact
from ..contracts.state import JobState, is_transition_allowed
from ..observability.events import STAGE_AGENTS
from .jobstore import JobStore, safe_artifact_name
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
    #: A decision the stage wants recorded without a success checkpoint and without a retry.
    #: ``revision_required`` commits the review evidence and returns to the revising stage;
    #: ``qa_repair_required`` commits the QA verdict and waits for the rework controller;
    #: ``waiting_resources`` releases ownership and keeps the request visible for later;
    #: ``paused`` stops at a safe boundary without cancelling the operator's intent. None of
    #: these is a failure, and none is a success: the runner commits what the stage staged
    #: (its evidence) and stops the chain.
    control: (
        Literal["revision_required", "qa_repair_required", "waiting_resources", "paused"] | None
    ) = None


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


#: Stage failures that have already staged evidence the operator must see. The runner commits
#: staged artifacts for these codes even though the stage failed — a QA verdict that says
#: ``blocked`` is not a crash to discard, it is the finding itself.
EVIDENCE_CODES = frozenset(
    {"qa_blocked", "publication_uncertain", "publication_key_mismatch", "revision_required"}
)


def _end_stage(store: JobStore, job_id: str, keeper: LeaseKeeper | None) -> None:
    """Clear the active-stage row for this worker, whatever happens next.

    Every exit from a stage's attempt loop goes through here: a committed stage, a failure, a
    control decision, a lost lease. A row left behind would read as "working" forever, which is
    exactly the studio lie this whole mechanism exists to prevent.
    """
    if keeper is None:
        return
    try:
        store.end_active_stage(job_id, token=keeper.token)
    except Exception:  # noqa: BLE001 - clearing bookkeeping must never mask the real outcome
        pass


class StageContext:
    """What a stage body receives instead of ``(store, job_id)``.

    Artifacts and files written through this context land in a run-owned staging directory and
    become canonical only when the runner validates and promotes them after the stage returns.
    A worker that loses its lease mid-stage can therefore no longer decorate a job whose lease
    another worker took over: promotion is fenced by the lease check in ``commit_stage``.
    """

    def __init__(
        self,
        store: JobStore,
        job_id: str,
        staging: Path,
        *,
        keeper: LeaseKeeper | None = None,
        cancel: CancelToken | None = None,
    ) -> None:
        self.store = store
        self.job_id = job_id
        self.staging = staging
        self.keeper = keeper
        self.cancel = cancel
        self.call: Any = None
        self.json_pending: list[tuple[str, dict[str, Any]]] = []
        self.files_pending: list[tuple[str, Path]] = []

    def write_artifact(self, name: str, payload: dict[str, Any]) -> None:
        safe = safe_artifact_name(name)
        tmp = self.staging / safe
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        self.json_pending.append((name, payload))

    def alloc(self, name: str) -> Path:
        """A staging path the stage writes itself (big binaries: video, wav, png)."""
        return self.staging / safe_artifact_name(name)

    def stage_file(self, name: str, path: Path) -> None:
        """Move an already-written file into staging so promotion covers it too."""
        safe = safe_artifact_name(name)
        target = self.staging / safe
        os.replace(path, target)
        self.files_pending.append((name, target))

    def assert_active(self) -> None:
        """Raise when this run should stop: cancelled, or the lease is gone."""
        if self.cancel is not None and self.cancel.is_cancelled():
            raise StageError("cancelled", "cancellation observed inside the stage", retryable=False)
        if self.keeper is not None and not self.keeper.renew():
            # The token in the keeper is stale once renew fails; LeaseLost's default records
            # "no live token" instead of a misleading one.
            raise LeaseLost(self.job_id, "lease lost during stage")


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
    run: Callable[[StageContext], StageOutcome]
    #: The agent credited with this stage's work. Events use it, so a studio projection can never
    #: attribute a stage to an agent that did not run it. Defaults to the stage's producer from
    #: STAGE_AGENTS when empty.
    agent_id: str = ""
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
        # One predicate, one place: ``_is_done`` is the same test chain validation used above, so
        # a stage that reports a control decision (a revise verdict) is never mistaken for a
        # completed stage here just because its artifact validates.
        if _is_done(store, job_id, stage):
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
        # The stage that is actually running, persisted with the worker's lease token. The studio
        # projection joins this to the lease row; the job's state alone names the stage that
        # *finished*, which is not the agent working right now.
        stage_agent = stage.agent_id or STAGE_AGENTS.get(stage.state.value, "FactoryOrchestrator")
        if keeper is not None:
            store.begin_active_stage(
                job_id, stage=stage.name, agent_id=stage_agent, token=keeper.token
            )
        # A stage that runs longer than the TTL must not age its own lease out: heartbeat every
        # ttl/3 while it executes. A lost lease inside the stage still surfaces through the
        # stage's own LeaseLost, the post-failure renew, or the post-success renew below.
        if keeper is not None:
            keeper.start_heartbeat()
        outcome: StageOutcome
        while True:
            attempts += 1
            # Run-owned staging, fresh per attempt: everything the stage writes lands here and
            # becomes canonical only through the runner's fenced commit below.
            staging = Path(store.job_dir(job_id)) / f".stage-run-{uuid.uuid4().hex}"
            staging.mkdir(parents=True, exist_ok=True)
            ctx = StageContext(
                store,
                job_id,
                staging,
                keeper=keeper,
                cancel=cancel,
            )
            committed = False
            try:
                outcome = stage.run(ctx)
            except LeaseLost:
                if keeper is not None:
                    keeper.stop_heartbeat()
                _discard_staging(staging)
                _end_stage(store, job_id, keeper)
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

            if outcome.ok and outcome.control is not None:
                # A decision, not a result: commit what the stage staged as evidence, then stop.
                # ``waiting_resources`` releases ownership so another worker can take the job; the
                # others keep it and wait for the rework controller (step 8) to reopen.
                problem = _validate_staged(ctx, stage)
                if problem is None:
                    promoted = _promote_staged(store, job_id, ctx, stage, validate=False)
                    if promoted is not None:
                        outcome = StageOutcome(ok=False, detail=promoted, error_code="missing_artifact")
                    else:
                        store.set_error(job_id, f"{stage.name}: {outcome.control} {outcome.detail}".strip())
                        if outcome.control == "waiting_resources":
                            store.transition(job_id, JobState.BLOCKED,
                                             detail=f"{stage.name} waiting: {outcome.detail}")
                        else:
                            store.transition(job_id, JobState.BLOCKED,
                                             detail=f"{stage.name} {outcome.control}: {outcome.detail}")
                        report["ok"] = False
                        report["stopped"] = outcome.control
                        report["detail"] = outcome.detail
                        report["stages"].append({"name": stage.name, "ok": False,
                                                 "control": outcome.control, "detail": outcome.detail})
                        _discard_staging(staging)
                        if keeper is not None:
                            keeper.stop_heartbeat()
                        return report
                        _end_stage(store, job_id, keeper)
                else:
                    outcome = StageOutcome(ok=False, detail=problem, error_code="missing_artifact")
            if outcome.ok:
                problem = _validate_staged(ctx, stage)
                if problem is None:
                    try:
                        promoted = _promote_staged(store, job_id, ctx, stage)
                    except LeaseLost:
                        # The lease died between the stage's own checks and the fenced commit:
                        # nothing canonical changed, so stop without recording anything.
                        report["ok"] = False
                        report["stopped"] = "lease_lost"
                        report["detail"] = f"lease lost at promotion of {stage.name}"
                        _discard_staging(staging)
                        _end_stage(store, job_id, keeper)
                        return report
                    committed = promoted is None
                    problem = promoted
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
                _discard_staging(staging)
                return report

            retrying = outcome.retryable and attempts < max_attempts
            if not retrying and not committed and ctx.json_pending and outcome.error_code in EVIDENCE_CODES:
                # Terminal failure with staged outputs: negative evidence — a QA verdict, an
                # uncertain publication record — is committed, not discarded. A crashed stage's
                # partial staging is dropped instead, leaving canonical clean.
                _promote_staged(store, job_id, ctx, stage, validate=False)

            if retrying:
                _discard_staging(staging)
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
            _discard_staging(staging)
            if keeper is not None:
                keeper.stop_heartbeat()
            return report
            _end_stage(store, job_id, keeper)

        _discard_staging(staging)
        _end_stage(store, job_id, keeper)
        report["stages"].append(
            {"name": stage.name, "ok": True, "attempts": attempts, "detail": outcome.detail}
        )
        if keeper is not None:
            keeper.stop_heartbeat()
            if not keeper.renew():
                report["ok"] = False
                report["stopped"] = "lease_lost"
                return report
        current = store.get(job_id).state
        if current != stage.state:
            store.transition(job_id, stage.state, detail=f"{stage.name} completed")

    report["finished_at"] = _now()
    return report


def _promote_staged(
    store: JobStore,
    job_id: str,
    ctx: StageContext,
    stage: Stage,
    *,
    validate: bool = True,
) -> str | None:
    """Move staged outputs into the canonical job dir; return the first problem or ``None``.

    With ``validate`` the stage's contract is checked against the *staged* payload before any
    canonical byte changes; promotion itself is a single fenced ``commit_stage`` whose lease
    check runs inside the same transaction that flips the state.
    """
    problem = _validate_staged(ctx, stage) if validate else None
    if problem is not None:
        return problem
    current = store.get(job_id).state
    target = (
        stage.state
        if current != stage.state and is_transition_allowed(current, stage.state)
        else None
    )
    store.commit_stage(
        job_id,
        token=ctx.keeper.token if ctx.keeper is not None else None,
        json_artifacts=ctx.json_pending,
        files=ctx.files_pending,
        target=target,
        detail=f"{stage.name} completed",
    )
    return None


def _discard_staging(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)


def _validate_staged(ctx: StageContext, stage: Stage) -> str | None:
    """Validate the stage's declared outputs where they sit, before any promotion."""
    staged_names = {name for name, _ in ctx.json_pending} | {name for name, _ in ctx.files_pending}
    for name in stage.produces:
        if name not in staged_names:
            return f"{stage.name} reported success but {name} is missing"
    if stage.contract is not None and stage.contract_artifact:
        payloads = dict(ctx.json_pending)
        payload = payloads.get(stage.contract_artifact)
        if payload is None:
            return f"{stage.name}: {stage.contract_artifact} was not written through the stage context"
        try:
            validate_artifact(stage.contract, payload)
        except ArtifactValidationError as exc:
            return f"{stage.name}: {exc}"
    return None


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
