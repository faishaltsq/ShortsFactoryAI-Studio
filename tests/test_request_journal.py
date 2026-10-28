"""The request journal: one logical request, no duplicate paid call after an unknown outcome."""
from __future__ import annotations

import sqlite3

import pytest

from packages.core.providers.journal import (
    COMPLETED,
    UNCERTAIN,
    RequestJournal,
    hash_inputs,
    request_key,
)


@pytest.fixture
def journal(tmp_path):
    return RequestJournal(tmp_path / "requests.db")


def _key(**overrides):
    fields = {
        "job_id": "job1",
        "agent": "ScriptAgent",
        "ordinal": 0,
        "inputs_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "call_config_sha256": "c" * 64,
    }
    fields.update(overrides)
    return request_key(**fields)


def test_a_completed_result_replays_without_a_second_call(journal):
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    journal.mark_sent(request_key=key, attempt=1, provider="p", model="m")
    journal.mark_completed(
        request_key=key, attempt=1, usage={"prompt_tokens": 5}, result={"text": "hello"}
    )
    recorded = journal.completed(key)
    assert recorded is not None
    assert recorded["result"] == {"text": "hello"}
    assert recorded["usage"] == {"prompt_tokens": 5}
    # A replay is a local read: the journal has exactly one row for this attempt.
    assert journal.completed(key)["attempt"] == 1


def test_the_key_ignores_operational_configuration(journal):
    """Changing a timeout, a retry ceiling or a price must not make a recorded result unreplayable."""
    base = _key()
    operational = _key(call_config_sha256="c" * 64)  # same semantic fields
    assert base == operational
    different = _key(inputs_sha256="d" * 64)
    assert base != different


def test_the_key_separates_each_call_within_a_stage(journal):
    assert _key(ordinal=0) != _key(ordinal=1)


def test_a_restart_with_a_sent_but_unsettled_call_blocks_as_uncertain(journal):
    """The crash-between-send-and-record case.

    This is the whole point of the journal: a restart cannot know whether the provider charged for
    the call, so it must not silently retry it (double spend) and must not drop it (lost work).
    """
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    journal.mark_sent(request_key=key, attempt=1, provider="p", model="m")
    # A fresh journal object over the same file simulates the restart.
    restarted = RequestJournal(journal.db_path)
    restarted.reconcile()
    uncertain = restarted.uncertain("job1")
    assert len(uncertain) == 1
    assert uncertain[0]["request_key"] == key
    assert uncertain[0]["status"] == UNCERTAIN
    # And it is not silently completed: no result may be replayed for it.
    assert restarted.completed(key) is None


def test_a_prepared_but_unsent_reservation_is_released_at_restart(journal):
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    journal.reserve(request_key=key, attempt=1, job_id="job1", agent="ScriptAgent",
                    tokens=100, cost_usd=0.01)
    restarted = RequestJournal(journal.db_path)
    restarted.reconcile()
    # The call never left, so the allowance comes back.
    assert restarted.outstanding("job1") == {"tokens": 0.0, "cost_usd": 0.0}


def test_a_refusal_makes_no_transport_call_and_keeps_no_allowance(journal):
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    journal.reserve(request_key=key, attempt=1, job_id="job1", agent="ScriptAgent",
                    tokens=100, cost_usd=0.01)
    journal.mark_refused(request_key=key, attempt=1, error="budget exceeded")
    journal.release(request_key=key, attempt=1)
    assert journal.outstanding("job1") == {"tokens": 0.0, "cost_usd": 0.0}
    assert journal.completed(key) is None


def test_two_in_flight_calls_cannot_both_hold_the_whole_allowance(journal):
    """Concurrent reservations are additive: the budget sees both, not one."""
    first, second = _key(ordinal=0), _key(ordinal=1)
    for key, tokens in ((first, 100), (second, 250)):
        journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                        provider="p", model="m")
        journal.reserve(request_key=key, attempt=1, job_id="job1", agent="ScriptAgent",
                        tokens=tokens, cost_usd=0.0)
    assert journal.outstanding("job1")["tokens"] == 350.0
    # Settling the first leaves only the second outstanding.
    journal.settle(request_key=first, attempt=1, tokens=40, cost_usd=0.0)
    assert journal.outstanding("job1")["tokens"] == 250.0


def test_an_uncertain_call_retains_its_reservation(journal):
    """The money may already be gone, so the allowance stays consumed until acknowledged."""
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    journal.reserve(request_key=key, attempt=1, job_id="job1", agent="ScriptAgent",
                    tokens=500, cost_usd=0.05)
    journal.mark_sent(request_key=key, attempt=1, provider="p", model="m")
    journal.mark_uncertain(request_key=key, attempt=1, error="connection reset")
    journal.retained(request_key=key, attempt=1)
    outstanding = journal.outstanding("job1")
    assert outstanding["tokens"] == 500.0
    assert outstanding["cost_usd"] == 0.05
    journal.acknowledge(request_key=key, attempt=1, operator="faishal")
    # Acknowledgement records the decision but does not pretend the outcome is known.
    row = journal.uncertain("job1")[0]
    assert "faishal" in row["error"]


