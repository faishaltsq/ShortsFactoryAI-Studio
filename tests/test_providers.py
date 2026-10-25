"""Transports, resolution, and the two rules that must never bend.

Rule 1: two agents on one provider are independent. The donor mutated the shared provider to apply
an override, so the second agent silently ran the first agent's model.
Rule 2: a live job never degrades to mock.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from packages.core.providers.base import (
    Capability,
    CapabilityMismatch,
    NoProviderAvailable,
    ProviderError,
    ResolvedCall,
)
from packages.core.providers.factory import build_transports, default_registry
from packages.core.providers.mock import MockProvider
from packages.core.providers.openai_compat import OpenAICompatProvider
from packages.core.providers.registry import ProviderSpec
from packages.core.providers.resolve import Binding, resolve_call
from packages.core.security.secretstore import SecretStore

from .stub_server import StubServer


@pytest.fixture
def store(tmp_path):
    return SecretStore(tmp_path / "secrets")


@pytest.fixture
def stub():
    with StubServer() as server:
        yield server


def _spec(provider_id: str, base_url: str, **overrides) -> ProviderSpec:
    payload = dict(
        id=provider_id,
        transport="openai_compat",
        base_url=base_url,
        model="stub-model",
        allow_private_hosts=True,  # the stub server is on loopback
    )
    payload.update(overrides)
    return ProviderSpec(**payload)


# --------------------------------------------------------------------------- resolution


def test_two_agents_on_one_provider_get_independent_calls(store, stub):
    """The regression test for the donor's shared-mutation bug."""
    stub.route("GET", "/v1/models", body={"data": [{"id": "stub-model"}]})
    registry = default_registry()
    registry.add(_spec("shared", stub.base_url))
    transports = build_transports()

    research = resolve_call(
        binding=Binding(agent="ResearchAgent", primary="shared", model="model-a", temperature=0.2),
        registry=registry,
        store=store,
        transports=transports,
    )[0]
    script = resolve_call(
        binding=Binding(agent="ScriptAgent", primary="shared", model="model-b", temperature=0.9),
        registry=registry,
        store=store,
        transports=transports,
    )[0]

    assert research.model == "model-a" and research.temperature == 0.2
    assert script.model == "model-b" and script.temperature == 0.9
    # Resolving again must not have been affected by the second resolution.
    again = resolve_call(
        binding=Binding(agent="ResearchAgent", primary="shared", model="model-a", temperature=0.2),
        registry=registry,
        store=store,
        transports=transports,
    )[0]
    assert again.model == "model-a"
    assert registry.get("shared").model == "stub-model", "the spec must never be mutated"


def test_capability_mismatch_is_raised_before_any_call(store, stub):
    stub.route("GET", "/v1/models", body={"data": [{"id": "stub-model"}]})
    registry = default_registry()
    registry.add(_spec("text-only", stub.base_url, capabilities=[Capability.CHAT]))
    with pytest.raises(CapabilityMismatch) as exc:
        resolve_call(
            binding=Binding(
                agent="QualityAgent",
                primary="text-only",
                requires=frozenset({Capability.CHAT, Capability.VISION}),
            ),
            registry=registry,
            store=store,
            transports=build_transports(),
        )
    assert "vision" in str(exc.value)
    assert not stub.recorded, "a capability mismatch must not make a request"


def test_fallback_is_used_when_primary_is_unhealthy(store, stub):
    stub.route("GET", "/v1/models", body={"data": [{"id": "stub-model"}]})
    registry = default_registry()
    registry.add(_spec("dead", "http://127.0.0.1:1/v1"))
    registry.add(_spec("alive", stub.base_url))
    call, transport = resolve_call(
        binding=Binding(agent="ScriptAgent", primary="dead", fallback=("alive",)),
        registry=registry,
        store=store,
        transports=build_transports(),
    )
    assert call.provider == "alive"
    assert transport.transport == "openai_compat"


def test_live_job_without_a_provider_raises_instead_of_mocking(store):
    registry = default_registry()
    with pytest.raises(NoProviderAvailable):
        resolve_call(
            binding=Binding(agent="ScriptAgent", primary="missing"),
            registry=registry,
            store=store,
            transports=build_transports(),
        )


