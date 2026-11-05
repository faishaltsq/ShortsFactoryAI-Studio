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
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.settings import Settings  # noqa: E402
from apps.api.state import AppState  # noqa: E402
from packages.core.contracts.artifacts import (  # noqa: E402
    AudioArtifact,
    MotionCodeArtifact,
    QaArtifact,
    ReadinessArtifact,
    RenderArtifact,
    StoryboardArtifact,
    TechnicalQaArtifact,
    VisualEvidenceArtifact,
)
from packages.core.contracts.base import validate_artifact  # noqa: E402
from packages.core.contracts.state import JobState  # noqa: E402
from packages.core.media.qc import sha256_file  # noqa: E402
from packages.core.orchestration.editorial import compute_inputs_hash, evaluate_job_readiness  # noqa: E402
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
    },
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run autonomous 3-domain causal visual storytelling benchmarks.",
    )
    parser.add_argument(
        "--mode",
        choices=["fresh", "resume", "verify-existing"],
        default="fresh",
        help="Execution mode: 'fresh' creates and runs brand new jobs; 'resume' continues incomplete jobs; 'verify-existing' validates existing artifacts without re-executing (default: fresh)",
    )
    parser.add_argument(
        "--benchmark",
        choices=["all", "a", "b", "c"],
        default="all",
        help="Which benchmark to run (default: all)",
    )
    parser.add_argument(
        "--renderer",
        choices=["custom-motion", "remotion", "legacy-template"],
        default="custom-motion",
        help="Rendering engine to request (default: custom-motion)",
    )
    parser.add_argument(
        "--fallback-policy",
        choices=["strict", "allow_legacy"],
        default="strict",
        help="Fallback policy if custom-motion fails (default: strict)",
    )
    parser.add_argument(
        "--tts-provider",
        choices=["voicestudio", "edge-tts", "sapi"],
        default="edge-tts",
        help="TTS provider to use (default: edge-tts)",
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
    state: AppState,
    benchmark: dict[str, Any],
    *,
    mode: str = "fresh",
    renderer: str = "custom-motion",
    fallback_policy: str = "strict",
    tts_provider: str = "voicestudio",
    mock: bool = False,
) -> dict[str, Any]:
    store = state.store
    key = benchmark["key"]
    name = benchmark["name"]
    domain = benchmark["domain"]
    title = benchmark["title"]
    topic = benchmark["topic"]
    duration = benchmark["target_duration_s"]

    print(f"\n{'=' * 75}")
    operation = "INSPECTING RECORDED EVIDENCE" if mode == "verify-existing" else "RUNNING"
    print(f"{operation} {name.upper()} [{domain}]")
    print(f"Judul: {title}")
    print(f"Topik: {topic}")
    print(f"Mode Runner: {mode.upper()} | Requested provider mode: {'MOCK' if mock else 'LIVE'}")
    print(f"Engine: {renderer} (Policy: {fallback_policy}) | TTS: {tts_provider}")
    print(f"{'=' * 75}")

    voice = "alloy" if tts_provider == "voicestudio" else "id-ID-ArdiNeural"
    payload = {
        "title": title,
        "topic": topic,
        "provider_mode": "mock" if mock else "live",
        "render_video": True,
        "renderer": renderer,
        "fallback_policy": fallback_policy,
        "tts_provider": tts_provider,
        "voice": voice,
        "language": "id",
        "target_duration_s": duration,
    }

    job_id = benchmark.get("existing_job_id") if mode != "fresh" else None
    wall_time = None
    execution = None
    if mode == "fresh":
        job_id = store.create(title=title, payload=payload, state=JobState.IDEA_DISCOVERY).id
    elif mode not in {"resume", "verify-existing"} or not job_id:
        raise ValueError("An existing job is required; resume never creates a paid replacement")
    store.get(job_id)
    if mode == "fresh" or (mode == "resume" and not (Path(store.job_dir(job_id)) / "output.mp4").is_file()):
        keeper = LeaseKeeper(state.settings.db_path, owner=f"bench-{key}-{job_id}")
        keeper.acquire(job_id)
        started = time.perf_counter()
        try:
            execution = run_job(state, job_id, keeper=keeper)
        finally:
            wall_time = time.perf_counter() - started
            keeper.release()
    result = collect_evidence(state, job_id)
    if result["renderer_actual"] not in (None, renderer) or (
        fallback_policy == "strict" and result["fallback_used"] is True
    ):
        result["status"] = "FAIL"
    if execution is not None and execution.get("ok") is not True:
        result["status"] = "FAIL"
    result.update(
        key=key, name=name, domain=domain, topic=topic, job_id=job_id, mode=mode,
        renderer_requested=renderer, ok=result["status"] == "PASS",
        wall_time_s=round(wall_time, 3) if wall_time is not None else None,
    )
    result["evidence"]["wall_time_s"] = metric(
        wall_time, "current invocation time.perf_counter (not lifetime production time)"
    )
    return result


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any, *, positive: bool = False) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and (value > 0 if positive else value >= 0)


