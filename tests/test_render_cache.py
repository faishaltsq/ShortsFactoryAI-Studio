"""Per-scene render cache: hits splice with zero renderer invocations, misses render once.

Proof is real, not stubbed-for-the-claim: parts are made by real ffmpeg (testsrc), the cache
validates them with the real ffprobe path, and the concat is the production concat. What is
stubbed is the Remotion subprocess itself (``render_storyboard``) — the unit of behavior under
test is the stage's cache/concat bookkeeping and the invocation counter is the observation the
roadmap asks for ("renderer invocations == 1" for one changed scene).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from packages.core.media.render import (
    SceneCache,
    build_render_stage,
    concat_parts,
    probe_media,
)

WIDTH, HEIGHT, FPS = 160, 288, 30
SCENE_FRAMES = 30  # 1s per scene; two scenes = 2s total.


def _ffmpeg_part(dest: Path, *, seconds: float, color: str) -> Path:
    """A real yuv420p H.264 part with a solid color; probe-verified before returning."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:s={WIDTH}x{HEIGHT}:r={FPS}:d={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(dest),
        ],
        capture_output=True, text=True, check=True,
    )
    return dest


def _storyboard(text_scene2: str = "second") -> dict[str, Any]:
    """Two scenes at 0..30 and 30..60. Scene text is the mutation lever between renders."""
    def scene(scene_id: str, start: int, text: str) -> dict[str, Any]:
        return {
            "sceneId": scene_id,
            "template": "ObjectExplainer",
            "segment": f"seg-{scene_id}",
            "startFrame": start,
            "durationInFrames": SCENE_FRAMES,
            "text": [{"role": "caption", "value": text, "style": {"role": "caption"}}],
            "camera": {"move": "static"},
            "motion": {"beats": []},
            "transition": {"kind": "cut", "frames": 0},
            "data": {"actors": [], "setting": "desert"},
        }

    return {
        "schema_version": 1,
        "fps": FPS,
        "width": WIDTH,
        "height": HEIGHT,
        "theme": "dusk",
        "scenes": [
            scene("sc1", 0, "first"),
            scene("sc2", SCENE_FRAMES, text_scene2),
        ],
        "subtitles": [],
    }


