"""Topic discovery: pure scoring, persistence, API route, and the recorded live path."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app as build_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.providers.registry import ProviderSpec
from packages.core.providers.usage import Budget

from .stub_server import StubServer


@pytest.fixture
def stub():
    with StubServer() as server:
        yield server

# --------------------------------------------------------------------------- pure scoring


def test_propose_topics_drops_avoid_list_hits():
    from packages.core.orchestration.discovery import propose_topics

    history = [
        {"title": "Fakta unik octopus"},
        {"title": "Fakta lain octopus"},
    ]
    out = propose_topics(history=history, avoid=["Sisi lain fakta"], limit=5)
    titles = [c["title"] for c in out]
    assert "Sisi lain fakta" not in titles, "an avoid-list hit must be dropped, not scored"
    assert "Sisi lain octopus" in titles, "the un-avoided theme still proposes"


def test_propose_topics_is_deterministic():
    from packages.core.orchestration.discovery import propose_topics

    history = [{"title": f"Topik produksi nomor {i}"} for i in range(6)]
    first = propose_topics(history=history, avoid=[], limit=3)
    second = propose_topics(history=history, avoid=[], limit=3)
    assert first == second, "mock discovery must be reproducible"
    assert len(first) <= 3
    for candidate in first:
        assert {"title", "angle", "why"} <= set(candidate)


def test_propose_scores_repeat_themes_higher():
    from packages.core.orchestration.discovery import propose_topics

    history = [
        {"title": "Ruang dalam kota"},
        {"title": "Ruang hijau kota"},
        {"title": "Kucing mengantuk"},
    ]
    out = propose_topics(history=history, avoid=[], limit=3)
    # "ruang" and "kota" each appear twice; everything else once (alphabetical tie-break). The
    # repeated themes must lead; nothing proposes an avoid-list repeat.
    titles = [c["title"] for c in out]
    assert titles, "a nonempty history must yield candidates"
    assert titles[0] in {"Sisi lain ruang", "Sisi lain kota"}
    assert titles[1] in {"Sisi lain ruang", "Sisi lain kota"}
    assert len(set(titles)) == len(titles), "candidates are distinct"


# --------------------------------------------------------------------------- store


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    state = AppState.build(settings, budget=Budget())
    return build_app(state)


@pytest.fixture
def client(app):
    return TestClient(app)


def _job(client, title: str) -> dict:
    response = client.post("/api/jobs", json={"title": title, "provider_mode": "mock"})
    assert response.status_code == 201, response.text
    return response.json()


def test_avoid_list_seeded_from_job_titles(client):
    _job(client, "Judul produksi pertama")
    store = client.app.state.studio.store
    assert store.topic_avoid_list() == ["Judul produksi pertama"]


def test_avoid_list_prefers_discovered_titles(client):
    _job(client, "Judul lama")
    store = client.app.state.studio.store
    store.record_topic_discovery(
        discovery_id="disc-1", payload={}, titles=["Kandidat baru"]
    )
    assert store.topic_avoid_list() == ["Kandidat baru"]


# --------------------------------------------------------------------------- API route


def test_discover_records_candidates_and_creates_no_job(client):
    _job(client, "Sejarah kereta bawah tanah")
    before = client.get("/api/jobs").json()

    response = client.post("/api/topics/discover", json={"limit": 3})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "ok"
    assert body["provider_mode"] == "mock"
    assert 1 <= len(body["candidates"]) <= 3
    assert all("Sejarah kereta bawah tanah" != c["title"] for c in body["candidates"]), (
        "the produced title was in the seeded avoid list"
    )

    after = client.get("/api/jobs").json()["jobs"]
    assert [j["id"] for j in after] == [j["id"] for j in before["jobs"]], (
        "discovery proposes metadata only; it must never create a job"
    )

    store = client.app.state.studio.store
    recorded = store.topic_discovery(body["discovery_id"])
    assert recorded is not None, "the discovery must be persisted"
    assert recorded["provider_mode"] == "mock"
    assert recorded["candidates"] == body["candidates"]


def test_discover_accepts_extra_avoid_titles(client):
    _job(client, "Topik ters summon ulang")
    response = client.post(
        "/api/topics/discover", json={"avoid": ["Topik ters summon ulang"], "limit": 2}
    )
    assert response.status_code == 200
    titles = [c["title"] for c in response.json()["candidates"]]
    assert "Topik ters summon ulang" not in titles


def test_discover_events_recorded_under_director_agent(client):
    _job(client, "Latarnya biru")
    response = client.post("/api/topics/discover", json={})
    body = response.json()
    events = client.app.state.studio.events.page(job_id=body["discovery_id"])
    agents = {event.agent_id for event in events}
    assert agents == {"DirectorAgent"}, "discovery is DirectorAgent's work in the projection"


# --------------------------------------------------------------------------- live path


@pytest.fixture
def live_app(tmp_path, stub):
    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    state = AppState.build(settings, budget=Budget())
    spec = ProviderSpec(
        id="stub",
        transport="openai_compat",
        base_url=stub.base_url,
        model="stub-model",
        allow_private_hosts=True,
    )
    state.registry.add(spec)
    return build_app(state)


def test_live_discovery_calls_provider_and_records_usage(live_app, stub):
    stub.route("GET", "/v1/models", body={"data": [{"id": "stub-model"}]})
    stub.route(
        "POST",
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "schema_version": 1,
                                "candidates": [
                                    {
                                        "title": "Kandidat model",
                                        "angle": "sisi tersembunyi",
                                        "why": "baru",
                                    },
                                    {"title": "", "angle": "x", "why": "y"},  # dropped: empty title
                                    {"title": "Tak lengkap"},  # dropped: missing angle/why
                                ],
                            }
                        )
                    }
                }
            ]
        },
    )
    client = TestClient(live_app)
    response = client.post("/api/topics/discover", json={"avoid": [], "limit": 5})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider_mode"] == "live"
    assert [c["title"] for c in body["candidates"]] == ["Kandidat model"], (
        "malformed rows are dropped, valid ones survive"
    )

    posts = [r for r in stub.recorded if r.path == "/v1/chat/completions"]
    assert len(posts) == 1
    sent = posts[0].body or {}
    assert sent["model"] == "stub-model"

    # The call is attributed and priced exactly like a pipeline call.
    usage = live_app.state.studio.usage.summary()
    assert usage["price_configured"] is False, "no price configured on the stub spec"
    assert usage["by_agent"], "the discovery call must appear in usage accounting"
