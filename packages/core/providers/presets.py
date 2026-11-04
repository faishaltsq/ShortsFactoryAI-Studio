"""Production presets: one named choice that binds every LLM agent at once.

A preset is a *whole-studio* decision, so it lives next to resolution rather than in the API: the
pipeline resolves bindings from ``state.bindings``, and a preset is what fills that dict. Keeping it
in ``packages/core`` means a CLI run and a test apply exactly the rule the HTTP app applies.

The rule that matters:

* **A preset names providers, not models.** "Everything on StepFun" is a provider statement; the
  model each agent sends comes from the configured provider's own ``model`` unless the preset
  overrides it explicitly. A preset that hardcodes a model name would run a model the operator's
  endpoint may not serve, which is precisely the failure this file exists to prevent.
* **No silent cross-family routing.** ``allow_fallback: false`` (the default for every StepFun
  preset) means an agent that cannot reach the named provider raises ``NoProviderAvailable``. It
  never quietly degrades to a different family, and a mock job stays ``publishable: false``.
* **Capabilities are checked, not assumed.** Applying a preset returns which agents the named
  provider cannot serve. A vision-only gap is reported, never papered over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agents.registry import AGENTS
from .base import Capability
from .registry import ProviderRegistry

#: The agents that make model calls. Deterministic agents (``AssetAgent``, ``AudioAgent``, ...) have
#: no provider to bind; binding one would be a lie the API would then have to display.
LLM_AGENTS: tuple[str, ...] = tuple(sorted(AGENTS))

#: Models a StepFun-family endpoint is known to serve. A preset that asks for a model outside this
#: set is refused at apply time rather than sent to an endpoint that will 404 on it.
STEPFUN_MODELS: frozenset[str] = frozenset(
    {
        "om/step-5-preview",
        "step-5-preview",
        "om/step-2-16k",
        "step-2-16k",
        "om/step-1-8k",
        "step-1-8k",
        "om/step-mini",
        "step-mini",
    }
)

#: Capabilities a preset may require. ``vision`` is optional per preset because a StepFun endpoint
#: may or may not expose it, and a preset must never claim it does.
PRESET_CAPABILITIES: frozenset[str] = frozenset({"chat", "json_schema", "vision"})


class PresetError(ValueError):
    """The requested preset cannot be applied. The message is safe to show the operator."""


@dataclass(frozen=True)
class Preset:
    """One selectable production configuration.

    ``agents`` is the set the preset binds; an empty tuple means "every LLM agent".
    ``require_capabilities`` are checked against the named provider and reported as gaps — a
    preset never claims a capability the provider does not have.
    """

    id: str
    label: str
    description: str
    provider: str
    agents: tuple[str, ...] = ()
    model: str | None = None
    allow_fallback: bool = False
    require_capabilities: frozenset[str] = field(
        default_factory=lambda: frozenset({"chat"})
    )
    #: Overrides merged on top of the generated binding, so a preset can pin a temperature or a
    #: system-prompt override without hardcoding a provider or a model.
    overrides: dict[str, object] = field(default_factory=dict)

    def agent_ids(self) -> tuple[str, ...]:
        return self.agents or LLM_AGENTS


#: The presets this build ships with. Adding one is additive: an unknown id in
# ``config/studio.json`` is refused at load rather than silently ignored, so a typo cannot leave
# the studio on the wrong routing.
PRESETS: dict[str, Preset] = {
    "full-stepfun-v2": Preset(
        id="full-stepfun-v2",
        label="Full StepFun V2",
        description=(
            "Every LLM agent on the operator's StepFun provider. Cross-family fallback is off by "
            "default, so an unreachable endpoint is a loud failure instead of a silent reroute to "
            "another model family."
        ),
        provider="stepfun",
        agents=(),
        model=None,
        allow_fallback=False,
        require_capabilities=frozenset({"chat"}),
    ),
}


def _cap_names(capabilities: Any) -> set[str]:
    """Capability *values*, not ``str(enum)``.

    ``Capability`` is a ``str`` enum but Python 3.11+ renders it as ``"Capability.CHAT"``, so a
    naive ``str(cap)`` silently reports every provider as missing ``chat``.
    """
    return {(cap.value if isinstance(cap, Capability) else str(cap)) for cap in capabilities}


def preset_ids() -> tuple[str, ...]:
    return tuple(sorted(PRESETS))


def get_preset(preset_id: str) -> Preset:
    """One preset by id. An unknown id raises rather than returning a default."""
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise PresetError(
            f"unknown production preset {preset_id!r}; known presets: {', '.join(preset_ids())}"
        )
    return preset


def apply_preset(
    preset_id: str,
    registry: ProviderRegistry,
    *,
    model: str | None = None,
    allow_fallback: bool | None = None,
    fallback: tuple[str, ...] | list[str] = (),
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Expand one preset into per-agent bindings, plus the capability gaps it cannot close.

    Returns ``(bindings, gaps)``. ``gaps`` names the agents the named provider cannot serve, so a
    caller can surface them before a job starts instead of discovering them mid-render. An empty
    ``gaps`` means the preset is fully serviceable by the current configuration.

    ``model`` overrides the preset's own model only when the operator explicitly passes one, and it
    must be a model the StepFun family is known to serve — an unknown model is refused here rather
    than sent to an endpoint that will reject it.
    """
    preset = get_preset(preset_id)
    spec = registry.specs.get(preset.provider)
    if spec is None:
        raise PresetError(
            f"preset {preset.id!r} needs provider {preset.provider!r}, which is not configured"
        )

    chosen_model = preset.model if model is None else model
    if chosen_model is not None and chosen_model not in STEPFUN_MODELS:
        raise PresetError(
            f"preset {preset.id!r} would use model {chosen_model!r}, which is not a known "
            f"StepFun model; known: {', '.join(sorted(STEPFUN_MODELS))}"
        )

    # Three ways to say "off", and only two ways to say "on". An explicit non-empty ``fallback``
    # list is itself the opt-in, so a caller that names providers cannot also have them silently
    # discarded by an omitted ``allow_fallback``.
    if allow_fallback is None:
        effective_fallback = preset.allow_fallback or bool(fallback)
    else:
        effective_fallback = allow_fallback
    declared_fallback = tuple(f for f in fallback if isinstance(f, str)) if effective_fallback else ()

    spec_capabilities = _cap_names(spec.capabilities)
    missing = sorted(preset.require_capabilities - spec_capabilities)

    bindings: dict[str, dict[str, object]] = {}
    gaps: list[str] = []
    for agent in preset.agent_ids():
        if agent not in AGENTS:
            continue
        entry: dict[str, object] = {
            "primary": preset.provider,
            "fallback": list(declared_fallback),
            "model": chosen_model,
        }
        entry.update(preset.overrides)
        bindings[agent] = entry
        # An agent whose own requirements exceed the provider's declared capabilities cannot run
        # under this preset. That is a gap to report, not a binding to soften.
        required = _cap_names(AGENTS[agent].requires)
        if not required.issubset(spec_capabilities):
            gaps.append(f"{agent}: needs {sorted(required - spec_capabilities)}")

    for gap in missing:
        gaps.append(f"{preset.provider}: missing {gap}")

    return bindings, sorted(set(gaps))


def preset_view(preset: Preset, registry: ProviderRegistry) -> dict[str, object]:
    """What the API may return about a preset: its shape plus whether it can actually run now.

    No credential, no URL, no key material — the same rule the provider endpoints follow.
    """
    spec = registry.specs.get(preset.provider)
    capabilities = sorted(_cap_names(spec.capabilities)) if spec else []
    return {
        "id": preset.id,
        "label": preset.label,
        "description": preset.description,
        "provider": preset.provider,
        "provider_configured": spec is not None,
        "provider_enabled": bool(spec.enabled) if spec else False,
        "provider_capabilities": capabilities,
        "agents": list(preset.agent_ids()),
        "model": preset.model,
        "allow_fallback": preset.allow_fallback,
        "require_capabilities": sorted(preset.require_capabilities),
        "serviceable": spec is not None
        and bool(spec.enabled)
        and preset.require_capabilities.issubset(_cap_names(spec.capabilities)),
    }


__all__ = [
    "LLM_AGENTS",
    "PRESETS",
    "PRESET_CAPABILITIES",
    "STEPFUN_MODELS",
    "Preset",
    "PresetError",
    "apply_preset",
    "get_preset",
    "preset_ids",
    "preset_view",
]
