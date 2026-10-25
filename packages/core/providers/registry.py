"""Provider configuration and its validation.

A ``ProviderSpec`` is operator data: transport, endpoint, credential *reference*, model, limits,
declared capabilities. It is validated on save and re-validated on load, because a file can be
edited by hand and a hand-edited file is exactly where a bad base URL comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..security.netguard import BlockedTarget, TargetPolicy, validate_base_url
from .base import Capability

TransportId = Literal["openai_compat", "anthropic", "ollama", "cli", "mock"]


class ProviderSpec(BaseModel):
    """One configured endpoint. Never contains a credential value, only a reference."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(default="", max_length=120)
    transport: TransportId = "openai_compat"
    base_url: str = ""
    model: str = Field(default="", max_length=200)
    credential: dict[str, str] | None = None
    capabilities: list[Capability] = Field(default_factory=lambda: [Capability.CHAT])
    timeout_s: float = Field(default=90.0, gt=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    allow_private_hosts: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    price_in_per_mtok: float | None = Field(default=None, ge=0)
    price_out_per_mtok: float | None = Field(default=None, ge=0)
    cli_command: str = ""

    @field_validator("base_url")
    @classmethod
    def _url_shape(cls, value: str) -> str:
        if not value:
            return ""
        try:
            return validate_base_url(value, TargetPolicy(allow_private_hosts=True))
        except BlockedTarget as exc:
            # Shape is validated here; the address policy is applied at call time with the
            # provider's own allow_private_hosts setting.
            raise ValueError(f"base_url invalid: {exc.reason}") from exc

    @field_validator("capabilities")
    @classmethod
    def _unique_capabilities(cls, value: list[Capability]) -> list[Capability]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _transport_requirements(self) -> ProviderSpec:
        if self.transport in {"openai_compat", "anthropic", "ollama"} and not self.base_url:
            raise ValueError(f"transport {self.transport!r} requires base_url")
        if self.transport == "mock":
            return self
        if self.transport == "cli" and not self.cli_command:
            raise ValueError("transport 'cli' requires cli_command")
        if not self.model:
            raise ValueError("a non-mock provider requires a model")
        if self.credential is not None:
            if len(self.credential) != 1 or next(iter(self.credential)) not in {"env", "dpapi"}:
                raise ValueError("credential must be {'env': NAME} or {'dpapi': ID}")
        return self

    @property
    def origin(self) -> tuple[str, str, int]:
        """The (scheme, host, port) a credential is bound to."""
        parts = urlsplit(self.base_url)
        scheme = parts.scheme.lower()
        return (scheme, (parts.hostname or "").lower(), parts.port or (443 if scheme == "https" else 80))

    def public_view(self) -> dict[str, Any]:
        """What the API may return. No credential value, no length, no prefix, no hash."""
        return {
            "id": self.id,
            "label": self.label,
            "transport": self.transport,
            "base_url": self.base_url,
            "model": self.model,
            "capabilities": [cap.value for cap in self.capabilities],
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "allow_private_hosts": self.allow_private_hosts,
            "enabled": self.enabled,
            "credential_source": (
                f"{next(iter(self.credential))}:{next(iter(self.credential.values()))}"
                if self.credential
                else None
            ),
            "cli_command": self.cli_command,
        }


@dataclass
class ProviderRegistry:
    """The set of configured providers, keyed by id."""

    specs: dict[str, ProviderSpec] = field(default_factory=dict)

    def add(self, spec: ProviderSpec) -> ProviderSpec:
        self.specs[spec.id] = spec
        return spec

    def get(self, provider_id: str) -> ProviderSpec:
        try:
            return self.specs[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown provider {provider_id!r}") from exc

    def enabled(self) -> list[ProviderSpec]:
        return [spec for spec in self.specs.values() if spec.enabled]

    def with_capability(self, capability: Capability) -> list[ProviderSpec]:
        return [spec for spec in self.enabled() if capability in spec.capabilities]

    def public_view(self) -> list[dict[str, Any]]:
        return [spec.public_view() for spec in self.specs.values()]
