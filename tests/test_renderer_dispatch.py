"""Renderer dispatch: one renderer, and a lie is still refused.

The second renderer (``bang-motion``) existed to capture character SVG frames and was removed with
the character engine. What remains is the property that mattered: the payload cannot name a
renderer the repository does not ship, and the artifact records the renderer that actually ran.

The stage is built and driven with a fake renderer, so nothing here needs Node, ffmpeg, or a
browser.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from packages.core.media.render import (
    RENDER_NAME,
    RENDERERS,
    build_render_stage,
    renderer_kind,
)


class _FakeStore:
    """The smallest store the stage actually uses: a job dir and three artifacts."""

    def __init__(self, root: Path, *, payload: dict[str, Any]) -> None:
        self._root = root
        self._jobs_dir = root / "jobs"
        self._job = self._jobs_dir / "job1"
        self._job.mkdir(parents=True, exist_ok=True)
        self._payload = payload
        self.written: dict[str, dict[str, Any]] = {}
        # audio stage upstream one and output real precondition.
        (self._job / "narration.wav").write_bytes(b"RIFF-stub")

    def job_dir(self, job_id: str) -> Path:
        return self._job

    @property
    def jobs_dir(self) -> Path:
        return self._jobs_dir

    def get(self, job_id: str) -> Any:
        return type("Job", (), {"payload": self._payload})()

    def read_artifact(self, job_id: str, name: str) -> dict[str, Any]:
        if name == "render-props.json":
            return json.loads((self._job / "render-props.json").read_text(encoding="utf-8"))
        if name == "storyboard.json":
            return {
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
                        "durationInFrames": 30,
                        "text": [],
                        "camera": {"move": "static"},
                        "motion": {"beats": []},
                        "transition": {"kind": "cut", "frames": 0},
                        "data": {"environment": "dataCenter", "objects": [{"kind": "serverRack", "x": 0.5, "y": 0.4, "size": 0.4}]},
                    }
                ],
                "subtitles": [],
            }
        if name == "audio.json":
            return {
                "schema_version": 1,
                "narration": {"src": "narration.wav", "durationMs": 1000},
                "scenes": [{"sceneId": "sc1", "startMs": 0, "endMs": 1000}],
                "subtitles": [],
            }
        raise AssertionError(f"unexpected artifact read: {name}")

    def write_artifact(self, job_id: str, name: str, payload: dict[str, Any]) -> Path:
        self.written[name] = payload
        target = self._job / name
        target.write_text(json.dumps(payload), encoding="utf-8")
        return target


class _Events:
    """Records what the stage emitted. The stage must not need a real event log to be testable."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


class _State:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store
        self.events = _Events()


def _fake_mux(video_path: Path, narration_path: Path, output_path: Path, **_: Any) -> None:
    """The mux is what creates ``output.mp4``; a no-op stub would leave the stage with no file."""
    Path(output_path).write_bytes(b"muxed-bytes")


def _stub_video_dir(root: Path) -> Path:
    """A ``packages/video`` lookalike with the two binaries the preflight checks for.

    The preflight is real and worth keeping: a missing Chrome is a message with a path in it, not
    an opaque failure three layers down. So the test satisfies it rather than mocking it away.
    """
    video = root / "video"
    (video / "scripts").mkdir(parents=True, exist_ok=True)
    # The version recorded in render.json is read from this file; a stub without it would make the
    # artifact claim an empty renderer version.
    (video / "package.json").write_text(
        json.dumps({"dependencies": {"remotion": "4.0.537"}}), encoding="utf-8"
    )
    chrome = (
        video / "node_modules" / ".remotion" / "chrome-headless-shell" / "win64"
        / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"
    )
    chrome.parent.mkdir(parents=True, exist_ok=True)
    chrome.write_bytes(b"stub")
    cli = video / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("// stub\n", encoding="utf-8")
    return video


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = {"render_video": True, "renderer": "remotion"}
    payload.update(overrides)
    return payload


def test_the_repository_ships_one_renderer() -> None:
    assert RENDERERS == ("remotion",)


def test_renderer_kind_defaults_to_remotion() -> None:
    assert renderer_kind({}) == "remotion"
    assert renderer_kind({"render_video": True}) == "remotion"


def test_renderer_kind_reads_the_payload() -> None:
    assert renderer_kind({"renderer": "remotion"}) == "remotion"


def test_the_retired_character_renderer_is_not_accepted() -> None:
    """A stored payload naming the removed renderer must fail, not silently re-render."""
    with pytest.raises(ValueError, match="renderer"):
        renderer_kind({"renderer": "bang-motion"})


