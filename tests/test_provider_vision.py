"""The vision boundary: bytes in, a declared capability, no silent pass, no leak.

Three properties are under test and each one has a specific way to be faked:

1. **Capability before the call.** A transport that cannot see must never be asked to. The mock
   declares no ``VISION``, so a job that reaches visual QC with only mock configured gets
   ``skipped_no_vision_provider`` — not a canned ``{"status": "passed"}``.
2. **The image is actually in the request.** Every transport is asserted against the recorded
   request body, per API, because the three formats differ: ``image_url`` with a data URI for
   OpenAI-compatible, a base64 ``image`` content block for Anthropic, a bare ``images`` array for
   Ollama.
3. **The bytes never leave through a side channel.** Not in a log line, not in an artifact, not
   in ``ProviderResult.raw``.
"""

from __future__ import annotations

import base64
import json

import pytest

from packages.core.providers.base import (
    Capability,
    CapabilityMismatch,
    ProviderError,
    ResolvedCall,
    VisionImage,
    VisionUnsupported,
)
from packages.core.providers.mock import MockProvider
from packages.core.providers.registry import ProviderSpec
from tests.stub_server import StubServer

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _call(**overrides) -> ResolvedCall:
    payload = {
        "provider": "stub",
        "transport": "openai_compat",
        "base_url": "http://127.0.0.1:1/v1",
        "model": "vision-model",
        "temperature": None,
        "max_tokens": 512,
        "timeout_s": 5.0,
        "max_retries": 0,
        "capabilities": frozenset({Capability.CHAT, Capability.VISION}),
        "allow_private_hosts": True,
    }
    payload.update(overrides)
    return ResolvedCall(**payload)


def _image(**overrides) -> VisionImage:
    payload = {"data": PNG, "media_type": "image/png", "label": "contact-sheet"}
    payload.update(overrides)
    return VisionImage(**payload)


# -- VisionImage -------------------------------------------------------------------------------


def test_vision_image_accepts_a_png():
    image = _image()
    assert image.media_type == "image/png"
    assert image.byte_size == len(PNG)


def test_vision_image_rejects_an_unsupported_media_type():
    with pytest.raises(ValueError, match="media_type"):
        _image(media_type="image/tiff")


def test_vision_image_rejects_empty_bytes():
    with pytest.raises(ValueError, match="empty"):
        _image(data=b"")


def test_vision_image_rejects_an_oversized_payload():
    with pytest.raises(ValueError, match="too large"):
        _image(data=b"x" * (5 * 1024 * 1024 + 1))


def test_vision_image_rejects_bytes_that_are_not_the_declared_type():
    """A JPEG declared as PNG is a lie the provider will reject with a worse message."""
    with pytest.raises(ValueError, match="does not look like"):
        _image(data=b"\xff\xd8\xff\xe0" + b"\x00" * 32, media_type="image/png")


def test_vision_image_data_uri_encodes_the_bytes():
    uri = _image().data_uri()
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == PNG


def test_vision_image_repr_never_contains_the_bytes():
    assert "iVBOR" not in repr(_image())
    assert "data:" not in repr(_image())


def test_vision_image_to_json_has_no_payload():
    payload = _image().to_json()
    assert payload == {"media_type": "image/png", "bytes": len(PNG), "label": "contact-sheet"}


# -- capability gate ---------------------------------------------------------------------------


def test_the_mock_transport_cannot_declare_vision():
    with pytest.raises(ValueError, match="vision"):
        ProviderSpec(
            id="mock",
            transport="mock",
            capabilities=[Capability.CHAT, Capability.VISION],
        )


def test_the_cli_transport_cannot_declare_vision():
    with pytest.raises(ValueError, match="vision"):
        ProviderSpec(
            id="cli",
            transport="cli",
            capabilities=[Capability.CHAT, Capability.VISION],
        )


def test_an_http_transport_may_declare_vision():
    spec = ProviderSpec(
        id="vision-a",
        transport="openai_compat",
        base_url="https://api.example.com/v1",
        model="gpt-4o",
        capabilities=[Capability.CHAT, Capability.VISION],
    )
    assert Capability.VISION in spec.capabilities


def test_the_mock_transport_refuses_a_vision_call_explicitly():
    with pytest.raises(VisionUnsupported, match="vision"):
        MockProvider().complete_vision(
            _call(capabilities=frozenset({Capability.VISION})),
            system="s",
            user="u",
            task="vision",
            images=[_image()],
        )


def test_a_vision_binding_with_no_vision_provider_fails_before_any_call():
    from packages.core.providers.registry import ProviderRegistry
    from packages.core.providers.resolve import Binding, resolve_call
    from packages.core.security.secretstore import SecretStore

    registry = ProviderRegistry()
    registry.add(
        ProviderSpec(
            id="text-only",
            transport="openai_compat",
            base_url="https://x.example/v1",
            model="text-only-1",
        )
    )
    with pytest.raises(CapabilityMismatch) as exc:
        resolve_call(
            binding=Binding(
                agent="QualityAgent",
                primary="text-only",
                requires=frozenset({Capability.CHAT, Capability.VISION}),
            ),
            registry=registry,
            store=SecretStore.__new__(SecretStore),
            transports={},
            allow_mock_fallback=True,
        )
    assert "vision" in str(exc.value)


# -- OpenAI-compatible -------------------------------------------------------------------------


def _openai_response(text: str = '{"status": "passed"}') -> dict:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        "model": "vision-model",
    }


