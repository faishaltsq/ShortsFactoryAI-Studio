"""OAuth plumbing, proven offline. No listener, no browser, no real endpoint.

The rule this file enforces: a refresh token must never appear in a repr, a returned dict, or an
error detail — and the two network-shaped operations must be ordinary PinnedHTTP form POSTs so they
obey netguard and the no-redirect rule.
"""

from __future__ import annotations

import sys

import pytest

from packages.core.providers.base import ProviderError
from packages.core.providers.http_base import PinnedHTTP
from packages.core.publish.oauth import (
    DEFAULT_SCOPES,
    TOKEN_SECRET_ID,
    TokenBundle,
    build_authorize_url,
    exchange_code,
    load_tokens,
    new_pkce_verifier,
    pkce_challenge,
    refresh,
    seal_tokens,
)
from packages.core.security.secretstore import CredentialRef, SecretStore, SecretStoreError
from tests.stub_server import StubServer

SENTINEL = "sf-SENTINEL-refresh-7c1d"


def _origin(stub: StubServer) -> str:
    return f"http://127.0.0.1:{stub.port}"


def _http() -> PinnedHTTP:
    return PinnedHTTP(timeout_s=5.0, max_retries=0)


# -- the authorize URL is pure and carries PKCE ---------------------------------------------------


