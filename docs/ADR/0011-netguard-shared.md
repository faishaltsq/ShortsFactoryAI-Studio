# ADR-0011 — One netguard for research and providers

**Status:** accepted

## Decision
`packages/core/security/netguard.py` is the single outbound-URL policy: scheme allow-list, CIDR
denial, resolve-then-pin, no redirects, size and time caps. Research retrieval and provider
transports both call it.

## Why not two implementations
The donor has a careful implementation for research and none for providers — the exact shape of a
security control that exists where it was needed first rather than where it is needed most. One
module, one test suite, two callers.
