"""Benchmark reporting cannot turn absent artifacts into production evidence."""
import json
from pathlib import Path

import pytest

from apps.api.settings import Settings
from apps.api.state import AppState
from packages.core.contracts.state import JobState
from scripts import run_causal_benchmarks as bench


@pytest.fixture
def recorded_job(tmp_path):
    state = AppState.build(Settings(
        data_dir=tmp_path / "data", db_path=tmp_path / "data/factory.db",
        jobs_dir=tmp_path / "data/jobs", secrets_dir=tmp_path / "data/secrets",
        studio_config=tmp_path / "config/studio.json",
    ).ensure())
    job = state.store.create(title="Evidence fixture", state=JobState.READY_FOR_APPROVAL)
    root = Path(state.store.job_dir(job.id))
    (root / "output.mp4").write_bytes(b"not production media")
    config = {**bench.BENCHMARKS[0], "existing_job_id": job.id, "wall_time_s": 123.45}
    return state, job, root, config


def verify(recorded_job):
    state, _, _, config = recorded_job
    return bench.run_single_benchmark(state, config, mode="verify-existing")


def test_missing_artifacts_never_get_positive_defaults(recorded_job):
    result = verify(recorded_job)
    assert result["ok"] is False
    assert result["bme_status"] == "UNVERIFIED"
    assert result["bme_passed"] is False
    for field in ("renderer_actual", "tts_sample_rate", "tts_alignment_mode", "wall_time_s"):
        assert result[field] is None
    assert result["evidence"]["cost_usd"]["status"] == "unavailable"
    assert result["evidence"]["cost_usd"]["value"] is None
    report = bench.generate_markdown_report([result])
    assert "UNVERIFIED" in report
    assert "PASS" not in report
    assert "16000" not in report
    assert "123.45" not in report


@pytest.mark.parametrize("qc", [[], {"creative": []}, {"creative": {"metrics": None}},
    {"creative": {"metrics": {"bme_dynamics": {"passed": True, "scene_metrics": []}}}},
    {"creative": {"metrics": {"bme_dynamics": {"passed": "true"}}}},
])
def test_malformed_or_incomplete_qc_is_unverified(recorded_job, qc):
    _, _, root, _ = recorded_job
    (root / "qc.json").write_text(json.dumps(qc), encoding="utf-8")
    result = verify(recorded_job)
    assert result["ok"] is False
    assert result["bme_status"] == "UNVERIFIED"
    assert result["bme_passed"] is False


def test_broken_json_is_reported_as_unavailable_evidence(recorded_job):
    _, _, root, _ = recorded_job
    (root / "render.json").write_text('{"renderer":', encoding="utf-8")
    result = verify(recorded_job)
    assert result["ok"] is False
    assert result["renderer_actual"] is None
    assert result["evidence"]["renderer"]["source"] == "render.json"
    assert result["evidence"]["renderer"]["status"] == "unavailable"


def test_null_bme_metrics_are_not_rendered_as_dynamic_pass(recorded_job):
    _, _, root, _ = recorded_job
    qc = {"technical": {"passed": True},
          "visual": {"status": "skipped_no_vision_provider", "provider": None,
                     "frames_inspected": 0, "frames_extracted": 0},
          "creative": {"passed": False, "metrics": {"bme_dynamics": {
        "status": "UNVERIFIED", "passed": False,
        "scene_metrics": [{"sceneId": "s1", "measured": False,
                           "delta_bm": None, "delta_me": None, "static": None}],
    }}}}
    (root / "qc.json").write_text(json.dumps(qc), encoding="utf-8")
    from packages.core.contracts.artifacts import QaArtifact
    from packages.core.contracts.base import validate_artifact

    validate_artifact(QaArtifact, qc)
    report = bench.generate_markdown_report([verify(recorded_job)])
    assert "s1" in report
    assert "UNVERIFIED" in report
    assert "PASS (DYNAMIC)" not in report
    assert "0.0000" not in report


def test_complete_pixel_measurements_can_pass_without_claiming_semantics():
    from packages.core.media.qc import evaluate_bme_dynamics

    scenes = [{"sceneId": "s1", "startFrame": 0, "durationInFrames": 90}]
    body = evaluate_bme_dynamics(scenes, [(b"\x00", b"\x80", b"\xff")])
    assert bench.bme_verdict(body, scenes) == "PASS"
    assert bench.bme_verdict(body, [{"sceneId": "s1"}]) == "UNVERIFIED"
    body["scene_metrics"][0]["delta_me"] = None
    assert bench.bme_verdict(body, scenes) == "UNVERIFIED"


@pytest.mark.parametrize("delta", [None, True, float("nan"), float("inf"), -0.1, "0.3"])
def test_bad_scene_metrics_cannot_certify_pass(delta):
    body = {"status": "PASS", "passed": True, "min_delta_threshold": 0.005,
            "scene_metrics": [{"sceneId": "s1", "measured": True,
                               "delta_bm": delta, "delta_me": 0.2, "static": False}]}
    assert bench.bme_verdict(body, [{"sceneId": "s1", "startFrame": 0, "durationInFrames": 90}]) == "UNVERIFIED"


@pytest.mark.parametrize("reported,cost,expected", [(True, 0.25, 0.25), (True, 0.0, 0.0),
    (False, 0.0, None), (True, None, None), (True, float("nan"), None)])
def test_cost_estimates_require_reported_usage_and_recorded_source(recorded_job, reported, cost, expected):
    state, job, _, _ = recorded_job
    key = "a" * 64
    state.requests.prepare(request_key=key, job_id=job.id, agent="QualityAgent", attempt=1,
                           provider="fixture", model="fixture")
    state.requests.mark_completed(request_key=key, attempt=1, usage={
        "reported": reported, "est_cost_usd": cost, "cost_source": "configured_rate_estimate",
    }, result={"text": "test only"})
    result = verify(recorded_job)
    assert result["evidence"]["cost_usd"]["value"] == expected
    assert result["evidence"]["cost_usd"]["status"] == ("estimated" if expected is not None else "unavailable")
    assert result["evidence"]["billed_cost_usd"]["value"] is None
    assert result["ok"] is False


def test_legacy_cached_success_is_not_a_verified_report():
    report = bench.generate_markdown_report([{"name": "legacy", "ok": True, "bme_passed": True}])
    assert "UNVERIFIED" in report
    assert "PASS" not in report


def test_incomplete_storyboard_cannot_supply_bme_coverage(recorded_job):
    _, _, root, _ = recorded_job
    (root / "storyboard.json").write_text(json.dumps({"scenes": [{"sceneId": "s1"}]}), encoding="utf-8")
    body = {"status": "PASS", "passed": True, "min_delta_threshold": 0.005,
            "scene_metrics": [{"sceneId": "s1", "measured": True,
                               "delta_bm": 0.2, "delta_me": 0.2, "static": False}]}
    (root / "qc.json").write_text(json.dumps({"creative": {"metrics": {"bme_dynamics": body}}}), encoding="utf-8")
    assert verify(recorded_job)["bme_status"] == "UNVERIFIED"


def test_invocation_timing_is_measured_without_substituting_lifetime_time(recorded_job, monkeypatch):
    state, _, _, config = recorded_job
    clock = iter([10.0, 13.0])
    monkeypatch.setattr(bench.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(bench, "run_job", lambda *a, **k: {"ok": False})
    result = bench.run_single_benchmark(state, config, mode="fresh")
    assert result["wall_time_s"] == 3.0
    assert result["evidence"]["wall_time_s"]["status"] == "measured"
    assert "not lifetime" in result["evidence"]["wall_time_s"]["source"]
    assert result["ok"] is False
