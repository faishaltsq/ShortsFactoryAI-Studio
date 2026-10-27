"""The TECHNICAL_QC stage and the approval gate, end to end on real files.

The stage must write ``technical-qc.json`` **even when it blocks** — a job that fails QC has to
carry the measurement that failed, or the operator has nothing to act on and the next run repeats
the same failure blind.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from packages.core.contracts.artifacts import TechnicalQaArtifact
from packages.core.contracts.base import validate_artifact
from packages.core.contracts.state import JobState
from packages.core.media.qc import sha256_file
from packages.core.orchestration.editorial import TECHNICAL_NAME, build_technical_qc_stage
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.runner import StageError, run_stages

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe are required for the technical QC stage",
)

FPS = 30
W, H = 270, 480
SCENE_FRAMES = 30
SCENES = 3


class _State:
    """The minimum a stage touches: a store and an event sink."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.events = _Events()


class _Events:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def emit(self, **kwargs) -> None:
        self.rows.append(kwargs)


def _props(scenes: int = SCENES, frames: int = SCENE_FRAMES) -> dict:
    return {
        "storyboard": {
            "fps": FPS,
            "width": W,
            "height": H,
            "scenes": [
                {
                    "sceneId": f"sc{index}",
                    "startFrame": index * frames,
                    "durationInFrames": frames,
                    "template": "IllustratedStory",
                    "segment": f"s{index}",
                    "text": [{"id": f"t{index}", "text": "Halo", "role": "title", "atFrame": 0}],
                    "data": {
                        "setting": "desert",
                        "timeOfDay": "dusk",
                        "actors": [],
                        "props": [],
                        "fx": [],
                        "shots": [{"framing": "wide", "camera": "pushIn", "weight": 1}],
                    },
                }
                for index in range(scenes)
            ],
            "subtitles": [
                {"startMs": index * 1000, "endMs": (index + 1) * 1000, "text": f"Bagian {index + 1}"}
                for index in range(scenes)
            ],
        }
    }


def _media(path: Path, *, seconds: float = 3.0, tone: bool = True, still: bool = False) -> Path:
    """A render that is clean by the same standards the gate applies.

    ``-color_range tv -colorspace bt709`` is not decoration: without it libx264 emits no
    ``color_range`` tag, ffprobe reports nothing, and the gate correctly refuses to call an
    untagged stream limited-range. ``loudnorm`` is applied because the real pipeline applies it in
    ``build_mix_argv`` and the gate measures the result — a raw sine sits near -22 LUFS.
    """
    video_filter = (
        ["-vf", f"trim=end_frame=1,loop=loop={int(seconds * FPS) - 1}:size=1:start=0,setpts=N/{FPS}/TB"]
        if still
        else []
    )
    audio = ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"] if tone else []
    proc = subprocess.run(  # noqa: S603
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d={seconds}",
            *audio,
            *video_filter,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-color_range", "tv", "-colorspace", "bt709",
            *(["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac"] if tone else []),
            "-t", str(seconds),
            *(["-shortest"] if tone else []),
            str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    return path


def _job(store: JobStore, *, seconds: float = 3.0, still: bool = False, tone: bool = True) -> tuple[str, dict]:
    job = store.create(title="qc", payload={"provider_mode": "mock", "render_video": True})
    job_dir = Path(store.job_dir(job.id))
    video = _media(job_dir / "output.mp4", seconds=seconds, still=still, tone=tone)
    props = _props()
    (job_dir / "render-props.json").write_text(json.dumps(props), encoding="utf-8")
    store.write_artifact(job.id, "storyboard.json", props["storyboard"])
    store.write_artifact(
        job.id,
        "audio.json",
        {
            "narration": {"src": "narration.wav", "durationMs": int(seconds * 1000), "voice": "system-default"},
            "scenes": [
                {"sceneId": f"sc{index}", "startMs": index * 1000, "endMs": (index + 1) * 1000}
                for index in range(SCENES)
            ],
            "subtitles": props["storyboard"]["subtitles"],
            "mix": {"music": None, "ducking": False, "loudness_lufs": -16},
        },
    )
    store.write_artifact(
        job.id,
        "render.json",
        {
            "src": "output.mp4",
            "sha256": sha256_file(video),
            "bytes": video.stat().st_size,
            "width": W,
            "height": H,
            "fps": FPS,
            "frames": SCENES * SCENE_FRAMES,
            "duration_ms": int(seconds * 1000),
            "video_codec": "h264",
            "audio_codec": "aac" if tone else None,
            "pix_fmt": "yuv420p",
            "scene_hashes": {f"sc{index}": "0" * 64 for index in range(SCENES)},
        },
    )
    # Walk the job to RENDERING so the stage's own transition is legal.
    for state in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
    ):
        store.transition(job.id, state)
    return job.id, props


@pytest.fixture
def store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


# -- the stage ---------------------------------------------------------------------------------


def test_the_stage_writes_a_valid_artifact_on_a_clean_render(store):
    state = _State(store)
    job_id, _ = _job(store)
    report = run_stages(store=store, job_id=job_id, stages=[build_technical_qc_stage(state)])
    assert report["ok"] is True, report
    payload = store.read_artifact(job_id, TECHNICAL_NAME)
    validate_artifact(TechnicalQaArtifact, payload)
    assert payload["passed"] is True, payload["failed"]
    assert store.get(job_id).state is JobState.TECHNICAL_QC