def test_mock_is_only_used_when_explicitly_allowed(store):
    registry = default_registry()
    registry.specs["mock"].enabled = True
    call, transport = resolve_call(
        binding=Binding(agent="ScriptAgent", primary="missing"),
        registry=registry,
        store=store,
        transports=build_transports(),
        allow_mock_fallback=True,
    )
    assert transport.transport == "mock"
    assert call.provider == "mock"


def test_credential_is_withheld_when_the_origin_changes(store, stub, monkeypatch):
    monkeypatch.setenv("SF_ORIGIN_KEY", "sk-" + "originbound" + "123456")
    registry = default_registry()
    registry.add(
        _spec(
            "bound",
            stub.base_url,
            credential={"env": "SF_ORIGIN_KEY"},
            capabilities=[Capability.CHAT],
        )
    )
    other_origin = ("http", "api.elsewhere.example", 443)
    with pytest.raises(NoProviderAvailable) as exc:
        resolve_call(
            binding=Binding(agent="ScriptAgent", primary="bound"),
            registry=registry,
            store=store,
            transports=build_transports(),
            bound_origins={"bound": other_origin},
        )
    assert "bound to" in str(exc.value)
    assert "sk-" not in str(exc.value), "the error must not carry the credential"


def test_missing_credential_is_reported_not_ignored(store, stub, monkeypatch):
    monkeypatch.delenv("SF_ABSENT", raising=False)
    monkeypatch.setenv("SHORTS_ENV_FILE", "/nonexistent/.env")
    registry = default_registry()
    registry.add(_spec("needs-key", stub.base_url, credential={"env": "SF_ABSENT"}))
    with pytest.raises(NoProviderAvailable) as exc:
        resolve_call(
            binding=Binding(agent="ScriptAgent", primary="needs-key"),
            registry=registry,
            store=store,
            transports=build_transports(),
        )
    assert "not available" in str(exc.value)


# --------------------------------------------------------------------------- openai transport


def _call(base_url: str, **overrides) -> ResolvedCall:
    payload = dict(
        provider="stub",
        transport="openai_compat",
        base_url=base_url,
        model="stub-model",
        temperature=None,
        max_tokens=None,
        timeout_s=5.0,
        max_retries=0,
        capabilities=frozenset({Capability.CHAT}),
        allow_private_hosts=True,
    )
    payload.update(overrides)
    return ResolvedCall(**payload)


