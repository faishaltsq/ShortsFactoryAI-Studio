"""OpenAI-compatible transport.

Covers OpenAI, DeepSeek, Groq, OpenRouter, llama.cpp, LM Studio, vLLM, and local routers — anything
that speaks ``POST {base}/chat/completions``. There is deliberately no vendor name in this module:
naming it after one vendor is how an error message ends up blaming a service that is not in the
request path.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..security.redact import redact
from .base import (
    Capability,
    Health,
    ProviderError,
    ProviderResult,
    ResolvedCall,
    Usage,
    VisionImage,
    VisionUnsupported,
    now_ms,
)
from .http_base import PinnedHTTP, ResumeInfo, health_from_response


def _as_response(response: httpx.Response | ResumeInfo) -> httpx.Response:
    """Narrow the transport union; no call here enables ``allow_resume_308``."""
    if isinstance(response, httpx.Response):
        return response
    raise ProviderError(
        "provider_bad_response",
        f"unexpected 308 resume response for a non-upload request (status {response.status_code})",
    )


class OpenAICompatProvider:
    name = "openai_compat"
    transport = "openai_compat"

    def __init__(self, http: PinnedHTTP | None = None) -> None:
        self._http = http

    def _client(self, call: ResolvedCall) -> PinnedHTTP:
        return self._http or PinnedHTTP(timeout_s=call.timeout_s, max_retries=call.max_retries)

    def _headers(self, call: ResolvedCall) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if call.credential:
            headers["Authorization"] = f"Bearer {call.credential}"
        return headers

    def health(self, call: ResolvedCall) -> Health:
        """Cheap reachability probe.

        ``/models`` frequently answers 200 without authentication, so this proves the endpoint is
        there — not that the credential works or that the model exists. The UI says so, and the
        first real completion is what proves the rest.
        """
        started = now_ms()
        try:
            response = self._client(call).request(
                "GET",
                f"{call.base_url}/models",
                headers=self._headers(call),
                allow_private_hosts=call.allow_private_hosts,
                secrets=(call.credential,),
                provider=call.provider,
            )
        except ProviderError as exc:
            return Health.down(redact(exc.detail, secrets=(call.credential,)))
        return health_from_response(_as_response(response), started)

    def list_models(self, call: ResolvedCall) -> list[str] | None:
        try:
            response = self._client(call).request(
                "GET",
                f"{call.base_url}/models",
                headers=self._headers(call),
                allow_private_hosts=call.allow_private_hosts,
                secrets=(call.credential,),
                provider=call.provider,
            )
        except ProviderError:
            return None
        try:
            payload = _as_response(response).json()
        except (json.JSONDecodeError, ValueError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return None
        return [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")]

    def complete_vision(
        self,
        call: ResolvedCall,
        *,
        system: str,
        user: str,
        task: str,
        images: list[VisionImage],
    ) -> ProviderResult:
        """One chat completion carrying image parts.

        The OpenAI-compatible shape is ``content: [{"type": "text"}, {"type": "image_url"}]`` with
        a data URI. ``detail: "high"`` is set because a contact sheet is 6 tiles: at ``auto`` a
        provider may downscale it until the tiles are unreadable, and then a confident verdict
        describes nothing.
        """
        if Capability.VISION not in call.capabilities:
            raise VisionUnsupported(f"{call.provider or 'provider'} (vision not declared)")
        if not images:
            raise ValueError("complete_vision requires at least one image")

        parts: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for image in images:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image.data_uri(), "detail": "high"},
                }
            )
        body: dict[str, Any] = {
            "model": call.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": parts},
            ],
        }
        if call.temperature is not None:
            body["temperature"] = call.temperature
        if call.max_tokens is not None:
            body["max_tokens"] = call.max_tokens

        started = now_ms()
        response = self._client(call).request(
            "POST",
            f"{call.base_url}/chat/completions",
            headers=self._headers(call),
            json=body,
            allow_private_hosts=call.allow_private_hosts,
            secrets=(call.credential,),
            provider=call.provider,
        )
        try:
            payload = _as_response(response).json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(
                "provider_bad_response",
                f"response was not JSON: {redact(_as_response(response).text[:200], secrets=(call.credential,))}",
                provider=call.provider,
            ) from exc

        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError(
                "provider_bad_response", "response contained no choices", provider=call.provider
            )
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if isinstance(reasoning, str) and reasoning.strip():
                content = reasoning
            else:
                raise ProviderError(
                    "provider_empty_completion",
                    f"model {payload.get('model', call.model)!r} returned empty content",
                    provider=call.provider,
                )
        raw_usage = payload.get("usage") or {}
        return ProviderResult(
            content=content,
            provider=call.provider,
            model=str(payload.get("model") or call.model),
            usage=Usage(
                prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
                completion_tokens=int(raw_usage.get("completion_tokens") or 0),
            ),
            elapsed_ms=max(0, now_ms() - started),
            raw={"finish_reason": choices[0].get("finish_reason"), "images": len(images)},
        )

    def complete(
        self, call: ResolvedCall, *, system: str, user: str, task: str
    ) -> ProviderResult:
        body: dict[str, Any] = {
            "model": call.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if call.temperature is not None:
            body["temperature"] = call.temperature
        if call.max_tokens is not None:
            body["max_tokens"] = call.max_tokens
        if Capability.JSON_SCHEMA in call.capabilities and call.params.get("json_mode"):
            body["response_format"] = {"type": "json_object"}
        # Only allow-listed passthrough keys: a free-form params dict is how an operator
        # accidentally overrides the model or injects a tool definition.
        for key in ("top_p", "stop", "presence_penalty", "frequency_penalty", "seed"):
            if key in call.params:
                body[key] = call.params[key]

        started = now_ms()
        response = self._client(call).request(
            "POST",
            f"{call.base_url}/chat/completions",
            headers=self._headers(call),
            json=body,
            allow_private_hosts=call.allow_private_hosts,
            secrets=(call.credential,),
            provider=call.provider,
        )
        try:
            payload = _as_response(response).json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(
                "provider_bad_response",
                f"response was not JSON: {redact(_as_response(response).text[:200], secrets=(call.credential,))}",
                provider=call.provider,
            ) from exc

        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError(
                "provider_bad_response",
                "response contained no choices",
                provider=call.provider,
            )
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if isinstance(reasoning, str) and reasoning.strip():
                content = reasoning
            else:
                raise ProviderError(
                    "provider_empty_completion",
                    f"model {payload.get('model', call.model)!r} returned empty content",
                    provider=call.provider,
                )
        raw_usage = payload.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
            completion_tokens=int(raw_usage.get("completion_tokens") or 0),
        )
        return ProviderResult(
            content=content,
            provider=call.provider,
            model=str(payload.get("model") or call.model),
            usage=usage,
            elapsed_ms=max(0, now_ms() - started),
            raw={"finish_reason": choices[0].get("finish_reason")},
        )