def metric(value: Any, source: str, status: str = "measured") -> dict[str, Any]:
    return {"value": value, "source": source, "status": status if value is not None else "unavailable"}


def bme_verdict(body: dict[str, Any], scenes: Any) -> str:
    if not isinstance(scenes, list) or not scenes or any(not isinstance(s, dict) for s in scenes):
        return "UNVERIFIED"
    if any(type(s.get("startFrame")) is not int or type(s.get("durationInFrames")) is not int
           or s["startFrame"] < 0 or s["durationInFrames"] <= 0 for s in scenes):
        return "UNVERIFIED"
    ids = [s.get("sceneId") for s in scenes]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        return "UNVERIFIED"
    rows = body.get("scene_metrics")
    threshold = body.get("min_delta_threshold")
    if not isinstance(rows, list) or len(rows) != len(ids) or not _number(threshold):
        return "UNVERIFIED"
    if any(not isinstance(row, dict) for row in rows):
        return "UNVERIFIED"
    row_ids = [row.get("sceneId") for row in rows]
    if any(not isinstance(i, str) for i in row_ids) or set(row_ids) != set(ids):
        return "UNVERIFIED"
    static = False
    for row in rows:
        bm, me = row.get("delta_bm"), row.get("delta_me")
        if row.get("measured") is not True or not _number(bm) or not _number(me) or bm > 1 or me > 1:
            return "UNVERIFIED"
        frozen = bm < threshold or me < threshold
        if row.get("static") is not frozen:
            return "UNVERIFIED"
        static = static or frozen
    expected = "FAIL" if static else "PASS"
    if body.get("status") != expected or body.get("passed") is not (not static):
        return "UNVERIFIED"
    return expected


