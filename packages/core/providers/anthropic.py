"""Anthropic native transport.

The differences that matter: ``system`` is a top-level field rather than a message, auth is
``x-api-key`` rather than a bearer token, and a version header is mandatory.
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

ANTHROPIC_VERSION = "2023-06-01"


def _as_response(response: httpx.Response | ResumeInfo) -> httpx.Response:
    """Narrow the transport union; no call here enables ``allow_resume_308``."""
    if isinstance(response, httpx.Response):
        return response
    raise ProviderError(
        "provider_bad_response",
        f"unexpected 308 resume response for a non-upload request (status {response.status_code})",
    )

#: Anthropic accepts these two only. webp is in the docs for some models; rejecting it here
#: keeps the failure at the boundary instead of at the provider.
ANTHROPIC_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


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
        """Probe the existing models endpoint, never an unjournaled paid message."""
        started = now_ms()
        try:
            response = self._client(call).request(
                "GET",
                f"{call.base_url}/v1/models",
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
                f"{call.base_url}/v1/models",
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
        """One message with base64 ``image`` blocks.

        Anthropic's shape is ``{"type": "image", "source": {"type": "base64", ...}}`` — not a data
        URI. Sending the OpenAI shape here produces a 400 that names no field, so the formats are
        kept visibly different rather than shared behind a helper that hides which one is wrong.
        """
        if Capability.VISION not in call.capabilities:
            raise VisionUnsupported(f"{call.provider or 'provider'} (vision not declared)")
        if not images:
            raise ValueError("complete_vision requires at least one image")
        for image in images:
            if image.media_type not in ANTHROPIC_MEDIA_TYPES:
                raise ValueError(
                    f"anthropic does not accept media_type {image.media_type!r}"
                )

        blocks: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": image.base64(),
                },
            }
            for image in images
        ]
        blocks.append({"type": "text", "text": user})
        body: dict[str, Any] = {
            "model": call.model,
            "max_tokens": call.max_tokens or 4096,
            "system": system,
            "messages": [{"role": "user", "content": blocks}],
        }
        if call.temperature is not None:
            body["temperature"] = call.temperature

        started = now_ms()
        response = self._client(call).request(
            "POST",
            f"{call.base_url}/v1/messages",
            retry_safe=False,
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

        blocks_out = payload.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks_out
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
            usage=Usage.from_provider(raw_usage.get("input_tokens"), raw_usage.get("output_tokens")),
            elapsed_ms=max(0, now_ms() - started),
            raw={"stop_reason": payload.get("stop_reason"), "images": len(images)},
        )

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
            retry_safe=False,
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
            usage=Usage.from_provider(raw_usage.get("input_tokens"), raw_usage.get("output_tokens")),
            elapsed_ms=max(0, now_ms() - started),
            raw={"stop_reason": payload.get("stop_reason")},
        )
