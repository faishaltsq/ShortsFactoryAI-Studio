"""Production presets: one named choice that binds every LLM agent at once.

The dangerous failures are all silent ones, so each test names one way the studio could lie:

* a preset that quietly routes an agent to another model family (the reroute the preset exists to
  prevent),
* an operator's explicit fallback opt-in that vanishes on the next restart,
* a preset offered as a choice while its provider is missing or capability-poor,
* a binding written into memory only, so a restart lands on different routing than the UI showed.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.config import ConfigError, ConfigStore, StudioConfig
from apps.api.main import create_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.agents.registry import AGENTS
from packages.core.providers.base import Capability
from packages.core.providers.presets import (
    LLM_AGENTS,
    PRESETS,
    PresetError,
    apply_preset,
    get_preset,
    preset_ids,
    preset_view,
)
from packages.core.providers.registry import ProviderRegistry, ProviderSpec
from packages.core.providers.usage import Budget

STEPFUN_MODEL = "om/step-5-preview"


def _stepfun(**overrides) -> ProviderSpec:
    fields: dict = {
        "id": "stepfun",
        "transport": "openai_compat",
        "base_url": "http://127.0.0.1:20128/v1",
        "model": STEPFUN_MODEL,
        "capabilities": [Capability.CHAT, Capability.JSON_SCHEMA],
        "allow_private_hosts": True,
    }
    fields.update(overrides)
    return ProviderSpec(**fields)


def _registry(*specs: ProviderSpec) -> ProviderRegistry:
    registry = ProviderRegistry()
    for spec in specs:
        registry.add(spec)
    return registry


def _settings(tmp_path, config: dict | None):
    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    if config is not None:
        settings.studio_config.parent.mkdir(parents=True, exist_ok=True)
        settings.studio_config.write_text(json.dumps(config), encoding="utf-8")
    return settings


# -- the preset shape ---------------------------------------------------------------------


def test_the_preset_binds_every_llm_agent_and_nothing_else() -> None:
    """Every model-calling agent is rebound; a deterministic agent is never written a provider.

    A binding on ``AudioAgent`` would be a lie the API then has to display, and an agent left out
    would keep the operator's previous routing while the UI reported the preset as active.
    """
    bindings, gaps = apply_preset("full-stepfun-v2", _registry(_stepfun()))
    assert gaps == []
    assert set(bindings) == set(LLM_AGENTS)
    assert set(bindings) == set(AGENTS)
    assert {entry["primary"] for entry in bindings.values()} == {"stepfun"}


def test_the_preset_sends_no_model_name_of_its_own() -> None:
    """``model=None`` means "the configured provider's declared model", not "provider default".

    A preset that pinned a model name would send a model the operator's endpoint may not serve —
    exactly the 404 this file exists to prevent. ``resolve_call`` fills the declared model in.
    """
    bindings, _ = apply_preset("full-stepfun-v2", _registry(_stepfun()))
    assert {entry["model"] for entry in bindings.values()} == {None}

    from packages.core.providers.resolve import Binding, resolve_call

    call, _ = resolve_call(
        binding=Binding(agent="MotionCoderAgent", primary="stepfun"),
        registry=_registry(_stepfun()),
        store=None,  # a credential-free provider resolves without a store
        transports={"openai_compat": object()},
    )
    assert call.model == STEPFUN_MODEL


def test_unknown_preset_id_is_refused_not_defaulted() -> None:
    """A typo in ``studio.json`` must not leave the studio on some default routing."""
    assert get_preset("full-stepfun-v2").id in preset_ids()
    with pytest.raises(PresetError, match="unknown production preset"):
        get_preset("full-stepfun-3")


def test_a_preset_without_its_provider_is_refused() -> None:
    with pytest.raises(PresetError, match="is not configured"):
        apply_preset("full-stepfun-v2", _registry())


# -- silent cross-family routing ------------------------------------------------------------


def test_fallback_is_off_unless_the_operator_asks_for_it() -> None:
    """The preset's whole point: an unreachable endpoint fails loudly, it does not reroute."""
    registry = _registry(_stepfun(), _stepfun(id="gemini", model="gemini-3.8-flash"))
    bindings, _ = apply_preset("full-stepfun-v2", registry)
    assert {tuple(entry["fallback"]) for entry in bindings.values()} == {()}
    assert PRESETS["full-stepfun-v2"].allow_fallback is False