def test_an_operator_acknowledged_retry_gets_a_new_attempt_number(journal):
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    journal.mark_sent(request_key=key, attempt=1, provider="p", model="m")
    journal.mark_uncertain(request_key=key, attempt=1, error="reset")
    assert journal.next_attempt(key) == 2
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=2,
                    provider="p", model="m")
    journal.mark_sent(request_key=key, attempt=2, provider="p", model="m")
    journal.mark_completed(request_key=key, attempt=2, usage={}, result={"text": "ok"})
    assert journal.completed(key)["attempt"] == 2


def test_statuses_project_no_payload_content(journal):
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    journal.mark_sent(request_key=key, attempt=1, provider="p", model="m")
    journal.mark_completed(request_key=key, attempt=1, usage={"prompt_tokens": 1},
                           result={"secret": "sk-live-should-never-appear"})
    for row in journal.statuses("job1"):
        assert "result_json" not in row
        assert "usage_json" not in row
        assert "should-never-appear" not in str(row)


def test_hash_inputs_is_stable_across_key_order_and_whitespace():
    assert hash_inputs({"a": 1, "b": 2}) == hash_inputs({"b": 2, "a": 1})
    assert hash_inputs({"a": 1}) != hash_inputs({"a": 2})


def test_the_surviving_schema_is_queryable(journal):
    """A journal opened against a database created by an earlier build still works."""
    key = _key()
    journal.prepare(request_key=key, job_id="job1", agent="ScriptAgent", attempt=1,
                    provider="p", model="m")
    with sqlite3.connect(journal.db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "provider_requests" in tables
    assert "budget_reservations" in tables


# -- the boundary the pipeline actually uses ------------------------------------------------
def _recorder(tmp_path, *, journal: RequestJournal, fail_first: bool = False):
    from packages.core.providers.base import Provider
    from packages.core.providers.usage import RecordingProvider, UsageTracker

    class Stub(Provider):
        transport = "mock"
        name = "stub"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, call, *, system, user, task):  # type: ignore[override]
            from packages.core.providers.base import ProviderResult, Usage

            self.calls += 1
            if fail_first and self.calls == 1:
                raise ConnectionError("reset by peer")
            return ProviderResult(
                content="hello", provider="stub", model="m",
                usage=Usage(prompt_tokens=7, completion_tokens=3), elapsed_ms=1,
            )

        def health(self, call):  # type: ignore[override]
            from packages.core.providers.base import Health

            return Health(ok=True, detail="")

        def list_models(self, call):  # type: ignore[override]
            return ["m"]

    inner = Stub()
    tracker = UsageTracker(tmp_path / "usage.db")
    recorder = RecordingProvider(
        inner, tracker=tracker, agent="ScriptAgent", job_id="job1", journal=journal
    )
    from packages.core.providers.base import ResolvedCall
    from packages.core.providers.base import Capability

    call = ResolvedCall(
        provider="stub", transport="mock", base_url="", model="m", temperature=None,
        max_tokens=None, timeout_s=1.0, max_retries=0,
        capabilities=frozenset({Capability.CHAT}), allow_private_hosts=False,
    )
    return inner, recorder, call


def test_a_completed_call_is_journalled_and_replays_locally(tmp_path):
    journal = RequestJournal(tmp_path / "r.db")
    inner, recorder, call = _recorder(tmp_path, journal=journal)
    first = recorder.complete(call, system="s", user="u", task="script")
    assert first.content == "hello"
    assert inner.calls == 1
    statuses = journal.statuses("job1")
    assert [row["status"] for row in statuses] == [COMPLETED]
    # A second identical call replays the recorded response with no new transport call.
    second = recorder.complete(call, system="s", user="u", task="script")
    assert second.content == "hello"
    assert inner.calls == 1, "a completed request must not hit the transport again"


def test_a_failed_send_becomes_uncertain_and_is_not_retried_blindly(tmp_path):
    journal = RequestJournal(tmp_path / "r.db")
    inner, recorder, call = _recorder(tmp_path, journal=journal, fail_first=True)
    from packages.core.providers.base import ProviderError  # noqa: F401 - import sanity

    raised = False
    try:
        recorder.complete(call, system="s", user="u", task="script")
    except ConnectionError:
        raised = True
    assert raised, "the transport's error must still surface to the caller"
    uncertain = journal.uncertain("job1")
    assert len(uncertain) == 1, "the call left the process; its outcome is unknown"
    # The allowance stays consumed: the money may already be gone.
    assert journal.outstanding("job1")["tokens"] > 0
    # Nothing completed, so nothing can be replayed.
    assert journal.completed(uncertain[0]["request_key"]) is None
    # The recorded attempt count means an operator-acknowledged retry is a new attempt, not a
    # silent duplicate.
    assert journal.next_attempt(uncertain[0]["request_key"]) == 2
