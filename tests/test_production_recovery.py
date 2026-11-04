"""Acceptance recovery must never turn an unknown paid outcome into an automatic retry."""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from scripts import run_production_acceptance as acceptance


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    return AppState.build(Settings(
        data_dir=tmp_path / 'data', db_path=tmp_path / 'data/factory.db',
        jobs_dir=tmp_path / 'data/jobs', secrets_dir=tmp_path / 'data/secrets',
        studio_config=tmp_path / 'config/studio.json',
    ).ensure())


def uncertain(state: AppState, job_id: str) -> str:
    key = 'a' * 64
    attempt = state.requests.claim_attempt(
        request_key=key, job_id=job_id, agent='ScriptAgent', provider='stepfun', model='configured',
    )
    state.requests.mark_sent(request_key=key, attempt=attempt, provider='stepfun', model='configured')
    state.requests.mark_uncertain(request_key=key, attempt=attempt, error='timeout after send')
    return key


def test_uncertain_outcome_stops_once_without_authorization(state, monkeypatch):
    job = state.store.create(title='Recovery fixture', state=JobState.BLOCKED)
    key = uncertain(state, job.id)
    calls = []

    def stopped(*args, **kwargs):
        calls.append(1)
        return {'ok': False, 'stopped': 'provider_outcome_unknown', 'stages': []}

    monkeypatch.setattr(acceptance, 'run_job', stopped)
    report = acceptance.run_pipeline(state, job.id, operator='operator', reason='Inspect interrupted run')
    assert report['stopped'] == 'provider_outcome_unknown'
    assert calls == [1]
    assert state.requests.statuses(job.id)[0]['status'] == 'uncertain'
    with pytest.raises(ValueError, match='explicit authorization'):
        state.requests.claim_attempt(
            request_key=key, job_id=job.id, agent='ScriptAgent', provider='stepfun', model='configured',
        )
    assert state.store.get(job.id).state == JobState.BLOCKED
    assert state.store.read_artifact(job.id, 'recovery-actions.json')['actions'][-1]['result'] == 'provider_outcome_unknown'


def test_resume_delegates_state_recovery_without_jumping_to_qc(state, monkeypatch):
    job = state.store.create(title='Failed fixture', state=JobState.FAILED)
    observed = []

    def refuse(*args, **kwargs):
        observed.append(state.store.get(job.id).state)
        return {'ok': False, 'stopped': 'resume_evidence_missing', 'stages': []}

    monkeypatch.setattr(acceptance, 'run_job', refuse)
    acceptance.run_pipeline(state, job.id, operator='operator', reason='Restore failed stage')
    assert observed == [JobState.FAILED]
    assert state.store.get(job.id).state == JobState.FAILED
    assert state.store.event_count(job.id) == 1  # Creation only; no manufactured state transition.


def test_authorization_requires_explicit_duplicate_cost_confirmation(state):
    job = state.store.create(title='Uncertain fixture', state=JobState.BLOCKED)
    key = uncertain(state, job.id)
    with pytest.raises(ValueError, match='duplicate'):
        acceptance.authorize_retry(
            state, job.id, request_key=key, attempt=1, operator='operator',
            reason='Provider cannot reconcile', confirm_duplicate_cost=False,
        )
    with pytest.raises(ValueError, match='explicit authorization'):
        state.requests.claim_attempt(
            request_key=key, job_id=job.id, agent='ScriptAgent', provider='stepfun', model='configured',
        )


def test_authorization_is_scoped_logged_single_use_and_does_not_run_pipeline(state, monkeypatch):
    job = state.store.create(title='Uncertain fixture', state=JobState.BLOCKED)
    other = state.store.create(title='Other job', state=JobState.BLOCKED)
    key = uncertain(state, job.id)
    monkeypatch.setattr(acceptance, 'run_job', lambda *a, **k: pytest.fail('authorization dispatched inference'))
    kwargs = dict(request_key=key, attempt=1, operator='operator', reason='Accept duplicate charge risk', confirm_duplicate_cost=True)
    with pytest.raises(ValueError, match='job'):
        acceptance.authorize_retry(state, other.id, **kwargs)
    acceptance.authorize_retry(state, job.id, **kwargs)
    history = state.store.read_artifact(job.id, 'recovery-actions.json')['actions']
    assert history[0]['operator'] == 'operator'
    assert history[0]['reason'] == 'Accept duplicate charge risk'
    assert history[-1]['result'] == 'authorized'
    claim = dict(request_key=key, job_id=job.id, agent='ScriptAgent', provider='stepfun', model='configured')
    assert state.requests.claim_attempt(**claim) == 2
    with pytest.raises(ValueError, match='active or completed'):
        state.requests.claim_attempt(**claim)
    assert state.requests.statuses(job.id)[0]['status'] == 'uncertain'
    assert state.store.get(job.id).state == JobState.BLOCKED


def test_empty_operator_reason_and_terminal_jobs_are_refused_before_execution(state, monkeypatch):
    monkeypatch.setattr(acceptance, 'run_job', lambda *a, **k: pytest.fail('unexpected execution'))
    job = state.store.create(title='Cancelled fixture', state=JobState.CANCELLED)
    for operator, reason in [('', 'reason'), ('operator', ' '), ('operator', 'reason')]:
        with pytest.raises(ValueError):
            acceptance.run_pipeline(state, job.id, operator=operator, reason=reason)


def test_cli_requires_an_explicit_job_and_action_before_building_runtime(monkeypatch):
    monkeypatch.setattr(acceptance.AppState, 'build', lambda *a, **k: pytest.fail('runtime created without action'))
    with pytest.raises(SystemExit) as exc:
        acceptance.main([])
    assert exc.value.code == 2