def test_naming_a_fallback_list_is_itself_the_opt_in() -> None:
    """An explicit non-empty list cannot be silently discarded by an omitted ``allow_fallback``.

    That combination — "here are the fallbacks" plus "you did not also say true" — used to drop
    the list and keep the preset's own default of off.
    """
    registry = _registry(_stepfun(), _stepfun(id="gemini", model="gemini-3.8-flash"))
    bindings, _ = apply_preset("full-stepfun-v2", registry, fallback=["gemini"])
    assert {tuple(entry["fallback"]) for entry in bindings.values()} == {("gemini",)}


def test_fallback_stays_off_when_explicitly_disabled_beside_a_list() -> None:
    registry = _registry(_stepfun(), _stepfun(id="gemini", model="gemini-3.8-flash"))
    bindings, _ = apply_preset(
        "full-stepfun-v2", registry, allow_fallback=False, fallback=["gemini"]
    )
    assert {tuple(entry["fallback"]) for entry in bindings.values()} == {()}


# -- capability gaps -----------------------------------------------------------------------


def test_a_capability_gap_is_reported_never_papered_over() -> None:
    """A provider that cannot serve ``chat`` yields a gap, not a softened binding.

    The gap names the agent and the missing capability, so an operator can fix the endpoint before
    a job discovers it mid-render.
    """
    registry = _registry(_stepfun(capabilities=[Capability.VISION]))
    bindings, gaps = apply_preset("full-stepfun-v2", registry)
    assert len(bindings) == len(LLM_AGENTS), "every agent still gets the preset's provider"
    assert gaps, "a provider that cannot chat must be reported"
    assert any("chat" in gap for gap in gaps)
    assert all("Capability." not in gap for gap in gaps), "report values, not enum reprs"


def test_capability_names_are_values_not_enum_reprs() -> None:
    """``str(Capability.CHAT)`` is ``'Capability.CHAT'`` on 3.11+; a naive ``str()`` would make
    every provider look incapable of ``chat`` and every preset unserviceable."""
    view = preset_view(get_preset("full-stepfun-v2"), _registry(_stepfun()))
    assert "chat" in view["provider_capabilities"]
    assert view["serviceable"] is True
    assert all("Capability." not in name for name in view["provider_capabilities"])


def test_a_missing_capability_makes_the_preset_unserviceable() -> None:
    view = preset_view(get_preset("full-stepfun-v2"), _registry(_stepfun(capabilities=[])))
    assert view["serviceable"] is False


def test_a_disabled_provider_makes_the_preset_unserviceable() -> None:
    """Configured but switched off is not available; offering it would be a choice the studio
    cannot honour."""
    view = preset_view(get_preset("full-stepfun-v2"), _registry(_stepfun(enabled=False)))
    assert view["provider_configured"] is True
    assert view["provider_enabled"] is False
    assert view["serviceable"] is False


def test_the_view_carries_no_credential_material() -> None:
    registry = _registry(_stepfun(credential={"env": "NINEROUTER_KEY"}))
    view = preset_view(get_preset("full-stepfun-v2"), registry)
    flattened = json.dumps(view)
    assert "NINEROUTER_KEY" not in flattened
    assert "credential" not in flattened


# -- model override ----------------------------------------------------------------------


def test_a_model_outside_the_stepfun_family_is_refused() -> None:
    with pytest.raises(PresetError, match="not a known"):
        apply_preset("full-stepfun-v2", _registry(_stepfun()), model="gpt-5-omega")


def test_an_explicit_stepfun_model_reaches_every_binding() -> None:
    bindings, _ = apply_preset(
        "full-stepfun-v2", _registry(_stepfun()), model="om/step-5-preview"
    )
    assert {entry["model"] for entry in bindings.values()} == {STEPFUN_MODEL}


# -- persisted configuration --------------------------------------------------------------


