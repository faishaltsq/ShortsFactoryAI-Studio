from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.config import ConfigStore
from packages.core.providers.registry import ProviderRegistry, ProviderSpec
from packages.core.providers.resolve import Binding, resolve_call
from packages.core.security.secretstore import CredentialRef, SecretStore


def test_stepfun_provider_spec_validation() -> None:
    spec = ProviderSpec(
        id="stepfun",
        label="StepFun Motion Coder",
        transport="openai_compat",
        base_url="http://127.0.0.1:20128/v1",
        model="om/step-5-preview",
        credential={"env": "NINEROUTER_KEY"},
        capabilities=["chat", "json_schema"],
        allow_private_hosts=True,
    )
    assert spec.id == "stepfun"
    assert spec.model == "om/step-5-preview"
    assert spec.capabilities == frozenset({"chat", "json_schema"})
    assert CredentialRef.parse(spec.credential).name == "NINEROUTER_KEY"


def test_stepfun_binding_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SecretStore(tmp_path)
    registry = ProviderRegistry(
        specs={
            "stepfun": ProviderSpec(
                id="stepfun",
                transport="openai_compat",
                base_url="http://127.0.0.1:20128/v1",
                model="om/step-5-preview",
                credential={"env": "NINEROUTER_KEY"},
                allow_private_hosts=True,
            )
        }
    )
    monkeypatch.setenv("NINEROUTER_KEY", "mock-secret-key")
    binding = Binding(primary="stepfun")
    call, _transport = resolve_call(
        binding=binding,
        registry=registry,
        store=store,
        transports={"openai_compat": object()},
    )
    assert call.provider == "stepfun"
    assert call.model == "om/step-5-preview"


def test_stepfun_in_studio_config() -> None:
    config_path = Path("config/studio.json")
    if not config_path.is_file():
        pytest.skip("local config/studio.json absent")
    store = ConfigStore(config_path)
    config = store.load()
    stepfun_entries = [p for p in config.providers if p.get("id") == "stepfun"]
    assert len(stepfun_entries) == 1
    entry = stepfun_entries[0]
    spec = ProviderSpec(**entry)
    assert spec.id == "stepfun"
    assert spec.model == "om/step-5-preview"
    assert spec.allow_private_hosts is True
    assert spec.capabilities == frozenset({"chat", "json_schema"})
    assert CredentialRef.parse(spec.credential).name == "NINEROUTER_KEY"

    registry = ProviderRegistry()
    registry.add(spec)
    assert registry.get("stepfun").id == "stepfun"
