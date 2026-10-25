"""Ollama local transport. Requires ``allow_private_hosts`` — that is the point."""

from __future__ import annotations

import json
from typing import Any

from ..security.redact import redact
from .base import Health, ProviderError, ProviderResult, ResolvedCall, Usage, now_ms
from .http_base import PinnedHTTP, health_from_response


class OllamaProvider:
    name = "ollama"
    transport = "ollama"

    def __init__(self, http: PinnedHTTP | None = None) -> None:
        self._http = http

    def _client(self, call: ResolvedCall) -> PinnedHTTP:
        return self._http or PinnedHTTP(timeout_s=call.timeout_s, max_retries=call.max_retries)

    def health(self, call: ResolvedCall) -> Health:
        started = now_ms()
        try:
            response = self._client(call).request(
                "GET",
                f"{call.base_url}/api/tags",
                allow_private_hosts=call.allow_private_hosts,
                provider=call.provider,
            )
        except ProviderError as exc:
            return Health.down(redact(exc.detail))
        return health_from_response(response, started)

    def list_models(self, call: ResolvedCall) -> list[str] | None:
        try:
            response = self._client(call).request(
                "GET",
                f"{call.base_url}/api/tags",
                allow_private_hosts=call.allow_private_hosts,
                provider=call.provider,
            )
        except ProviderError:
            return None
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return None
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return None
        return [str(m.get("name")) for m in models if isinstance(m, dict) and m.get("name")]

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
        options: dict[str, Any] = {}
        if call.temperature is not None:
            options["temperature"] = call.temperature
        if call.max_tokens is not None:
            options["num_predict"] = call.max_tokens
        if options:
            body["options"] = options
        if call.params.get("json_mode"):
            body["format"] = "json"

        started = now_ms()
        response = self._client(call).request(
            "POST",
            f"{call.base_url}/api/chat",
            json=body,
            allow_private_hosts=call.allow_private_hosts,
            provider=call.provider,
        )
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(
                "provider_bad_response",
                f"response was not JSON: {redact(response.text[:200])}",
                provider=call.provider,
            ) from exc

        message = payload.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError(
                "provider_empty_completion",
                "response contained no message content",
                provider=call.provider,
            )
        return ProviderResult(
            content=content,
            provider=call.provider,
            model=str(payload.get("model") or call.model),
            usage=Usage(
                prompt_tokens=int(payload.get("prompt_eval_count") or 0),
                completion_tokens=int(payload.get("eval_count") or 0),
            ),
            elapsed_ms=max(0, now_ms() - started),
            raw={"done_reason": payload.get("done_reason")},
        )
