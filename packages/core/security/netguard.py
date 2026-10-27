"""Outbound URL policy: the one place that decides whether we may talk to a host.

Two callers share this: research retrieval (fetches arbitrary web pages) and provider transports
(POST to an operator-configured base URL with a credential attached). The donor tree had a careful
policy for the first and none for the second, which is the shape of a control that exists where it
was needed first rather than where it is most dangerous.

The policy has three parts, and all three are needed:

1. **Static deny list.** Private, loopback, link-local, CGNAT, multicast, and platform metadata
   ranges are refused by literal address.
2. **Resolve-then-pin.** A hostname is resolved once; every returned address is validated; the
   connection is made to the validated address. A hostname that resolves public on the first
   query and private on the second never gets a second chance, because we never re-resolve.
3. **No redirects.** A 3xx is an error. Following a redirect re-opens the whole question with a
   target the policy never saw.

``allow_private_hosts`` is a per-provider opt-in. It exists because Ollama and local routers are
legitimately on loopback. It is deliberately a flag on a specific provider, not a global setting,
so enabling it for one endpoint cannot silently enable it for every endpoint.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# Literal ranges that must never be reached. Kept explicit rather than computed from
# ``is_private`` because ``is_private`` alone misses CGNAT, the Azure platform address, and the
# documentation ranges that some SSRF filters forget.
_DENIED_V4 = tuple(
    ipaddress.ip_network(value)
    for value in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",  # CGNAT: reachable inside many ISPs and cloud VPCs
        "127.0.0.0/8",
        "169.254.0.0/16",  # link-local, includes AWS/GCP metadata at 169.254.169.254
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "168.63.129.16/32",  # Azure platform virtual IP; looks public, is not
    )
)

_GLOBAL_V6 = ipaddress.ip_network("2000::/3")
_DENIED_V6 = tuple(
    ipaddress.ip_network(value) for value in ("2001::/23", "2002::/16", "3fff::/20")
)

_LOCAL_SUFFIXES = (
    "localhost",
    "localdomain",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".home.arpa",
    ".in-addr.arpa",
    ".ip6.arpa",
)

ALLOWED_SCHEMES = frozenset({"http", "https"})


class BlockedTarget(ValueError):
    """The requested target violates outbound policy. Never downgraded to a warning."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"blocked target {url!r}: {reason}")


@dataclass(frozen=True)
class TargetPolicy:
    """What this caller is allowed to reach.

    ``allow_private_hosts`` is required for Ollama and local routers. It is scoped to one
    provider's configuration, so an operator cannot accidentally open the whole system.
    """

    allow_private_hosts: bool = False
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    max_url_length: int = 2048


@dataclass(frozen=True)
class OutboundPolicy:
    """The resolved decision for one URL: exactly what to connect to."""

    url: str
    scheme: str
    host: str
    port: int
    pinned_ip: str
    addresses: tuple[str, ...]


def _is_denied_ip(address: str) -> str | None:
    """Return a reason when the literal address is denied, else ``None``."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return f"{address!r} is not an IP address"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address):
        for network in _DENIED_V4:
            if ip in network:
                return f"{ip} is in denied range {network}"
        return None
    if ip.is_loopback:
        return f"{ip} is loopback"
    if ip.is_link_local:
        return f"{ip} is link-local"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return f"{ip} is multicast/reserved/unspecified"
    if ip not in _GLOBAL_V6:
        return f"{ip} is outside global unicast 2000::/3"
    for network in _DENIED_V6:
        if ip in network:
            return f"{ip} is in denied range {network}"
    return None


def _host_is_local_name(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered == "localhost":
        return True
    return any(lowered.endswith(suffix) for suffix in _LOCAL_SUFFIXES)


def _split(url: str, policy: TargetPolicy) -> tuple[str, str, int, str]:
    if not url or len(url) > policy.max_url_length:
        raise BlockedTarget(url, "url is empty or too long")
    if any(ch in url for ch in ("\x00", "\n", "\r", "\t", " ")):
        raise BlockedTarget(url, "url contains whitespace or control characters")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise BlockedTarget(url, f"scheme {scheme!r} is not http/https")
    if parts.username or parts.password:
        raise BlockedTarget(url, "credentials embedded in the URL")
    host = parts.hostname or ""
    if not host:
        raise BlockedTarget(url, "no host")
    port = parts.port or (443 if scheme == "https" else 80)
    return scheme, host, port, parts.path or "/"


def _resolve(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedTarget(host, f"cannot resolve: {exc}") from exc
    addresses = tuple(
        str(address)
        for address in dict.fromkeys(
            info[4][0] for info in infos if isinstance(info[4][0], (str, bytes))
        )
    )
    if not addresses:
        raise BlockedTarget(host, "resolved to no addresses")
    return addresses


def resolve_and_pin(url: str, policy: TargetPolicy | None = None) -> OutboundPolicy:
    """Validate ``url`` and return the address to connect to.

    This is the only function a transport should call before making a request. It performs the
    DNS lookup itself, so the caller must connect to ``pinned_ip`` rather than re-resolving the
    hostname.
    """
    policy = policy or TargetPolicy()
    scheme, host, port, _path = _split(url, policy)

    literal = None
    try:
        literal = str(ipaddress.ip_address(host))
    except ValueError:
        literal = None

    if literal is not None:
        reason = _is_denied_ip(literal)
        if reason and not policy.allow_private_hosts:
            raise BlockedTarget(url, reason)
        return OutboundPolicy(url, scheme, host, port, literal, (literal,))

    if _host_is_local_name(host) and not policy.allow_private_hosts:
        raise BlockedTarget(url, f"{host!r} is a local name")

    if policy.allowed_hosts and host.lower() not in policy.allowed_hosts:
        raise BlockedTarget(url, f"{host!r} is not in the allowed host list")

    addresses = _resolve(host, port)
    for address in addresses:
        reason = _is_denied_ip(address)
        if reason and not policy.allow_private_hosts:
            raise BlockedTarget(url, f"{host} resolves to {address}: {reason}")
    return OutboundPolicy(url, scheme, host, port, addresses[0], addresses)


def check_target(url: str, policy: TargetPolicy | None = None) -> None:
    """Raise :class:`BlockedTarget` if ``url`` may not be reached."""
    resolve_and_pin(url, policy)


def validate_base_url(value: str, policy: TargetPolicy | None = None) -> str:
    """Validate an operator-supplied provider base URL without performing DNS.

    Used at configuration time: saving a provider must not depend on the endpoint being up, but
    it must still refuse the shapes that can never be legitimate.
    """
    policy = policy or TargetPolicy()
    scheme, host, port, _path = _split(value, policy)
    if host.lower() in {"", "0.0.0.0"}:
        raise BlockedTarget(value, "wildcard host")
    if _host_is_local_name(host) and not policy.allow_private_hosts:
        raise BlockedTarget(value, f"{host!r} is a local name; set allow_private_hosts to use it")
    try:
        literal = str(ipaddress.ip_address(host))
    except ValueError:
        literal = None
    if literal is not None:
        reason = _is_denied_ip(literal)
        if reason and not policy.allow_private_hosts:
            raise BlockedTarget(value, reason)
    return value.rstrip("/")
