"""HTTP surface: the gate is server-side, and a mock job is never publishable."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from packages.core.providers.usage import Budget


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
    return create_app(state)


@pytest.fixture
def client(app):
    return TestClient(app)


def _create(client, **overrides):
    payload = {"title": "Uji", "topic": "sejarah singkat", "provider_mode": "mock"}
    payload.update(overrides)
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health_reports_vision_availability(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["vision_available"] is False, "no provider declares vision by default"


def test_create_and_fetch_a_job(client):
    job = _create(client)
    assert job["state"] == JobState.IDEA_DISCOVERY.value
    assert job["is_mock"] is True
    fetched = client.get(f"/api/jobs/{job['id']}").json()
    assert fetched["payload"]["topic"] == "sejarah singkat"
    assert fetched["events"][0]["to_state"] == "IDEA_DISCOVERY"


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_create_requires_a_title(client):
    assert client.post("/api/jobs", json={"title": ""}).status_code == 422


def test_create_rejects_unknown_fields(client):
    response = client.post("/api/jobs", json={"title": "x", "surprise": 1})
    assert response.status_code == 422


def test_create_requires_at_least_one_character(client):
    response = client.post("/api/jobs", json={"title": "x", "characters": []})
    assert response.status_code == 422


def test_artifact_route_refuses_traversal(client):
    job = _create(client)
    response = client.get(f"/api/jobs/{job['id']}/artifact/..%2Fescape.json")
    assert response.status_code in {404, 422}


def test_missing_video_is_404_not_an_empty_file(client):
    job = _create(client)
    assert client.get(f"/api/jobs/{job['id']}/video").status_code == 404


def test_video_range_request_returns_206(client, app):
    job = _create(client)
    path = app.state.studio.store.job_dir(job["id"]) / "output.mp4"
    path.write_bytes(b"0123456789")
    response = client.get(f"/api/jobs/{job['id']}/video", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["accept-ranges"] == "bytes"


def test_bad_range_is_416(client, app):
    job = _create(client)
    (app.state.studio.store.job_dir(job["id"]) / "output.mp4").write_bytes(b"0123456789")
    response = client.get(f"/api/jobs/{job['id']}/video", headers={"Range": "bytes=99-200"})
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


def test_approval_is_refused_before_ready(client):
    job = _create(client)
    response = client.post(f"/api/jobs/{job['id']}/approve", json={"operator": "op"})
    assert response.status_code == 409
    assert "READY_FOR_APPROVAL" in response.json()["detail"]


def test_rejection_requires_a_reason(client, app):
    job = _create(client)
    app.state.studio.store.transition(job["id"], JobState.TOPIC_SELECTED)
    for state in (
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ):
        app.state.studio.store.transition(job["id"], state)
    response = client.post(
        f"/api/jobs/{job['id']}/reject", json={"operator": "op", "reason": ""}
    )
    assert response.status_code == 422


def test_approval_gate_blocks_when_artifacts_are_missing(client, app):
    job = _create(client)
    app.state.studio.store.transition(job["id"], JobState.TOPIC_SELECTED)
    for state in (
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ):
        app.state.studio.store.transition(job["id"], state)
    response = client.post(f"/api/jobs/{job['id']}/approve", json={"operator": "op"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "video_present" in detail and "publishable" in detail


def test_a_mock_job_is_never_publishable(client, app):
    """The check that matters: clean artifacts do not make fabricated content publishable."""
    job = _create(client)
    store = app.state.studio.store
    store.transition(job["id"], JobState.TOPIC_SELECTED)
    for state in (
        JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED, JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY, JobState.ASSETS_READY, JobState.AUDIO_READY,
        JobState.RENDERING, JobState.TECHNICAL_QC, JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job["id"], state)
    (store.job_dir(job["id"]) / "output.mp4").write_bytes(b"fake")
    store.write_artifact(job["id"], "render.json", {"sha256": "a" * 64, "frames": 900})
    store.write_artifact(job["id"], "qc.json", {"technical": {"passed": True}})

    response = client.post(f"/api/jobs/{job['id']}/approve", json={"operator": "op"})
    assert response.status_code == 409
    assert "publishable" in response.json()["detail"]
    assert store.get(job["id"]).state is JobState.READY_FOR_APPROVAL


def test_cancel_is_recorded_and_refused_on_a_terminal_job(client, app):
    job = _create(client)
    assert client.post(f"/api/jobs/{job['id']}/cancel", json={"reason": "test"}).status_code == 202
    app.state.studio.store.transition(job["id"], JobState.CANCELLED)
    assert client.post(f"/api/jobs/{job['id']}/cancel", json={}).status_code == 409


def test_delete_removes_the_job(client):
    job = _create(client)
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_studio_snapshot_has_every_agent_and_a_cursor(client):
    job = _create(client)  # creation itself writes the first event
    body = client.get("/api/studio/snapshot").json()
    assert body["cursor"] >= 1
    assert len(body["agents"]) == 14
    assert body["job_id"] is None or body["job_id"] == job["id"]


def test_a_snapshot_with_no_events_still_lists_every_agent(client):
    body = client.get("/api/studio/snapshot").json()
    assert body["cursor"] == 0
    assert {agent["agent_id"] for agent in body["agents"]} == set(
        __import__("packages.core.observability.events", fromlist=["AGENT_IDS"]).AGENT_IDS
    )


def test_provider_upsert_never_returns_the_secret(client):
    secret = "sk-" + "apisentinel" + "987654321"
    response = client.put(
        "/api/providers",
        json={
            "id": "test-provider",
            "transport": "openai_compat",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "capabilities": ["chat"],
            "credential_secret": secret,
        },
    )
    assert response.status_code == 200, response.text
    assert secret not in response.text
    listing = client.get("/api/providers")
    assert secret not in listing.text
    entry = next(p for p in listing.json()["providers"] if p["id"] == "test-provider")
    assert entry["credential_source"].startswith("dpapi:")


def test_provider_env_credential_is_reported_as_a_reference_only(client):
    response = client.put(
        "/api/providers",
        json={
            "id": "env-provider",
            "transport": "openai_compat",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "capabilities": ["chat"],
            "credential_env": "MY_SECRET_KEY",
        },
    )
    assert response.status_code == 200
    entry = next(
        p for p in client.get("/api/providers").json()["providers"] if p["id"] == "env-provider"
    )
    assert entry["credential_source"] == "env:MY_SECRET_KEY"


def test_provider_with_a_private_url_requires_the_flag(client):
    response = client.put(
        "/api/providers",
        json={
            "id": "local",
            "transport": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "llama",
            "capabilities": ["chat"],
        },
    )
    # The shape is accepted; the address policy is applied at call time with the flag.
    assert response.status_code == 200
    entry = next(p for p in client.get("/api/providers").json()["providers"] if p["id"] == "local")
    assert entry["allow_private_hosts"] is False


def test_provider_test_reports_reachability_not_authentication(client, monkeypatch):
    client.put(
        "/api/providers",
        json={
            "id": "unreachable",
            "transport": "openai_compat",
            "base_url": "http://127.0.0.1:1/v1",
            "model": "m",
            "capabilities": ["chat"],
            "allow_private_hosts": True,
        },
    )
    body = client.post("/api/providers/test", json={"id": "unreachable"}).json()
    assert body["ok"] is False
    assert "reachability only" in body["note"]


def test_usage_endpoint_shape(client):
    body = client.get("/api/usage/today").json()
    assert set(body) == {"tokens", "cost_usd", "calls"}


def test_token_is_enforced_when_configured(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "d",
        db_path=tmp_path / "d" / "f.db",
        jobs_dir=tmp_path / "d" / "jobs",
        secrets_dir=tmp_path / "d" / "secrets",
        studio_config=tmp_path / "c" / "studio.json",
        api_token="expected-token",
    ).ensure()
    client = TestClient(create_app(AppState.build(settings)))
    assert client.get("/api/jobs").status_code == 200, "reads stay open"
    response = client.post("/api/jobs", json={"title": "x"})
    assert response.status_code == 401


# -- render_video: a job-level request, never a provider setting -------------------------------


def test_render_video_true_is_echoed_in_the_job_payload(client):
    job = _create(client, render_video=True)
    fetched = client.get(f"/api/jobs/{job['id']}").json()
    assert fetched["payload"]["render_video"] is True


def test_render_video_defaults_to_false_and_is_recorded_explicitly(client):
    """The field is a declared default, so it is present as False rather than absent.

    ``CreateJobBody.model_dump()`` includes defaults, and the API stores that dump verbatim, so a
    job created without the flag records ``render_video: False``. Asserting "absent" here would
    encode a guess about the serialiser rather than the behaviour that exists.
    """
    job = _create(client)
    fetched = client.get(f"/api/jobs/{job['id']}").json()
    assert fetched["payload"]["render_video"] is False


def test_render_video_rejects_a_non_boolean(client):
    response = client.post("/api/jobs", json={"title": "x", "render_video": "yes"})
    assert response.status_code == 422, response.text


def test_create_job_body_forbids_unknown_fields(client):
    response = client.post("/api/jobs", json={"title": "x", "render_videoo": True})
    assert response.status_code == 422, response.text