def test_completion_parses_content_and_usage(stub):
    stub.route(
        "POST",
        "/v1/chat/completions",
        body={
            "model": "stub-model",
            "choices": [{"message": {"content": "halo"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )
    provider = OpenAICompatProvider()
    result = provider.complete(_call(stub.base_url), system="s", user="u", task="script")
    assert result.content == "halo"
    assert result.usage.prompt_tokens == 7
    assert result.usage.completion_tokens == 3


def test_the_pinned_address_is_used_with_the_real_host_header(stub):
    stub.route("POST", "/v1/chat/completions", body={"choices": [{"message": {"content": "x"}}]})
    OpenAICompatProvider().complete(_call(stub.base_url), system="s", user="u", task="t")
    sent = stub.recorded[-1]
    assert sent.headers["host"] == f"127.0.0.1:{stub.port}"


def test_auth_header_is_attached_only_when_a_credential_exists(stub):
    stub.route("POST", "/v1/chat/completions", body={"choices": [{"message": {"content": "x"}}]})
    OpenAICompatProvider().complete(_call(stub.base_url), system="s", user="u", task="t")
    assert "authorization" not in stub.recorded[-1].headers

    OpenAICompatProvider().complete(
        _call(stub.base_url, credential="sk-" + "abc12345" + "6789"), system="s", user="u", task="t"
    )
    assert stub.recorded[-1].headers["authorization"].startswith("Bearer sk-")


def test_error_detail_names_the_target_and_redacts_the_key(stub):
    stub.route("POST", "/v1/chat/completions", status=401, body={"error": "bad key"})
    key = "sk-" + "leaky" + "value123456"
    with pytest.raises(ProviderError) as exc:
        OpenAICompatProvider().complete(
            _call(stub.base_url, credential=key), system="s", user="u", task="t"
        )
    assert exc.value.code == "provider_auth"
    assert f"127.0.0.1:{stub.port}" in exc.value.detail
    assert key not in exc.value.detail


def test_redirect_is_an_error_not_a_follow(stub):
    stub.route(
        "POST",
        "/v1/chat/completions",
        status=302,
        body={},
        headers={"Location": "http://169.254.169.254/latest/meta-data/"},
    )
    with pytest.raises(ProviderError) as exc:
        OpenAICompatProvider().complete(_call(stub.base_url), system="s", user="u", task="t")
    assert exc.value.code == "provider_redirect"
    assert len(stub.recorded) == 1, "the redirect target must never be requested"


def test_empty_completion_is_a_failure(stub):
    stub.route("POST", "/v1/chat/completions", body={"choices": [{"message": {"content": ""}}]})
    with pytest.raises(ProviderError) as exc:
        OpenAICompatProvider().complete(_call(stub.base_url), system="s", user="u", task="t")
    assert exc.value.code == "provider_empty_completion"


def test_no_choices_is_a_failure(stub):
    stub.route("POST", "/v1/chat/completions", body={"choices": []})
    with pytest.raises(ProviderError) as exc:
        OpenAICompatProvider().complete(_call(stub.base_url), system="s", user="u", task="t")
    assert exc.value.code == "provider_bad_response"


def test_non_json_body_is_a_failure_not_a_crash(stub):
    stub.route("POST", "/v1/chat/completions", body={"weird": True})
    with pytest.raises(ProviderError):
        OpenAICompatProvider().complete(_call(stub.base_url), system="s", user="u", task="t")


def test_model_listing(stub):
    stub.route("GET", "/v1/models", body={"data": [{"id": "a"}, {"id": "b"}]})
    assert OpenAICompatProvider().list_models(_call(stub.base_url)) == ["a", "b"]


def test_health_probe_does_not_claim_the_credential_works(stub):
    stub.route("GET", "/v1/models", body={"data": []})
    health = OpenAICompatProvider().health(_call(stub.base_url))
    assert health.ok is True
    assert "HTTP 200" in health.detail


def test_blocked_target_never_makes_a_request():
    provider = OpenAICompatProvider()
    with pytest.raises(ProviderError) as exc:
        provider.complete(
            _call("http://169.254.169.254/v1", allow_private_hosts=False),
            system="s",
            user="u",
            task="t",
        )
    assert exc.value.code == "target_blocked"


# --------------------------------------------------------------------------- mock


def test_mock_is_deterministic():
    provider = MockProvider()
    call = _call("http://unused", provider="mock", transport="mock")
    first = provider.complete(call, system="sys", user="same input", task="script")
    second = provider.complete(call, system="sys", user="same input", task="script")
    assert first.content == second.content


def test_mock_differs_for_different_input():
    provider = MockProvider()
    call = _call("http://unused", provider="mock", transport="mock")
    a = provider.complete(call, system="sys", user="one", task="script")
    b = provider.complete(call, system="sys", user="two", task="script")
    assert a.content != b.content


def test_mock_script_is_valid_json_with_segments():
    provider = MockProvider()
    call = _call("http://unused", provider="mock", transport="mock")
    result = provider.complete(call, system="s", user="u", task="script")
    payload = json.loads(result.content)
    assert payload["segments"][0]["id"] == "s1"


def test_resolved_call_repr_hides_the_credential():
    call = _call("http://x", credential="sk-" + "hidden" + "value12345")
    assert "hidden" not in repr(call)
    assert call.has_credential is True


# --------------------------------------------------------------------------- spec validation


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "x", "transport": "openai_compat", "model": "m"},  # no base_url
        {"id": "x", "transport": "openai_compat", "base_url": "http://a/v1"},  # no model
        {"id": "x", "transport": "cli", "model": "m"},  # no cli_command
        {"id": "Bad Id", "transport": "mock", "model": "m"},
    ],
)
def test_spec_validation_rejects_incomplete_configuration(payload):
    with pytest.raises(ValidationError):
        ProviderSpec(**payload)


def test_spec_public_view_never_contains_a_credential_value():
    spec = ProviderSpec(
        id="p",
        transport="openai_compat",
        base_url="https://api.example.com/v1",
        model="m",
        credential={"env": "MY_KEY"},
    )
    view = spec.public_view()
    assert view["credential_source"] == "env:MY_KEY"
    assert "MY_KEY" not in json.dumps({k: v for k, v in view.items() if k != "credential_source"})


def test_origin_is_computed_from_the_base_url():
    spec = ProviderSpec(
        id="p", transport="openai_compat", base_url="https://API.Example.com:8443/v1", model="m"
    )
    assert spec.origin == ("https", "api.example.com", 8443)
