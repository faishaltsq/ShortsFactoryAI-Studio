"""Binding an agent to a provider, and resolving a call.

Resolution is pure: it reads configuration, filters candidates by capability and health, and
returns a frozen ``ResolvedCall``. It never mutates a provider.

The capability filter runs **before** any network call, so a binding that requires ``vision`` and
has no vision-capable provider fails loudly at configuration time rather than producing a
confident description of frames nobody looked at.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..security.secretstore import CredentialRef, SecretStore
from .base import (
    Capability,
    CapabilityMismatch,
    Health,
    NoProviderAvailable,
    Provider,
    ResolvedCall,
)
from .registry import ProviderRegistry, ProviderSpec


@dataclass(frozen=True)
class Binding:
    """One agent's provider preference.

    ``primary`` is tried first, then ``fallback`` in order. ``requires`` is what the agent needs;
    a candidate missing any of it is skipped with a recorded reason.
    """

    agent: str
    primary: str | None = None
    fallback: tuple[str, ...] = ()
    requires: frozenset[Capability] = frozenset({Capability.CHAT})
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    def candidates(self) -> list[str]:
        out: list[str] = []
        if self.primary:
            out.append(self.primary)
        out.extend(self.fallback)
        return out


def build_call(
    spec: ProviderSpec,
    *,
    binding: Binding,
    credential: str,
) -> ResolvedCall:
    """Freeze the configuration into a call value. The credential is attached here and only here."""
    return ResolvedCall(
        provider=spec.id,
        transport=spec.transport,
        base_url=spec.base_url.rstrip("/"),
        model=binding.model or spec.model,
        temperature=binding.temperature if binding.temperature is not None else spec.temperature,
        max_tokens=binding.max_tokens if binding.max_tokens is not None else spec.max_tokens,
        timeout_s=spec.timeout_s,
        max_retries=spec.max_retries,
        capabilities=frozenset(spec.capabilities),
        allow_private_hosts=spec.allow_private_hosts,
        params=dict(spec.params),
        credential=credential,
    )


def _credential_for(spec: ProviderSpec, store: SecretStore, bound_origin: tuple[str, str, int] | None) -> tuple[str, str | None]:
    """Resolve the credential for ``spec``, honouring origin binding.

    Returns ``(value, problem)``. ``problem`` is a human-readable reason the credential was
    withheld, or ``None``. Withholding is deliberate: an operator who edits ``base_url`` to a new
    host must not have their existing key travel there.
    """
    ref = CredentialRef.parse(spec.credential)
    if ref is None:
        return "", None
    if bound_origin is not None and spec.origin != bound_origin:
        return "", (
            f"credential is bound to {bound_origin[0]}://{bound_origin[1]}:{bound_origin[2]} "
            f"but base_url is {spec.origin[0]}://{spec.origin[1]}:{spec.origin[2]}"
        )
    value = store.resolve(ref)
    if not value:
        return "", f"credential {ref.kind}:{ref.name} is not available"
    return value, None


def resolve_call(
    *,
    binding: Binding,
    registry: ProviderRegistry,
    store: SecretStore,
    transports: dict[str, Provider],
    health: dict[str, Health] | None = None,
    allow_mock_fallback: bool = False,
    bound_origins: dict[str, tuple[str, str, int]] | None = None,
) -> tuple[ResolvedCall, Provider]:
    """Pick the first candidate that can serve this agent, or raise.

    ``allow_mock_fallback`` is only true for a job that was created in explicit mock mode. A live
    job never degrades to mock.
    """
    health = health or {}
    bound_origins = bound_origins or {}
    reasons: list[str] = []

    for provider_id in binding.candidates():
        spec = registry.specs.get(provider_id)
        if spec is None:
            reasons.append(f"{provider_id}: not configured")
            continue
        if not spec.enabled:
            reasons.append(f"{provider_id}: disabled")
            continue

        missing = binding.requires - frozenset(spec.capabilities)
        if missing:
            # Not a runtime failure to retry: the operator must fix the binding.
            raise CapabilityMismatch(binding.agent, provider_id, frozenset(missing))

        transport = transports.get(spec.transport)
        if transport is None:
            reasons.append(f"{provider_id}: transport {spec.transport!r} not available")
            continue

        credential, problem = _credential_for(spec, store, bound_origins.get(provider_id))
        call = build_call(spec, binding=binding, credential=credential)

        if problem and spec.credential is not None:
            reasons.append(f"{provider_id}: {problem}")
            continue

        report = health.get(provider_id)
        if report is None:
            report = transport.health(call)
        if not report.ok:
            reasons.append(f"{provider_id}: unhealthy ({report.detail})")
            continue

        return call, transport

    if allow_mock_fallback:
        mock_spec = registry.specs.get("mock")
        mock_transport = transports.get("mock")
        if mock_spec is not None and mock_transport is not None:
            call = build_call(mock_spec, binding=binding, credential="")
            return call, mock_transport

    raise NoProviderAvailable(binding.agent, reasons or ["no candidates configured"])
