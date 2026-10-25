"""Request bodies. Response shapes are built inline because they are projections, not models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateJobBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(default="", max_length=400)
    genre: str = Field(default="edukasi", max_length=80)
    language: str = Field(default="id", max_length=16)
    target_duration_s: int = Field(default=45, ge=10, le=90)
    style: str = Field(default="illustrated", max_length=80)
    voice: str = Field(default="id-ID-ArdiNeural", max_length=80)
    audience: str = Field(default="umum", max_length=80)
    intensity: str = Field(default="sedang", max_length=80)
    music: str = Field(default="none", max_length=80)
    characters: list[str] = Field(default_factory=lambda: ["maya"])
    renderer: Literal["remotion", "bang-motion"] = "remotion"
    provider_mode: Literal["live", "mock"] = "mock"

    @field_validator("characters")
    @classmethod
    def _known_characters(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one character is required")
        return value


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=400)


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: str = Field(min_length=1, max_length=120)


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=600)


class ProviderBody(BaseModel):
    """Provider create/update. Note what is absent: there is no credential *value* field.

    A credential arrives as ``credential_env`` or ``credential_secret`` (a value sealed with DPAPI
    at write time), and is never read back.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(default="", max_length=120)
    transport: Literal["openai_compat", "anthropic", "ollama", "cli", "mock"] = "openai_compat"
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    capabilities: list[Literal["chat", "json_schema", "tools", "vision"]] = Field(
        default_factory=lambda: ["chat"]
    )
    timeout_s: float = Field(default=90.0, gt=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    allow_private_hosts: bool = False
    enabled: bool = True
    cli_command: str = Field(default="", max_length=260)
    credential_env: str = Field(default="", max_length=120)
    credential_secret: str = Field(default="", max_length=4000, exclude=True)


class BindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(min_length=1, max_length=64)
    primary: str | None = Field(default=None, max_length=64)
    fallback: list[str] = Field(default_factory=list)
    requires: list[Literal["chat", "json_schema", "tools", "vision"]] = Field(
        default_factory=lambda: ["chat"]
    )
    model: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class TestProviderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)


class StudioPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: dict[str, Any] = Field(default_factory=dict)