def test_the_artifact_records_observed_values_and_thresholds(store):
    state = _State(store)
    job_id, _ = _job(store)
    run_stages(store=store, job_id=job_id, stages=[build_technical_qc_stage(state)])
    payload = store.read_artifact(job_id, TECHNICAL_NAME)
    assert payload["observed"]["width"] == W
    assert payload["observed"]["frames"] == SCENES * SCENE_FRAMES
    assert payload["thresholds"]["black_frames"].startswith("blackdetect=")
    assert payload["detectors"]["blackdetect"]["ran"] is True


def test_a_silent_render_blocks_but_still_writes_the_artifact(store):
    """The evidence must survive the failure, or the operator cannot act on it."""
    state = _State(store)
    job_id, _ = _job(store, tone=False)
    report = run_stages(store=store, job_id=job_id, stages=[build_technical_qc_stage(state)])
    assert report["ok"] is False
    assert report["stopped"] == "qa_blocked"
    payload = store.read_artifact(job_id, TECHNICAL_NAME)
    validate_artifact(TechnicalQaArtifact, payload)
    assert payload["passed"] is False
    assert "audio_stream_count" in payload["failed"]
    assert store.get(job_id).state is JobState.BLOCKED


def test_a_frozen_render_blocks_on_frozen_frames(store):
    state = _State(store)
    job_id, _ = _job(store, still=True)
    report = run_stages(store=store, job_id=job_id, stages=[build_technical_qc_stage(state)])
    assert report["ok"] is False
    payload = store.read_artifact(job_id, TECHNICAL_NAME)
    assert "frozen_frames" in payload["failed"], payload["failed"]


def test_a_tampered_output_blocks_on_the_checksum(store):
    state = _State(store)
    job_id, _ = _job(store)
    with open(Path(store.job_dir(job_id)) / "output.mp4", "ab") as handle:
        handle.write(b"tamper")
    report = run_stages(store=store, job_id=job_id, stages=[build_technical_qc_stage(state)])
    assert report["ok"] is False
    assert "checksum" in store.read_artifact(job_id, TECHNICAL_NAME)["failed"]


def test_a_blocked_stage_emits_a_blocked_event_naming_the_checks(store):
    state = _State(store)
    job_id, _ = _job(store, tone=False)
    run_stages(store=store, job_id=job_id, stages=[build_technical_qc_stage(state)])
    descriptions = [row["description"] for row in state.events.rows]
    assert any("technical" in text.lower() for text in descriptions)


def test_the_stage_declares_its_contract(store):
    stage = build_technical_qc_stage(_State(store))
    assert stage.contract is TechnicalQaArtifact
    assert stage.contract_artifact == TECHNICAL_NAME
    assert stage.state is JobState.TECHNICAL_QC
    assert TECHNICAL_NAME in stage.produces


def test_a_missing_render_is_a_clean_stage_error_not_a_crash(store, tmp_path):
    state = _State(store)
    job = store.create(title="x", payload={"provider_mode": "mock"})
    for state_name in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY, JobState.ASSETS_READY,
        JobState.AUDIO_READY, JobState.RENDERING,
    ):
        store.transition(job.id, state_name)
    with pytest.raises(StageError) as exc:
        build_technical_qc_stage(state).run(stage_ctx(store, job.id, tmp_path))
    assert exc.value.code == "qa_blocked"
    assert exc.value.retryable is False


def test_a_render_shorter_than_its_narration_blocks_on_duration(store):
    """The property the removed ``frame_duration`` check was reaching for.

    ``validate_render`` no longer asks a second time whether the frame span is shorter than the
    narration. The question is still asked — here, once, against ``audio.json`` with the frame
    count from ``render-props.json`` — so a render that stops before the voice does cannot pass.
    """
    state = _State(store)
    job_id, _ = _job(store, seconds=3.0)
    # Claim a 5 s narration for a 3 s render: the voice would run 2 s past the picture.
    store.write_artifact(
        job_id,
        "audio.json",
        {
            "narration": {"src": "narration.wav", "durationMs": 5000, "voice": "system-default"},
            "scenes": [
                {"sceneId": f"sc{index}", "startMs": index * 1666, "endMs": (index + 1) * 1666}
                for index in range(SCENES)
            ],
            "subtitles": [
                {"startMs": index * 1666, "endMs": (index + 1) * 1666, "text": f"Bagian {index + 1}"}
                for index in range(SCENES)
            ],
            "mix": {"music": None, "ducking": False, "loudness_lufs": -16},
        },
    )
    report = run_stages(store=store, job_id=job_id, stages=[build_technical_qc_stage(state)])
    assert report["ok"] is False
    payload = store.read_artifact(job_id, TECHNICAL_NAME)
    assert "duration" in payload["failed"], payload["failed"]
    assert payload["observed"]["expected_duration_ms"] == 5000.0
    assert payload["observed"]["duration_ms"] < 3200


def stage_ctx(store, job_id, tmp: Path | None = None) -> Any:
    """A stage context for direct stage.run() calls outside run_stages."""
    from packages.core.orchestration.runner import NullCancel, StageContext

    return StageContext(
        store,
        job_id,
        (tmp or Path(tempfile.mkdtemp(prefix="stagectx-"))),
        cancel=NullCancel(),
    )