def test_openai_vision_puts_a_data_uri_image_in_the_request():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        server.route("POST", "/v1/chat/completions", body=_openai_response())
        call = _call(base_url=server.base_url)
        OpenAICompatProvider().complete_vision(
            call, system="s", user="u", task="vision", images=[_image()]
        )
        body = server.recorded[-1].body

    parts = body["messages"][-1]["content"]
    assert isinstance(parts, list)
    image_parts = [part for part in parts if part.get("type") == "image_url"]
    assert len(image_parts) == 1
    url = image_parts[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG
    assert any(part.get("type") == "text" and part["text"] == "u" for part in parts)


def test_openai_vision_returns_the_text_and_the_usage():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        server.route("POST", "/v1/chat/completions", body=_openai_response('{"status":"passed"}'))
        result = OpenAICompatProvider().complete_vision(
            _call(base_url=server.base_url), system="s", user="u", task="vision", images=[_image()]
        )
    assert result.content == '{"status":"passed"}'
    assert result.usage.prompt_tokens == 11
    assert result.usage.completion_tokens == 7


def test_openai_vision_never_puts_the_bytes_in_the_result():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        server.route("POST", "/v1/chat/completions", body=_openai_response())
        result = OpenAICompatProvider().complete_vision(
            _call(base_url=server.base_url), system="s", user="u", task="vision", images=[_image()]
        )
    blob = json.dumps({"content": result.content, "raw": result.raw})
    assert "iVBOR" not in blob
    assert "base64" not in blob


def test_openai_vision_refuses_when_the_provider_did_not_declare_vision():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        call = _call(base_url=server.base_url, capabilities=frozenset({Capability.CHAT}))
        with pytest.raises(VisionUnsupported, match="vision"):
            OpenAICompatProvider().complete_vision(
                call, system="s", user="u", task="vision", images=[_image()]
            )
        assert server.recorded == [], "no request may be sent when the capability is absent"


def test_openai_vision_rejects_an_empty_image_list():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        with pytest.raises(ValueError, match="at least one image"):
            OpenAICompatProvider().complete_vision(
                _call(base_url=server.base_url), system="s", user="u", task="vision", images=[]
            )
        assert server.recorded == []


# -- Anthropic ---------------------------------------------------------------------------------


def _anthropic_response(text: str = '{"status": "passed"}') -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 9, "output_tokens": 5},
        "model": "claude-vision",
        "stop_reason": "end_turn",
    }


def test_anthropic_vision_uses_an_image_content_block():
    from packages.core.providers.anthropic import AnthropicProvider

    with StubServer() as server:
        server.route("POST", "/v1/messages", body=_anthropic_response())
        call = _call(
            base_url=server.base_url.removesuffix("/v1"),
            transport="anthropic",
            provider="stub-anthropic",
        )
        AnthropicProvider().complete_vision(
            call, system="s", user="u", task="vision", images=[_image()]
        )
        body = server.recorded[-1].body

    blocks = body["messages"][-1]["content"]
    images = [block for block in blocks if block.get("type") == "image"]
    assert len(images) == 1
    assert images[0]["source"]["type"] == "base64"
    assert images[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(images[0]["source"]["data"]) == PNG
    assert body["system"] == "s"


def test_anthropic_vision_rejects_an_unsupported_type_before_sending():
    from packages.core.providers.anthropic import AnthropicProvider

    with StubServer() as server:
        call = _call(base_url=server.base_url, transport="anthropic")
        with pytest.raises(ValueError, match="media_type"):
            AnthropicProvider().complete_vision(
                call, system="s", user="u", task="vision",
                images=[_image(media_type="image/webp")],
            )
        assert server.recorded == []


# -- Ollama ------------------------------------------------------------------------------------


def _ollama_response(text: str = '{"status": "passed"}') -> dict:
    return {
        "message": {"content": text},
        "prompt_eval_count": 4,
        "eval_count": 3,
        "model": "llava",
        "done_reason": "stop",
    }


def test_ollama_vision_sends_bare_base64_in_an_images_array():
    from packages.core.providers.ollama import OllamaProvider

    with StubServer() as server:
        server.route("POST", "/api/chat", body=_ollama_response())
        call = _call(base_url=server.base_url.replace("/v1", ""), transport="ollama")
        OllamaProvider().complete_vision(
            call, system="s", user="u", task="vision", images=[_image()]
        )
        body = server.recorded[-1].body

    images = body["messages"][-1]["images"]
    assert images == [base64.b64encode(PNG).decode("ascii")]


# -- malformed responses -----------------------------------------------------------------------


def test_a_vision_response_that_is_not_json_text_is_still_returned_verbatim():
    """Parsing is the caller's job. A transport that silently repaired the model's answer would
    hide the failure the repair prompt exists to fix."""
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        server.route("POST", "/v1/chat/completions", body=_openai_response("not json at all"))
        result = OpenAICompatProvider().complete_vision(
            _call(base_url=server.base_url), system="s", user="u", task="vision", images=[_image()]
        )
    assert result.content == "not json at all"


def test_an_empty_vision_completion_is_a_provider_error():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    with StubServer() as server:
        server.route("POST", "/v1/chat/completions", body=_openai_response(""))
        with pytest.raises(ProviderError, match="empty"):
            OpenAICompatProvider().complete_vision(
                _call(base_url=server.base_url), system="s", user="u", task="vision", images=[_image()]
            )


def test_a_credential_never_appears_in_a_vision_error():
    from packages.core.providers.openai_compat import OpenAICompatProvider

    secret = "sk-SENTINEL-vision-1"
    with StubServer() as server:
        server.route("POST", "/v1/chat/completions", status=401, body={"error": f"bad key {secret}"})
        call = _call(base_url=server.base_url, credential=secret)
        with pytest.raises(ProviderError) as exc:
            OpenAICompatProvider().complete_vision(
                call, system="s", user="u", task="vision", images=[_image()]
            )
    assert secret not in str(exc.value)
