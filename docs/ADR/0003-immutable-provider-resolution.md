# ADR-0003 — Provider resolution is immutable and capability-checked

**Status:** accepted

## Context
The donor mutates the selected provider to apply per-agent overrides:

```python
# donor packages/core/providers/router.py:202-209
if override is not None and provider.name != "mock":
    if override.model:
        target.model = override.model
```

With `ResearchAgent` and `ScriptAgent` both resolving through the worker chain, the second call
runs the first agent's model. The bug is silent: usage is logged under the right agent name with
the wrong model.

## Decision
`resolve(agent)` returns a frozen `ResolvedCall(provider_id, transport, base_url, model,
temperature, credential_ref, capabilities)`. Adapters are stateless with respect to
configuration. Per-call values are arguments, never assignments.

## Capability validation
`Capability = {chat, json_schema, tools, vision}`. A binding declares `requires`. Resolution
filters candidates by `requires <= provider.capabilities` **before** any network call and raises
`CapabilityMismatch(agent, provider, missing)`.

## Consequences
Two agents on one provider are provably independent (regression test). A `vision` requirement
with no vision provider is a visible configuration error, not a runtime surprise — which is what
makes the "never claim a text model inspected frames" rule enforceable.
