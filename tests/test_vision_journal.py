"""Paid image requests obey the same durable boundary as text requests."""
from dataclasses import replace

import pytest

from packages.core.providers.base import (
    Capability,
    ProviderError,
    ProviderResult,
    ResolvedCall,
    Usage,
    VisionImage,
)
from packages.core.providers.journal import RequestJournal
from packages.core.providers.mock import MockProvider
from packages.core.providers.usage import RecordingProvider, UsageTracker


class VisionStub(MockProvider):
    def __init__(self, failure=None):
        self.sent = 0
        self.failure = failure

    def complete_vision(self, call, *, system, user, task, images):
        self.sent += 1
        if self.failure:
            raise self.failure
        return ProviderResult("observed", "vision", "served-model", Usage(7, 3), 12)


def setup(tmp_path, inner=None):
    journal = RequestJournal(tmp_path / "requests.db")
    recorder = RecordingProvider(
        inner or VisionStub(), tracker=UsageTracker(tmp_path / "usage.db"),
        agent="QualityAgent", job_id="job", journal=journal, price_in=1, price_out=2,
    )
    call = ResolvedCall(
        provider="vision", transport="mock", base_url="", model="configured-model",
        temperature=0.2, max_tokens=100, timeout_s=2, max_retries=2,
        capabilities=frozenset({Capability.VISION}), allow_private_hosts=False,
    )
    return recorder, journal, call


def invoke(recorder, call, images=None):
    return recorder.complete_vision(call, system="s", user="u", task="vision",
                                    images=images or [VisionImage(b"\x89PNG\r\n\x1a\nfixture")])


def test_completed_vision_replays_after_restart_with_usage_and_cost(tmp_path):
    inner = VisionStub()
    recorder, journal, call = setup(tmp_path, inner)
    assert invoke(recorder, call).content == "observed"
    rows = journal.statuses("job")
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["prepared_at"] and rows[0]["sent_at"] and rows[0]["settled_at"]
    assert rows[0]["model"] == "served-model"
    saved = journal.completed(rows[0]["request_key"])
    assert saved["usage"]["prompt_tokens"] == 7
    assert saved["usage"]["reported"] is True
    assert saved["usage"]["est_cost_usd"] == pytest.approx(0.000013)
    restarted, _, _ = setup(tmp_path, inner)
    restarted.tracker.set_limits(max_daily_tokens=1, max_daily_cost_usd=None, unlimited=False)
    assert invoke(restarted, call).model == "served-model"
    assert inner.sent == 1
    assert len(restarted.tracker.for_job("job")) == 1


@pytest.mark.parametrize("failure", [ConnectionError("lost response"), SystemExit("process crash")])
def test_unknown_vision_outcome_survives_restart_and_requires_one_explicit_authorization(tmp_path, failure):
    inner = VisionStub(failure)
    recorder, journal, call = setup(tmp_path, inner)
    with pytest.raises(type(failure)):
        invoke(recorder, call)
    restarted, journal, _ = setup(tmp_path, inner)
    journal.reconcile()
    rows = journal.uncertain("job")
    assert len(rows) == 1
    assert journal.outstanding("job")["tokens"] > 0
    with pytest.raises(ProviderError) as exc:
        invoke(restarted, call)
    assert exc.value.code == "provider_outcome_unknown"
    assert inner.sent == 1
    journal.acknowledge(request_key=rows[0]["request_key"], attempt=1, operator="test-operator")
    inner.failure = None
    assert invoke(restarted, call).content == "observed"
    assert inner.sent == 2
    assert [row["status"] for row in journal.statuses("job")] == ["uncertain", "completed"]
    invoke(restarted, call)
    assert inner.sent == 2


def test_vision_identity_binds_image_bytes_order_and_effective_model(tmp_path):
    inner = VisionStub()
    recorder, journal, call = setup(tmp_path, inner)
    a = VisionImage(b"\x89PNG\r\n\x1a\nfirst")
    b = VisionImage(b"\x89PNG\r\n\x1a\nsecond")
    invoke(recorder, call, [a, b])
    invoke(recorder, call, [b, a])
    invoke(recorder, replace(call, model="other-model"), [a, b])
    invoke(recorder, replace(call, timeout_s=20, max_retries=0), [a, b])
    assert inner.sent == 3
    assert len({row["request_key"] for row in journal.statuses("job")}) == 3


