"""Frame measurement failures must survive the editorial persistence boundary."""
from __future__ import annotations

import hashlib
from pathlib import Path

from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from packages.core.orchestration import editorial
from packages.core.orchestration.runner import run_stages


def test_extraction_failure_persists_unverified_without_requesting_static_repair(tmp_path, monkeypatch):
    state = AppState.build(Settings(
        data_dir=tmp_path / "data", db_path=tmp_path / "data/factory.db",
        jobs_dir=tmp_path / "data/jobs", secrets_dir=tmp_path / "data/secrets",
        studio_config=tmp_path / "config/studio.json",
    ).ensure())
    job = state.store.create(title="Decoder failure fixture", state=JobState.TECHNICAL_QC)
    props = {"scenes": [{"sceneId": "mechanism", "startFrame": 0, "durationInFrames": 90}]}
    video = Path(state.store.job_dir(job.id)) / "output.mp4"
    # Not production media: the decoder boundary below deterministically fails.
    video.write_bytes(b"unit-test decoder input")
    for name, payload in {
        "storyboard.json": props,
        "audio.json": {"narration": {"durationMs": 3000}},
        "render.json": {"src": "output.mp4", "sha256": hashlib.sha256(video.read_bytes()).hexdigest()},
        "technical-qc.json": {"passed": True, "failed": [], "checks": {}},
    }.items():
        state.store.write_artifact(job.id, name, payload)

    def decode_failure(*args, **kwargs):
        raise RuntimeError("incomplete decoder output")

    monkeypatch.setattr(editorial, "_storyboard", lambda _: props)
    monkeypatch.setattr(editorial, "verify_voice_locale", lambda *a, **k: (True, ""))
    monkeypatch.setattr(editorial, "measure_static", lambda _: (0.0, None))
    monkeypatch.setattr(editorial, "extract_bme_frames", decode_failure)
    monkeypatch.setattr(editorial, "extract_contact_sheet", decode_failure)
    monkeypatch.setattr(editorial, "_vision_call", lambda *a: None)

    result = run_stages(store=state.store, job_id=job.id, stages=[editorial.build_editorial_qc_stage(state)])

    assert result["stopped"] == "qa_blocked"
    assert state.store.get(job.id).state is JobState.BLOCKED
    qa = state.store.read_artifact(job.id, "qc.json")
    evidence = qa["creative"]["metrics"]["bme_dynamics"]
    assert evidence["status"] == "UNVERIFIED"
    assert evidence["passed"] is False
    assert evidence["unmeasured_scenes"] == ["mechanism"]
    assert evidence["static_scenes"] == []
    assert evidence["scene_metrics"][0]["delta_bm"] is None
    assert "incomplete decoder output" in evidence["error"]
    assert state.usage.for_job(job.id) == []
    manifest = state.store.read_artifact(job.id, "visual-evidence.json")
    assert manifest["complete"] is False
    assert manifest["inspection_status"] == "UNVERIFIED"
    assert manifest["provider"] is None and manifest["model"] is None
    assert qa["semantic"]["status"] == "UNVERIFIED"
    assert all(item["repair_scope"] == "none" for item in qa["semantic"]["criteria"])