def collect_evidence(state: AppState, job_id: str) -> dict[str, Any]:
    store = state.store
    root = Path(store.job_dir(job_id)).resolve()
    issues: list[str] = []
    sources: dict[str, Any] = {}

    def load(name: str) -> dict[str, Any]:
        try:
            payload = store.read_artifact(job_id, name)
            if not isinstance(payload, dict):
                raise ValueError("artifact must be an object")
            contract = {
                "storyboard.json": StoryboardArtifact, "qc.json": QaArtifact,
                "audio.json": AudioArtifact, "render.json": RenderArtifact,
                "motion-code.json": MotionCodeArtifact, "technical-qc.json": TechnicalQaArtifact,
                "readiness.json": ReadinessArtifact,
                "visual-evidence.json": VisualEvidenceArtifact,
            }.get(name)
            if contract is not None:
                # Validate without taking model defaults as observations in the source file.
                validate_artifact(contract, payload)
            sources[name] = {"sha256": sha256_file(root / name), "status": "recorded"}
            return payload
        except (OSError, ValueError, TypeError):
            issues.append(f"{name}: missing, malformed or unreadable")
            sources[name] = {"sha256": None, "status": "unavailable"}
            return {}

    storyboard = load("storyboard.json")
    qa = load("qc.json")
    audio = load("audio.json")
    render = load("render.json")
    tts = load("tts_metadata.json")
    motion = load("motion-code.json")
    technical = load("technical-qc.json")
    readiness = load("readiness.json")
    load("visual-evidence.json")
    creative = _object(qa.get("creative"))
    bme = _object(_object(creative.get("metrics")).get("bme_dynamics"))
    bme_status = bme_verdict(bme, storyboard.get("scenes"))
    rows = bme.get("scene_metrics")
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    narration = _object(audio.get("narration"))
    duration = narration.get("durationMs")
    duration = float(duration) if _number(duration, positive=True) else None
    rate = tts.get("sample_rate")
    rate = rate if type(rate) is int and rate > 0 else None
    alignment = tts.get("alignment_mode")
    alignment = alignment if isinstance(alignment, str) and alignment.strip() else None
    renderer = render.get("renderer")
    renderer = renderer if renderer in ("custom-motion", "remotion", "legacy-template") else None
    fallback = render.get("fallback_used")
    fallback = fallback if isinstance(fallback, bool) else None
    video = root / "output.mp4"
    verified_video = False
    src = render.get("src")
    if isinstance(src, str) and src:
        candidate = (root / src).resolve()
        if candidate.is_relative_to(root) and candidate == video and video.is_file():
            verified_video = video.stat().st_size > 0 and sha256_file(video) == render.get("sha256")
    digest = render.get("sha256") if verified_video else None
    binding = compute_inputs_hash(render_sha256=digest, narration_ms=duration, storyboard=storyboard) if digest and duration else None
    bound = binding is not None and technical.get("inputs_sha256") == binding and readiness.get("inputs_sha256") == binding
    checks = [technical.get("passed"), _object(qa.get("technical")).get("passed"), creative.get("passed")]
    visual = _object(qa.get("visual"))
    try:
        current_readiness = evaluate_job_readiness(store, job_id)
        semantic_status = current_readiness["semantic_status"]
    except Exception:  # noqa: BLE001 - no bound semantic evidence means no semantic conclusion
        semantic_status = "UNVERIFIED"
    visual_verified = semantic_status == "PASS"
    complete = (
        not issues and verified_video and bound and bme_status == "PASS"
        and all(v is True for v in checks) and readiness.get("ready") is True and renderer is not None and fallback is not None
        and rate is not None and alignment is not None and visual_verified
        and motion.get("validated_by_codeguard") is True
        and store.get(job_id).state is JobState.READY_FOR_APPROVAL
    )
    failed = bme_status == "FAIL" or any(v is False for v in checks) or semantic_status == "FAIL" or visual.get("status") == "failed"
    status = "PASS" if complete else ("FAIL" if failed else "UNVERIFIED")
    request_rows = state.requests.statuses(job_id)
    costs = []
    for request in request_rows:
        saved = state.requests.completed(request["request_key"]) if request["status"] == "completed" else None
        usage = _object(saved.get("usage")) if saved else {}
        cost = usage.get("est_cost_usd")
        if usage.get("cost_source") == "configured_rate_estimate" and usage.get("reported") is True and _number(cost):
            costs.append(cost)
    cost_total = sum(costs) if costs and len(costs) == len(request_rows) else None
    return {
        "evidence_format": "v3-e", "status": status,
        "final_state": store.get(job_id).state.value,
        "renderer_actual": renderer, "fallback_used": fallback, "render_sha256": digest,
        "video_path": str(video) if video.is_file() else None,
        "video_size_mb": round(video.stat().st_size / (1024 * 1024), 3) if video.is_file() else None,
        "motion_code_validated": motion.get("validated_by_codeguard") if type(motion.get("validated_by_codeguard")) is bool else None,
        "tts_sample_rate": rate, "tts_alignment_mode": alignment,
        "narration_duration_s": duration / 1000 if duration is not None else None,
        "voice": narration.get("voice") if isinstance(narration.get("voice"), str) else None,
        "scenes": [
            {"sceneId": scene.get("sceneId"),
             "layout_mode": _object(scene.get("data")).get("layout_mode") or scene.get("layout_mode"),
             "causal_action": _object(scene.get("causal_state")).get("causal_action"),
             "resulting_state": _object(scene.get("causal_state")).get("resulting_state")}
            for scene in storyboard.get("scenes", []) if isinstance(scene, dict)
        ],
        "motion_code_skills": motion.get("skill_hashes") if isinstance(motion.get("skill_hashes"), list) else None,
        "bme_status": bme_status, "bme_passed": bme_status == "PASS", "bme_metrics": rows,
        "semantic_visual_status": semantic_status,
        "artifact_sources": sources, "issues": issues,
        "evidence": {
            "renderer": metric(renderer, "render.json", "recorded"),
            "tts_sample_rate": metric(rate, "tts_metadata.json#sample_rate", "recorded"),
            "tts_alignment_mode": metric(alignment, "tts_metadata.json#alignment_mode", "recorded"),
            "narration_duration_s": metric(duration / 1000 if duration is not None else None, "audio.json#narration.durationMs", "recorded"),
            "bme": metric(bme_status if bme_status != "UNVERIFIED" else None, "qc.json#creative.metrics.bme_dynamics", "recorded"),
            "semantic_visual": metric(semantic_status if semantic_status != "UNVERIFIED" else None,
                                      "qc.json#semantic + visual-evidence.json + current render/context binding", "recorded"),
            "cost_usd": metric(cost_total, "provider_requests.usage_json.est_cost_usd (complete reported-usage coverage only)", "estimated"),
            "billed_cost_usd": metric(None, "no provider invoice source"),
        },
    }


