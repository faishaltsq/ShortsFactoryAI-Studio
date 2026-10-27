"""M1 wiring proof: JobService.publish renders the thumbnail before the upload, under one lease.

The thumbnail stage and the publish stage were each proven alone; this file proves the wiring
point the thumbnail module's docstring promised: append the thumbnail stage between the approval
and the insert, in the same ``run_stages`` call, so a crash between them resumes under the
runner's reuse rules. The renderer is stubbed (a real Remotion render is the slow suite's job);
the transport is the real ``StubTransport``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
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
    return create_app(AppState.build(settings, budget=Budget()))


def _approved_live_job_with_media_inputs(app) -> str:
    """An APPROVED job through the real gate, plus the two files the thumbnail stage reads.

    ``metadata.json`` and ``render-props.json`` are not gate inputs (the publish flow is what
    first needs them), so the approval fixture does not write them. The thumbnail stage treats a
    missing props file as a hard stage error, so a publishable job must carry them by publish
    time — this fixture adds exactly that, nothing more.
    """
    from tests.test_api_approval_gate import _ready_job

    client = TestClient(app)
    job_id, _ = _ready_job(client, app, provider_mode="live")
    client.post(f"/api/jobs/{job_id}/approve", json={"operator": "op"}).raise_for_status()
    store = app.state.studio.store
    store.write_artifact(job_id, "metadata.json", {
        "schema_version": 1, "title": "Uji", "description": "", "tags": [],
        "category_id": "22", "made_for_kids": False, "synthetic_media": True, "thumbnail": {},
    })
    store.write_artifact(job_id, "render-props.json", {"storyboard": {"scenes": []}})
    return job_id


def test_publish_renders_the_thumbnail_before_the_upload(app, monkeypatch):
    import hashlib

    from packages.core.publish import thumbnail as thumb_mod

    store = app.state.studio.store
    job_id = _approved_live_job_with_media_inputs(app)
    calls: list[dict] = []

    def fake_render(**kwargs):
        calls.append(kwargs)
        Path(kwargs["out_path"]).write_bytes(b"\x89PNG\r\n\x1a\nthumbnail-bytes")
        return {"elapsed_ms": 1}

    monkeypatch.setattr(thumb_mod, "render_storyboard", fake_render)
    client_response = TestClient(app).post(f"/api/jobs/{job_id}/publish", json={})
    assert client_response.status_code == 200, client_response.text
    report = client_response.json()

    assert report["ok"] is True, report
    names = [row["name"] for row in report["stages"]]
    assert names == ["ThumbnailAgent", "PublisherAgent"], names
    assert (store.job_dir(job_id) / "thumb.png").is_file()
    metadata = store.read_artifact(job_id, "metadata.json")
    thumb = metadata["thumbnail"]
    assert thumb["path"] == "thumb.png"
    assert thumb["sha256"] == hashlib.sha256(b"\x89PNG\r\n\x1a\nthumbnail-bytes").hexdigest()


def test_a_second_thumbnail_run_reuses_without_rerendering(app, monkeypatch):
    """Idempotence: the stage's ``done_when`` reports reuse once the digest matches the bytes."""
    from packages.core.orchestration.runner import run_stages
    from packages.core.publish import thumbnail as thumb_mod
    from packages.core.publish.thumbnail import build_thumbnail_stage

    store = app.state.studio.store
    job_id = _approved_live_job_with_media_inputs(app)
    render_calls: list[dict] = []

    def fake_render(**kwargs):
        render_calls.append(kwargs)
        Path(kwargs["out_path"]).write_bytes(b"\x89PNG\r\n\x1a\nthumbnail-bytes")
        return {"elapsed_ms": 1}

    monkeypatch.setattr(thumb_mod, "render_storyboard", fake_render)

    response = TestClient(app).post(f"/api/jobs/{job_id}/publish", json={})
    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json()["stages"]] == [
        "ThumbnailAgent", "PublisherAgent",
    ]
    assert len(render_calls) == 1

    # The job is now at PRIVATE_UPLOAD, past the service's APPROVED-only publish — so reuse is
    # proven at the stage level, which is where the runner's artifact_reused rule lives.
    state = app.state.studio
    report = run_stages(
        store=store,
        job_id=job_id,
        stages=[build_thumbnail_stage(state, video_dir=Path("."))],
    )
    assert report["ok"] is True, report
    assert report["stages"][0]["reused"] is True, report["stages"]
    assert len(render_calls) == 1, "a second run must not re-render the thumbnail"
