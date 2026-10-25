"""Outbound policy. Every case here is a request that must not leave the machine."""

from __future__ import annotations

import socket

import pytest

from packages.core.security.netguard import (
    BlockedTarget,
    TargetPolicy,
    check_target,
    resolve_and_pin,
    validate_base_url,
)

DENIED_LITERALS = [
    "http://127.0.0.1:8080/v1",
    "http://127.1.2.3/v1",
    "http://10.1.2.3/v1",
    "http://172.16.5.4/v1",
    "http://192.168.1.10/v1",
    "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.1/v1",
    "http://0.0.0.0/v1",
    "http://168.63.129.16/v1",
    "http://224.0.0.1/v1",
    "http://[::1]/v1",
    "http://[fd00::1]/v1",
    "http://[fe80::1]/v1",
]


@pytest.mark.parametrize("url", DENIED_LITERALS)
def test_private_and_special_literals_are_refused(url):
    with pytest.raises(BlockedTarget):
        check_target(url)


def test_public_literal_is_allowed_without_dns():
    policy = resolve_and_pin("https://93.184.216.34/v1")
    assert policy.pinned_ip == "93.184.216.34"
    assert policy.port == 443


def test_allow_private_hosts_permits_loopback():
    policy = resolve_and_pin(
        "http://127.0.0.1:11434/api/chat", TargetPolicy(allow_private_hosts=True)
    )
    assert policy.pinned_ip == "127.0.0.1"
    assert policy.port == 11434


def test_localhost_name_needs_the_flag():
    with pytest.raises(BlockedTarget):
        check_target("http://localhost:20128/v1")
    assert resolve_and_pin(
        "http://localhost:20128/v1", TargetPolicy(allow_private_hosts=True)
    ).host == "localhost"


def test_embedded_credentials_are_refused():
    with pytest.raises(BlockedTarget) as exc:
        check_target("https://user:pass@example.com/v1")
    assert "credentials embedded" in str(exc.value)


def test_non_http_scheme_is_refused():
    for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/"):
        with pytest.raises(BlockedTarget):
            check_target(url)


def test_control_characters_are_refused():
    with pytest.raises(BlockedTarget):
        check_target("https://example.com/\r\nHost: evil")


def test_dns_rebinding_is_closed_by_pinning(monkeypatch):
    """A host that answers public then private must be refused on the first answer.

    The policy resolves once and returns the pinned IP. There is no second resolution, so a
    rebinding attacker cannot make validation see one address and the connection use another.
    """
    calls = {"n": 0}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls["n"] += 1
        address = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    policy = resolve_and_pin("https://rebind.example.com/v1")
    assert policy.pinned_ip == "93.184.216.34"
    assert calls["n"] == 1, "policy must resolve exactly once"


def test_hostname_resolving_to_private_is_refused(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))
        ],
    )
    with pytest.raises(BlockedTarget) as exc:
        check_target("https://internal.example.com/v1")
    assert "resolves to 10.0.0.5" in str(exc.value)


def test_one_bad_address_among_good_ones_is_refused(monkeypatch):
    """A host with both a public and a private A record must be refused entirely."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ],
    )
    with pytest.raises(BlockedTarget):
        check_target("https://mixed.example.com/v1")


def test_allowed_hosts_allowlist_is_enforced(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    with pytest.raises(BlockedTarget) as exc:
        check_target(
            "https://api.other.com/v1",
            TargetPolicy(allowed_hosts=frozenset({"api.allowed.com"})),
        )
    assert "not in the allowed host list" in str(exc.value)


def test_validate_base_url_accepts_a_public_endpoint_without_dns():
    assert validate_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"


def test_validate_base_url_refuses_metadata_ip():
    with pytest.raises(BlockedTarget):
        validate_base_url("http://169.254.169.254/v1")


def test_validate_base_url_refuses_wildcard_host():
    with pytest.raises(BlockedTarget):
        validate_base_url("http://0.0.0.0:8000/v1")


def test_ipv4_mapped_ipv6_is_checked_as_ipv4():
    with pytest.raises(BlockedTarget):
        check_target("http://[::ffff:127.0.0.1]/v1")