def generate_markdown_report(results: list[dict[str, Any]]) -> str:
    import subprocess

    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = "unavailable"
    lines = ["# Production Benchmark Evidence", "", f"**Git:** `{git_sha}`",
             "Evidence is a recorded snapshot, not a publish recommendation. Pixel change does not establish causal fidelity.",
             "", "| Benchmark | Job | State | Evidence verdict | B/M/E |",
             "| --- | --- | --- | --- | --- |"]
    for res in results:
        current = res.get("evidence_format") == "v3-e" and isinstance(res.get("evidence"), dict)
        verdict = res.get("status") if current and res.get("status") in {"PASS", "FAIL", "UNVERIFIED"} else "UNVERIFIED"
        bme = res.get("bme_status") if current and res.get("bme_status") in {"PASS", "FAIL", "UNVERIFIED"} else "UNVERIFIED"
        lines.append(f"| {res.get('name', 'unavailable')} | {res.get('job_id', 'unavailable')} | {res.get('final_state', 'unavailable')} | {verdict} | {bme} |")
    for res in results:
        lines.extend(["", f"## {res.get('name', 'unavailable')}",
                      f"Job: `{res.get('job_id', 'unavailable')}`; mode: `{res.get('mode', 'unavailable')}`",
                      f"Topic (declared): {res.get('topic', 'unavailable')}",
                      f"Output: `{res.get('video_path') or 'unavailable'}`; checksum: `{res.get('render_sha256') or 'unavailable'}`",
                      "", "| Metric | Value | Measurement kind | Evidence source |", "| --- | --- | --- | --- |"])
        for name, item in _object(res.get("evidence")).items():
            item = _object(item)
            value = item.get("value")
            lines.append(f"| {name} | {value if value is not None else 'unavailable'} | {item.get('status', 'unavailable')} | {item.get('source', 'unavailable')} |")
        lines.extend(["", "### B/M/E observations", "| Scene | B→M | M→E | Measurement |", "| --- | --- | --- | --- |"])
        metrics = res.get("bme_metrics")
        for row in metrics if isinstance(metrics, list) else []:
            row = _object(row)
            measured = row.get("measured") is True and _number(row.get("delta_bm")) and _number(row.get("delta_me"))
            bm = f"{row['delta_bm']:.4f}" if measured else "unavailable"
            me = f"{row['delta_me']:.4f}" if measured else "unavailable"
            observation = ("static" if row.get("static") is True else "pixel change") if measured else "UNVERIFIED"
            lines.append(f"| {row.get('sceneId', 'unavailable')} | {bm} | {me} | {observation} |")
        lines.extend(["", "### Artifact sources", "```json", json.dumps(_object(res.get("artifact_sources")), indent=2), "```"])
        lines.extend(["", "### Declared scene intent (not rendered-visual verification)",
                      "```json", json.dumps(res.get("scenes") or [], ensure_ascii=False, indent=2), "```"])
        lines.extend(str(issue) for issue in res.get("issues", []) if isinstance(issue, str))
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

    settings = Settings.from_env().ensure()
    state = AppState.build(settings)

    results_cache = ROOT / "data" / "benchmark_history.json"
    cached: dict[str, Any] = {}
    if results_cache.is_file():
        try:
            cached = json.loads(results_cache.read_text(encoding="utf-8"))
        except Exception:
            cached = {}

    for bench in selected:
        res = run_single_benchmark(
            state,
            bench,
            mode=args.mode,
            renderer=args.renderer,
            fallback_policy=args.fallback_policy,
            tts_provider=args.tts_provider,
            mock=args.mock,
        )
        cached[res["key"]] = res

    results = [cached[b["key"]] for b in BENCHMARKS if b["key"] in cached]
    results_cache.parent.mkdir(parents=True, exist_ok=True)
    results_cache.write_text(json.dumps(cached, indent=2), encoding="utf-8")

    report_md = generate_markdown_report(results)
    args.report_file.parent.mkdir(parents=True, exist_ok=True)
    args.report_file.write_text(report_md, encoding="utf-8")
    print(f"\nBenchmark report written to: {args.report_file}")

    all_passed = bool(selected) and all(
        b["key"] in cached and cached[b["key"]].get("evidence_format") == "v3-e"
        and cached[b["key"]].get("status") == "PASS" and cached[b["key"]].get("ok") is True
        for b in selected
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
