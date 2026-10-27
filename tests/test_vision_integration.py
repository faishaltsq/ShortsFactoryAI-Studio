"""Vision through the real resolver and the real HTTP client, against a loopback stub.

What was stubbed before this file:

- `tests/test_provider_vision.py` drove each transport's `complete_vision` against a real
  `StubServer` over real `PinnedHTTP` — so the wire format *was* exercised — but it hand-built a
  `ResolvedCall` and never touched `ProviderSpec`, `resolve_call`, the capability filter, or the
  credential path. A transport that mangled the payload, or a resolver that let a text-only
  provider through, would not have been caught.
- `tests/test_vision_agent.py` used an in-process `_StubProvider` that bypasses HTTP entirely. That
  is the right unit test for the decision logic and proves nothing about the wire.
- Nothing drove a *job* through the stages with a vision provider, so `visual.status == "passed"`
  had never been produced by the pipeline.

These tests close that gap using only loopback. No network, no credential, no real model.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from packages.core.providers.base import (
    Capability,
    CapabilityMismatch,
    ProviderError,
    VisionImage,
)
from packages.core.providers.registry import ProviderRegistry, ProviderSpec
from packages.core.providers.resolve import Binding, resolve_call
from packages.core.security.secretstore import SecretStore
from tests.stub_server import StubServer

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
    b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 64


def _image(data: bytes = PNG, media_type: str = "image/png") -> VisionImage:
    return VisionImage(data=data, media_type=media_type, label="contact-sheet")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _registry(spec: ProviderSpec) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.add(spec)
    return registry


def _resolve(registry: ProviderRegistry, provider_id: str, *, transports: dict):
    return resolve_call(
        binding=Binding(
            agent="QualityAgent",
            primary=provider_id,
            requires=frozenset({Capability.CHAT, Capability.VISION}),
        ),
        registry=registry,
        store=SecretStore.__new__(SecretStore),
        transports=transports,
    )


# -- OpenAI-compatible -------------------------------------------------------------------------


def test_openai_vision_resolves_and_sends_a_data_uri_with_the_exact_bytes():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "vision-1"}]})
        server.route(
            "POST",
            "/v1/chat/completions",
            body={
                "choices": [{"message": {"content": '{"status":"passed"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                "model": "vision-1",
            },
        )
        spec = ProviderSpec(
            id="vision-a",
            transport="openai_compat",
            base_url=server.base_url,
            model="vision-1",
            capabilities=[Capability.CHAT, Capability.VISION],
            allow_private_hosts=True,
        )
        call, transport = _resolve(
            _registry(spec), "vision-a", transports={"openai_compat": OpenAICompatProvider()}
        )
        result = transport.complete_vision(
            call, system="s", user="u", task="vision", images=[_image()]
        )
        body = server.recorded[-1].body

    parts = body["messages"][-1]["content"]
    url = next(p for p in parts if p.get("type") == "image_url")["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    sent = base64.b64decode(url.split(",", 1)[1])
    assert _sha(sent) == _sha(PNG), "the transport must not alter the image bytes"
    assert result.content == '{"status":"passed"}'
    assert call.provider == "vision-a", "the resolved call carries the operator's provider id"


def test_openai_vision_preserves_jpeg_bytes_too():
    """A re-encode would still decode; the digest is the only check that catches it."""
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "m"}]})
        server.route("POST", "/v1/chat/completions",
                     body={"choices": [{"message": {"content": "{}"}}], "usage": {}})
        spec = ProviderSpec(
            id="vision-jpeg", transport="openai_compat", base_url=server.base_url,
            model="m", capabilities=[Capability.CHAT, Capability.VISION], allow_private_hosts=True,
        )
        call, transport = _resolve(
            _registry(spec), "vision-jpeg", transports={"openai_compat": OpenAICompatProvider()}
        )
        transport.complete_vision(
            call, system="s", user="u", task="vision",
            images=[_image(JPEG, "image/jpeg")],
        )
        body = server.recorded[-1].body

    url = next(
        p for p in body["messages"][-1]["content"] if p.get("type") == "image_url"
    )["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert _sha(base64.b64decode(url.split(",", 1)[1])) == _sha(JPEG)


# -- Anthropic ---------------------------------------------------------------------------------


def test_anthropic_vision_resolves_and_sends_a_base64_block_with_the_exact_bytes():
    from packages.core.providers.anthropic import AnthropicProvider

    with StubServer() as server:
        server.route(
            "POST",
            "/v1/messages",
            body={"content": [{"type": "text", "text": "{}"}],
                  "usage": {"input_tokens": 1, "output_tokens": 1}},
        )
        spec = ProviderSpec(
            id="vision-claude",
            transport="anthropic",
            base_url=server.base_url.removesuffix("/v1"),
            model="claude-vision",
            capabilities=[Capability.CHAT, Capability.VISION],
            allow_private_hosts=True,
        )
        call, transport = _resolve(
            _registry(spec), "vision-claude", transports={"anthropic": AnthropicProvider()}
        )
        transport.complete_vision(call, system="s", user="u", task="vision", images=[_image()])
        body = server.recorded[-1].body

    block = next(b for b in body["messages"][-1]["content"] if b.get("type") == "image")
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "image/png"
    assert _sha(base64.b64decode(block["source"]["data"])) == _sha(PNG)


# -- Ollama ------------------------------------------------------------------------------------


def test_ollama_vision_resolves_and_sends_bare_base64_with_the_exact_bytes():
    from packages.core.providers.ollama import OllamaProvider

    with StubServer() as server:
        server.route("GET", "/api/tags", body={"models": [{"name": "llava"}]})
        server.route(
            "POST",
            "/api/chat",
            body={"message": {"content": "{}"}, "prompt_eval_count": 1, "eval_count": 1},
        )
        spec = ProviderSpec(
            id="vision-ollama",
            transport="ollama",
            base_url=server.base_url.removesuffix("/v1"),
            model="llava",
            capabilities=[Capability.CHAT, Capability.VISION],
            allow_private_hosts=True,
        )
        call, transport = _resolve(
            _registry(spec), "vision-ollama", transports={"ollama": OllamaProvider()}
        )
        transport.complete_vision(call, system="s", user="u", task="vision", images=[_image()])
        body = server.recorded[-1].body

    encoded = body["messages"][-1]["images"][0]
    assert not encoded.startswith("data:"), "ollama wants bare base64, not a data URI"
    assert _sha(base64.b64decode(encoded)) == _sha(PNG)


# -- the gate and the error path ---------------------------------------------------------------


def test_a_text_only_spec_is_refused_before_any_request_reaches_the_server():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        spec = ProviderSpec(
            id="text-only",
            transport="openai_compat",
            base_url=server.base_url,
            model="text-1",
            capabilities=[Capability.CHAT],
            allow_private_hosts=True,
        )
        with pytest.raises(CapabilityMismatch) as exc:
            _resolve(_registry(spec), "text-only", transports={"openai_compat": OpenAICompatProvider()})
        assert "vision" in str(exc.value)
        assert server.recorded == [], "the capability gate must fire before the socket is opened"


def test_a_401_carries_no_credential_in_its_detail():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    secret = "sk-SENTINEL-vision-loopback-42"
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "m"}]})
        server.route("POST", "/v1/chat/completions", status=401, body={"error": f"bad key {secret}"})
        spec = ProviderSpec(
            id="vision-auth",
            transport="openai_compat",
            base_url=server.base_url,
            model="m",
            capabilities=[Capability.CHAT, Capability.VISION],
            allow_private_hosts=True,
        )
        call, transport = _resolve(
            _registry(spec), "vision-auth", transports={"openai_compat": OpenAICompatProvider()}
        )
        call = type(call)(
            provider=call.provider, transport=call.transport, base_url=call.base_url,
            model=call.model, temperature=call.temperature, max_tokens=call.max_tokens,
            timeout_s=call.timeout_s, max_retries=0, capabilities=call.capabilities,
            allow_private_hosts=call.allow_private_hosts, credential=secret,
        )
        with pytest.raises(ProviderError) as exc:
            transport.complete_vision(call, system="s", user="u", task="vision", images=[_image()])

    assert secret not in str(exc.value)
    assert exc.value.code == "provider_auth"


def test_a_vision_call_is_recorded_in_the_usage_log(tmp_path):
    """A vision call can cost an order of magnitude more than a text call; it must not escape."""
    from packages.core.providers.openai_compat import OpenAICompatProvider
    from packages.core.providers.usage import RecordingProvider, UsageTracker

    tracker = UsageTracker(tmp_path / "usage.db")
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "vision-1"}]})
        server.route(
            "POST",
            "/v1/chat/completions",
            body={"choices": [{"message": {"content": "{}"}}],
                  "usage": {"prompt_tokens": 40, "completion_tokens": 6}, "model": "vision-1"},
        )
        spec = ProviderSpec(
            id="vision-usage", transport="openai_compat", base_url=server.base_url,
            model="vision-1", capabilities=[Capability.CHAT, Capability.VISION],
            allow_private_hosts=True,
        )
        call, transport = _resolve(
            _registry(spec), "vision-usage", transports={"openai_compat": OpenAICompatProvider()}
        )
        recorder = RecordingProvider(
            transport, tracker=tracker, agent="QualityAgent", job_id="job-1"
        )
        recorder.complete_vision(call, system="s", user="u", task="vision", images=[_image()])

    rows = tracker.for_job("job-1")
    assert len(rows) == 1
    assert rows[0]["agent"] == "QualityAgent"
    assert rows[0]["provider"] == "vision-usage"
    assert rows[0]["prompt_tokens"] == 40
