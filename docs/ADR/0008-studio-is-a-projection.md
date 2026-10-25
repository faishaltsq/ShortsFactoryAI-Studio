# ADR-0008 — The 3D studio is a projection, never a source of truth

**Status:** accepted

## Decision
React Three Fiber scene reading `StudioSnapshot` from the persisted event log. Read-only: no
writes, no starting work, no marking complete. Character state derives from the latest event's
`status` plus server-computed lease validity.

## Why server-side staleness
If the client decides "no event for 30 s means idle", closing the laptop lid leaves characters
typing forever on reconnect. Staleness is a property of the lease, computed where the lease lives.

## Consequences
The scene can be deleted and the product still works — which is exactly the property that keeps it
from becoming the product (R-12).
