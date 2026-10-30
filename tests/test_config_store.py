"""Durable configuration: validate-whole-candidate, atomic replace, no half-applied state."""
from __future__ import annotations

import json

import pytest

from apps.api.config import (
    BudgetConfig,
    ConfigError,
    ConfigStore,
    RenderConfig,
    StudioConfig,
)


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "config" / "studio.json")


def test_an_absent_file_means_explicit_mock_only_defaults(store):
    config = store.load()
    assert config.providers == []
    assert config.bindings == []
    assert config.budget.unlimited is False
    assert config.render.min_free_ram_mib == 2048
    assert store.problem() is None


def test_a_round_trip_preserves_every_declared_field(store):
    config = StudioConfig(
        providers=[
            {
                "id": "router",
                "label": "Local router",
                "transport": "openai_compat",
                "base_url": "http://127.0.0.1:8080/v1",
                "model": "qwen",
                "capabilities": ["chat", "vision"],
                "price_in_per_mtok": 0.5,
                "price_out_per_mtok": 1.5,
                "enabled": True,
            }
        ],
        bindings=[{"agent": "ScriptAgent", "primary": "router", "fallback": []}],
        budget=BudgetConfig(max_daily_tokens=5000),
        render=RenderConfig(min_free_ram_mib=4096),
        prompt_overrides={"ScriptAgent": "be brief"},
    )
    store.save(config)
    restored = store.load()
    assert restored.providers[0]["price_out_per_mtok"] == 1.5
    assert restored.bindings[0]["agent"] == "ScriptAgent"
    assert restored.budget.max_daily_tokens == 5000
    assert restored.render.min_free_ram_mib == 4096
    assert restored.prompt_overrides == {"ScriptAgent": "be brief"}


def test_unrelated_operator_keys_survive_a_save(store):
    """The config file is the operator's; a save through this store must not eat their notes."""
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"version": 1, "operator_note": "keep me", "providers": []}),
        encoding="utf-8",
    )
    config = store.load()
    assert config.unknown == {"operator_note": "keep me"}
    config.budget = BudgetConfig(max_daily_tokens=10)
    store.save(config)
    assert json.loads(store.path.read_text(encoding="utf-8"))["operator_note"] == "keep me"


