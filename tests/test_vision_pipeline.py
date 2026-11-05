"""A job driven through the real stages with a vision provider that speaks the real wire format.

This proves semantic evidence and explicit manual review through the pipeline, not model accuracy
or scientific verification. Everything is loopback:

- the narration is real SAPI output, so `audio.json` timings are measured;
- the render is a real Remotion subprocess, so `technical-qc.json` measures a real file;
- individual sampled PNGs are extracted by the real ffmpeg path;
- the vision provider is `OpenAICompatProvider` over `PinnedHTTP` against a loopback `StubServer`
  that answers in the OpenAI chat-completions shape.

Marked `slow`: it renders. Run with `-m slow` or let the default suite include it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.core.contracts.state import JobState
from packages.core.providers.base import Capability
from packages.core.providers.openai_compat import OpenAICompatProvider
from packages.core.providers.registry import ProviderSpec
from packages.core.providers.usage import Budget
from tests.stub_server import StubServer

pytestmark = pytest.mark.slow


def _stub_answer(request, *, failure=False) -> dict:
    from packages.core.contracts.semantic import VisualEvidenceArtifact
    from tests.test_semantic_vision import answer

    parts = request.body["messages"][-1]["content"]
    prompt = next(part["text"] for part in parts if part.get("type") == "text")
    manifest = VisualEvidenceArtifact.model_validate(json.loads(prompt)["frame_manifest"])
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(answer(manifest, failure=failure))
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        "model": "vision-stub",
    }


def _run_job(tmp_path, server: StubServer, monkeypatch):
    """Build the app, register the vision provider, run one job to a terminal state."""
    from apps.api.main import create_app
    from apps.api.settings import Settings
    from apps.api.state import AppState

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    # Mock resource telemetry so the render admission gate does not block on low host RAM.
    # Every other rendering test does this; this file omitted it and failed under memory pressure.
    from packages.core.orchestration import resources
    monkeypatch.setattr(resources, "probe_telemetry", lambda **_kw: resources.Telemetry(8192, 8192))
    state = AppState.build(settings, budget=Budget())

    # A vision-capable provider at the loopback stub. `allow_private_hosts` is the documented
    # opt-in for a local endpoint, and the resolver's health probe hits /models first.
    state.registry.add(
        ProviderSpec(
            id="vision-stub",
            transport="openai_compat",
            base_url=server.base_url,
            model="vision-stub",
            capabilities=[Capability.CHAT, Capability.VISION],
            allow_private_hosts=True,
        )
    )
    state.transports["openai_compat"] = OpenAICompatProvider()
    # Bind every agent explicitly. `_primary_for` returns the first enabled non-mock provider for
    # any agent without a binding, so registering the vision stub alone would route ScriptAgent to
    # a model that declares no `json_schema` and the job would block before it ever rendered.
    # QualityAgent gets the vision stub; every other agent stays on the mock transport.
    state.bindings = {
        "QualityAgent": {"primary": "vision-stub"},
        "ResearchAgent": {"primary": "mock"},
        "TopicSelectionAgent": {"primary": "mock"},
        "ScriptAgent": {"primary": "mock"},
        "CreativeDirectorAgent": {"primary": "mock"},
        "StoryboardAgent": {"primary": "mock"},
        "MetadataAgent": {"primary": "mock"},
    }
    state.registry.specs["mock"].enabled = True

    from fastapi.testclient import TestClient

    client = TestClient(create_app(state))
    job = client.post(
        "/api/jobs",
        json={
            "title": "vision proof",
            "topic": "local narration",
            "provider_mode": "mock",
            "render_video": True,
            "voice": "system-default",
            "target_duration_s": 10,
        },
    ).json()
    client.post(f"/api/jobs/{job['id']}/run")

    import time

    deadline = time.time() + 900
    terminal = {JobState.READY_FOR_APPROVAL, JobState.BLOCKED, JobState.FAILED}
    store = state.store
    while time.time() < deadline and (store.get(job["id"]).state not in terminal or job["id"] in state.running):
        time.sleep(2)
    assert store.get(job["id"]).state in terminal and job["id"] not in state.running
    return job["id"], state, Path(store.job_dir(job["id"])), client


def test_a_scripted_visual_pass_without_scientific_evidence_requires_explicit_manual_policy(tmp_path, monkeypatch):
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "vision-stub"}]})
        server.route("POST", "/v1/chat/completions", body=_stub_answer)

        job_id, state, job_dir, client = _run_job(tmp_path, server, monkeypatch)
        recorded = list(server.recorded)

    store = state.store
    qc = json.loads((job_dir / "qc.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "visual-evidence.json").read_text(encoding="utf-8"))

    assert store.get(job_id).state is JobState.BLOCKED, (
        f"{store.get(job_id).state} / {store.get(job_id).last_error}"
    )
    assert qc["visual"]["status"] == "unverified"
    assert qc["semantic"]["status"] == "UNVERIFIED"
    assert qc["visual"]["provider"] == "vision-stub"
    assert qc["visual"]["frames_inspected"] == qc["visual"]["frames_extracted"] == len(manifest["frames"])
    assert len(manifest["frames"]) > 6
    assert qc["visual"]["findings"] == []
    rows = [row for row in state.requests.statuses(job_id) if row["agent"] == "QualityAgent"]
    assert len(rows) == 1 and rows[0]["status"] == "completed"
    assert not store.has_artifact(job_id, "approval.json")
    render = store.read_artifact(job_id, "render.json")
    permission = client.post(f"/api/jobs/{job_id}/manual-review-policy", json={
        "operator": "fixture-reviewer", "reason": "Explicit fixture manual review permission",
        "render_sha256": render["sha256"], "allow_unverified": True,
    })
    assert permission.status_code == 200, permission.text
    from packages.core.orchestration.editorial import build_readiness_stage
    from packages.core.orchestration.runner import run_stages
    report = run_stages(store=store, job_id=job_id, stages=[build_readiness_stage(state)])
    assert report["ok"], report
    readiness = store.read_artifact(job_id, "readiness.json")
    assert readiness["ready"] is True and readiness["semantic_status"] == "UNVERIFIED"
    assert readiness["human_approved"] is False
    assert not store.has_artifact(job_id, "approval.json")

    # The image really travelled: one POST to the chat endpoint carrying a data URI.
    chat = [r for r in recorded if r.path.endswith("/chat/completions")]
    assert len(chat) == 1, "exactly one vision call"
    parts = chat[0].body["messages"][-1]["content"]
    image_parts = [p for p in parts if p.get("type") == "image_url"]
    assert len(image_parts) == len(manifest["frames"])
    import base64
    import hashlib
    for image, frame in zip(image_parts, manifest["frames"], strict=True):
        prefix, data = image["image_url"]["url"].split(",", 1)
        assert prefix == "data:image/png;base64"
        assert hashlib.sha256(base64.b64decode(data)).hexdigest() == frame["sha256"]


def test_a_major_finding_blocks_the_job_with_a_recorded_repair(tmp_path, monkeypatch):
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "vision-stub"}]})
        server.route(
            "POST",
            "/v1/chat/completions",
            body=lambda request: _stub_answer(request, failure=True),
        )
        job_id, state, job_dir, _client = _run_job(tmp_path, server, monkeypatch)

    store = state.store
    record = store.get(job_id)
    qc = json.loads((job_dir / "qc.json").read_text(encoding="utf-8"))

    assert record.state is JobState.BLOCKED
    assert qc["visual"]["status"] == "failed"
    assert qc["visual"]["findings"][0]["severity"] == "major"
    assert qc["repairs"], "a blocked gate must record the decision"
    assert qc["repairs"][0]["target"] == "visual"
    assert qc["repairs"][0]["action"] == "blocked"
    assert qc["repairs"][0]["artifacts_invalidated"] == []
    assert "visual" in (record.last_error or "")
