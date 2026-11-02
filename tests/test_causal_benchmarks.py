from __future__ import annotations

import unittest.mock as mock
from pathlib import Path
from typing import Any

import scripts.run_causal_benchmarks as bench_mod


def test_parse_args_defaults_to_fresh_mode() -> None:
    args = bench_mod.parse_args([])
    assert args.mode == "fresh"
    assert args.renderer == "custom-motion"
    assert args.fallback_policy == "strict"
    assert args.tts_provider == "edge-tts"


def test_parse_args_supports_modes_and_overrides() -> None:
    args = bench_mod.parse_args([
        "--mode", "verify-existing",
        "--benchmark", "b",
        "--renderer", "remotion",
        "--fallback-policy", "allow_legacy",
        "--tts-provider", "edge-tts",
        "--mock",
    ])
    assert args.mode == "verify-existing"
    assert args.benchmark == "b"
    assert args.renderer == "remotion"
    assert args.fallback_policy == "allow_legacy"
    assert args.tts_provider == "edge-tts"
    assert args.mock is True


def test_fresh_mode_never_reuses_existing_job_id(tmp_path: Path) -> None:
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
    state = AppState.build(settings, budget=Budget())

    benchmark = {
        "key": "a",
        "name": "Benchmark A",
        "domain": "Tech",
        "title": "Title A",
        "topic": "Topic A",
        "target_duration_s": 18,
        "existing_job_id": "0a4613ede915a12b",
    }

    # Simulate existing output.mp4 on disk for existing_job_id
    existing_dir = state.store.job_dir("0a4613ede915a12b")
    existing_dir.mkdir(parents=True, exist_ok=True)
    (existing_dir / "output.mp4").write_bytes(b"fake-existing-video")

    created_jobs: list[str] = []

    def fake_run_job(_state: Any, job_id: str, **_kwargs: Any) -> dict[str, Any]:
        created_jobs.append(job_id)
        # Create output.mp4 in newly created job dir
        job_dir = Path(_state.store.job_dir(job_id))
        (job_dir / "output.mp4").write_bytes(b"fake-fresh-video")
        return {"ok": True}

    with mock.patch("scripts.run_causal_benchmarks.run_job", side_effect=fake_run_job):
        with mock.patch("scripts.run_causal_benchmarks.LeaseKeeper"):
            res = bench_mod.run_single_benchmark(
                state,
                benchmark,
                mode="fresh",
                renderer="custom-motion",
                fallback_policy="strict",
                tts_provider="voicestudio",
                mock=True,
            )

    assert len(created_jobs) == 1
    assert created_jobs[0] != "0a4613ede915a12b"
    assert res["job_id"] == created_jobs[0]
    created_job = state.store.get(created_jobs[0])
    assert created_job is not None
    assert created_job.payload["renderer"] == "custom-motion"
    assert created_job.payload["fallback_policy"] == "strict"
    assert created_job.payload["tts_provider"] == "voicestudio"


def test_verify_existing_mode_reads_artifacts_without_running_job(tmp_path: Path) -> None:
    from apps.api.settings import Settings
    from apps.api.state import AppState
    from packages.core.contracts.state import JobState
    from packages.core.providers.usage import Budget

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    state = AppState.build(settings, budget=Budget())

    job = state.store.create(
        title="Title B",
        payload={"renderer": "custom-motion"},
        state=JobState.READY_FOR_APPROVAL,
    )
    job_dir = Path(state.store.job_dir(job.id))
    (job_dir / "output.mp4").write_bytes(b"existing-video")

    state.store.write_artifact(job.id, "render.json", {
        "renderer": "custom-motion",
        "fallback_used": False,
        "sha256": "f" * 64,
    })
    state.store.write_artifact(job.id, "tts_metadata.json", {
        "sample_rate": 24000,
        "alignment_mode": "aligned",
    })

    benchmark = {
        "key": "b",
        "name": "Benchmark B",
        "domain": "Science",
        "title": "Title B",
        "topic": "Topic B",
        "target_duration_s": 18,
        "existing_job_id": job.id,
    }

    with mock.patch("scripts.run_causal_benchmarks.run_job") as mock_run:
        res = bench_mod.run_single_benchmark(state, benchmark, mode="verify-existing")
        assert not mock_run.called

    assert res["job_id"] == job.id
    assert res["renderer_actual"] == "custom-motion"
    assert res["fallback_used"] is False
    assert res["tts_sample_rate"] == 24000
    assert res["tts_alignment_mode"] == "aligned"

    report = bench_mod.generate_markdown_report([res])
    assert "Benchmark B" in report
    assert "custom-motion" in report
    assert "aligned (24000Hz)" in report
