"""Anthropic native transport.

The differences that matter: ``system`` is a top-level field rather than a message, auth is
``x-api-key`` rather than a bearer token, and a version header is mandatory.
"""

from __future__ import annotations

import json
from typing import Any

from ..security.redact import redact
from .base import Health, ProviderError, ProviderResult, ResolvedCall, Usage, now_ms
from .http_base import PinnedHTTP, health_from_response

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"
    transport = "anthropic"

    def __init__(self, http: PinnedHTTP | None = None) -> None:
        self._http = http

    def _client(self, call: ResolvedCall) -> PinnedHTTP:
        return self._http or PinnedHTTP(timeout_s=call.timeout_s, max_retries=call.max_retries)

    def _headers(self, call: ResolvedCall) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if call.credential:
            headers["x-api-key"] = call.credential
        return headers

    def health(self, call: ResolvedCall) -> Health:
        """Anthropic has no free models endpoint; a 1-token message is the honest probe."""
        started = now_ms()
        try:
            response = self._client(call).request(
                "POST",
                f"{call.base_url}/v1/messages",
                headers=self._headers(call),
                json={
                    "model": call.model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                allow_private_hosts=call.allow_private_hosts,
                secrets=(call.credential,),
                provider=call.provider,
            )
        except ProviderError as exc:
            return Health.down(redact(exc.detail, secrets=(call.credential,)))
        return health_from_response(response, started)

    def list_models(self, call: ResolvedCall) -> list[str] | None:
        try:
            response = self._client(call).request(
                "GET",
                f"{call.base_url}/v1/models",
                headers=self._headers(call),
                allow_private_hosts=call.allow_private_hosts,
                secrets=(call.credential,),
                provider=call.provider,
            )
        except ProviderError:
            return None
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return None
        return [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")]

    def complete(
        self, call: ResolvedCall, *, system: str, user: str, task: str
    ) -> ProviderResult:
        body: dict[str, Any] = {
            "model": call.model,
            "max_tokens": call.max_tokens or 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if call.temperature is not None:
            body["temperature"] = call.temperature

        started = now_ms()
        response = self._client(call).request(
            "POST",
            f"{call.base_url}/v1/messages",
            headers=self._headers(call),
            json=body,
            allow_private_hosts=call.allow_private_hosts,
            secrets=(call.credential,),
            provider=call.provider,
        )
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(
                "provider_bad_response",
                f"response was not JSON: {redact(response.text[:200], secrets=(call.credential,))}",
                provider=call.provider,
            ) from exc

        blocks = payload.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text.strip():
            raise ProviderError(
                "provider_empty_completion",
                "response contained no text block",
                provider=call.provider,
            )
        raw_usage = payload.get("usage") or {}
        return ProviderResult(
            content=text,
            provider=call.provider,
            model=str(payload.get("model") or call.model),
            usage=Usage(
                prompt_tokens=int(raw_usage.get("input_tokens") or 0),
                completion_tokens=int(raw_usage.get("output_tokens") or 0),
            ),
            elapsed_ms=max(0, now_ms() - started),
            raw={"stop_reason": payload.get("stop_reason")},
        )
