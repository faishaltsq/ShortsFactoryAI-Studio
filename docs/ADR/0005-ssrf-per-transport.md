# ADR-0005 — SSRF policy is shared and explicit

**Status:** accepted

## Context
Measured: the donor validates provider `base_url` for scheme, hostname and embedded credentials
only. The CIDR deny list exists in `research/retrieval.py` and is never applied to provider
endpoints. The operator UI can point a provider at a metadata address and the server will POST
there with an `Authorization` header.

## Decision
One `netguard` module used by both research and providers. Deny private/loopback/link-local/
CGNAT/multicast/metadata ranges and non-global IPv6. Resolve once, validate every address, pin the
IP. No redirects. `allow_private_hosts` is a per-provider opt-in, required for Ollama, and shown
as a warning in the UI.

## Consequences
Local routers need one explicit flag. That friction is the point: a local endpoint should be a
deliberate choice, not a default.
