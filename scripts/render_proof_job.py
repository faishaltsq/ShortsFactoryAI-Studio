"""Produce one real rendered job, or fail saying why. No fabricated media, ever.

This is the fixture path the browser proof depends on. It drives the same pipeline the product
uses — mock providers, real SAPI narration, real Remotion subprocess, real ffprobe gate — and then
prints the job id so a Playwright run can point at it.

Two modes:

``--render``   create the job through the API and run it to completion (slow: a Remotion render).
``--inspect``  do not render; read an existing job directory and report the motion-beat stills.

The stills are extracted from ``output.mp4`` with ffmpeg at the frames the storyboard's motion
beats name. They are evidence, not decoration: ``--inspect`` prints, for each beat, whether the
frame changed against the previous beat and where the file is, so a static character cannot be
mistaken for animation by looking at one image.

Usage::

    uv run python scripts/render_proof_job.py --render
    uv run python scripts/render_proof_job.py --inspect <job_id>

Exit codes: 0 success, 1 the job did not reach a rendered state, 2 the video is missing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.settings import Settings  # noqa: E402 - after the sys.path fix

#: The job the Phase 2.6 gate is proved against. Mock providers, real narration, real render.
PROOF_TITLE = "Phase 2.6 browser proof"
PROOF_PAYLOAD: dict[str, Any] = {
    "title": PROOF_TITLE,
    "topic": "bukti render karakter",
    "provider_mode": "mock",
    "render_video": True,
    "renderer": "remotion",
    "voice": "system-default",
    "target_duration_s": 10,
    "characters": ["maya"],
}

TERMINAL = {"READY_FOR_APPROVAL", "BLOCKED", "FAILED", "CANCELLED"}


def _api() -> str:
    import os

    return os.environ.get("STUDIO_API_ORIGIN", "http://127.0.0.1:8019").rstrip("/")


def _post(path: str, body: dict[str, Any] | None = None) -> Any:
    from packages.core.providers.http_base import PinnedHTTP

    # Local loopback only; the explicit flag is the documented opt-in for private hosts.
    response = PinnedHTTP(timeout_s=30.0, max_retries=0).request(
        "POST", f"{_api()}{path}", json=body or {}, allow_private_hosts=True,
    )
    response.raise_for_status()
    return response.json()


def _get(path: str) -> Any:
    from packages.core.providers.http_base import PinnedHTTP

    response = PinnedHTTP(timeout_s=30.0, max_retries=0).request(
        "GET", f"{_api()}{path}", allow_private_hosts=True,
    )
    response.raise_for_status()
    return response.json()


def render_job(*, timeout_s: int) -> int:
    """Create and run the proof job against the live API, then wait for it to settle."""
    created = _post("/api/jobs", PROOF_PAYLOAD)
    job_id = created["id"]
    print(f"job {job_id} created (mock, render_video=true, voice=system-default)", flush=True)
    _post(f"/api/jobs/{job_id}/run")
    print("render started; this is the slow part", flush=True)

    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        detail = _get(f"/api/jobs/{job_id}")
        state = detail["state"]
        if state != last:
            print(f"  {state}", flush=True)
            last = state
        if state in TERMINAL:
            break
        time.sleep(2)
    else:
        print(f"FAIL job {job_id} did not settle within {timeout_s}s", file=sys.stderr)
        return 1

    detail = _get(f"/api/jobs/{job_id}")
    if detail["state"] != "READY_FOR_APPROVAL":
        # A blocked job still has has_video=True from a partial chain; only a settled
        # READY_FOR_APPROVAL with valid readiness/QC evidence counts as proof.
        print(
            f"FAIL job {job_id} ended at {detail['state']}, not READY_FOR_APPROVAL"
            f" (last_error: {detail.get('last_error')})",
            file=sys.stderr,
        )
        return 2
    if not detail["has_video"]:
        print(
            f"FAIL job {job_id} reached READY_FOR_APPROVAL with no output.mp4",
            file=sys.stderr,
        )
        return 2

    # The Playwright spec reads this pointer instead of guessing an id or depending on a manual
    # run. It lives in the API's own data dir, so the spec and the server cannot disagree about
    # which job is the fixture.
    pointer = Path(Settings.from_env().data_dir) / "proof-job.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps({"job_id": job_id, "title": PROOF_TITLE, "state": detail["state"]}, indent=2),
        encoding="utf-8",
    )
    print(f"job_id={job_id}")
    print(f"pointer={pointer}")
    print(f"state={detail['state']} has_video={detail['has_video']}")
    return 0


def _ffmpeg_still(video: Path, frame: int, fps: float, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{frame / fps:.6f}", "-i", str(video),
        "-frames:v", "1", str(out),
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        print(f"  ffmpeg failed for frame {frame}: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return False
    return out.is_file()


def _delta(a: Path, b: Path) -> dict[str, float] | None:
    """Perceptual distance between two stills via ffmpeg's own SSIM filter.

    No extra Python dependency: ffmpeg is already required for the stills and for the media gate.
    ``all`` is 1.0 for identical frames, so ``1 - all`` is the fraction of structure that moved.
    """
    argv = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(a), "-i", str(b),
        "-lavfi", "ssim", "-f", "null", "-",
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603
    log = f"{proc.stderr or ''}{proc.stdout or ''}"
    for line in log.splitlines():
        if "All:" in line and "SSIM" in line:
            try:
                value = float(line.split("All:")[1].split()[0])
            except (IndexError, ValueError):
                return None
            return {"ssim": round(value, 5), "changed": round(1.0 - value, 5)}
    return None


def inspect_job(job_id: str, out_dir: Path) -> int:
    settings = Settings.from_env()
    job_dir = Path(settings.jobs_dir) / job_id
    video = job_dir / "output.mp4"
    if not video.is_file():
        print(f"ERROR no output.mp4 for job {job_id}: {video}", file=sys.stderr)
        return 2

    props_path = job_dir / "render-props.json"
    props = json.loads(props_path.read_text(encoding="utf-8"))
    storyboard = props.get("storyboard", props)
    fps = float(storyboard.get("fps") or 30)

    print(f"job {job_id}")
    print(f"video {video} ({video.stat().st_size} bytes)")
    print(f"fps {fps:g}")

    previous: Path | None = None
    for scene in storyboard["scenes"]:
        scene_id = scene["sceneId"]
        start = int(scene["startFrame"])
        beats = (scene.get("motion") or {}).get("beats") or []
        for index, beat in enumerate(beats):
            # A beat past the scene's own length cannot be rendered; clamp and say so.
            offset = int(beat.get("atFrame", 0))
            clamped = min(offset, int(scene["durationInFrames"]) - 1)
            frame = start + max(0, clamped)
            out = out_dir / f"{scene_id}-beat{index}-{beat.get('kind')}-f{frame}.png"
            if not _ffmpeg_still(video, frame, fps, out):
                continue
            note = "" if clamped == offset else f" (beat atFrame {offset} clamped to {clamped})"
            delta = _delta(previous, out) if previous else None
            delta_text = "n/a" if delta is None else f"ssim={delta['ssim']} changed={delta['changed']}"
            print(f"  {out}  t={frame / fps:.3f}s  beat={beat.get('kind')}  "
                  f"delta_vs_previous={delta_text}{note}")
            previous = out

    audio_path = job_dir / "audio.json"
    if audio_path.is_file():
        audio = json.loads(audio_path.read_text(encoding="utf-8"))
        narration = audio.get("narration") or {}
        print(f"narration durationMs={narration.get('durationMs')} voice={narration.get('voice')}")
        for timing in audio.get("scenes") or []:
            print(f"  scene {timing.get('sceneId')} {timing.get('startMs')}..{timing.get('endMs')} ms")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--render", action="store_true", help="create and run the proof job")
    parser.add_argument("--inspect", metavar="JOB_ID", help="extract motion-beat stills")
    parser.add_argument("--out", default="data/proof-stills", help="still output directory")
    parser.add_argument("--timeout", type=int, default=900, help="render wait budget, seconds")
    args = parser.parse_args(argv)

    if not args.render and not args.inspect:
        parser.error("one of --render or --inspect is required")
    if args.render:
        code = render_job(timeout_s=args.timeout)
        if code != 0:
            return code
    if args.inspect:
        return inspect_job(args.inspect, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