def test_config_round_trips_the_preset_and_its_fallback_opt_in() -> None:
    """The preset is re-expanded on every load, so an opt-in that lived only in memory would
    disappear on the next restart while the UI still showed it."""
    config = StudioConfig.from_json(
        {
            "version": 1,
            "preset": "full-stepfun-v2",
            "preset_fallback": ["gemini"],
            "bindings": [{"agent": "MotionCoderAgent", "primary": "old-router"}],
        }
    )
    assert config.preset == "full-stepfun-v2"
    assert config.preset_fallback == ["gemini"]
    again = StudioConfig.from_json(config.to_json())
    assert (again.preset, again.preset_fallback) == (config.preset, config.preset_fallback)

    absent = StudioConfig.from_json({"version": 1})
    assert absent.preset is None and absent.preset_fallback == []
    assert "preset" not in absent.to_json(), "an unset preset must not be written"


def test_malformed_preset_fields_are_refused() -> None:
    with pytest.raises(ConfigError, match="preset"):
        StudioConfig.from_json({"version": 1, "preset": 5})
    with pytest.raises(ConfigError, match="preset_fallback"):
        StudioConfig.from_json({"version": 1, "preset_fallback": ["a", 3]})


def test_config_store_persists_a_preset_across_a_reload(tmp_path) -> None:
    path = tmp_path / "config" / "studio.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = ConfigStore(path)
    config = store.load()
    config.preset = "full-stepfun-v2"
    config.preset_fallback = ["gemini"]
    store.save(config)

    reloaded = ConfigStore(path).load()
    assert reloaded.preset == "full-stepfun-v2"
    assert reloaded.preset_fallback == ["gemini"]


# -- the preset reaches the running studio --------------------------------------------------


def _studio_json(preset: str | None, *, fallback: list[str] | None = None) -> dict:
    config: dict = {
        "providers": [
            {
                "id": "stepfun",
                "transport": "openai_compat",
                "base_url": "http://127.0.0.1:9/v1",
                "model": STEPFUN_MODEL,
                "capabilities": ["chat", "json_schema"],
                "enabled": True,
            },
            {
                "id": "gemini",
                "transport": "openai_compat",
                "base_url": "http://127.0.0.1:9/v1",
                "model": "gemini-3.8-flash",
                "capabilities": ["chat", "json_schema"],
                "enabled": True,
            },
        ],
        "bindings": [{"agent": "MotionCoderAgent", "primary": "gemini"}],
    }
    if preset is not None:
        config["preset"] = preset
    if fallback:
        config["preset_fallback"] = fallback
    return config


def test_a_preset_wins_over_a_stale_per_agent_binding(tmp_path) -> None:
    """Otherwise the UI reports the preset active while one agent keeps its old provider."""
    state = AppState.build(_settings(tmp_path, _studio_json("full-stepfun-v2")), budget=Budget())
    assert state.preset == "full-stepfun-v2"
    assert state.bindings["MotionCoderAgent"]["primary"] == "stepfun"
    assert state.bindings["MotionCoderAgent"]["fallback"] == []


def test_no_preset_leaves_the_operator_bindings_alone(tmp_path) -> None:
    state = AppState.build(_settings(tmp_path, _studio_json(None)), budget=Budget())
    assert state.preset is None
    assert state.bindings["MotionCoderAgent"]["primary"] == "gemini"


def test_a_preset_whose_provider_is_absent_is_skipped_with_a_note(tmp_path) -> None:
    """Silently dropping it would let the studio keep running on routing the operator replaced,
    and raising would stop the studio from starting over a warning."""
    config = _studio_json("full-stepfun-v2")
    config["providers"] = [p for p in config["providers"] if p["id"] != "stepfun"]
    state = AppState.build(_settings(tmp_path, config), budget=Budget())
    assert state.preset is None
    assert state.bindings["MotionCoderAgent"]["primary"] == "gemini", "bindings survive"
    events = state.events.page(after=0, limit=50)
    notes = [event.description or "" for event in events]
    assert any(
        "full-stepfun-v2" in note and "dilewati" in note for note in notes
    ), f"a skipped preset must leave a note, got {notes}"


