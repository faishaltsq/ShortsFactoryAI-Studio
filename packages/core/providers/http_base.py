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
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from ..security.netguard import BlockedTarget, TargetPolicy, resolve_and_pin
from ..security.redact import redact
from .base import Health, ProviderError, now_ms

#: How much of a file is read per chunk when streaming an upload. 256 KB is small enough that a
#: 200 MB video never sits in memory and large enough that the per-chunk overhead is irrelevant.
UPLOAD_CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True)
class UploadBody:
    """A request body streamed from a file, with the length and type the server is told.

    ``content_length`` is declared rather than inferred at send time on purpose: a server that is
    told 5 MB and receives 4.9 MB can reject the upload, while a chunked-encoding body with no
    declared length leaves a truncated transfer looking exactly like a complete one.

    ``start`` exists for the resumable-upload protocol, where one request carries one range of the
    file rather than the whole thing. It is the byte offset the stream begins at, and it defaults
    to 0 so every existing caller is unaffected.
    """

    path: Path
    content_length: int
    content_type: str = "application/octet-stream"
    chunk_bytes: int = UPLOAD_CHUNK_BYTES
    #: Byte offset the stream starts at. Only meaningful together with ``content_length``, which
    #: describes the slice rather than the whole file.
    start: int = 0

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        content_type: str = "application/octet-stream",
        content_length: int | None = None,
        chunk_bytes: int = UPLOAD_CHUNK_BYTES,
        start: int = 0,
    ) -> UploadBody:
        resolved = Path(path)
        if not resolved.is_file():
            raise FileNotFoundError(f"upload body file does not exist: {resolved}")
        size = resolved.stat().st_size
        if start < 0 or start > size:
            raise ValueError(f"start {start} is outside the file ({size} bytes) for {resolved}")
        remaining = size - start
        if content_length is not None and content_length != remaining:
            raise ValueError(
                f"content_length {content_length} does not match {remaining} bytes remaining "
                f"from offset {start} for {resolved}"
            )
        return cls(
            path=resolved,
            content_length=remaining,
            content_type=content_type,
            chunk_bytes=chunk_bytes,
            start=start,
        )

    @property
    def size(self) -> int:
        return self.content_length

    def chunks(self) -> Iterator[bytes]:
        """Yield the slice in bounded pieces. Never reads the whole file into memory."""
        remaining = self.content_length
        with open(self.path, "rb") as handle:
            if self.start:
                handle.seek(self.start)
            while remaining > 0:
                chunk = handle.read(min(self.chunk_bytes, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
                yield chunk


@dataclass(frozen=True)
class ResumeInfo:
    """A 308 the caller explicitly asked to receive instead of an error.

    Carries what a resumable upload needs to continue: how much the server already has, and where
    to send the rest. It is returned *only* when ``allow_resume_308`` is set; otherwise a 308 is
    the same ``provider_redirect`` error as any other 3xx.
    """

    status_code: int
    range_header: str
    location: str

    @property
    def bytes_received(self) -> int:
        """The number of bytes already accepted, parsed from ``Range: bytes=0-99``."""
        match = self.range_header.strip()
        if not match.lower().startswith("bytes="):
            return 0
        spec = match.split("=", 1)[1].split(",")[0]
        _, _, end = spec.partition("-")
        try:
            return int(end) + 1
        except ValueError:
            return 0


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
        data: Mapping[str, str] | None = None,
        body: UploadBody | None = None,
        allow_private_hosts: bool = False,
        secrets: tuple[str, ...] = (),
        provider: str = "",
        allow_resume_308: bool = False,
        retry_safe: bool = True,
    ) -> httpx.Response | ResumeInfo:
        """Send one request through the shared policy.

        Body encodings are mutually exclusive — ``json``, ``data`` (form) and ``body`` (a streamed
        upload). Two at once is a caller bug, and guessing which one to send is how a request goes
        out in a shape nobody intended.

        ``allow_resume_308`` is the only relaxation of ADR-005, and it is narrow: it returns the
        308 as :class:`ResumeInfo` for *that one call*. Every other 3xx still raises, and the
        address policy is untouched.
        """
        provided = [
            name
            for name, value in (("json", json), ("data", data), ("body", body))
            if value is not None
        ]
        if len(provided) > 1:
            raise ValueError(
                "pass at most one of json, data, body; got " + " and ".join(provided)
            )
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
        request_kwargs: dict[str, Any] = {}
        if data is not None:
            # Encoded here rather than handed to httpx as a dict, so the wire bytes are a property
            # of this module and a test can assert them exactly.
            request_kwargs["content"] = urlencode(dict(data)).encode("utf-8")
            out_headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            request_kwargs["content"] = body.chunks()
            out_headers["Content-Type"] = body.content_type
            out_headers["Content-Length"] = str(body.content_length)
        else:
            request_kwargs["json"] = json
        extensions: dict[str, Any] = {}
        if original.scheme == "https":
            # Keep the real hostname for SNI and certificate validation.
            extensions["sni_hostname"] = original.hostname

        last_error: str = ""
        # Paid inference can be accepted even when the response is a timeout or 500.
        retry_limit = self.max_retries if retry_safe else 0
        for attempt in range(retry_limit + 1):
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
                        extensions=extensions,
                        **request_kwargs,
                    )
            except httpx.TimeoutException as exc:
                last_error = f"timeout after {self.timeout_s:g}s"
                if attempt < retry_limit:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise ProviderError(
                    "provider_timeout", last_error, provider=provider, retryable=True
                ) from exc
            except httpx.HTTPError as exc:
                last_error = redact(f"{type(exc).__name__}: {exc}", secrets=secrets)
                if attempt < retry_limit:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise ProviderError(
                    "provider_unreachable", last_error, provider=provider, retryable=True
                ) from exc

            if response.status_code == 308 and allow_resume_308:
                # Opt-in, per call, for resumable upload only. Returned rather than raised because
                # a 308 is the protocol's way of saying "keep going from here", not a redirection.
                return ResumeInfo(
                    status_code=308,
                    range_header=response.headers.get("range", ""),
                    location=response.headers.get("location", ""),
                )

            if 300 <= response.status_code < 400:
                raise ProviderError(
                    "provider_redirect",
                    f"HTTP {response.status_code} redirect to "
                    f"{redact(response.headers.get('location', '?'), secrets=secrets)}; "
                    "redirects are not followed",
                    provider=provider,
                    retryable=False,
                )

            if response.status_code in RETRY_STATUS and attempt < retry_limit:
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
