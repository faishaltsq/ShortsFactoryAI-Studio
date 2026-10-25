"""Shared HTTP behaviour: pinning, redirect refusal, bounded retries, honest errors.

Every HTTP transport goes through :class:`PinnedHTTP` so that three properties hold everywhere and
are tested once:

1. **The connection goes to the address the policy validated**, not to whatever the hostname
   resolves to a moment later. The URL is rebuilt against the pinned IP, the ``Host`` header
   carries the real name, and TLS keeps the real SNI. A DNS-rebinding attacker who answers
   differently on the second query never gets a second query.
2. **Redirects are errors.** Following one re-opens the SSRF question with a target the policy
   never saw.
3. **Error detail is useful and redacted.** ``[429] usage limit reached, reset after 18m`` is
   surfaced; ``Authorization: Bearer ...`` is not.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..security.netguard import BlockedTarget, TargetPolicy, resolve_and_pin
from ..security.redact import redact
from .base import Health, ProviderError, now_ms

#: Transport-level retry on these status codes. 4xx other than 408/429 is not retried: the request
#: is wrong, and repeating it just costs money.
RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _pinned_url(url: str, pinned_ip: str) -> str:
    """Rebuild ``url`` so the socket goes to ``pinned_ip`` while the path and query survive."""
    parts = urlsplit(url)
    host = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


class PinnedHTTP:
    """A thin httpx wrapper that enforces outbound policy on every request."""

    def __init__(self, *, timeout_s: float = 90.0, max_retries: int = 2) -> None:
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        allow_private_hosts: bool = False,
        secrets: tuple[str, ...] = (),
        provider: str = "",
        stream: bool = False,
    ) -> httpx.Response:
        policy = TargetPolicy(allow_private_hosts=allow_private_hosts)
        try:
            target = resolve_and_pin(url, policy)
        except BlockedTarget as exc:
            # A blocked target is a configuration error, not a transient failure.
            raise ProviderError(
                "target_blocked",
                redact(str(exc), secrets=secrets),
                provider=provider,
                retryable=False,
            ) from exc

        original = urlsplit(url)
        host_header = original.netloc.rsplit("@", 1)[-1]
        out_headers = dict(headers or {})
        out_headers["Host"] = host_header
        out_headers.setdefault("Accept", "application/json")
        extensions: dict[str, Any] = {}
        if original.scheme == "https":
            # Keep the real hostname for SNI and certificate validation.
            extensions["sni_hostname"] = original.hostname

        last_error: str = ""
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout_s,
                    follow_redirects=False,
                    verify=True,
                    trust_env=False,
                ) as client:
                    response = client.request(
                        method,
                        _pinned_url(url, target.pinned_ip),
                        headers=out_headers,
                        json=json,
                        extensions=extensions,
                    )
            except httpx.TimeoutException as exc:
                last_error = f"timeout after {self.timeout_s:g}s"
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise ProviderError(
                    "provider_timeout", last_error, provider=provider, retryable=True
                ) from exc
            except httpx.HTTPError as exc:
                last_error = redact(f"{type(exc).__name__}: {exc}", secrets=secrets)
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise ProviderError(
                    "provider_unreachable", last_error, provider=provider, retryable=True
                ) from exc

            if 300 <= response.status_code < 400:
                raise ProviderError(
                    "provider_redirect",
                    f"HTTP {response.status_code} redirect to "
                    f"{redact(response.headers.get('location', '?'), secrets=secrets)}; "
                    "redirects are not followed",
                    provider=provider,
                    retryable=False,
                )

            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                time.sleep(min(2**attempt, 8))
                continue

            if response.status_code >= 400:
                raise ProviderError(
                    self._error_code(response.status_code),
                    self._error_detail(response, url, secrets),
                    provider=provider,
                    retryable=response.status_code in RETRY_STATUS,
                )

            return response

        raise ProviderError("provider_unreachable", last_error, provider=provider, retryable=True)

    @staticmethod
    def _error_code(status: int) -> str:
        if status in {401, 403}:
            return "provider_auth"
        if status == 429:
            return "provider_rate_limit"
        if status == 404:
            return "provider_not_found"
        if 400 <= status < 500:
            return "provider_bad_request"
        return "provider_server_error"

    @staticmethod
    def _error_detail(response: httpx.Response, url: str, secrets: tuple[str, ...]) -> str:
        """One line, redacted, with the target named and whether a credential was attached.

        Without the target and the credential clause, ``HTTP 401`` cannot be told apart from "the
        key was withheld" — the failure that hides longest, because ``/models`` answers 200
        without auth while every completion 401s.
        """
        parts = urlsplit(url)
        where = f"{parts.hostname or '?'}:{parts.port or ('443' if parts.scheme == 'https' else '80')}"
        body = ""
        try:
            body = response.text[:600]
        except Exception:  # noqa: BLE001 - a broken body must not mask the status
            body = ""
        detail = redact(body, secrets=secrets, limit=200)
        return f"HTTP {response.status_code} from {where}: {detail or '<empty body>'}"


def health_from_response(response: httpx.Response, started_ms: int) -> Health:
    return Health.up(
        detail=f"HTTP {response.status_code}",
        latency_ms=max(0, now_ms() - started_ms),
    )
