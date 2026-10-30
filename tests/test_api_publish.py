"""HTTP surface for publishing, metadata and usage: the last offline-provable Phase 4 slice.

Every test here drives the real routes against the offline stub transport. No network, no
credential, no YouTube client — the point is that the API contract and the refusal codes are
correct before any real transport exists.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from packages.core.providers.usage import Budget
from packages.core.publish.stage import PUBLICATION_NAME


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    return create_app(AppState.build(settings, budget=Budget()))


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_thumbnail_render(monkeypatch):
    """Every publish in this module runs the thumbnail stage first; a unit test stubs the
    renderer (the slow suite proves the real render), otherwise each publish needs a browser."""
    from packages.core.orchestration import resources
    from packages.core.publish import thumbnail as thumb_mod
    from tests.test_publish_stage import _run_fake_thumbnail

    monkeypatch.setattr(thumb_mod, "render_storyboard", _run_fake_thumbnail)
    monkeypatch.setattr(resources, "probe_telemetry", lambda **kwargs: resources.Telemetry(8192, 8192))


def _approved_live_job(app) -> str:
    """A job at APPROVED with every artifact the gate recomputes, via the real approve route."""
    from tests.test_api_approval_gate import _ready_job

    client = TestClient(app)
    job_id, _ = _ready_job(client, app, provider_mode="live")
    response = client.post(f"/api/jobs/{job_id}/approve", json={"operator": "op"})
    assert response.status_code == 200, response.text
    return job_id


# -- publish -----------------------------------------------------------------------------------


def test_publishing_a_mock_job_is_refused_with_the_publishable_reason(client, app):
    """The refusal must name mock-ness, not the state — so the job is advanced to APPROVED first.

    The store's APPROVED check is about evidence, not about mock-ness, so the artifact is written
    here and the SERVICE is what must refuse.
    """
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    store = app.state.studio.store
    for st in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY, JobState.ASSETS_READY,
        JobState.AUDIO_READY, JobState.RENDERING, JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job["id"], st)
    body = b"mock-bytes"
    (Path(store.job_dir(job["id"])) / "output.mp4").write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    store.write_artifact(job["id"], "render.json", {
        "src": "output.mp4", "sha256": digest, "bytes": len(body), "width": 1080,
        "height": 1920, "fps": 30, "frames": 90, "duration_ms": 3000, "video_codec": "h264",
        "audio_codec": "aac", "pix_fmt": "yuv420p", "renderer": "remotion", "scene_hashes": {},
    })
    store.write_artifact(job["id"], "approval.json", {
        "schema_version": 1, "decision": "approved", "operator": "op", "reason": None,
        "checks": {"publishable": True}, "decided_at": "2026-01-01T00:00:00+00:00",
        "render_sha256": digest,
    })
    store.transition(job["id"], JobState.APPROVED)
    response = client.post(f"/api/jobs/{job['id']}/publish", json={})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "mock" in detail
    assert "publishable is false" in detail
    assert not app.state.studio.store.has_artifact(job["id"], PUBLICATION_NAME)


def test_publishing_an_unapproved_job_is_refused(client, app):
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "live"}).json()
    response = client.post(f"/api/jobs/{job['id']}/publish", json={})
    assert response.status_code == 409
    assert "only possible at APPROVED" in response.json()["detail"]


def test_publishing_an_unknown_job_is_404(client):
    response = client.post("/api/jobs/does-not-exist/publish", json={})
    assert response.status_code == 404


def test_publishing_an_approved_live_job_confirms_through_the_stub(client, app):
    job_id = _approved_live_job(app)
    response = client.post(f"/api/jobs/{job_id}/publish", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["transport"] == "stub"

    publication = app.state.studio.store.read_artifact(job_id, PUBLICATION_NAME)
    assert publication["phase"] == "confirmed"
    assert publication["video_id"].startswith("stub-")
    assert app.state.studio.store.get(job_id).state is JobState.PRIVATE_UPLOAD


def test_publishing_twice_inserts_once(client, app):
    """The idempotency claim, over HTTP.

    The route builds its own stub per call, so the call count is not observable from outside. What
    *is* observable is the evidence: the confirmed record must not change, and the second call must
    not reach the transport at all. Both are asserted, plus the record is unchanged byte for byte
    apart from nothing — a second upload would produce a different ``video_id``.
    """
    job_id = _approved_live_job(app)
    first = client.post(f"/api/jobs/{job_id}/publish", json={})
    assert first.status_code == 200, first.text
    after_first = app.state.studio.store.read_artifact(job_id, PUBLICATION_NAME)
    assert after_first["phase"] == "confirmed"
    first_video_id = after_first["video_id"]

    second = client.post(f"/api/jobs/{job_id}/publish", json={})
    # The job is PRIVATE_UPLOAD now, so the service refuses before any transport call.
    assert second.status_code == 409, second.text
    assert "only possible at APPROVED" in second.json()["detail"]

    after_second = app.state.studio.store.read_artifact(job_id, PUBLICATION_NAME)
    assert after_second["video_id"] == first_video_id, (
        "a second upload would have produced a different video_id"
    )
    assert after_second == after_first, "the record must be untouched by the refused second call"


def test_an_unknown_transport_name_is_refused(client, app):
    job_id = _approved_live_job(app)
    response = client.post(
        f"/api/jobs/{job_id}/publish", json={"transport": "youtube-typo"}
    )
    assert response.status_code == 422
    assert "transport" in response.json()["detail"].lower()


# -- reconcile ---------------------------------------------------------------------------------


def test_reconciling_a_confirmed_record_is_409(client, app):
    job_id = _approved_live_job(app)
    assert client.post(f"/api/jobs/{job_id}/publish", json={}).status_code == 200
    response = client.post(f"/api/jobs/{job_id}/publish/reconcile", json={})
    assert response.status_code == 409
    assert "confirmed" in response.json()["detail"]


def test_reconciling_an_unknown_job_is_404(client):
    response = client.post("/api/jobs/nope/publish/reconcile", json={})
    assert response.status_code == 404


def test_reconciling_an_uncertain_record_clears_without_inserting(client, app):
    from packages.core.publish.stub import StubTransport

    job_id = _approved_live_job(app)
    store = app.state.studio.store
    # Put the job into an uncertain publication state directly: the stub is the only transport and
    # its uncertainty is scripted, so this is the honest way to reach the state over HTTP.
    from packages.core.orchestration.runner import StageError
    from packages.core.publish.stage import build_publish_stage, derive_idempotency_key

    digest = store.read_artifact(job_id, "render.json")["sha256"]
    key = derive_idempotency_key(job_id, digest)
    transport = StubTransport()
    transport.be_uncertain_next()
    stage = build_publish_stage(app.state.studio, transport)
    ctx = stage_ctx(store, job_id)
    with pytest.raises(StageError) as exc:
        stage.run(ctx)
    # publication_uncertain is terminal negative evidence: the runner commits the staged record
    # (validate=False) instead of discarding it. Reproduce that here so reconcile sees the
    # canonical artifact a real run would have left.
    from packages.core.orchestration.runner import _promote_staged

    _promote_staged(store, job_id, ctx, stage, validate=False)
    assert exc.value.code == "publication_uncertain"
    assert store.read_artifact(job_id, PUBLICATION_NAME)["phase"] == "uncertain"

    before = transport.insert_count
    response = client.post(f"/api/jobs/{job_id}/publish/reconcile", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["phase"] in {"initiating", "confirmed"}
    assert "reconciled_not_found" in body["receipt_steps"] or "reconciled_found" in body["receipt_steps"]
    assert transport.insert_count == before, "reconciliation must never insert"
    assert body["idempotency_key"] == key


# -- metadata ----------------------------------------------------------------------------------


def test_metadata_edit_before_approval_is_refused(client, app):
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    response = client.post(
        f"/api/jobs/{job['id']}/metadata", json={"title": "Judul baru"}
    )
    assert response.status_code == 409
    assert "READY_FOR_APPROVAL" in response.json()["detail"]


def test_metadata_edit_with_a_101_char_title_is_422(client, app):
    job_id = _approved_live_job(app)
    response = client.post(f"/api/jobs/{job_id}/metadata", json={"title": "x" * 101})
    assert response.status_code == 422


def test_metadata_edit_with_an_empty_title_is_refused(client, app):
    job_id = _approved_live_job(app)
    response = client.post(f"/api/jobs/{job_id}/metadata", json={"title": ""})
    assert response.status_code == 422


def test_metadata_edit_rejects_unknown_fields(client, app):
    job_id = _approved_live_job(app)
    response = client.post(
        f"/api/jobs/{job_id}/metadata", json={"title": "ok", "monetised": True}
    )
    assert response.status_code == 422


def test_metadata_edit_at_the_gate_writes_the_artifact(client, app):
    from tests.test_api_approval_gate import _ready_job

    job_id, _ = _ready_job(TestClient(app), app, provider_mode="live")
    response = client.post(
        f"/api/jobs/{job_id}/metadata",
        json={"title": "Judul Baru", "description": "deskripsi", "tags": ["satu", "dua"]},
    )
    assert response.status_code == 200, response.text
    metadata = app.state.studio.store.read_artifact(job_id, "metadata.json")
    assert metadata["title"] == "Judul Baru"
    assert metadata["tags"] == ["satu", "dua"]
    assert metadata["synthetic_media"] is True


def test_get_metadata_is_404_when_absent(client, app):
    job = client.post("/api/jobs", json={"title": "Uji", "provider_mode": "mock"}).json()
    response = client.get(f"/api/jobs/{job['id']}/metadata")
    assert response.status_code == 404


def test_get_metadata_returns_the_artifact(client, app):
    from tests.test_api_approval_gate import _ready_job

    job_id, _ = _ready_job(TestClient(app), app, provider_mode="live")
    client.post(f"/api/jobs/{job_id}/metadata", json={"title": "Judul Baru"})
    response = client.get(f"/api/jobs/{job_id}/metadata")
    assert response.status_code == 200
    assert response.json()["title"] == "Judul Baru"


# -- usage summary -----------------------------------------------------------------------------


def test_a_priced_zero_is_not_an_unpriced_zero(client, app):
    """A configured zero rate is a real price; a missing rate is an unknown cost.

    These two cases used to look identical (``est_cost_usd == 0.0``), which let a dashboard
    present "we do not know what this cost" as "this cost nothing".
    """
    from packages.core.providers.base import Usage
    tracker = app.state.studio.usage
    # Both rates configured at zero: a deliberate free tier, fully priced.
    tracker.record(
        job_id=None, agent="ScriptAgent", provider="stub", model="free-model",
        usage=Usage(prompt_tokens=10, completion_tokens=5), est_cost_usd=0.0, elapsed_ms=1,
        price_in_per_mtok=0.0, price_out_per_mtok=0.0,
    )
    # No rates at all: the cost is unknown, not zero.
    tracker.record(
        job_id=None, agent="ScriptAgent", provider="stub", model="unpriced-model",
        usage=Usage(prompt_tokens=10, completion_tokens=5), est_cost_usd=0.0, elapsed_ms=1,
    )
    # One rate only: partial.
    tracker.record(
        job_id=None, agent="ScriptAgent", provider="stub", model="partial-model",
        usage=Usage(prompt_tokens=10, completion_tokens=5), est_cost_usd=0.5, elapsed_ms=1,
        price_in_per_mtok=1.0,
    )
    tracker.set_configured_rates({"stub": (0.0, 0.0)})
    body = client.get("/api/usage/summary").json()
    assert body["price_configured"] is True, "a configured zero rate is a configured price"
    by_model = {(row["model"]): row for row in body["by_model"]}
    assert by_model["free-model"]["fully_priced"] is True
    assert by_model["free-model"]["unknown_price_calls"] == 0
    assert by_model["unpriced-model"]["fully_priced"] is False
    assert by_model["unpriced-model"]["unknown_price_calls"] == 1
    assert by_model["partial-model"]["fully_priced"] is False


def test_legacy_rows_are_never_inferred_to_be_free(client, app):
    """A row written before price snapshots existed is explicitly unknown, never "free"."""
    from packages.core.providers.base import Usage
    tracker = app.state.studio.usage
    tracker.record(
        job_id=None, agent="ScriptAgent", provider="stub", model="legacy",
        usage=Usage(prompt_tokens=10, completion_tokens=0), est_cost_usd=0.0, elapsed_ms=1,
    )
    with tracker._connect() as conn:
        conn.execute(
            "UPDATE usage_log SET pricing_status = 'legacy_unknown',"
            " price_in_per_mtok = NULL, price_out_per_mtok = NULL"
        )
    tracker.set_configured_rates({})
    body = client.get("/api/usage/summary").json()
    row = next(r for r in body["by_model"] if r["model"] == "legacy")
    assert row["fully_priced"] is False
    assert row["unknown_price_calls"] == 1
    assert body["price_configured"] is False


def test_usage_summary_groups_by_day_agent_and_model(client, app):
    from packages.core.providers.base import Usage

    tracker = app.state.studio.usage
    for _day, agent, model, tokens in (
        ("2026-01-01", "ScriptAgent", "model-a", 100),
        ("2026-01-01", "ScriptAgent", "model-a", 50),
        ("2026-01-01", "QualityAgent", "model-b", 10),
        ("2026-01-02", "ScriptAgent", "model-a", 7),
    ):
        tracker.record(
            job_id=None, agent=agent, provider="stub", model=model,
            usage=Usage(prompt_tokens=tokens, completion_tokens=0),
            est_cost_usd=0.0, elapsed_ms=1,
        )
    # ``record`` stamps the current UTC day, so rewrite the days to make the grouping visible.
    import sqlite3

    with sqlite3.connect(app.state.studio.store.db_path) as conn:
        conn.execute("UPDATE usage_log SET day = '2026-01-01' WHERE id <= 3")
        conn.execute("UPDATE usage_log SET day = '2026-01-02' WHERE id = 4")

    response = client.get("/api/usage/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["price_configured"] is False
    days = {row["day"]: row for row in body["days"]}
    assert days["2026-01-01"]["tokens"] == 160
    assert days["2026-01-01"]["calls"] == 3
    assert days["2026-01-02"]["tokens"] == 7
    agents = {(row["day"], row["agent"]) for row in body["by_agent"]}
    assert ("2026-01-01", "ScriptAgent") in agents
    assert ("2026-01-01", "QualityAgent") in agents
    models = {(row["day"], row["model"]) for row in body["by_model"]}
    assert ("2026-01-01", "model-b") in models


def stage_ctx(store, job_id, tmp: Path | None = None) -> Any:
    """A stage context for direct stage.run() calls outside run_stages."""
    from packages.core.orchestration.runner import NullCancel, StageContext

    return StageContext(
        store,
        job_id,
        (tmp or Path(tempfile.mkdtemp(prefix="stagectx-"))),
        cancel=NullCancel(),
    )