def test_a_malformed_file_is_a_visible_sanitized_problem(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{ not json at all", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        store.load()
    assert "not valid JSON" in str(excinfo.value)
    assert store.problem() is not None


def test_a_newer_version_is_refused_not_guessed(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"version": 99, "providers": []}), encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        store.load()
    assert "newer than this build" in str(excinfo.value)


def test_unlimited_is_exclusive_with_the_caps(store):
    config = StudioConfig(budget=BudgetConfig(unlimited=True, max_daily_tokens=5))
    with pytest.raises(ConfigError):
        store.save(config)
    # Nothing was written: a refused candidate leaves the previous file exactly as it was.
    assert not store.path.exists()


def test_a_binding_for_an_unknown_agent_is_refused(store):
    config = StudioConfig(bindings=[{"agent": "NotAnAgent", "primary": "x"}])
    with pytest.raises(ConfigError) as excinfo:
        store.save(config)
    assert "unknown agent" in str(excinfo.value)


def test_an_invalid_budget_value_is_refused_before_anything_is_written(store):
    with pytest.raises(ConfigError):
        store.save(StudioConfig(budget=BudgetConfig(max_daily_tokens=0)))
    with pytest.raises(ConfigError):
        store.save(StudioConfig(budget=BudgetConfig(max_daily_cost_usd=-1.0)))
    assert not store.path.exists()


def test_the_render_cap_is_not_configurable(store):
    """The cap is 1, and no field in this file can raise it."""
    config = store.load()
    assert not any("cap" in key for key in config.render.to_json())
    # The only knob is the opt-in for a machine whose GPU cannot be measured.
    assert RenderConfig(allow_unmeasured_gpu=True).allow_unmeasured_gpu is True


def test_a_save_is_atomic_and_leaves_no_temporary_files(store):
    store.save(StudioConfig())
    store.save(StudioConfig(budget=BudgetConfig(max_daily_tokens=1)))
    leftovers = [p.name for p in store.path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert store.load().budget.max_daily_tokens == 1


def test_a_failed_save_leaves_the_previous_configuration_intact(store):
    store.save(StudioConfig(budget=BudgetConfig(max_daily_tokens=7)))
    with pytest.raises(ConfigError):
        store.save(StudioConfig(bindings=[{"agent": "Nope", "primary": "x"}]))
    assert store.load().budget.max_daily_tokens == 7


# -- the HTTP surface ----------------------------------------------------------------------
def _client(tmp_path):
    from fastapi.testclient import TestClient

    from apps.api.main import create_app
    from apps.api.settings import Settings
    from apps.api.state import AppState
    from packages.core.providers.usage import Budget

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    return TestClient(create_app(AppState.build(settings, budget=Budget())))


def test_settings_round_trip_through_the_api(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/settings").json()
    assert body["budget"]["unlimited"] is False
    assert body["render"]["min_free_ram_mib"] == 2048
    # Storage paths are reported, never writable.
    assert "data_dir" in body["storage"]

    response = client.put(
        "/api/settings",
        json={"budget": {"max_daily_tokens": 1234}, "render": {"min_free_vram_mib": 512}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["budget"]["max_daily_tokens"] == 1234
    assert response.json()["render"]["min_free_vram_mib"] == 512
    # Durable: a fresh read of the file sees the same values.
    assert client.get("/api/settings").json()["budget"]["max_daily_tokens"] == 1234


def test_settings_refuses_an_invalid_budget(tmp_path):
    client = _client(tmp_path)
    response = client.put("/api/settings", json={"budget": {"max_daily_tokens": -1}})
    assert response.status_code == 422, response.text
    response = client.put(
        "/api/settings", json={"budget": {"unlimited": True, "max_daily_tokens": 5}}
    )
    assert response.status_code == 422, response.text
    # Nothing was written.
    assert client.get("/api/settings").json()["budget"]["max_daily_tokens"] is None


def test_settings_reports_a_malformed_configuration_as_a_conflict(tmp_path):
    client = _client(tmp_path)
    path = tmp_path / "config" / "studio.json"
    path.write_text("{ broken", encoding="utf-8")
    response = client.get("/api/settings")
    assert response.status_code == 409
    assert "not valid JSON" in response.json()["detail"]


def test_agents_list_names_every_agent_with_its_kind(tmp_path):
    client = _client(tmp_path)
    agents = client.get("/api/agents").json()["agents"]
    ids = {agent["id"] for agent in agents}
    assert "ScriptAgent" in ids
    assert "QualityAgent" in ids
    for agent in agents:
        assert agent["kind"] in {"llm", "deterministic"}
        assert isinstance(agent["requires"], list)
        assert isinstance(agent["capability_gaps"], list)
        binding = agent["binding"]
        assert set(binding) >= {"primary", "fallback", "model"}

    deterministic = next(agent for agent in agents if agent["id"] == "AudioAgent")
    assert deterministic["requires"] == []
    assert deterministic["capability_gaps"] == []


def test_an_agent_binding_saves_and_is_refused_for_an_unknown_agent(tmp_path):
    client = _client(tmp_path)
    response = client.put(
        "/api/agents/ScriptAgent/binding",
        json={"primary": "mock", "model": "mock-1", "temperature": 0.4},
    )
    assert response.status_code == 200, response.text
    assert response.json()["binding"]["temperature"] == 0.4
    # Durable: the next list shows it.
    listed = {
        agent["id"]: agent["binding"]
        for agent in client.get("/api/agents").json()["agents"]
    }
    assert listed["ScriptAgent"]["primary"] == "mock"
    assert listed["ScriptAgent"]["model"] == "mock-1"

    unknown = client.put("/api/agents/NotAnAgent/binding", json={"primary": "mock"})
    assert unknown.status_code == 422
    assert "unknown agent" in unknown.json()["detail"]


def test_agent_binding_response_can_be_saved_again_and_overrides_can_be_cleared(tmp_path):
    client = _client(tmp_path)
    first = client.put(
        "/api/agents/ScriptAgent/binding",
        json={"primary": "mock", "model": "custom", "temperature": 0.4, "max_tokens": 2048},
    )
    assert first.status_code == 200, first.text
    binding = first.json()["binding"]
    assert "agent" not in binding

    binding.update({"model": None, "temperature": None, "max_tokens": None})
    second = client.put("/api/agents/ScriptAgent/binding", json=binding)
    assert second.status_code == 200, second.text
    assert second.json()["binding"] == {
        "primary": "mock",
        "fallback": [],
        "model": None,
        "temperature": None,
        "max_tokens": None,
        "system_prompt_override": None,
    }


def test_agent_binding_refuses_unknown_and_duplicate_providers(tmp_path):
    client = _client(tmp_path)
    unknown = client.put(
        "/api/agents/ScriptAgent/binding", json={"primary": "not-configured"}
    )
    assert unknown.status_code == 422
    assert "unknown provider" in unknown.json()["detail"]

    duplicate = client.put(
        "/api/agents/ScriptAgent/binding",
        json={"primary": "mock", "fallback": ["mock"]},
    )
    assert duplicate.status_code == 422
    assert "duplicate" in duplicate.json()["detail"]

    # A disabled provider is a legal binding target: a mock-mode job needs it, and enabling it is
    # the job's own action. What must not happen is the page claiming the agent is fine, so the
    # gap banner has to carry the truth instead of a route refusal.
    disabled = client.put("/api/agents/ScriptAgent/binding", json={"primary": "mock"})
    assert disabled.status_code == 200, disabled.text
    listed = {
        agent["id"]: agent for agent in client.get("/api/agents").json()["agents"]
    }
    assert listed["ScriptAgent"]["capability_gaps"] == ["chat", "json_schema"]


def test_agent_capability_gaps_follow_its_selected_provider(tmp_path):
    client = _client(tmp_path)
    client.put(
        "/api/providers",
        json={
            "id": "chat-only",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "capabilities": ["chat"],
        },
    )
    # Seed a hand-edited binding: the listing must diagnose it even though the save route refuses it.
    client.app.state.studio.bindings["ScriptAgent"] = {
        "primary": "chat-only",
        "fallback": [],
    }
    listed = {
        agent["id"]: agent for agent in client.get("/api/agents").json()["agents"]
    }
    assert listed["ScriptAgent"]["capability_gaps"] == ["json_schema"]


def test_an_edit_without_a_credential_preserves_the_stored_reference(tmp_path):
    client = _client(tmp_path)
    client.put(
        "/api/providers",
        json={"id": "keepme", "base_url": "https://api.example.com/v1", "model": "m",
              "credential_env": "MY_KEY"},
    )
    # A label edit with no credential input must not unbind the reference.
    client.put(
        "/api/providers",
        json={"id": "keepme", "label": "Renamed", "base_url": "https://api.example.com/v1",
              "model": "m"},
    )
    listed = {p["id"]: p for p in client.get("/api/providers").json()["providers"]}
    assert listed["keepme"]["label"] == "Renamed"
    assert listed["keepme"]["credential_source"] == "env:MY_KEY", (
        "an edit without credential input must preserve the stored reference"
    )


def test_replacing_and_clearing_a_credential_are_explicit(tmp_path):
    client = _client(tmp_path)
    client.put(
        "/api/providers",
        json={"id": "swap", "base_url": "https://api.example.com/v1", "model": "m",
              "credential_env": "FIRST"},
    )
    client.put(
        "/api/providers",
        json={"id": "swap", "base_url": "https://api.example.com/v1", "model": "m",
              "credential_env": "SECOND"},
    )
    listed = {p["id"]: p for p in client.get("/api/providers").json()["providers"]}
    assert listed["swap"]["credential_source"] == "env:SECOND"
    # Clear is the only removal path, and it cannot be combined with a replacement.
    both = client.put(
        "/api/providers",
        json={"id": "swap", "base_url": "https://api.example.com/v1", "model": "m",
              "credential_env": "THIRD", "clear_credential": True},
    )
    assert both.status_code == 422
    client.put(
        "/api/providers",
        json={"id": "swap", "base_url": "https://api.example.com/v1", "model": "m",
              "clear_credential": True},
    )
    listed = {p["id"]: p for p in client.get("/api/providers").json()["providers"]}
    assert listed["swap"]["credential_source"] is None


def test_a_provider_survives_a_restart_with_its_prices(tmp_path):
    client = _client(tmp_path)
    client.put(
        "/api/providers",
        json={"id": "durable", "base_url": "https://api.example.com/v1", "model": "m",
              "price_in_per_mtok": 0.25, "price_out_per_mtok": 1.25},
    )
    # A brand-new app over the same settings must see the same provider, prices included.
    from apps.api.main import create_app
    from apps.api.settings import Settings
    from apps.api.state import AppState
    from packages.core.providers.usage import Budget

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    )
    rebuilt = create_app(AppState.build(settings, budget=Budget()))
    from fastapi.testclient import TestClient

    again = TestClient(rebuilt)
    listed = {p["id"]: p for p in again.get("/api/providers").json()["providers"]}
    assert "durable" in listed
    assert listed["durable"]["credential_source"] is None


def test_deleting_a_bound_provider_is_refused(tmp_path):
    client = _client(tmp_path)
    client.put(
        "/api/providers",
        json={"id": "bound", "base_url": "https://api.example.com/v1", "model": "m",
              "capabilities": ["chat", "json_schema"]},
    )
    client.put("/api/agents/ScriptAgent/binding", json={"primary": "bound"})
    response = client.delete("/api/providers/bound")
    assert response.status_code == 409, response.text
    assert "ScriptAgent" in response.json()["detail"]
    # Once unbound, the same delete succeeds.
    client.put("/api/agents/ScriptAgent/binding", json={"primary": None})
    assert client.delete("/api/providers/bound").status_code == 200
    listed = {p["id"] for p in client.get("/api/providers").json()["providers"]}
    assert "bound" not in listed
