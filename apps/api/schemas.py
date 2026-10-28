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
    #: A job-level request for the Phase 2 render chain. Not a provider setting: it decides
    #: whether the pipeline appends the Remotion + technical-QC stages at all.
    #: ``strict`` because lax mode turns ``"yes"``/``"on"``/``1`` into True, and a string typo
    #: must not silently start a multi-minute render.
    render_video: bool = Field(default=False, strict=True)
    #: Queue priority: lower runs first. Bounded 1..9 to keep the calendar readable.
    priority: int = Field(default=5, ge=1, le=9)
    #: Earliest production start (ISO-8601 UTC). Production scheduling only — never approval
    #: or publication: the approval gate always waits for a human, scheduled or not.
    scheduled_for: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    @field_validator("characters")
    @classmethod
    def _known_characters(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one character is required")
        return value


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=400)

class DiscoverTopicsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Operator-supplied extra titles to avoid, on top of the persisted avoid list.
    avoid: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=5, ge=1, le=10)


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
    #: Omitted/empty credential inputs *preserve* the stored reference, so a label or URL edit
    #: never silently unbinds a working credential. This flag is the only way to remove one, and
    #: it cannot be combined with a replacement.
    clear_credential: bool = False
    #: USD per million tokens. Absent, ``estimate_cost`` returns 0.0 by design rather than
    #: inventing a price — so every recorded cost would be 0.0 and the cost dashboard would show
    #: a real-looking zero. Setting these is what makes ``est_cost_usd`` a measurement.
    price_in_per_mtok: float | None = Field(default=None, ge=0, le=10_000)
    price_out_per_mtok: float | None = Field(default=None, ge=0, le=10_000)


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


class AgentBindingBody(BaseModel):
    """One per-agent provider binding. A credential is never part of a binding."""

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(min_length=1, max_length=64)
    primary: str | None = Field(default=None, min_length=1, max_length=64)
    fallback: list[str] = Field(default_factory=list, max_length=8)


class BindingsBody(BaseModel):
    """The full binding list replaces the current set; empty list clears all bindings."""

    model_config = ConfigDict(extra="forbid")

    bindings: list[AgentBindingBody] = Field(default_factory=list)


class StudioPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: dict[str, Any] = Field(default_factory=dict)


class SettingsBody(BaseModel):
    """Budget and render settings. Storage paths are deliberately absent: they are read-only and
    startup-only, so a request cannot move the operator's data directory."""
    model_config = ConfigDict(extra="forbid")
    budget: BudgetSettings | None = None
    render: RenderSettings | None = None
class BudgetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_daily_tokens: int | None = Field(default=None, gt=0)
    max_daily_cost_usd: float | None = Field(default=None, gt=0)
    unlimited: bool = False
class RenderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_free_ram_mib: int = Field(default=2048, gt=0)
    min_free_vram_mib: int = Field(default=1024, gt=0)
    allow_unmeasured_gpu: bool = False
class AgentBindingUpdate(BaseModel):
    """A per-agent binding. Immutable model/temperature/token overrides must reach the call."""
    model_config = ConfigDict(extra="forbid")
    primary: str | None = Field(default=None, max_length=64)
    fallback: list[str] = Field(default_factory=list, max_length=8)
    model: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    system_prompt_override: str | None = Field(default=None, max_length=8000)
class RetryRequestBody(BaseModel):
    """An operator's deliberate decision to re-attempt a call whose outcome is unknown."""
    model_config = ConfigDict(extra="forbid")
    operator: str = Field(min_length=1, max_length=120)
    confirm_possible_duplicate: bool = False
class PublishBody(BaseModel):
    """Which transport to publish through.

    Defaults to the offline stub because that is the only transport this build has. The value is
    a closed set, so a typo cannot silently fall back to the stub and record a real upload that
    never happened.
    """

    model_config = ConfigDict(extra="forbid")

    #: A plain string, validated by the route's resolver rather than by a Literal. A Literal makes
    #: pydantic produce a 422 whose ``detail`` is a list of dicts; the route's own refusal names
    #: the offending transport in one readable sentence, which is what an operator needs.
    transport: str = Field(default="stub", min_length=1, max_length=40)


class ReconcileBody(BaseModel):
    """Reconciliation takes no parameters yet; the body exists so the route is not a bare POST."""

    model_config = ConfigDict(extra="forbid")

    transport: str = Field(default="stub", min_length=1, max_length=40)


class MetadataBody(BaseModel):
    """A metadata edit. Every field is optional; omitted fields keep their current value.

    ``extra="forbid"`` is the important part: a typo in a field name must be a 422, not a silently
    ignored key that leaves the operator believing they changed something.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=50)
    category_id: str | None = Field(default=None, max_length=10)
    made_for_kids: bool | None = None