def test_the_authorize_url_carries_pkce_and_state():
    url = build_authorize_url(
        client_id="cid.apps.googleusercontent.com",
        redirect_uri="http://127.0.0.1:8765/callback",
        scopes=DEFAULT_SCOPES,
        state="st-123",
        code_challenge="chal-abc",
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "code_challenge=chal-abc" in url
    assert "code_challenge_method=S256" in url
    assert "state=st-123" in url
    assert "access_type=offline" in url
    assert "youtube.upload" in url


def test_the_authorize_url_refuses_a_missing_state():
    with pytest.raises(ValueError, match="state"):
        build_authorize_url(
            client_id="c", redirect_uri="http://127.0.0.1:1/cb", scopes=DEFAULT_SCOPES,
            state="", code_challenge="x",
        )


def test_the_authorize_url_refuses_a_missing_pkce_challenge():
    with pytest.raises(ValueError, match="code_challenge"):
        build_authorize_url(
            client_id="c", redirect_uri="http://127.0.0.1:1/cb", scopes=DEFAULT_SCOPES,
            state="s", code_challenge="",
        )


def test_pkce_challenge_matches_the_rfc_example():
    """RFC 7636 appendix B. A hand-rolled encoder that differs here breaks every real exchange."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_a_verifier_is_long_and_unique():
    a, b = new_pkce_verifier(), new_pkce_verifier()
    assert len(a) >= 43
    assert a != b


# -- exchange and refresh are form POSTs through the stub -----------------------------------------


def test_exchange_code_posts_a_form_and_returns_a_bundle():
    with StubServer() as stub:
        stub.route("POST", "/token", body={
            "access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
            "scope": "youtube.upload", "token_type": "Bearer",
        })
        bundle = exchange_code(
            http=_http(),
            token_endpoint=f"{_origin(stub)}/token",
            client_id="cid",
            client_secret="csecret",
            code="the-code",
            redirect_uri="http://127.0.0.1:8765/callback",
            code_verifier="verifier",
            allow_private_hosts=True,
        )
        assert bundle.access_token == "at-1"
        assert bundle.refresh_token == "rt-1"
        assert bundle.expires_in == 3600

        recorded = stub.recorded[-1]
        assert recorded.headers["content-type"] == "application/x-www-form-urlencoded"
        assert b"grant_type=authorization_code" in recorded.raw
        assert b"code_verifier=verifier" in recorded.raw


def test_refresh_posts_a_form_and_keeps_the_old_refresh_token_when_none_is_returned():
    with StubServer() as stub:
        stub.route("POST", "/token", body={"access_token": "at-2", "expires_in": 1800})
        bundle = refresh(
            http=_http(),
            token_endpoint=f"{_origin(stub)}/token",
            client_id="cid",
            client_secret="csecret",
            refresh_token="rt-old",
            allow_private_hosts=True,
        )
        assert bundle.access_token == "at-2"
        assert bundle.refresh_token == "rt-old", "a refresh must not lose the durable token"
        assert b"grant_type=refresh_token" in stub.recorded[-1].raw


def test_a_token_response_without_an_access_token_is_a_provider_error():
    with StubServer() as stub:
        stub.route("POST", "/token", body={"scope": "x"})
        with pytest.raises(ProviderError) as exc:
            refresh(
                http=_http(), token_endpoint=f"{_origin(stub)}/token",
                client_id="c", client_secret="s", refresh_token="rt",
                allow_private_hosts=True,
            )
        assert exc.value.code == "oauth_bad_response"


def test_the_token_endpoint_still_obeys_the_no_redirect_rule():
    with StubServer() as stub:
        stub.route("POST", "/token", status=302, body={}, headers={"location": "http://evil.example/t"})
        with pytest.raises(ProviderError) as exc:
            refresh(
                http=_http(), token_endpoint=f"{_origin(stub)}/token",
                client_id="c", client_secret="s", refresh_token="rt",
                allow_private_hosts=True,
            )
        assert exc.value.code == "provider_redirect"


# -- a planted token never leaks ------------------------------------------------------------------


def test_a_sentinel_token_never_appears_in_an_error_detail():
    with StubServer() as stub:
        stub.route("POST", "/token", status=401, body={"error": f"invalid_grant {SENTINEL}"})
        with pytest.raises(ProviderError) as exc:
            refresh(
                http=_http(), token_endpoint=f"{_origin(stub)}/token",
                client_id="c", client_secret="s", refresh_token=SENTINEL,
                allow_private_hosts=True,
            )
        assert SENTINEL not in exc.value.detail
        assert "[redacted]" in exc.value.detail


def test_a_token_bundle_never_shows_its_values():
    bundle = TokenBundle(access_token="at-secret", refresh_token=SENTINEL, expires_in=60)
    assert SENTINEL not in repr(bundle)
    assert "at-secret" not in repr(bundle)
    shown = bundle.to_dict()
    assert SENTINEL not in str(shown)
    assert "at-secret" not in str(shown)
    assert shown["has_refresh_token"] is True


# -- sealing through the DPAPI store ---------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_a_token_bundle_round_trips_through_the_secret_store(tmp_path):
    store = SecretStore(tmp_path)
    bundle = TokenBundle(
        access_token="at-round", refresh_token=SENTINEL, expires_in=3600,
        scope="youtube.upload",
    )
    ref = seal_tokens(store, bundle)
    assert ref.kind == "dpapi"
    assert ref.name == TOKEN_SECRET_ID

    # No plaintext on disk.
    blob = (tmp_path / f"{TOKEN_SECRET_ID}.bin").read_bytes()
    assert SENTINEL.encode() not in blob
    assert b"at-round" not in blob

    loaded = load_tokens(store, ref)
    assert loaded.access_token == "at-round"
    assert loaded.refresh_token == SENTINEL
    assert loaded.scope == "youtube.upload"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_loading_a_bundle_that_does_not_exist_is_an_error(tmp_path):
    store = SecretStore(tmp_path)
    with pytest.raises(SecretStoreError, match="no sealed token bundle"):
        load_tokens(store, CredentialRef("dpapi", "absent"))


def test_a_sealed_payload_that_is_not_a_bundle_is_refused():
    with pytest.raises(SecretStoreError, match="not a token bundle"):
        TokenBundle.from_payload('{"something": "else"}')

@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_client_credentials_round_trip_through_secret_store(tmp_path):
    from packages.core.publish.oauth import (
        CLIENT_SECRET_ID,
        ClientCredentials,
        load_client_credentials,
        seal_client_credentials,
    )

    store = SecretStore(tmp_path)
    creds = ClientCredentials(client_id="cid-123.apps.googleusercontent.com", client_secret="cs-supersecret")
    ref = seal_client_credentials(store, creds)
    assert ref.kind == "dpapi"
    assert ref.name == CLIENT_SECRET_ID

    # No plaintext on disk
    blob = (tmp_path / f"{CLIENT_SECRET_ID}.bin").read_bytes()
    assert b"cs-supersecret" not in blob

    # Repr does not show client_secret
    assert "cs-supersecret" not in repr(creds)

    loaded = load_client_credentials(store)
    assert loaded.client_id == "cid-123.apps.googleusercontent.com"
    assert loaded.client_secret == "cs-supersecret"
