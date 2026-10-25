"""Redaction: the last line before a credential reaches a log or a response."""

from __future__ import annotations

from packages.core.security.redact import REDACTED, redact, redact_url

SENTINEL = "sk-SENTINEL-4f19c2ae-DO-NOT-LEAK"


def test_known_secret_is_removed():
    assert SENTINEL not in redact(f"failed with key {SENTINEL}", secrets=(SENTINEL,))


def test_credential_shaped_value_is_removed_even_when_unknown():
    assert "sk-abcdefghijkl" not in redact("boom sk-abcdefghijkl boom")


def test_bearer_token_is_removed():
    out = redact("Authorization: Bearer abcdef123456.xyz")
    assert "abcdef123456" not in out
    assert REDACTED in out


def test_jwt_is_removed():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
    assert "eyJhbGciOiJIUzI1NiJ9" not in redact(f"token={jwt}")


def test_key_value_shape_is_redacted():
    out = redact("api_key=supersecretvalue123")
    assert "supersecretvalue123" not in out


def test_output_is_single_line_and_bounded():
    out = redact("a\n\nb\t\tc" + "x" * 500)
    assert "\n" not in out and "\t" not in out
    assert len(out) <= 240


def test_url_userinfo_is_stripped():
    assert "user:pass" not in redact_url("https://user:pass@example.com/v1")


def test_url_query_credential_is_stripped():
    out = redact_url("https://example.com/v1?api_key=abc123&x=1")
    assert "abc123" not in out