def test_a_persisted_fallback_opt_in_survives_a_restart(tmp_path) -> None:
    config = _studio_json("full-stepfun-v2", fallback=["gemini"])
    state = AppState.build(_settings(tmp_path, config), budget=Budget())
    assert state.bindings["MotionCoderAgent"]["fallback"] == ["gemini"]


# -- HTTP surface -------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(AppState.build(_settings(tmp_path, _studio_json(None)), budget=Budget()))
    )


def test_get_presets_lists_them_with_serviceability(client) -> None:
    body = client.get("/api/presets").json()
    ids = {entry["id"] for entry in body["presets"]}
    assert "full-stepfun-v2" in ids
    assert body["active"] is None
    entry = next(e for e in body["presets"] if e["id"] == "full-stepfun-v2")
    assert entry["serviceable"] is True
    assert entry["allow_fallback"] is False
    assert entry["provider"] == "stepfun"
    assert entry["agents"] == sorted(LLM_AGENTS)


def test_activating_a_preset_rebinds_every_agent_and_persists(client, tmp_path) -> None:
    response = client.put("/api/presets", json={"preset": "full-stepfun-v2"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preset"] == "full-stepfun-v2"
    assert {b["primary"] for b in body["bindings"].values()} == {"stepfun"}

    providers = client.get("/api/providers").json()
    assert providers["preset"] == "full-stepfun-v2"

    persisted = ConfigStore(tmp_path / "config" / "studio.json").load()
    assert persisted.preset == "full-stepfun-v2"
    assert persisted.bindings, "the rebind is durable, not memory-only"


def test_activating_an_unknown_preset_is_422(client) -> None:
    response = client.put("/api/presets", json={"preset": "no-such-preset"})
    assert response.status_code == 422


def test_activating_an_unserviceable_preset_is_422(tmp_path) -> None:
    """Offering routing the studio cannot honour turns the first job into a mystery failure."""
    config = _studio_json(None)
    for provider in config["providers"]:
        if provider["id"] == "stepfun":
            provider["capabilities"] = ["vision"]  # present and enabled, but cannot chat
    client = TestClient(
        create_app(AppState.build(_settings(tmp_path, config), budget=Budget()))
    )
    response = client.put("/api/presets", json={"preset": "full-stepfun-v2"})
    assert response.status_code == 422, response.text
    assert "serviceable" in response.text, response.text

def test_activating_a_preset_whose_provider_is_missing_is_422(tmp_path) -> None:
    config = _studio_json(None)
    config["providers"] = [p for p in config["providers"] if p["id"] != "stepfun"]
    client = TestClient(
        create_app(AppState.build(_settings(tmp_path, config), budget=Budget()))
    )
    response = client.put("/api/presets", json={"preset": "full-stepfun-v2"})
    assert response.status_code == 422, response.text
    assert "not configured" in response.text, response.text


def test_activating_a_preset_with_an_unknown_fallback_is_422(client) -> None:
    response = client.put(
        "/api/presets", json={"preset": "full-stepfun-v2", "fallback": ["ghost"]}
    )
    assert response.status_code == 422


def test_clearing_the_preset_leaves_the_bindings_in_place(client) -> None:
    client.put("/api/presets", json={"preset": "full-stepfun-v2"})
    response = client.put("/api/presets", json={"preset": None})
    assert response.status_code == 200
    assert response.json()["preset"] is None
    assert client.get("/api/providers").json()["preset"] is None


def test_activating_a_preset_requires_a_token_when_one_is_configured(tmp_path) -> None:
    """A whole-studio routing change is a mutating route like any other."""
    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
        api_token="s3cret",
    ).ensure()
    settings.studio_config.parent.mkdir(parents=True, exist_ok=True)
    settings.studio_config.write_text(json.dumps(_studio_json(None)), encoding="utf-8")
    client = TestClient(create_app(AppState.build(settings, budget=Budget())))
    assert client.put("/api/presets", json={"preset": "full-stepfun-v2"}).status_code == 401
    ok = client.put(
        "/api/presets",
        json={"preset": "full-stepfun-v2"},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert ok.status_code == 200, ok.text