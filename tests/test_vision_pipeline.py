"""A job driven through the real stages with a vision provider that speaks the real wire format.

This is the test that makes `visual.status == "passed"` a fact about the pipeline rather than a
fact about a stub object. Everything is loopback:

- the narration is real SAPI output, so `audio.json` timings are measured;
- the render is a real Remotion subprocess, so `technical-qc.json` measures a real file;
- the contact sheet is extracted by the real ffmpeg path;
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


def _stub_answer(status: str, frames: int, findings: list[dict] | None = None) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": status,
                            "frames_inspected": frames,
                            "findings": findings or [],
                        }
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        "model": "vision-stub",
    }


def _run_job(tmp_path, server: StubServer):
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
    while time.time() < deadline and store.get(job["id"]).state not in terminal:
        time.sleep(2)
    return job["id"], store, Path(store.job_dir(job["id"]))


def test_a_vision_pass_reaches_ready_for_approval(tmp_path):
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "vision-stub"}]})
        # Five frames is what the keyframe plan extracts for this storyboard; the stub is told the
        # count through the prompt, and the answer must account for exactly that many.
        server.route("POST", "/v1/chat/completions", body=_stub_answer("passed", 5))

        job_id, store, job_dir = _run_job(tmp_path, server)
        recorded = list(server.recorded)

    qc = json.loads((job_dir / "qc.json").read_text(encoding="utf-8"))
    readiness = json.loads((job_dir / "readiness.json").read_text(encoding="utf-8"))

    assert store.get(job_id).state is JobState.READY_FOR_APPROVAL, (
        f"{store.get(job_id).state} / {store.get(job_id).last_error}"
    )
    assert qc["visual"]["status"] == "passed"
    assert qc["visual"]["provider"] == "vision-stub"
    assert qc["visual"]["frames_inspected"] == qc["visual"]["frames_extracted"] == 5
    assert qc["visual"]["findings"] == []
    assert readiness["ready"] is True
    assert readiness["visual_status"] == "passed"

    # The image really travelled: one POST to the chat endpoint carrying a data URI.
    chat = [r for r in recorded if r.path.endswith("/chat/completions")]
    assert len(chat) == 1, "exactly one vision call"
    parts = chat[0].body["messages"][-1]["content"]
    image_parts = [p for p in parts if p.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_a_major_finding_blocks_the_job_with_a_recorded_repair(tmp_path):
    with StubServer() as server:
        server.route("GET", "/v1/models", body={"data": [{"id": "vision-stub"}]})
        server.route(
            "POST",
            "/v1/chat/completions",
            body=_stub_answer(
                "passed",
                5,
                [{"atMs": 1200, "issue": "karakter hilang dari bingkai", "severity": "major"}],
            ),
        )
        job_id, store, job_dir = _run_job(tmp_path, server)

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
