"""Explicit production recovery using the existing journal, leases and pipeline.

This command never approves content, edits router state, or retries an unknown
provider outcome automatically. Authorization and execution are separate actions.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.settings import Settings  # noqa: E402
from apps.api.state import AppState  # noqa: E402
from packages.core.contracts.state import JobState  # noqa: E402
from packages.core.orchestration.leases import LeaseKeeper  # noqa: E402
from packages.core.orchestration.pipeline import run_job  # noqa: E402
from packages.core.security.redact import redact  # noqa: E402


def _decision(operator: str, reason: str) -> None:
    if not operator.strip() or not reason.strip():
        raise ValueError('Recovery requires a named operator and a non-empty reason')


def _record(state: AppState, job_id: str, keeper: LeaseKeeper, **action: Any) -> None:
    name = 'recovery-actions.json'
    history = state.store.read_artifact(job_id, name) if state.store.has_artifact(job_id, name) else {'actions': []}
    if not isinstance(history, dict) or not isinstance(history.get('actions'), list):
        raise ValueError('Recovery audit is invalid; restore it before continuing')
    # Persist intent before any authorization or request; malformed history never resets the log.
    entry = {key: redact(value) if isinstance(value, str) else value for key, value in action.items()}
    entry['recorded_at'] = dt.datetime.now(dt.UTC).isoformat()
    history['actions'].append(entry)
    state.store.commit_stage(job_id, token=keeper.token, json_artifacts=[(name, history)])


def run_pipeline(state: AppState, job_id: str, *, operator: str, reason: str) -> dict[str, Any]:
    """One explicit resume; the runner alone selects legal, evidence-backed stage recovery."""
    _decision(operator, reason)
    job = state.store.get(job_id)
    if job.state in {
        JobState.CANCELLED, JobState.REJECTED, JobState.APPROVED, JobState.PRIVATE_UPLOAD,
        JobState.SCHEDULED, JobState.PUBLISHED,
    }:
        raise ValueError(f'Acceptance recovery cannot run a job in {job.state.value}')
    if job.state == JobState.READY_FOR_APPROVAL:
        return {'job_id': job_id, 'ok': True, 'stopped': 'human_approval_required', 'stages': []}
    keeper = LeaseKeeper(state.store.db_path, owner=f'acceptance-{job_id}')
    keeper.acquire(job_id)
    try:
        _record(state, job_id, keeper, action='resume', operator=operator, reason=reason, result='requested')
        try:
            report = run_job(state, job_id, keeper=keeper)
        except Exception as exc:
            _record(state, job_id, keeper, action='resume', operator=operator, reason=reason,
                    result='error', error=type(exc).__name__)
            raise
        _record(state, job_id, keeper, action='resume', operator=operator, reason=reason,
                result=report.get('stopped') or ('completed' if report.get('ok') else 'failed'))
        return report
    finally:
        keeper.release()


def authorize_retry(
    state: AppState, job_id: str, *, request_key: str, attempt: int,
    operator: str, reason: str, confirm_duplicate_cost: bool,
) -> None:
    """Authorize exactly one journal retry, never dispatch it or erase its uncertain predecessor."""
    _decision(operator, reason)
    if not confirm_duplicate_cost:
        raise ValueError('Explicit confirmation of possible duplicate provider cost is required')
    keeper = LeaseKeeper(state.store.db_path, owner=f'acceptance-authorize-{job_id}')
    keeper.acquire(job_id)
    try:
        rows = state.requests.statuses(job_id)
        matching = [row for row in rows if row['request_key'] == request_key]
        if not matching:
            raise ValueError('Request does not belong to this job')
        latest = max(matching, key=lambda row: int(row['attempt']))
        if latest['status'] != 'uncertain' or int(latest['attempt']) != attempt:
            raise ValueError('Only the latest uncertain attempt for this job may be authorized')
        detail = dict(action='authorize_retry', operator=operator, reason=reason,
                      request_key=request_key, attempt=attempt)
        _record(state, job_id, keeper, **detail, result='requested')
        try:
            state.requests.acknowledge(request_key=request_key, attempt=attempt, operator=operator)
        except Exception as exc:
            _record(state, job_id, keeper, **detail, result='error', error=type(exc).__name__)
            raise
        _record(state, job_id, keeper, **detail, result='authorized')
    finally:
        keeper.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--resume', action='store_true')
    actions.add_argument('--list-uncertain', action='store_true')
    actions.add_argument('--authorize-retry', action='store_true')
    parser.add_argument('--request-key')
    parser.add_argument('--attempt', type=int)
    parser.add_argument('--by', dest='operator')
    parser.add_argument('--reason')
    parser.add_argument('--confirm-duplicate-cost', action='store_true')
    args = parser.parse_args(argv)
    if not args.list_uncertain:
        if not args.operator or not args.operator.strip() or not args.reason or not args.reason.strip():
            parser.error('--by and --reason are required for recovery decisions')
        if args.authorize_retry and (
            not args.request_key or not args.attempt or args.attempt < 1 or not args.confirm_duplicate_cost
        ):
            parser.error('--authorize-retry needs --request-key, positive --attempt and --confirm-duplicate-cost')
    try:
        state = AppState.build(Settings.from_env().ensure())
        state.store.get(args.job_id)
        if args.list_uncertain:
            # Only journal metadata; never print provider error bodies or response payloads.
            rows = [{key: row[key] for key in ('request_key', 'attempt', 'agent', 'status', 'provider', 'model')}
                    for row in state.requests.uncertain(args.job_id)]
            print(json.dumps({'job_id': args.job_id, 'uncertain': rows}, ensure_ascii=False))
            return 0
        if args.authorize_retry:
            authorize_retry(state, args.job_id, request_key=args.request_key, attempt=args.attempt,
                            operator=args.operator, reason=args.reason,
                            confirm_duplicate_cost=args.confirm_duplicate_cost)
            print(json.dumps({'job_id': args.job_id, 'authorized': True, 'dispatched': False}))
            return 0
        report = run_pipeline(state, args.job_id, operator=args.operator, reason=args.reason)
        final = state.store.get(args.job_id)
        print(json.dumps({'job_id': args.job_id, 'ok': report.get('ok'),
                          'stopped': report.get('stopped'), 'state': final.state.value,
                          'human_approval_required': final.state == JobState.READY_FOR_APPROVAL}))
        return 0 if report.get('ok') and final.state == JobState.READY_FOR_APPROVAL else 1
    except Exception as exc:
        print(redact(f'{type(exc).__name__}: {exc}'), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
