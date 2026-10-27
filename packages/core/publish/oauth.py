"""OAuth plumbing: pure functions, a stub-tested exchange, and DPAPI-sealed tokens.

This module is the *plumbing*, not a working YouTube connection. There is no listener, no browser
launch, and no real endpoint anywhere in it. What it does provide is the part that is worth
proving offline:

* the authorize URL is built from an explicit PKCE challenge, not from a secret;
* a code exchange and a refresh are ordinary form POSTs through :class:`PinnedHTTP`, so they obey
  netguard and the no-redirect rule like every other outbound request;
* the token bundle is sealed with the existing DPAPI store, and nothing in this module ever returns
  a refresh token in a shape that could be logged.

``exchange_code`` and ``refresh`` take an injected ``PinnedHTTP`` so a test can point them at a
loopback stub. **No real provider is contacted, and this does not constitute a working OAuth flow:**
the consent screen, the redirect listener, and the real token endpoint are all absent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from ..providers.base import ProviderError
from ..providers.http_base import PinnedHTTP
from ..security.secretstore import CredentialRef, SecretStore, SecretStoreError

#: The scope a private-upload-only publisher needs. Narrower than the full upload scope on purpose:
#: a token that cannot publish publicly cannot publish publicly by accident.
DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)

#: Where the sealed bundle lives. One id, so an operator has one thing to rotate.
TOKEN_SECRET_ID = "oauth-youtube"


@dataclass(frozen=True)
class TokenBundle:
    """What a refresh cycle needs. ``repr`` is overridden so a traceback cannot leak a token.

    ``access_token`` is short-lived; ``refresh_token`` is the durable one. Both are excluded from
    ``repr`` and from :meth:`to_dict` — the only way out of this object is :meth:`sealed_payload`,
    which is what the secret store writes.
    """

    access_token: str = field(repr=False)
    refresh_token: str = field(default="", repr=False)
    expires_in: int = 0
    scope: str = ""
    token_type: str = "Bearer"

    def __repr__(self) -> str:  # never the values
        return (
            f"TokenBundle(access_token=[redacted], refresh_token=[redacted], "
            f"expires_in={self.expires_in}, scope={self.scope!r})"
        )

    @property
    def has_refresh_token(self) -> bool:
        return bool(self.refresh_token)

    def to_dict(self) -> dict[str, Any]:
        """What may be shown or returned. **Never** the tokens."""
        return {
            "expires_in": self.expires_in,
            "scope": self.scope,
            "token_type": self.token_type,
            "has_refresh_token": self.has_refresh_token,
        }

    def sealed_payload(self) -> str:
        """The only serialisation that contains the values. Written to the secret store."""
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_in": self.expires_in,
                "scope": self.scope,
                "token_type": self.token_type,
            },
            sort_keys=True,
        )

    @classmethod
    def from_payload(cls, payload: str) -> TokenBundle:
        data = json.loads(payload)
        if not isinstance(data, dict) or not data.get("access_token"):
            raise SecretStoreError("sealed token bundle is not a token bundle")
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=str(data.get("refresh_token") or ""),
            expires_in=int(data.get("expires_in") or 0),
            scope=str(data.get("scope") or ""),
            token_type=str(data.get("token_type") or "Bearer"),
        )


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...] | list[str],
    state: str,
    code_challenge: str,
) -> str:
    """The consent URL. Pure: it opens no browser and stores nothing.

    ``state`` and ``code_challenge`` are required rather than generated here, so the caller owns
    the anti-CSRF value and the PKCE verifier. A helper that generates its own state would have to
    remember it somewhere, which is the bug this shape avoids.
    """
    if not client_id.strip():
        raise ValueError("client_id is required")
    if not redirect_uri.strip():
        raise ValueError("redirect_uri is required")
    if not state.strip():
        raise ValueError("state is required; it is the anti-CSRF value")
    if not code_challenge.strip():
        raise ValueError("code_challenge is required (PKCE S256)")
    if not scopes:
        raise ValueError("at least one scope is required")
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",  # asks for a refresh token
            "prompt": "consent",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def pkce_challenge(verifier: str) -> str:
    """S256 challenge for a verifier. Pure, so a test can check the RFC 7636 example."""
    if not verifier:
        raise ValueError("code verifier is required")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_pkce_verifier() -> str:
    """A high-entropy verifier. The caller must keep it until the exchange."""
    return secrets.token_urlsafe(64)


def _token_from_response(response: Any, *, provider: str) -> TokenBundle:
    """Parse a token response. A malformed body is a provider error, not a silent empty token."""
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - a non-JSON token response is a provider error
        raise ProviderError(
            "oauth_bad_response", "token endpoint returned a non-JSON body", provider=provider
        ) from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ProviderError(
            "oauth_bad_response",
            "token endpoint returned no access_token",
            provider=provider,
        )
    return TokenBundle(
        access_token=str(payload["access_token"]),
        refresh_token=str(payload.get("refresh_token") or ""),
        expires_in=int(payload.get("expires_in") or 0),
        scope=str(payload.get("scope") or ""),
        token_type=str(payload.get("token_type") or "Bearer"),
    )


def exchange_code(
    *,
    http: PinnedHTTP,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    allow_private_hosts: bool = False,
) -> TokenBundle:
    """Exchange an authorization code for tokens. A form POST, through netguard.

    ``client_secret`` is passed as a form field and registered as a redaction secret for the call,
    so it cannot appear in a raised error detail.
    """
    if not code.strip():
        raise ValueError("authorization code is required")
    if not code_verifier.strip():
        raise ValueError("code_verifier is required (PKCE)")
    response = http.request(
        "POST",
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        secrets=(client_secret, code),
        provider="oauth",
        allow_private_hosts=allow_private_hosts,
    )
    return _token_from_response(response, provider="oauth")


def refresh(
    *,
    http: PinnedHTTP,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    allow_private_hosts: bool = False,
) -> TokenBundle:
    """Refresh an access token. Returns a bundle; a refresh may or may not return a new refresh token."""
    if not refresh_token.strip():
        raise ValueError("refresh_token is required")
    response = http.request(
        "POST",
        token_endpoint,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        secrets=(client_secret, refresh_token),
        provider="oauth",
        allow_private_hosts=allow_private_hosts,
    )
    bundle = _token_from_response(response, provider="oauth")
    if not bundle.refresh_token:
        # The endpoint often omits it on refresh; keep the one we already had.
        bundle = TokenBundle(
            access_token=bundle.access_token,
            refresh_token=refresh_token,
            expires_in=bundle.expires_in,
            scope=bundle.scope,
            token_type=bundle.token_type,
        )
    return bundle


def seal_tokens(store: SecretStore, tokens: TokenBundle, *, secret_id: str = TOKEN_SECRET_ID) -> CredentialRef:
    """Seal the bundle with DPAPI and return a reference. Never writes plaintext."""
    return store.put(secret_id, tokens.sealed_payload())


def load_tokens(store: SecretStore, ref: CredentialRef) -> TokenBundle:
    """Unseal a bundle. An empty resolution is an error here: a caller asked for tokens."""
    payload = store.resolve(ref)
    if not payload:
        raise SecretStoreError(f"no sealed token bundle for {ref.kind}:{ref.name}")
    return TokenBundle.from_payload(payload)