@pytest.mark.parametrize("kind,path", [
    ("openai_compat", "/v1/chat/completions"),
    ("anthropic", "/v1/v1/messages"),
    ("ollama", "/v1/api/chat"),
])
@pytest.mark.parametrize("vision", [True, False])
def test_inference_transport_does_not_hide_billable_retries(tmp_path, kind, path, vision):
    from packages.core.providers.anthropic import AnthropicProvider
    from packages.core.providers.http_base import PinnedHTTP
    from packages.core.providers.ollama import OllamaProvider
    from packages.core.providers.openai_compat import OpenAICompatProvider
    from tests.stub_server import StubServer

    adapters = {"openai_compat": OpenAICompatProvider, "anthropic": AnthropicProvider,
                "ollama": OllamaProvider}
    with StubServer() as server:
        server.route("POST", path, status=500, body={"error": "accepted but response lost"})
        inner = adapters[kind](http=PinnedHTTP(timeout_s=2, max_retries=2))
        recorder, journal, call = setup(tmp_path, inner)
        call = replace(call, transport=kind, base_url=server.base_url, allow_private_hosts=True)
        def send(target):
            if vision:
                return invoke(target, call)
            return target.complete(call, system="s", user="u", task="text")
        with pytest.raises(ProviderError):
            send(recorder)
        assert len([r for r in server.recorded if r.method == "POST"]) == 1
        restarted, _, _ = setup(tmp_path, inner)
        with pytest.raises(ProviderError) as exc:
            send(restarted)
        assert exc.value.code == "provider_outcome_unknown"
        assert len(server.recorded) == 1
        assert len(journal.uncertain("job")) == 1


def test_provider_omitting_usage_does_not_acquire_a_zero_cost_estimate(tmp_path):
    class NoUsage(VisionStub):
        def complete_vision(self, call, **kwargs):
            return ProviderResult("observed", "vision", "model")

    recorder, journal, call = setup(tmp_path, NoUsage())
    invoke(recorder, call)
    saved = journal.completed(journal.statuses("job")[0]["request_key"])
    assert saved["usage"]["reported"] is False
    assert saved["usage"]["est_cost_usd"] is None
    assert saved["usage"]["cost_source"] == "unavailable"


def test_editorial_resolver_attaches_the_job_journal(tmp_path):
    from apps.api.settings import Settings
    from apps.api.state import AppState
    from packages.core.orchestration.editorial import _vision_call
    from packages.core.providers.openai_compat import OpenAICompatProvider
    from packages.core.providers.registry import ProviderSpec
    from tests.stub_server import StubServer

    state = AppState.build(Settings(
        data_dir=tmp_path / "data", db_path=tmp_path / "data/factory.db",
        jobs_dir=tmp_path / "data/jobs", secrets_dir=tmp_path / "data/secrets",
        studio_config=tmp_path / "config/studio.json",
    ).ensure())
    job = state.store.create(title="Resolver fixture")
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "fixture"}]})
        server.route("POST", "/v1/chat/completions", body={
            "model": "fixture", "choices": [{"message": {"content": "observed"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })
        state.registry.add(ProviderSpec(id="vision", transport="openai_compat",
            base_url=server.base_url, model="fixture", allow_private_hosts=True,
            capabilities=[Capability.CHAT, Capability.VISION]))
        state.bindings = {"QualityAgent": {"primary": "vision"}}
        state.transports["openai_compat"] = OpenAICompatProvider()
        call, recorder = _vision_call(state, job)
        assert recorder.journal is state.requests
        assert invoke(recorder, call).content == "observed"
        assert invoke(recorder, call).content == "observed"
        assert len([r for r in server.recorded if r.method == "POST"]) == 1
        assert state.requests.statuses(job.id)[0]["status"] == "completed"
        assert len(state.usage.for_job(job.id)) == 1


def test_anthropic_health_never_generates_an_unjournaled_completion(tmp_path):
    from packages.core.providers.anthropic import AnthropicProvider
    from tests.stub_server import StubServer

    _, _, call = setup(tmp_path)
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "fixture"}]})
        server.route("POST", "/v1/messages", body={"content": [{"type": "text", "text": "hi"}]})
        call = replace(call, transport="anthropic", base_url=server.base_url.removesuffix("/v1"), allow_private_hosts=True)
        assert AnthropicProvider().health(call).ok
        assert [r.method for r in server.recorded] == ["GET"]
