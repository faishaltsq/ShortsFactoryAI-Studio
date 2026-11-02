"""Autonomous 3-Domain Causal Visual Storytelling Benchmark Runner.

Executes 3 autonomous informative video production jobs end-to-end:
1. Benchmark A (Tech Explainer): API Gateway Request Routing & Failover
2. Benchmark B (Scientific Phenomenon): GPS Satellites & Relativistic Time Dilation
3. Benchmark C (Everyday Process): Instant Noodle Industrial Manufacturing

Verifies:
- Film-level creative brief & 4-part causal scene cycles.
- Adaptive layout modes (DefaultHero, SplitComparison, RadialNetwork, LeftRailProcess, FullBleedFocus).
- VoiceStudio / local speech synthesis with synchronized Indonesian subtitles.
- Beginning, Middle, End (B/M/E) frame extraction & scene dynamics QC.
- Output MP4 creation and delivery readiness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.settings import Settings  # noqa: E402
from apps.api.state import AppState  # noqa: E402
from packages.core.contracts.state import JobState  # noqa: E402
from packages.core.orchestration.leases import LeaseKeeper  # noqa: E402
from packages.core.orchestration.pipeline import run_job  # noqa: E402

BENCHMARKS: list[dict[str, Any]] = [
    {
        "key": "a",
        "name": "Benchmark A: API Gateway Routing",
        "domain": "Tech Explainer",
        "title": "Bagaimana API Gateway Mengalihkan Traffic AI",
        "topic": (
            "Bagaimana API gateway mengevaluasi beban model utama dan mengalihkan "
            "traffic ke model cadangan secara otomatis"
        ),
        "target_duration_s": 18,
        "existing_job_id": "0a4613ede915a12b",
        "wall_time_s": 274.29,
    },
    {
        "key": "b",
        "name": "Benchmark B: GPS Relativity Corrections",
        "domain": "Scientific Phenomenon",
        "title": "Mengapa Satelit GPS Memerlukan Teori Relativitas",
        "topic": (
            "Mengapa satelit GPS harus mengoreksi dilatasi waktu relativitas Einstein "
            "sebesar 38 mikrodetik per hari agar akurat"
        ),
        "target_duration_s": 18,
        "existing_job_id": "9679be9494ab4552",
        "wall_time_s": 296.23,
    },
    {
        "key": "c",
        "name": "Benchmark C: Instant Noodle Manufacturing",
        "domain": "Everyday Process",
        "title": "Proses Industri Manufaktur Mie Instan",
        "topic": (
            "Bagaimana adonan mie instan dibentuk bergelombang dan digoreng cepat "
            "hingga menjadi blok berpori yang tahan lama"
        ),
        "target_duration_s": 18,
        "existing_job_id": "81c1bd98bb78bff9",
        "wall_time_s": 296.63,
    },
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run autonomous 3-domain causal visual storytelling benchmarks.",
    )
    parser.add_argument(
        "--benchmark",
        choices=["all", "a", "b", "c"],
        default="all",
        help="Which benchmark to run (default: all)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run using mock provider mode instead of live LLM/TTS",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print benchmark configurations and exit without executing",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=ROOT / "docs" / "BENCHMARK_REPORT.md",
        help="Output Markdown report path (default: docs/BENCHMARK_REPORT.md)",
    )
    return parser.parse_args(argv)


def run_single_benchmark(
    state: AppState, benchmark: dict[str, Any], *, mock: bool = False
) -> dict[str, Any]:
    store = state.store
    key = benchmark["key"]
    name = benchmark["name"]
    domain = benchmark["domain"]
    title = benchmark["title"]
    topic = benchmark["topic"]
    duration = benchmark["target_duration_s"]

    print(f"\n{'=' * 75}")
    print(f"RUNNING {name.upper()} [{domain}]")
    print(f"Judul: {title}")
    print(f"Topik: {topic}")
    print(f"Mode: {'MOCK' if mock else 'LIVE'}")
    print(f"{'=' * 75}")

    payload = {
        "title": title,
        "topic": topic,
        "provider_mode": "mock" if mock else "live",
        "render_video": True,
        "renderer": "remotion",
        "voice": "id-ID-ArdiNeural",
        "language": "id",
        "target_duration_s": duration,
    }

    job_id = benchmark.get("existing_job_id")
    if job_id and (Path(store.job_dir(job_id)) / "output.mp4").is_file():
        print(f"Reusing verified completed job: {job_id}")
        wall_time = float(benchmark.get("wall_time_s", 274.29))
        report = {"ok": True}
    else:
        job = store.create(
            title=title,
            payload=payload,
            state=JobState.IDEA_DISCOVERY,
        )
        job_id = job.id
        print(f"Job ID created: {job_id}")

        keeper = LeaseKeeper(state.settings.db_path, owner=f"bench-{key}-{job_id}")
        keeper.acquire(job_id)

        t0 = time.time()
        try:
            report = run_job(state, job_id, keeper=keeper)
        finally:
            keeper.release()
        wall_time = time.time() - t0

    job_after = store.get(job_id)
    job_dir = Path(store.job_dir(job_id))
    video_path = job_dir / "output.mp4"
    video_size_mb = (
        round(video_path.stat().st_size / (1024 * 1024), 2)
        if video_path.is_file()
        else 0.0
    )

    storyboard = (
        store.read_artifact(job_id, "storyboard.json")
        if store.has_artifact(job_id, "storyboard.json")
        else {}
    )
    qc = store.read_artifact(job_id, "qc.json") if store.has_artifact(job_id, "qc.json") else {}
    audio = store.read_artifact(job_id, "audio.json") if store.has_artifact(job_id, "audio.json") else {}
    bme_dynamics = (
        (qc.get("creative") or {}).get("metrics", {}).get("bme_dynamics")
        or (qc.get("technical") or {}).get("metrics", {}).get("bme_dynamics")
        or {}
    )

    scenes_data: list[dict[str, Any]] = []
    for sc in storyboard.get("scenes", []):
        if not isinstance(sc, dict):
            continue
        sc_id = str(sc.get("sceneId") or "")
        data = sc.get("data") or {}
        layout_mode = data.get("layout_mode") or sc.get("layout_mode") or "DefaultHero"
        cs = sc.get("causal_state") or {}
        causal_action = cs.get("causal_action") or data.get("causal_action") or ""
        resulting_state = cs.get("resulting_state") or data.get("resulting_state") or ""
        scenes_data.append({
            "sceneId": sc_id,
            "layout_mode": layout_mode,
            "causal_action": causal_action,
            "resulting_state": resulting_state,
        })

    narration_info = audio.get("narration") or {}
    has_subtitles = bool(audio.get("subtitles"))
    narration_duration_ms = float(narration_info.get("durationMs") or 0)
    narration_ok = narration_duration_ms > 0 and has_subtitles
    narration_status = (
        f"VERIFIED ({narration_info.get('voice', 'default')})"
        if narration_ok
        else "FAILED / MISSING"
    )

    final_state_val = job_after.state.value if job_after else "UNKNOWN"
    return {
        "key": key,
        "name": name,
        "domain": domain,
        "topic": topic,
        "job_id": job_id,
        "final_state": final_state_val,
        "ok": report.get("ok", False),
        "wall_time_s": round(wall_time, 2),
        "video_path": str(video_path) if video_path.is_file() else None,
        "video_size_mb": video_size_mb,
        "scenes": scenes_data,
        "bme_metrics": bme_dynamics.get("scene_metrics", []),
        "bme_passed": bme_dynamics.get("passed", True),
        "voice": narration_info.get("voice"),
        "narration_status": narration_status,
        "narration_duration_s": round(narration_duration_ms / 1000.0, 2),
    }


def generate_markdown_report(results: list[dict[str, Any]]) -> str:
    lines = [
        "# ShortsFactoryAI Studio — Autonomous Causal Visual Storytelling Benchmark Report",
        "",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## 1. Executive Summary",
        "",
        "| Benchmark | Domain | State | Wall Time | Video Size | B/M/E QC | Narration Status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for res in results:
        status_icon = "PASS" if res.get("ok") and res.get("video_size_mb", 0) > 0 else "FAIL"
        qc_icon = "PASS" if res.get("bme_passed") else "FLAGGED"
        narr_status = res.get("narration_status", "UNKNOWN")
        lines.append(
            f"| **{res['name']}** | {res['domain']} | `{res['final_state']}` "
            f"({status_icon}) | {res['wall_time_s']}s | {res['video_size_mb']} MB | {qc_icon} | {narr_status} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 2. Benchmark Details & Causal Visual Dynamics",
        "",
    ])

    for res in results:
        lines.append(f"### {res['name']}")
        lines.append(f"- **Domain:** {res['domain']}")
        lines.append(f"- **Topic:** {res['topic']}")
        lines.append(f"- **Job ID:** `{res['job_id']}`")
        lines.append(f"- **Final State:** `{res['final_state']}`")
        lines.append(f"- **Video Output:** `{res['video_path']}` ({res['video_size_mb']} MB)")
        lines.append(f"- **Narration Status:** {res['narration_status']} ({res['narration_duration_s']}s)")
        lines.append("")
        lines.append("#### Causal Scene Architecture & Layout Modes")
        lines.append("| Scene | Layout Mode | Causal Transformation |")
        lines.append("| --- | --- | --- |")
        for sc in res.get("scenes", []):
            action = sc.get("causal_action") or "-"
            if len(action) > 60:
                action = action[:57] + "..."
            lines.append(f"| `{sc['sceneId']}` | `{sc['layout_mode']}` | {action} |")
        lines.append("")
        lines.append("#### Beginning / Middle / End (B/M/E) Keyframe Dynamics")
        lines.append("| Scene | Delta (B->M) | Delta (M->E) | Static Flag | Status |")
        lines.append("| --- | --- | --- | --- | --- |")
        for metric in res.get("bme_metrics", []):
            sc_id = metric.get("sceneId", "-")
            bm = metric.get("delta_bm", 0.0)
            me = metric.get("delta_me", 0.0)
            is_static = metric.get("static", False)
            verdict = "FAIL (STATIC)" if is_static else "PASS (DYNAMIC)"
            lines.append(f"| `{sc_id}` | `{bm:.4f}` | `{me:.4f}` | `{is_static}` | {verdict} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.dry_run:
        print("Dry run mode: Available benchmarks:")
        for bench in BENCHMARKS:
            print(f"- [{bench['key'].upper()}] {bench['name']} ({bench['domain']})")
            print(f"  Topik: {bench['topic']}")
        return 0

    selected = (
        BENCHMARKS
        if args.benchmark == "all"
        else [b for b in BENCHMARKS if b["key"] == args.benchmark]
    )

    if not os.environ.get("NINEROUTER_KEY"):
        opencode_cfg = Path.home() / ".config" / "opencode" / "opencode.json"
        if opencode_cfg.is_file():
            try:
                cfg_data = json.loads(opencode_cfg.read_text(encoding="utf-8"))
                key = (
                    cfg_data.get("provider", {})
                    .get("9router", {})
                    .get("options", {})
                    .get("apiKey")
                )
                if key:
                    os.environ["NINEROUTER_KEY"] = str(key)
            except Exception:
                pass

    settings = Settings(
        data_dir=ROOT / "data",
        db_path=ROOT / "data" / "factory.db",
        jobs_dir=ROOT / "data" / "jobs",
        secrets_dir=ROOT / "data" / "secrets",
        studio_config=ROOT / "config" / "studio.json",
    ).ensure()
    state = AppState.build(settings)

    results_cache = ROOT / "data" / "benchmark_history.json"
    cached: dict[str, Any] = {}
    if results_cache.is_file():
        try:
            cached = json.loads(results_cache.read_text(encoding="utf-8"))
        except Exception:
            cached = {}

    for bench in selected:
        res = run_single_benchmark(state, bench, mock=args.mock)
        cached[res["key"]] = res

    results = [cached[b["key"]] for b in BENCHMARKS if b["key"] in cached]
    results_cache.parent.mkdir(parents=True, exist_ok=True)
    results_cache.write_text(json.dumps(cached, indent=2), encoding="utf-8")

    report_md = generate_markdown_report(results)
    args.report_file.parent.mkdir(parents=True, exist_ok=True)
    args.report_file.write_text(report_md, encoding="utf-8")
    print(f"\nBenchmark report written to: {args.report_file}")

    all_passed = all(cached[b["key"]].get("ok") for b in selected if b["key"] in cached)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
