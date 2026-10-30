"""M4 per-agent provider bindings: load, resolve, API round-trip.

A binding pins which provider an agent uses. The dangerous failure is the silent one — a
binding that names an unknown agent, or a fallback list that is never consulted in the
declared order — so each test names one way the system could lie.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.providers.usage import Budget


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


def _app(tmp_path, config: dict | None):
    return create_app(AppState.build(_settings(tmp_path, config), budget=Budget()))


def _live_spec(tmp_path, spec_id: str):
    """Register one enabled openai_compat provider backed by the shared stub server."""
    from packages.core.providers.base import Capability
    from packages.core.providers.registry import ProviderSpec

    return ProviderSpec(
        id=spec_id,
        label=spec_id,
        transport="openai_compat",
        base_url="http://127.0.0.1:9/v1",
        model="stub-model",
        capabilities=[Capability.CHAT, Capability.JSON_SCHEMA],
        enabled=True,
    )


# -- config load ---------------------------------------------------------------------------


def test_bindings_load_from_studio_json(tmp_path):
    state = AppState.build(
        _settings(
            tmp_path,
            {"bindings": [{"agent": "ResearchAgent", "primary": "router-a"}]},
        ),
        budget=Budget(),
    )
    assert state.bindings == {"ResearchAgent": {"primary": "router-a", "fallback": []}}


def test_binding_overrides_survive_restart_and_reach_resolution(tmp_path):
    from packages.core.orchestration.pipeline import _binding_for

    state = AppState.build(
        _settings(
            tmp_path,
            {
                "bindings": [
                    {
                        "agent": "ScriptAgent",
                        "primary": "mock",
                        "fallback": [],
                        "model": "bound-model",
                        "temperature": 0.25,
                        "max_tokens": 2048,
                        "system_prompt_override": "Use the operator prompt.",
                    }
                ]
            },
        ),
        budget=Budget(),
    )

    binding = _binding_for(state, "ScriptAgent")
    assert binding.model == "bound-model"
    assert binding.temperature == 0.25
    assert binding.max_tokens == 2048
    assert state.bindings["ScriptAgent"]["system_prompt_override"] == "Use the operator prompt."


def test_the_prompt_override_reaches_the_call_and_the_provenance_hash(tmp_path):
    """The override is what the model is sent, not a string the provenance happens to hash.

    ``_with_provenance`` hashes the prompt it believes was sent. If the call still sends the
    class constant, the artifact records a hash of a prompt nobody used — provenance that is a
    claim about a run rather than a fact about it.
    """
    from packages.core.providers.mock import MockProvider

    sent: list[str] = []

    class Recording(MockProvider):
        def complete(self, call, *, system, user, task):  # type: ignore[override]
            sent.append(system)
            return super().complete(call, system=system, user=user, task=task)

    state = AppState.build(
        _settings(
            tmp_path,
            {
                "bindings": [
                    {
                        "agent": "ScriptAgent",
                        "primary": "mock",
                        "system_prompt_override": "Use the operator prompt.",
                    }
                ]
            },
        ),
        budget=Budget(),
    )
    state.transports["mock"] = Recording()
    state.registry.specs["mock"].enabled = True

    job = state.store.create(title="Uji", payload={"provider_mode": "mock"})
    from packages.core.agents.registry import AGENTS
    from packages.core.orchestration.pipeline import _context, _with_provenance

    ctxp = _context(state, job, "ScriptAgent")
    agent = AGENTS["ScriptAgent"](ctxp)
    artifact = agent.produce(task="script", topic="sejarah", duration_s=45, language="id")

    assert sent, "the agent never called the provider"
    assert sent[0] == "Use the operator prompt."
    # The provenance must hash the same string that was actually sent.
    from packages.core.prompts import sha256

    provenance = _with_provenance(artifact.to_json(), "ScriptAgent", ctxp, state)["provenance"]
    assert provenance["prompt_sha256"] == sha256("Use the operator prompt.")


def test_unknown_agent_in_config_raises_at_build(tmp_path):
    with pytest.raises(ValueError, match="unknown agent"):
        AppState.build(
            _settings(tmp_path, {"bindings": [{"agent": "NotAnAgent", "primary": "x"}]}),
            budget=Budget(),
        )


def test_malformed_binding_is_skipped_with_a_note_event(tmp_path):
    state = AppState.build(
        _settings(
            tmp_path,
            {"bindings": ["ResearchAgent", {"agent": "ScriptAgent", "primary": 7}, {"agent": "ResearchAgent", "primary": "ok"}]},
        ),
        budget=Budget(),
    )
    # the two malformed entries are skipped; the well-formed one still binds
    assert state.bindings == {"ResearchAgent": {"primary": "ok", "fallback": []}}
    notes = [
        event
        for event in state.events.recent_per_job(limit=10).get("studio-config", [])
        if "binding dilewati" in event.description
    ]
    assert len(notes) == 2, "each skipped binding must persist a note, never vanish silently"


# -- resolution -----------------------------------------------------------------------------


def test_bound_primary_is_the_provider_the_agent_sees(tmp_path):
    from packages.core.orchestration.pipeline import _primary_for

    app = _app(tmp_path, None)
    state = app.state.studio
    spec = _live_spec(tmp_path, "router-a")
    state.registry.add(spec)
    state.bindings["ResearchAgent"] = {"primary": "router-a", "fallback": []}
    assert _primary_for(state, "ResearchAgent") == "router-a"
    # an unbound agent still resolves dynamically: first enabled non-mock provider
    assert _primary_for(state, "ScriptAgent") == "router-a"


def test_fallback_order_is_the_declaration_order(tmp_path):
    from packages.core.orchestration.pipeline import _fallback_for

    app = _app(tmp_path, None)
    state = app.state.studio
    state.bindings["ScriptAgent"] = {"primary": "a", "fallback": ["b", "c"]}
    assert _fallback_for(state, "ScriptAgent") == ["b", "c"]
    assert _fallback_for(state, "QualityAgent") == []


# -- API -------------------------------------------------------------------------------------


def test_bindings_round_trip_through_the_api(tmp_path):
    client = TestClient(_app(tmp_path, None))
    body = {"bindings": [{"agent": "ScriptAgent", "primary": "router-a", "fallback": ["b"]}]}
    response = client.put("/api/providers/bindings", json=body)
    assert response.status_code == 200, response.text
    listed = client.get("/api/providers").json()
    assert {"agent": "ScriptAgent", "primary": "router-a", "fallback": ["b"]} in listed[
        "bindings"
    ], "a PUT binding must be visible in the next GET"


def test_api_rejects_unknown_agent(tmp_path):
    client = TestClient(_app(tmp_path, None))
    response = client.put(
        "/api/providers/bindings", json={"bindings": [{"agent": "Ghost", "primary": "x"}]}
    )
    assert response.status_code == 422