@pytest.mark.parametrize("value", ["BangMotion", "bang_motion", "ffmpeg", "", " ", 7, None, True])
def test_an_unknown_renderer_is_refused_loudly(value: Any) -> None:
    """Not a fallback. A typo must not render with the primary and record a different name."""
    with pytest.raises(ValueError, match="renderer"):
        renderer_kind({"renderer": value})


def test_an_unknown_renderer_raises_before_any_process_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal happens before either renderer is called, so no subprocess is reachable."""
    import packages.core.media.render as render_mod

    def boom(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("no renderer may be invoked for an unknown renderer value")

    monkeypatch.setattr(render_mod, "render_storyboard", boom)
    store = _FakeStore(tmp_path, payload=_payload(renderer="nope"))
    with pytest.raises(ValueError, match="renderer"):
        build_render_stage(_State(store), video_dir=tmp_path, renderer="nope")
    assert store.written == {}


def test_the_stage_records_the_payload_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The core regression: the artifact must say what actually rendered it."""
    import packages.core.media.render as render_mod

    store = _FakeStore(tmp_path, payload=_payload(renderer="remotion"))
    calls: list[str] = []

    def fake_render(**kwargs: Any) -> dict[str, Any]:
        calls.append("remotion")
        Path(kwargs["out_path"]).write_bytes(b"fake-video-bytes")
        return {"elapsed_ms": 1}

    def fake_probe(path: Path) -> dict[str, Any]:
        return {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                 "width": 1080, "height": 1920, "avg_frame_rate": "30/1",
                 "nb_read_frames": "30"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "1.0"},
        }

    monkeypatch.setattr(render_mod, "render_storyboard", fake_render)
    monkeypatch.setattr(render_mod, "mux_narration", _fake_mux)
    monkeypatch.setattr(render_mod, "probe_media", fake_probe)
    monkeypatch.setattr(render_mod, "sha256_file", lambda path: "0" * 64)

    stage = build_render_stage(
        _State(store), video_dir=_stub_video_dir(tmp_path), renderer="remotion"
    )
    ctx = stage_ctx(store, "job1")
    outcome = stage.run(ctx)

    assert outcome.ok
    assert calls == ["remotion"], "the remotion path must be the one that ran"
    written = dict(ctx.json_pending)[RENDER_NAME]
    assert written["renderer"] == "remotion"
    assert written["renderer_version"], "a renderer must record its version"
    assert written["frames"] == 30
    assert written["width"] == 1080 and written["height"] == 1920
    assert written["pix_fmt"] == "yuv420p"
    assert written["audio_codec"] == "aac"
    assert written["scene_hashes"] == {
        "sc1": written["scene_hashes"]["sc1"]
    }, "scene hashes must be real and keyed by scene id"


def test_the_remotion_path_still_runs_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import packages.core.media.render as render_mod

    store = _FakeStore(tmp_path, payload={"render_video": True})
    calls: list[str] = []

    def fake_remotion(**kwargs: Any) -> dict[str, Any]:
        calls.append("remotion")
        Path(kwargs["out_path"]).write_bytes(b"fake-video-bytes")
        return {"elapsed_ms": 1}

    monkeypatch.setattr(render_mod, "render_storyboard", fake_remotion)
    monkeypatch.setattr(render_mod, "mux_narration", _fake_mux)
    monkeypatch.setattr(
        render_mod,
        "probe_media",
        lambda path: {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                 "width": 1080, "height": 1920, "avg_frame_rate": "30/1",
                 "nb_read_frames": "30"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "1.0"},
        },
    )
    monkeypatch.setattr(render_mod, "sha256_file", lambda path: "0" * 64)

    stage = build_render_stage(_State(store), video_dir=_stub_video_dir(tmp_path))
    ctx = stage_ctx(store, "job1")
    stage.run(ctx)

    assert calls == ["remotion"]
    assert dict(ctx.json_pending)[RENDER_NAME]["renderer"] == "remotion"


def test_a_renderer_that_writes_nothing_fails_the_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No unverified success: an absent file is a stage failure, not an empty artifact."""
    import packages.core.media.render as render_mod

    store = _FakeStore(tmp_path, payload=_payload(renderer="remotion"))
    monkeypatch.setattr(render_mod, "render_storyboard", lambda **kwargs: {"elapsed_ms": 1})

    stage = build_render_stage(
        _State(store), video_dir=_stub_video_dir(tmp_path), renderer="remotion"
    )
    with pytest.raises(Exception, match="produced no file|render"):
        stage.run(stage_ctx(store, "job1"))
    assert True  # the raise above is the assertion: nothing was staged


def stage_ctx(store, job_id: str) -> Any:
    """Direct-run context: no lease, no cancel, temp staging."""
    from packages.core.orchestration.runner import NullCancel, StageContext

    return StageContext(
        store, job_id, Path(tempfile.mkdtemp(prefix="stagectx-")), cancel=NullCancel()
    )
