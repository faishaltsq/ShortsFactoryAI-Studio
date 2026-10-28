"""Durable studio configuration: providers, bindings, budgets, render policy.

One validated store around ``Settings.studio_config``. Nothing else in the process writes that
file, so "what is the operator's configuration?" has exactly one answer and one writer.

Rules this file exists to enforce:

* **Validate the whole candidate before swapping.** A save that would leave the runtime with half
  a new configuration is refused; the previous configuration stays live.
* **A malformed file is a visible sanitized error, not a partial load.** Live/autonomous dispatch
  is disabled rather than guessing which providers the operator meant.
* **Credentials are references.** ``{"env": NAME}`` or ``{"dpapi": ID}``; a value never enters the
  file, a response, a log line or an artifact.
* **Atomic replace.** Temp file in the same directory, flush, fsync, replace, fsync the directory.
  A crash mid-save leaves either the old file or the new one, never a truncated one.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.core.observability.events import AGENT_IDS
from packages.core.providers.base import Capability
from packages.core.providers.registry import ProviderSpec
from packages.core.security.secretstore import SecretStore

#: Configuration schema version. Bumped when the on-disk shape changes incompatibly; readers
#: refuse a newer version rather than guessing at fields they do not understand.
CONFIG_VERSION = 1


class ConfigError(ValueError):
    """The candidate configuration is invalid. The message is safe to show the operator."""


@dataclass
class BudgetConfig:
    """Daily spend limits. ``unlimited`` is exclusive with the caps and is an explicit choice."""

    max_daily_tokens: int | None = None
    max_daily_cost_usd: float | None = None
    unlimited: bool = False

    def validate(self) -> None:
        if self.unlimited:
            if self.max_daily_tokens is not None or self.max_daily_cost_usd is not None:
                raise ConfigError("unlimited is exclusive with the daily caps")
            return
        if self.max_daily_tokens is not None and self.max_daily_tokens <= 0:
            raise ConfigError("max_daily_tokens must be a positive integer")
        if self.max_daily_cost_usd is not None and self.max_daily_cost_usd <= 0:
            raise ConfigError("max_daily_cost_usd must be a positive number")

    def to_json(self) -> dict[str, Any]:
        return {
            "max_daily_tokens": self.max_daily_tokens,
            "max_daily_cost_usd": self.max_daily_cost_usd,
            "unlimited": self.unlimited,
        }

    @classmethod
    def from_json(cls, payload: Any) -> BudgetConfig:
        if not isinstance(payload, dict):
            raise ConfigError("budget must be an object")
        tokens = payload.get("max_daily_tokens")
        cost = payload.get("max_daily_cost_usd")
        for name, value in (("max_daily_tokens", tokens), ("max_daily_cost_usd", cost)):
            if value is not None and not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ConfigError(f"budget.{name} must be null or a number")
        config = cls(
            max_daily_tokens=int(tokens) if tokens is not None else None,
            max_daily_cost_usd=float(cost) if cost is not None else None,
            unlimited=bool(payload.get("unlimited", False)),
        )
        config.validate()
        return config


@dataclass
class RenderConfig:
    """Admission policy for the one global render slot. The cap is not configurable: it is 1."""

    min_free_ram_mib: int = 2048
    min_free_vram_mib: int = 1024
    allow_unmeasured_gpu: bool = False

    def validate(self) -> None:
        if self.min_free_ram_mib <= 0:
            raise ConfigError("render.min_free_ram_mib must be a positive integer")
        if self.min_free_vram_mib <= 0:
            raise ConfigError("render.min_free_vram_mib must be a positive integer")

    def to_json(self) -> dict[str, Any]:
        return {
            "min_free_ram_mib": self.min_free_ram_mib,
            "min_free_vram_mib": self.min_free_vram_mib,
            "allow_unmeasured_gpu": self.allow_unmeasured_gpu,
        }

    @classmethod
    def from_json(cls, payload: Any) -> RenderConfig:
        if not isinstance(payload, dict):
            raise ConfigError("render must be an object")
        return cls(
            min_free_ram_mib=int(payload.get("min_free_ram_mib", 2048)),
            min_free_vram_mib=int(payload.get("min_free_vram_mib", 1024)),
            allow_unmeasured_gpu=bool(payload.get("allow_unmeasured_gpu", False)),
        )


@dataclass
class StudioConfig:
    """The whole durable configuration. ``unknown`` keeps unrelated operator keys."""

    providers: list[dict[str, Any]] = field(default_factory=list)
    bindings: list[dict[str, Any]] = field(default_factory=list)
    credential_origins: dict[str, dict[str, Any]] = field(default_factory=dict)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    unknown: dict[str, Any] = field(default_factory=dict)
    version: int = CONFIG_VERSION

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"version": self.version}
        payload.update(self.unknown)
        payload["providers"] = self.providers
        payload["bindings"] = self.bindings
        payload["credential_origins"] = self.credential_origins
        payload["budget"] = self.budget.to_json()
        payload["render"] = self.render.to_json()
        payload["prompt_overrides"] = self.prompt_overrides
        return payload

    @classmethod
    def from_json(cls, payload: Any) -> StudioConfig:
        if not isinstance(payload, dict):
            raise ConfigError("configuration must be a JSON object")
        version = payload.get("version", CONFIG_VERSION)
        if not isinstance(version, int) or version > CONFIG_VERSION:
            raise ConfigError(
                f"configuration version {version!r} is newer than this build understands "
                f"({CONFIG_VERSION})"
            )
        known = {
            "version",
            "providers",
            "bindings",
            "credential_origins",
            "budget",
            "render",
            "prompt_overrides",
        }
        unknown = {key: value for key, value in payload.items() if key not in known}
        return cls(
            providers=_provider_list(payload.get("providers", [])),
            bindings=_binding_list(payload.get("bindings", [])),
            credential_origins=_origins(payload.get("credential_origins", {})),
            budget=BudgetConfig.from_json(payload.get("budget", {})),
            render=RenderConfig.from_json(payload.get("render", {})),
            prompt_overrides=_prompt_overrides(payload.get("prompt_overrides", {})),
            unknown=unknown,
            version=version,
        )


def _provider_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConfigError("'providers' must be a list")
    for entry in value:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ConfigError("every provider entry needs a string 'id'")
    return [dict(entry) for entry in value]


def _binding_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConfigError("'bindings' must be a list")
    for entry in value:
        if not isinstance(entry, dict) or not isinstance(entry.get("agent"), str):
            raise ConfigError("every binding entry needs a string 'agent'")
        if entry["agent"] not in AGENT_IDS:
            raise ConfigError(f"binding names unknown agent {entry['agent']!r}")
    return [dict(entry) for entry in value]


def _origins(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ConfigError("'credential_origins' must be an object")
    result: dict[str, dict[str, Any]] = {}
    for key, origin in value.items():
        if isinstance(key, str) and isinstance(origin, dict):
            result[key] = dict(origin)
    return result


def _prompt_overrides(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConfigError("'prompt_overrides' must be an object")
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


class ConfigStore:
    """Read/write ``studio.json`` under the application lock, atomically."""

    def __init__(self, path: Path, *, secrets: SecretStore | None = None) -> None:
        self.path = Path(path)
        self.secrets = secrets
        self._lock = threading.RLock()

    # -- reading ---------------------------------------------------------------------------
    def load(self) -> StudioConfig:
        """The durable configuration, or explicit mock-only defaults when the file is absent.

        A malformed file raises ``ConfigError``: the caller disables live dispatch and surfaces
        the sanitized reason. It never falls back to "the first enabled provider", because that
        would silently pick a provider the operator did not choose.
        """
        with self._lock:
            if not self.path.is_file():
                return StudioConfig()
            try:
                raw = self.path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ConfigError(f"cannot read {self.path.name}: {exc.strerror}") from exc
            try:
                payload = json.loads(raw)
            except ValueError as exc:
                raise ConfigError(f"{self.path.name} is not valid JSON: {exc}") from exc
            return StudioConfig.from_json(payload)

    def problem(self) -> str | None:
        """The sanitized reason the configuration is unusable, or ``None`` when it is fine."""
        try:
            self.load()
        except ConfigError as exc:
            return str(exc)
        return None

    # -- writing ---------------------------------------------------------------------------
    def save(self, config: StudioConfig) -> StudioConfig:
        """Validate, then replace atomically. The runtime object is never half-swapped."""
        config.budget.validate()
        config.render.validate()
        StudioConfig.from_json(config.to_json())  # round-trip: a candidate that cannot be read
        # back is not a candidate.
        payload = config.to_json()
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            )
            temporary = Path(handle.name)
            try:
                with handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                _fsync_directory(self.path.parent)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        return config

    # -- providers -------------------------------------------------------------------------
    def provider_specs(self) -> list[ProviderSpec]:
        """Full ``ProviderSpec`` records, not the truncated startup subset."""
        specs: list[ProviderSpec] = []
        for entry in self.load().providers:
            specs.append(
                ProviderSpec(
                    id=entry["id"],
                    label=entry.get("label", ""),
                    transport=entry.get("transport", "openai_compat"),
                    base_url=entry["base_url"],
                    model=entry.get("model", ""),
                    credential=entry.get("credential"),
                    capabilities=[Capability(c) for c in entry.get("capabilities", ["chat"])],
                    allow_private_hosts=entry.get("allow_private_hosts", False),
                    enabled=entry.get("enabled", True),
                    price_in_per_mtok=entry.get("price_in_per_mtok"),
                    price_out_per_mtok=entry.get("price_out_per_mtok"),
                    cli_command=entry.get("cli_command"),
                )
            )
        return specs

    def origin_of(self, provider_id: str) -> dict[str, Any] | None:
        """The ``(scheme, host, port)`` a provider's credential was bound to at load time."""
        return self.load().credential_origins.get(provider_id)


def _fsync_directory(directory: Path) -> None:
    """Make the rename itself durable. Best effort: not every filesystem allows this."""
    with contextlib.suppress(OSError, AttributeError, ValueError):
        descriptor = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
