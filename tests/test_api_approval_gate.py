"""The approval gate must recompute, not read a claim.

Every test here builds a job that *looks* ready and then removes exactly one piece of evidence.
The old gate passed several of these: it read ``qc.json.technical.passed`` without validating the
artifact, never recomputed the output hash, and had no opinion about editorial or visual QC.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from packages.core.orchestration.editorial import compute_inputs_hash
from packages.core.providers.usage import Budget

READY_STATES = (
    JobState.TOPIC_SELECTED,
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
)


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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ready_job(client, app, *, provider_mode: str = "mock") -> tuple[str, dict]:
    """A job at READY_FOR_APPROVAL with every artifact the gate requires, all coherent."""
    job = client.post(
        "/api/jobs", json={"title": "Uji", "provider_mode": provider_mode}
    ).json()
    job_id = job["id"]
    store = app.state.studio.store
    for state in READY_STATES:
        store.transition(job_id, state)

    payload = b"\x00\x00\x00\x18ftypmp42" + b"0" * 200
    (Path(store.job_dir(job_id)) / "output.mp4").write_bytes(payload)
    digest = _sha(payload)
    store.write_artifact(
        job_id,
        "render.json",
        {
            "src": "output.mp4",
            "sha256": digest,
            "bytes": len(payload),
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "frames": 90,
            "duration_ms": 3000,
            "video_codec": "h264",
            "audio_codec": "aac",
            "pix_fmt": "yuv420p",
            "renderer": "remotion",
            "scene_hashes": {},
        },
    )
    # The readiness and technical hashes must be computed the same way the gate computes them,
    # or the fixture would be asserting a binding the real stage could never produce.
    storyboard = {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "dusk",
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "ObjectExplainer",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 90,
                "assetRefs": [],
                "text": [{"id": "t1", "text": "Halo", "role": "title", "atFrame": 0}],
                "camera": {"shot": "wide", "move": "static", "amplitude": 0.12},
                "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
                "transition": {"kind": "cut", "frames": 0},
                "data": {
                    "setting": "desert",
                    "timeOfDay": "dusk",
                    "actors": [],
                    "props": [],
                    "fx": [],
                    "shots": [{"framing": "wide", "camera": "pushIn", "weight": 1}],
                },
            }
        ],
        "subtitles": [{"startMs": 0, "endMs": 2000, "text": "Halo"}],
    }
    store.write_artifact(job_id, "storyboard.json", storyboard)
    store.write_artifact(
        job_id,
        "audio.json",
        {
            "narration": {"src": "narration.wav", "durationMs": 3000, "voice": "system-default"},
            "scenes": [{"sceneId": "sc1", "startMs": 0, "endMs": 3000}],
            "subtitles": storyboard["subtitles"],
            "mix": {"music": None, "ducking": False, "loudness_lufs": -16},
        },
    )
    store.write_artifact(job_id, "render-props.json", {"storyboard": {"scenes": []}})
    store.write_artifact(job_id, "metadata.json", {
        "schema_version": 1, "title": "Uji", "description": "", "tags": [],
        "category_id": "22", "made_for_kids": False, "synthetic_media": True, "thumbnail": {},
    })
    # Hash exactly what the stages hash. ``compute_inputs_hash`` canonicalises the storyboard
    # through the contract and ignores ``created_at``, so a raw dict and a stored artifact agree.
    # An earlier version of this fixture pre-canonicalised with ``model_dump``, which included
    # ``created_at`` — the same defect the hash itself had, and it made these tests pass or fail
    # depending on the wall-clock second.
    inputs = compute_inputs_hash(render_sha256=digest, narration_ms=3000, storyboard=storyboard)
    store.write_artifact(
        job_id,
        "technical-qc.json",
        {
            "passed": True,
            "checks": {"resolution": True},
            "observed": {"width": 1080},
            "thresholds": {"resolution": "1080x1920"},
            "failed": [],
            "detectors": {},
            "inputs_sha256": inputs,
        },
    )
    store.write_artifact(
        job_id,
        "qc.json",
        {
            "technical": {"passed": True, "failed": []},
            "creative": {"passed": True, "metrics": {"static_ratio": 0.1}, "failed": []},
            "visual": {
                "status": "skipped_no_vision_provider",
                "provider": None,
                "frames_extracted": 3,
                "frames_inspected": 0,
                "findings": [],
            },
            "repairs": [],
        },
    )
    store.write_artifact(
        job_id,
        "readiness.json",
        {
            "ready": True,
            "checks": {"technical": True, "creative": True, "visual": True, "checksum": True},
            "blockers": [],
            "technical_passed": True,
            "creative_passed": True,
            "visual_status": "skipped_no_vision_provider",
            "inputs_sha256": inputs,
        },
    )
    return job_id, {"inputs": inputs, "sha256": digest, "payload": payload}


def _approve(client, job_id: str):
    return client.post(f"/api/jobs/{job_id}/approve", json={"operator": "op"})


# -- the honest path ---------------------------------------------------------------------------


def test_a_fully_evidenced_live_job_can_be_approved(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    response = _approve(client, job_id)
    assert response.status_code == 200, response.text
    assert response.json()["checks"]["publishable"] is True
    assert app.state.studio.store.get(job_id).state is JobState.APPROVED


def test_a_mock_job_is_still_never_publishable(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="mock")
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "publishable" in response.json()["detail"]
    assert app.state.studio.store.get(job_id).state is JobState.READY_FOR_APPROVAL


# -- each missing piece blocks, and names itself -----------------------------------------------


def test_a_missing_technical_artifact_blocks(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    (Path(app.state.studio.store.job_dir(job_id)) / "technical-qc.json").unlink()
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "technical" in response.json()["detail"]


def test_a_missing_qa_artifact_blocks(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    (Path(app.state.studio.store.job_dir(job_id)) / "qc.json").unlink()
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "editorial" in response.json()["detail"] or "qc" in response.json()["detail"]


def test_a_missing_readiness_artifact_blocks(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    (Path(app.state.studio.store.job_dir(job_id)) / "readiness.json").unlink()
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "readiness" in response.json()["detail"]


def test_a_tampered_output_blocks_on_the_recomputed_hash(client, app):
    """The old gate trusted render.json.sha256. It never looked at the file."""
    job_id, _ = _ready_job(client, app, provider_mode="live")
    with open(Path(app.state.studio.store.job_dir(job_id)) / "output.mp4", "ab") as handle:
        handle.write(b"tamper")
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "checksum" in response.json()["detail"]


def test_a_technical_artifact_that_failed_blocks(client, app):
    job_id, ctx = _ready_job(client, app, provider_mode="live")
    app.state.studio.store.write_artifact(
        job_id,
        "technical-qc.json",
        {
            "passed": False,
            "checks": {"resolution": False},
            "observed": {},
            "thresholds": {"resolution": "1080x1920"},
            "failed": ["resolution"],
            "detectors": {},
            "inputs_sha256": ctx["inputs"],
        },
    )
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "technical" in response.json()["detail"]


def test_a_creative_failure_blocks(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    app.state.studio.store.write_artifact(
        job_id,
        "qc.json",
        {
            "technical": {"passed": True, "failed": []},
            "creative": {"passed": False, "metrics": {"static_ratio": 0.9}, "failed": ["static_ratio"]},
            "visual": {
                "status": "skipped_no_vision_provider",
                "provider": None,
                "frames_extracted": 3,
                "frames_inspected": 0,
                "findings": [],
            },
            "repairs": [],
        },
    )
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "creative" in response.json()["detail"]


def test_a_failed_visual_pass_blocks(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    app.state.studio.store.write_artifact(
        job_id,
        "qc.json",
        {
            "technical": {"passed": True, "failed": []},
            "creative": {"passed": True, "metrics": {"static_ratio": 0.1}, "failed": []},
            "visual": {
                "status": "failed",
                "provider": "vision-a",
                "frames_extracted": 3,
                "frames_inspected": 3,
                "findings": [{"atMs": 0, "issue": "missing character", "severity": "blocker"}],
            },
            "repairs": [],
        },
    )
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "visual" in response.json()["detail"]


def test_a_skipped_visual_pass_does_not_block(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    response = _approve(client, job_id)
    assert response.status_code == 200, response.text


def test_a_readiness_artifact_that_says_not_ready_blocks(client, app):
    job_id, ctx = _ready_job(client, app, provider_mode="live")
    app.state.studio.store.write_artifact(
        job_id,
        "readiness.json",
        {
            "ready": False,
            "checks": {"technical": True, "creative": True, "visual": True, "checksum": False},
            "blockers": ["checksum"],
            "technical_passed": True,
            "creative_passed": True,
            "visual_status": "skipped_no_vision_provider",
            "inputs_sha256": ctx["inputs"],
        },
    )
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "readiness" in response.json()["detail"]


def test_a_readiness_artifact_bound_to_a_different_hash_blocks(client, app):
    """A verdict computed against other bytes must not authorise these bytes."""
    job_id, _ = _ready_job(client, app, provider_mode="live")
    app.state.studio.store.write_artifact(
        job_id,
        "readiness.json",
        {
            "ready": True,
            "checks": {"technical": True, "creative": True, "visual": True, "checksum": True},
            "blockers": [],
            "technical_passed": True,
            "creative_passed": True,
            "visual_status": "skipped_no_vision_provider",
            "inputs_sha256": "b" * 64,
        },
    )
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "readiness" in response.json()["detail"]


def test_an_invalid_technical_artifact_blocks_rather_than_crashing(client, app):
    """A hand-edited artifact that no longer validates must be a 409, not a 500."""
    job_id, ctx = _ready_job(client, app, provider_mode="live")
    app.state.studio.store.write_artifact(
        job_id,
        "technical-qc.json",
        {"passed": "yes", "checks": {"resolution": "yes"}, "thresholds": {}},
    )
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "technical" in response.json()["detail"]


def test_no_credential_or_image_data_appears_in_the_refusal(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    with open(Path(app.state.studio.store.job_dir(job_id)) / "output.mp4", "ab") as handle:
        handle.write(b"tamper")
    response = _approve(client, job_id)
    body = json.dumps(response.json())
    assert "base64" not in body
    assert "data:image" not in body
    assert "sk-" not in body


def test_a_blocked_job_cannot_be_resumed_into_approved(client, app):
    """The gate is not bypassable by a resume path, because the store demands its artifact.

    ``_approval_checks`` runs only on ``POST /approve``. A scheduler or a resume helper calling
    ``JobStore.transition(READY_FOR_APPROVAL -> APPROVED)`` would therefore approve without any
    evidence. This drives the store directly — as such a helper would — and asserts the refusal.
    """
    from packages.core.orchestration.jobstore import IllegalTransition

    job_id, _ = _ready_job(client, app, provider_mode="live")
    store = app.state.studio.store
    # The gate runs for real, then the job fails after approval (an upload failure is the case
    # that makes this round trip reachable at all).
    assert _approve(client, job_id).status_code == 200, "the fixture must reach APPROVED"
    store.transition(job_id, JobState.BLOCKED, detail="upload failed")

    with pytest.raises(IllegalTransition) as exc:
        store.transition(job_id, JobState.APPROVED, detail="scheduler resume")
    assert "BLOCKED -> APPROVED" in str(exc.value)
    assert store.get(job_id).state is JobState.BLOCKED

    # ``PRIVATE_UPLOAD`` stays shut behind it: the only inbound edge is APPROVED.
    with pytest.raises(IllegalTransition):
        store.transition(job_id, JobState.PRIVATE_UPLOAD)
    assert store.get(job_id).state is JobState.BLOCKED


def test_resuming_to_the_gate_state_does_not_authorise_approval(client, app):
    """Reaching ``READY_FOR_APPROVAL`` is not passing the gate.

    This is the residual the allow-list alone could not close: the state is reachable from
    ``BLOCKED`` (covered at store level in ``tests/test_jobstore.py``), and being there must not be
    sufficient. With no ``approval.json`` the direct transition is refused; the approve route is
    the only door, and it opens immediately once it has run.
    """
    from packages.core.orchestration.jobstore import IllegalTransition

    job_id, _ = _ready_job(client, app, provider_mode="live")
    store = app.state.studio.store
    (Path(store.job_dir(job_id)) / "approval.json").unlink(missing_ok=True)
    assert store.get(job_id).state is JobState.READY_FOR_APPROVAL

    with pytest.raises(IllegalTransition) as exc:
        store.transition(job_id, JobState.APPROVED, detail="shortcut")
    assert "approval.json" in str(exc.value)
    assert store.get(job_id).state is JobState.READY_FOR_APPROVAL

    # The route is the only door, and it works.
    assert _approve(client, job_id).status_code == 200
    assert store.get(job_id).state is JobState.APPROVED


def test_the_approve_route_records_the_render_it_approved(client, app):
    """``approval.json`` must name the render, or a stale decision could authorise a new file."""
    job_id, ctx = _ready_job(client, app, provider_mode="live")
    assert _approve(client, job_id).status_code == 200
    approval = app.state.studio.store.read_artifact(job_id, "approval.json")
    assert approval["render_sha256"] == ctx["sha256"]
    assert approval["decision"] == "approved"
    assert approval["checks"]["publishable"] is True


def test_a_stale_approval_blocks_after_a_re_render(client, app):
    """A re-render after approval invalidates it: the artifact names bytes that no longer exist."""
    from packages.core.orchestration.jobstore import IllegalTransition

    job_id, ctx = _ready_job(client, app, provider_mode="live")
    store = app.state.studio.store
    assert _approve(client, job_id).status_code == 200
    store.transition(job_id, JobState.BLOCKED, detail="upload failed")

    # A re-render produces different bytes and a new render.json digest.
    new_payload = b"\x00\x00\x00\x18ftypmp42" + b"1" * 200
    (Path(store.job_dir(job_id)) / "output.mp4").write_bytes(new_payload)
    store.write_artifact(
        job_id, "render.json", {**store.read_artifact(job_id, "render.json"),
                                "sha256": hashlib.sha256(new_payload).hexdigest()}
    )

    store.transition(job_id, JobState.READY_FOR_APPROVAL, detail="re-review")
    with pytest.raises(IllegalTransition) as exc:
        store.transition(job_id, JobState.APPROVED, detail="stale")
    assert "stale approval" in str(exc.value)
    assert store.get(job_id).state is JobState.READY_FOR_APPROVAL


def test_the_fixture_hash_does_not_depend_on_the_clock(monkeypatch):
    """The gate fixture must be deterministic; a clock-dependent hash made these tests flaky."""
    import packages.core.contracts.base as base

    monkeypatch.setattr(base, "_utc_now", lambda: "2026-01-01T00:00:00+00:00")
    first = compute_inputs_hash(render_sha256="a" * 64, narration_ms=3000, storyboard={"scenes": []})
    monkeypatch.setattr(base, "_utc_now", lambda: "2026-01-01T00:00:07+00:00")
    second = compute_inputs_hash(render_sha256="a" * 64, narration_ms=3000, storyboard={"scenes": []})
    assert first == second