class _Store:
    """Same shape the dispatch tests use, with the timed props file kept current."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._jobs_dir = root / "jobs"
        self._job = self._jobs_dir / "job1"
        self._job.mkdir(parents=True, exist_ok=True)
        self.written: dict[str, dict[str, Any]] = {}
        (self._job / "narration.wav").write_bytes(b"RIFF-stub")
        self.set_storyboard(_storyboard())

    def set_storyboard(self, storyboard: dict[str, Any]) -> None:
        (self._job / "storyboard.json").write_text(
            json.dumps(storyboard), encoding="utf-8"
        )
        # audio.json drives the real update_storyboard_from_audio: both scenes 1s, contiguous,
        # no per-word speech — so the timed doc here equals the raw storyboard, keeping the
        # test's attention on cache bookkeeping rather than timing math.
        audio = {
            "schema_version": 1,
            "narration": {"src": "narration.wav", "durationMs": 2000},
            "scenes": [
                {"sceneId": "sc1", "startMs": 0, "endMs": 1000},
                {"sceneId": "sc2", "startMs": 1000, "endMs": 2000},
            ],
            "subtitles": [],
        }
        (self._job / "audio.json").write_text(json.dumps(audio), encoding="utf-8")
        # The timed props file the stage reads; also keep storyboard.json current because
        # _finalize_render re-reads it for scene hashes.
        (self._job / "render-props.json").write_text(
            json.dumps({"storyboard": storyboard}), encoding="utf-8"
        )

    def job_dir(self, job_id: str) -> Path:
        return self._job

    @property
    def jobs_dir(self) -> Path:
        return self._jobs_dir

    def get(self, job_id: str) -> Any:
        return type("Job", (), {"payload": {"render_video": True, "renderer": "remotion"}})()

    def read_artifact(self, job_id: str, name: str) -> dict[str, Any]:
        return json.loads((self._job / name).read_text(encoding="utf-8"))

    def write_artifact(self, job_id: str, name: str, payload: dict[str, Any]) -> Path:
        self.written[name] = payload
        target = self._job / name
        target.write_text(json.dumps(payload), encoding="utf-8")
        return target


class _Events:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


class _State:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.events = _Events()


def _fake_mux(video_path: Path, narration_path: Path, output_path: Path, **_: Any) -> None:
    """Real ffmpeg mux: video plus a real (silent) 1s AAC narration stream.

    _finalize_render rejects a merged file without exactly one audio stream; a byte copy would
    not survive that gate. The narration waveform is irrelevant below the timing stage.
    """
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-shortest", "-c:a", "aac", str(output_path),
        ],
        capture_output=True, text=True, check=True,
    )


def _stub_video_dir(root: Path) -> Path:
    video = root / "video"
    cli = video / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("// stub\n", encoding="utf-8")
    return video


class _Probe:
    """probe_media stand-in that answers per-path: cache parts ffprobe for real; outputs scripted."""

    def __init__(self) -> None:
        self.real_probe = probe_media
        self.scripted: dict[Path, dict[str, Any]] = {}

    def register(self, path: Path, *, frames: int, seconds: float) -> None:
        self.scripted[Path(path).name] = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                 "width": WIDTH, "height": HEIGHT, "avg_frame_rate": f"{FPS}/1",
                 "nb_read_frames": str(frames)},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": f"{seconds}"},
        }

    def __call__(self, path: Path) -> dict[str, Any]:
        key = Path(path).name
        if key in self.scripted:
            return self.scripted[key]
        return self.real_probe(path)


def _stage_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: _Store) -> dict[str, Any]:
    import packages.core.media.render as render_mod

    calls: list[tuple[int, int] | None] = []

    def fake_render(**kwargs: Any) -> dict[str, Any]:
        frames = kwargs.get("frames")
        calls.append(frames)
        out = Path(kwargs["out_path"])
        start, end = frames if frames else (0, 2 * SCENE_FRAMES - 1)
        scene_index = 0 if start < SCENE_FRAMES else 1
        color = "red" if scene_index == 0 else "blue"
        _ffmpeg_part(out, seconds=(end - start + 1) / FPS, color=color)
        return {"elapsed_ms": 1, "port": 0}

    probe = _Probe()

    monkeypatch.setattr(render_mod, "render_storyboard", fake_render)
    monkeypatch.setattr(render_mod, "mux_narration", _fake_mux)
    monkeypatch.setattr(render_mod, "probe_media", probe)
    monkeypatch.setattr(
        render_mod, "renderer_version", lambda video_dir: "stub-remotion-1.0"
    )

    def run_stage() -> dict[str, Any]:
        # The merged artifact (output.mp4) is probed inside the stage; its scripted response
        # must exist before the run. Frame count = whole timeline; cache parts keep real probes.
        probe.register("output.mp4", frames=2 * SCENE_FRAMES, seconds=2.0)
        state = _State(store)
        stage = build_render_stage(state, video_dir=_stub_video_dir(tmp_path))
        from packages.core.orchestration.runner import NullCancel, StageContext

        ctx = StageContext(
            store, "job1", Path(tempfile.mkdtemp(prefix="cache-")), cancel=NullCancel()
        )
        outcome = stage.run(ctx)
        return {"outcome": outcome, "state": state, "ctx": ctx}

    return {"calls": calls, "probe": probe, "run_stage": run_stage, "render_mod": render_mod}


def _video_probe(path: Path) -> dict[str, Any]:
    probe = probe_media(path)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    return {
        "frames": int(video.get("nb_read_frames") or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
    }


def test_second_identical_render_splices_from_cache_with_zero_invocations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    store = _Store(root)
    env = _stage_env(tmp_path, monkeypatch, store)
    cache_root = root / "render-cache"

    first = env["run_stage"]()
    assert first["outcome"].ok
    assert env["calls"] == [(0, SCENE_FRAMES - 1), (SCENE_FRAMES, 2 * SCENE_FRAMES - 1)]
    assert cache_root.is_dir() and len(list(cache_root.rglob("*.mp4"))) == 2

    # Second render, unchanged storyboard: both keys live -> no renderer calls at all.
    env["calls"].clear()
    second = env["run_stage"]()
    assert second["outcome"].ok
    assert env["calls"] == [], "an unchanged storyboard must re-render nothing"

    # The cache-spliced video is a real file with the full timeline; probe the staged bytes.
    merged = second["ctx"].staging / "output.mp4"
    video = _video_probe(merged)
    assert video["frames"] == 2 * SCENE_FRAMES
    assert (video["width"], video["height"]) == (WIDTH, HEIGHT)


def test_one_changed_scene_rerenders_exactly_that_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    store = _Store(root)
    env = _stage_env(tmp_path, monkeypatch, store)

    env["run_stage"]()
    parts_before = sorted(p.name for p in (root / "render-cache").rglob("*.mp4"))
    store.set_storyboard(_storyboard(text_scene2="CHANGED"))

    env["calls"].clear()
    second = env["run_stage"]()
    assert second["outcome"].ok
    assert env["calls"] == [(SCENE_FRAMES, 2 * SCENE_FRAMES - 1)], (
        "only scene 2's window may render; scene 1 must come from cache verbatim"
    )
    parts_after = sorted(p.name for p in (root / "render-cache").rglob("*.mp4"))
    assert len(parts_after) == 3, "scene 1 keeps its part; scene 2 gains a second, keyed part"
    assert parts_before[0] in parts_after, "scene 1's part file is reused, not rewritten"
    assert set(parts_after) - set(parts_before), "scene 2's new content must be a new key"


def test_a_truncated_cache_part_is_a_miss_not_poison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    store = _Store(root)
    env = _stage_env(tmp_path, monkeypatch, store)

    env["run_stage"]()
    parts = sorted((root / "render-cache").rglob("*.mp4"))
    assert len(parts) == 2
    # Corrupt one part in place: existence passes, probe must fail it.
    parts[0].write_bytes(parts[0].read_bytes()[:64])

    env["calls"].clear()
    rerender = env["run_stage"]()
    assert rerender["outcome"].ok
    assert len(env["calls"]) == 1, "exactly the corrupted scene may re-render"


def test_concat_parts_produces_a_real_mergable_timeline(tmp_path: Path) -> None:
    """The production concat: two different-colored real parts merge, probe sees both durations."""
    p1 = _ffmpeg_part(tmp_path / "p1.mp4", seconds=1.0, color="red")
    p2 = _ffmpeg_part(tmp_path / "p2.mp4", seconds=1.0, color="blue")
    out = tmp_path / "merged.mp4"
    concat_parts([p1, p2], out)
    probe = _video_probe(out)
    assert probe["frames"] == 2 * SCENE_FRAMES
    assert (probe["width"], probe["height"]) == (WIDTH, HEIGHT)
    # Single-part path is a straight copy, also probe-clean.
    single = tmp_path / "single.mp4"
    concat_parts([p1], single)
    assert _video_probe(single)["frames"] == SCENE_FRAMES


def test_cache_keys_differ_when_global_pixel_inputs_differ(tmp_path: Path) -> None:
    """Watermark and total length change pixels; keys must separate those storyboards."""
    from packages.core.media.render import _cache_key

    def key(*, total_frames: int, watermark: str) -> str:
        return _cache_key(
            scene_hash="h" * 64,
            renderer="remotion",
            renderer_version_value="1.0",
            theme='"dusk"',
            width=WIDTH,
            height=HEIGHT,
            fps=FPS,
            total_frames=total_frames,
            watermark=watermark,
        )

    assert len({key(total_frames=60, watermark=""), key(total_frames=90, watermark=""),
                key(total_frames=60, watermark="ACME")}) == 3
    cache = SceneCache(tmp_path / "render-cache")
    assert cache.hit(key(total_frames=60, watermark=""),
                     width=WIDTH, height=HEIGHT, fps=FPS, frames=SCENE_FRAMES) is None
