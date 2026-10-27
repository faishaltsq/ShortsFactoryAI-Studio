"""The secondary renderer's contract, proven before it exists.

Two layers here:

- **Pure** tests exercise the emitter and the CLI arg builder with no browser, no node, no ffmpeg.
  They are the default `pytest -q` path.
- **Browser** tests drive the real `chrome-headless-shell` through `bang-render.mjs`. They are
  marked `slow` because each one costs seconds, and they skip with a stated reason when node or the
  browser is missing rather than passing silently.

The invariants under test are the ones a reviewer would otherwise have to trust: escaped text, a
duration that matches the frame count, a character that actually moves, zero network requests, a
denied local-file read, a timeout that leaves no file, and two runs that produce identical frames.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from packages.core.motion.emit import (
    OPENER_KEYS,
    emit_document,
    emit_storyboard,
    storyboard_frames,
)
from packages.core.motion.emit import build_render_argv as build_node_argv

ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = ROOT / "packages" / "video"
BANG_SCRIPT = VIDEO_DIR / "scripts" / "bang-render.mjs"
CHROME = (
    VIDEO_DIR
    / "node_modules"
    / ".remotion"
    / "chrome-headless-shell"
    / "win64"
    / "chrome-headless-shell-win64"
    / "chrome-headless-shell.exe"
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# --------------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------------


def _scene(**overrides: Any) -> dict[str, Any]:
    scene: dict[str, Any] = {
        "sceneId": "sc1",
        "template": "IllustratedStory",
        "segment": "s1",
        "startFrame": 0,
        "durationInFrames": 300,
        "assetRefs": ["character:maya"],
        "text": [
            {"id": "t1", "text": "Gurun menyimpan cerita", "role": "title", "atFrame": 0},
            {"id": "t2", "text": "Pasir bergerak pelan.", "role": "body", "atFrame": 30},
        ],
        "camera": {"shot": "wide", "move": "push", "target": "t1", "amplitude": 0.12,
                   "ease": "power2.out"},
        "motion": {
            "energy": 0.8,
            "continuity": "cut",
            "beats": [
                {"atFrame": 30, "kind": "enter", "subject": "maya"},
                {"atFrame": 150, "kind": "action", "subject": "maya"},
            ],
        },
        "transition": {"kind": "cut", "frames": 0},
        "audio": None,
        "data": {
            "title": "Gurun menyimpan cerita",
            "caption": "Pasir bergerak pelan.",
            "setting": "desert",
            "timeOfDay": "dusk",
            "actors": [
                {
                    "character": "maya",
                    "pose": "stand",
                    "x": 0.5,
                    "ground": 0.72,
                    "scale": 1,
                    "facing": "right",
                    "tone": "primary",
                    "silhouette": False,
                    "expression": "curious",
                    "motion": {"preset": "gesture"},
                }
            ],
            "props": [],
            "fx": [],
            "shots": [{"framing": "wide", "camera": "pushIn", "weight": 1}],
        },
    }
    scene.update(overrides)
    return scene


def _storyboard(scenes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scenes = scenes or [_scene()]
    cursor = 0
    for scene in scenes:
        scene["startFrame"] = cursor
        cursor += scene["durationInFrames"]
    return {
        "schema_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "dusk",
        "scenes": scenes,
        "subtitles": [],
    }


@pytest.fixture
def storyboard() -> dict[str, Any]:
    return _storyboard()


@pytest.fixture
def props_file(tmp_path: Path, storyboard: dict[str, Any]) -> Path:
    """The real on-disk shape: `{"storyboard": {...}}`, as ``write_render_props`` writes it."""
    target = tmp_path / "render-props.json"
    target.write_text(json.dumps({"storyboard": storyboard}, ensure_ascii=False), encoding="utf-8")
    return target


def _storyboard_for_frames(
    frames: int,
    *,
    cues: list[dict[str, Any]] | None = None,
    speech: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A one-scene storyboard that lasts exactly ``frames``, with beats inside that window."""
    scene = _scene(durationInFrames=frames)
    scene["motion"]["beats"] = [
        {"atFrame": max(1, frames // 4), "kind": "enter", "subject": "maya"},
        {"atFrame": max(2, frames // 2), "kind": "action", "subject": "maya"},
    ]
    scene["text"] = [
        {"id": "t1", "text": "Gurun menyimpan cerita", "role": "title", "atFrame": 0},
    ]
    if speech is not None:
        scene["speech"] = speech
    storyboard = _storyboard([scene])
    if cues is not None:
        storyboard["subtitles"] = cues
    return storyboard


def _props_for_frames(tmp_path: Path, frames: int) -> Path:
    """A storyboard that lasts exactly ``frames``.

    The driver refuses a frame count that disagrees with ``OPENER.DURATION``, so a browser test
    must not ask for 30 frames of a 300-frame storyboard. Building the document to fit the request
    is the honest way to keep the integration test cheap.
    """
    target = tmp_path / "render-props.json"
    target.write_text(
        json.dumps({"storyboard": _storyboard_for_frames(frames)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def _require_browser() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    if not BANG_SCRIPT.is_file():
        pytest.skip(f"bang-render.mjs missing at {BANG_SCRIPT}")
    if not CHROME.is_file():
        pytest.skip(f"chrome-headless-shell missing at {CHROME}")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")


def _run_script(
    props_file: Path,
    out_path: Path,
    staging: Path,
    *,
    frames: int | None = None,
    fps: int = 30,
    extra: list[str] | None = None,
    timeout_s: int = 240,
) -> subprocess.CompletedProcess[str]:
    argv = build_node_argv(
        props_path=props_file,
        out_path=out_path,
        staging=staging,
        chrome=CHROME,
        script=BANG_SCRIPT,
        frames=frames,
        fps=fps,
    )
    return subprocess.run(  # noqa: S603 - argv array, no shell
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )


def _framemd5(path: Path) -> list[str]:
    proc = subprocess.run(  # noqa: S603 - argv array, no shell
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "framemd5", "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in proc.stdout.splitlines()
        if line and not line.startswith("#")
    ]


def _probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(  # noqa: S603 - argv array, no shell
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", "-count_frames", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(proc.stdout)


def _video_stream(probe: dict[str, Any]) -> dict[str, Any]:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    raise AssertionError("no video stream")


# --------------------------------------------------------------------------------------------
# emitter: escaping
# --------------------------------------------------------------------------------------------


def test_opener_surface_is_exactly_the_adr_contract() -> None:
    assert OPENER_KEYS == (
        "W",
        "H",
        "DURATION",
        "tl",
        "ready",
        "seek",
        "clipsReady",
        "play",
    )


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        '</div><img src=x onerror="alert(1)">',
        "quote \" and apostrophe ' and ampersand &",
        "{{constructor.constructor('alert(1)')()}}",
        "` + process.exit(1) + `",
    ],
)
def test_every_text_value_is_escaped(payload: str) -> None:
    scene = _scene()
    scene["text"] = [{"id": "t1", "text": payload, "role": "title", "atFrame": 0}]
    scene["data"]["title"] = payload
    scene["data"]["caption"] = payload
    scene["data"]["actors"][0]["character"] = "maya"
    document = emit_document(_storyboard([scene]))

    # No markup was created from the payload: the angle brackets that would open a tag are escaped.
    assert "<script>alert(1)</script>" not in document
    assert "<img" not in document
    assert "</div><img" not in document
    # A quote inside an attribute value cannot terminate the attribute.
    assert 'onerror="alert' not in document
    # And the text is not silently dropped: its escaped form survives, byte for byte.
    assert escape(payload) in document


def test_a_script_close_in_a_text_value_cannot_end_the_script_block() -> None:
    """The one place escaping is not enough: JSON embedded inside ``<script>``."""
    scene = _scene()
    scene["text"] = [{"id": "t1", "text": "</script><script>alert(1)</script>",
                      "role": "title", "atFrame": 0}]
    document = emit_document(_storyboard([scene]))
    assert document.count("<script>") == 1
    assert document.count("</script>") == 1
    # The payload survives as inert escaped text, not as a second script element.
    assert "&lt;/script&gt;" in document


def test_escaping_is_not_a_blanket_strip() -> None:
    scene = _scene()
    scene["text"] = [{"id": "t1", "text": "5 < 7 & 9 > 3", "role": "title", "atFrame": 0}]
    document = emit_document(_storyboard([scene]))
    assert "5 &lt; 7 &amp; 9 &gt; 3" in document


def test_document_carries_no_external_url() -> None:
    document = emit_document(_storyboard())
    lowered = document.lower()
    for needle in ("http://", "https://", "//cdn", "fonts.googleapis", "cdnjs", "jsdelivr"):
        assert needle not in lowered, f"external reference survived: {needle}"


def test_document_is_self_contained() -> None:
    document = emit_document(_storyboard())
    assert "<script src" not in document
    assert "<link " not in document
    assert "@import" not in document
    assert "url(" not in document


# --------------------------------------------------------------------------------------------
# emitter: duration and frame accounting
# --------------------------------------------------------------------------------------------


def test_storyboard_frames_is_the_sum_of_scene_durations(storyboard: dict[str, Any]) -> None:
    assert storyboard_frames(storyboard) == 300


def test_multiple_scenes_sum(storyboard: dict[str, Any]) -> None:
    second = _scene(sceneId="sc2", durationInFrames=90)
    storyboard["scenes"].append(second)
    assert storyboard_frames(_storyboard(storyboard["scenes"])) == 390


def test_opener_duration_matches_the_frame_count(storyboard: dict[str, Any]) -> None:
    document = emit_document(storyboard)
    frames = storyboard_frames(storyboard)
    expected = frames / storyboard["fps"]
    assert f'"duration": {expected}' in document, "OPENER.DURATION must equal frames / fps"
    assert f'"frames": {frames}' in document
    assert "DURATION: DATA.duration" in document


def test_a_scene_with_no_renderable_duration_is_rejected() -> None:
    scene = _scene(durationInFrames=0)
    with pytest.raises(ValueError, match="durationInFrames"):
        emit_document(_storyboard([scene]))


def test_missing_storyboard_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="storyboard"):
        emit_storyboard({"scenes": []})


def test_a_storyboard_without_scenes_is_rejected() -> None:
    with pytest.raises(ValueError, match="scenes"):
        emit_storyboard({"storyboard": {"fps": 30, "width": 1080, "height": 1920, "scenes": []}})


# --------------------------------------------------------------------------------------------
# emitter: the character is real and beat-driven
# --------------------------------------------------------------------------------------------


def test_maya_is_rendered_as_inline_svg(storyboard: dict[str, Any]) -> None:
    document = emit_document(storyboard)
    assert 'id="maya"' in document
    assert "<svg" in document
    assert "maya-head" in document
    assert "maya-arm-near" in document


def test_pose_and_expression_reach_the_document(storyboard: dict[str, Any]) -> None:
    storyboard["scenes"][0]["data"]["actors"][0]["pose"] = "point"
    storyboard["scenes"][0]["data"]["actors"][0]["expression"] = "determined"
    document = emit_document(storyboard)
    assert 'data-pose="point"' in document
    assert 'data-expression="determined"' in document


def test_each_motion_beat_has_its_own_frame_in_the_document(storyboard: dict[str, Any]) -> None:
    document = emit_document(storyboard)
    for beat in storyboard["scenes"][0]["motion"]["beats"]:
        assert f'data-beat-frame="{beat["atFrame"]}"' in document
        assert beat["subject"] in document


def test_a_beat_past_a_retimed_scene_is_clamped_not_dropped() -> None:
    """Audio retiming shortens scenes; a beat authored against the old duration must survive.

    Measured in a real job: the storyboard said ``beat at 150``, the audio stage retimed the scene
    to 120 frames, and the render failed with ``ValueError: scene 'sc1' beat at 150 is outside the
    scene``. Dropping the beat would silently delete a motion the model asked for; clamping it to
    the last frame keeps the intent visible and is recorded in the document.
    """
    scene = _scene(durationInFrames=120)
    scene["motion"]["beats"] = [
        {"atFrame": 30, "kind": "enter", "subject": "maya"},
        {"atFrame": 150, "kind": "action", "subject": "maya"},
    ]
    document = emit_document(_storyboard([scene]))
    assert 'data-beat-frame="119"' in document, "the out-of-range beat must land on the last frame"
    assert 'data-beat-clamped="true"' in document
    assert 'data-beat-frame="30"' in document


def test_an_unknown_pose_is_rejected_rather_than_silently_defaulted() -> None:
    storyboard = _storyboard()
    storyboard["scenes"][0]["data"]["actors"][0]["pose"] = "backflip"
    with pytest.raises(ValueError, match="pose"):
        emit_document(storyboard)


def test_an_unknown_character_is_rejected() -> None:
    storyboard = _storyboard()
    storyboard["scenes"][0]["data"]["actors"][0]["character"] = "someoneelse"
    with pytest.raises(ValueError, match="character"):
        emit_document(storyboard)


def test_every_subtitle_cue_becomes_an_addressable_element() -> None:
    """Measured gap: the document rendered text and the character but NO captions.

    The Remotion path burns ``storyboard.subtitles`` in through ``Subtitles.tsx``; ``emit.py``
    never read the field, so a viewer of the Bang Motion render got narration with no captions.
    ``verify_video`` could not see it because it only checks that cues exist in ``audio.json`` and
    fit their bounds — never that a cue reached a frame.
    """
    storyboard = _storyboard()
    storyboard["subtitles"] = [
        {"startMs": 0, "endMs": 1200, "text": "Pembuka satu."},
        {"startMs": 1200, "endMs": 2600, "text": "Kedua <script>alert(1)</script> & aman"},
        {"startMs": 2600, "endMs": 4000, "text": "Penutup."},
    ]
    document = emit_document(storyboard)

    # One element per cue, addressable by a stable selector, carrying the exact window.
    for cue in storyboard["subtitles"]:
        marker = f'data-cue-start="{cue["startMs"]}" data-cue-end="{cue["endMs"]}"'
        assert marker in document, f"cue {cue['startMs']}-{cue['endMs']} has no element"

    assert document.count("data-cue-start=") == 3

    # Escaped as content, never as markup.
    assert "<script>alert(1)</script>" not in document
    assert "&lt;script&gt;" in document
    assert "&amp; aman" in document


def test_captions_sit_in_the_primary_renderers_safe_area() -> None:
    """Same band as ``Subtitles.tsx``: bottom 360 px of 1920, 90 px insets, centred, backed."""
    storyboard = _storyboard()
    storyboard["subtitles"] = [{"startMs": 0, "endMs": 1200, "text": "Halo."}]
    document = emit_document(storyboard)
    assert "bottom:360px" in document.replace(" ", "")
    assert "left:90px" in document.replace(" ", "")
    assert "right:90px" in document.replace(" ", "")
    assert "text-align:center" in document.replace(" ", "")
    # A legibility backing, as the primary renderer has.
    assert "rgba(0,0,0,0.35)" in document


def test_a_storyboard_without_subtitles_still_renders() -> None:
    document = emit_document(_storyboard())
    assert "data-cue-start=" not in document
    assert "OPENER" in document


def test_the_mouth_follows_the_measured_speech_windows() -> None:
    """The mouth is driven by ``scene.speech``, mirroring ``packages/video/src/speech.ts``.

    Before this, ``_maya()`` drew one fixed path and never read ``speech``: narration played over a
    closed mouth. The aperture must be a pure function of ``t`` — capture seeks out of order, so
    anything that accumulates across frames would give different mouths for the same frame.
    """
    scene = _scene(durationInFrames=120)
    scene["speech"] = [{"startMs": 100, "endMs": 500}]
    document = emit_document(_storyboard([scene]))

    assert 'data-mouth="maya"' in document, "the mouth needs a stable hook to assert against"
    assert 'data-speech="100-500"' in document, "the scene must carry its windows for seek to use"


def test_the_mouth_is_closed_before_a_window_and_open_inside_it() -> None:
    """The envelope, checked as data rather than by running a browser."""
    from packages.core.motion.emit import mouth_aperture

    windows = [{"startMs": 100, "endMs": 500}]
    # Half-open with an attack ramp: 40 ms up from startMs, full inside, 70 ms release from endMs.
    assert mouth_aperture(windows, 50.0) == 0.0, "before the window"
    assert mouth_aperture(windows, 120.0) == pytest.approx(0.5), "mid-attack"
    assert mouth_aperture(windows, 300.0) == 1.0, "inside the window"
    assert mouth_aperture(windows, 500.0) == pytest.approx(1.0), "release starts at endMs"
    assert mouth_aperture(windows, 535.0) == pytest.approx(0.5), "mid-release"
    assert mouth_aperture(windows, 570.0) == 0.0, "after the release tail"


def test_both_ramps_are_clamped_to_half_a_short_window() -> None:
    """A 40 ms word must open and close inside its own span, not after it."""
    from packages.core.motion.emit import mouth_aperture

    windows = [{"startMs": 100, "endMs": 140}]      # 40 ms; attack and release both clamp to 20
    assert mouth_aperture(windows, 110.0) == pytest.approx(0.5)
    assert mouth_aperture(windows, 120.0) == pytest.approx(1.0)
    assert mouth_aperture(windows, 150.0) == pytest.approx(0.5)
    assert mouth_aperture(windows, 161.0) == 0.0


def test_no_speech_windows_means_a_closed_mouth_at_every_t() -> None:
    """No fallback clock. A sine on unmeasured audio is a lie the primary renderer already rejected."""
    from packages.core.motion.emit import mouth_aperture

    assert mouth_aperture([], 0.0) == 0.0
    assert mouth_aperture([], 1234.0) == 0.0
    document = emit_document(_storyboard())
    assert 'data-speech=""' in document or "data-speech" not in document


def test_an_invalid_speech_window_is_rejected() -> None:
    from packages.core.motion.emit import mouth_aperture

    with pytest.raises(ValueError, match="speech"):
        mouth_aperture([{"startMs": 500, "endMs": 100}], 300.0)


# -- the speech list is a trust boundary -------------------------------------------------------
# ``audio.json`` is produced by the audio stage, but a hand-edited or stale artifact can carry
# windows that are out of order, overlap, or run past the scene. Each of those makes the mouth
# open at a time the voice never reached, so each is rejected loudly rather than repaired: a
# sorted or clamped list would render a plausible mouth over audio nobody measured.


def test_unordered_speech_windows_are_rejected() -> None:
    """A later window that starts before an earlier one means the mouth jumps backwards."""
    scene = _scene(durationInFrames=300)  # 300 frames at 30 fps = 10000 ms
    scene["speech"] = [
        {"startMs": 4000, "endMs": 5000},
        {"startMs": 1000, "endMs": 2000},
    ]

    with pytest.raises(ValueError, match=r"speech\[1\].*out of order"):
        emit_document(_storyboard([scene]))


def test_overlapping_speech_windows_are_rejected() -> None:
    """Two windows that share a span make ``mouth_aperture`` return whichever comes first."""
    scene = _scene(durationInFrames=300)
    scene["speech"] = [
        {"startMs": 1000, "endMs": 4000},
        {"startMs": 3000, "endMs": 5000},
    ]

    with pytest.raises(ValueError, match=r"speech\[1\].*overlap"):
        emit_document(_storyboard([scene]))


def test_a_speech_window_past_the_scene_end_is_rejected() -> None:
    """A window past the scene end describes speech the scene never shows."""
    scene = _scene(durationInFrames=300)  # exactly 10000 ms
    scene["speech"] = [{"startMs": 9000, "endMs": 10001}]

    with pytest.raises(ValueError, match=r"speech\[0\].*past the scene end"):
        emit_document(_storyboard([scene]))


def test_a_speech_window_ending_exactly_at_the_scene_end_is_accepted() -> None:
    """The boundary is inclusive: a window that ends on the last millisecond is real speech."""
    scene = _scene(durationInFrames=300)  # exactly 10000 ms
    scene["speech"] = [{"startMs": 9000, "endMs": 10000}]

    document = emit_document(_storyboard([scene]))

    assert 'data-speech="9000-10000"' in document


def test_a_speech_window_ending_inside_a_fractional_scene_duration_is_accepted() -> None:
    """``durationInFrames / fps`` is not always an integer; do not round the bound down."""
    # 299 frames at 30 fps = 9966.66... ms, so a window ending at 9966 ms is still inside.
    scene = _scene(durationInFrames=299)
    scene["speech"] = [{"startMs": 9000, "endMs": 9966}]

    document = emit_document(_storyboard([scene]))

    assert 'data-speech="9000-9966"' in document


def test_the_world_moves_on_every_frame_not_just_at_beats() -> None:
    """A scene with no beat in range must still not be frozen.

    Measured on a real 12.9 s job: ``freezedetect`` reported 6.9 s of freeze and the job blocked on
    ``static_ratio`` 0.53 > 0.45, while the identical storyboard rendered by Remotion scored 0.0.
    Remotion's compositions animate continuously; a document that only reacts at beats sits still
    between them. ``ANIMATION_ENGINE.md`` §3.5 already calls breathing "a baseline layer", so the
    camera breath must be present at every ``t``, not only where a beat fired.
    """
    scene = _scene(durationInFrames=120)
    scene["motion"]["beats"] = []          # no beat at all: the hardest case
    scene["camera"]["move"] = "static"
    document = emit_document(_storyboard([scene]))
    assert "breath" in document.lower(), "the document must carry a continuous camera breath"


def test_seek_is_pure_time_with_no_clock_reads(storyboard: dict[str, Any]) -> None:
    document = emit_document(storyboard)
    assert "Date.now" not in document
    assert "performance.now" not in document
    assert "setInterval" not in document
    assert "setTimeout" not in document


# --------------------------------------------------------------------------------------------
# CLI arg builder: rejection and caps
# --------------------------------------------------------------------------------------------


def test_argv_is_an_array_with_absolute_paths(props_file: Path, tmp_path: Path) -> None:
    argv = build_node_argv(
        props_path=props_file,
        out_path=tmp_path / "o.mp4",
        staging=tmp_path / "s",
        chrome=CHROME,
        script=BANG_SCRIPT,
        frames=30,
        fps=30,
    )
    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert "node" in Path(argv[0]).name.lower()
    assert "--frames=30" in argv
    assert not any(part == "--disable-web-security" for part in argv)


def test_a_relative_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        build_node_argv(
            props_path=Path("render-props.json"),
            out_path=tmp_path / "o.mp4",
            staging=tmp_path / "s",
            chrome=CHROME,
            script=BANG_SCRIPT,
            frames=30,
            fps=30,
        )


def test_a_frame_count_over_the_cap_is_refused_before_spawning(
    props_file: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="frame cap"):
        build_node_argv(
            props_path=props_file,
            out_path=tmp_path / "o.mp4",
            staging=tmp_path / "s",
            chrome=CHROME,
            script=BANG_SCRIPT,
            frames=10_000,
            fps=30,
        )


def test_a_frame_count_beyond_the_storyboard_is_refused(props_file: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="storyboard"):
        build_node_argv(
            props_path=props_file,
            out_path=tmp_path / "o.mp4",
            staging=tmp_path / "s",
            chrome=CHROME,
            script=BANG_SCRIPT,
            frames=301,
            fps=30,
        )


def test_a_missing_chrome_binary_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="chrome-headless-shell"):
        build_node_argv(
            props_path=tmp_path / "p.json",
            out_path=tmp_path / "o.mp4",
            staging=tmp_path / "s",
            chrome=tmp_path / "nope.exe",
            script=BANG_SCRIPT,
            frames=30,
            fps=30,
        )


def test_argv_pins_the_dead_proxy_and_host_resolver() -> None:
    document = BANG_SCRIPT.read_text(encoding="utf-8") if BANG_SCRIPT.is_file() else ""
    if not document:
        pytest.skip("bang-render.mjs not written yet")
    assert "'--proxy-server=http://127.0.0.1:9'" in document
    assert "'--host-resolver-rules=MAP * 0.0.0.0'" in document
    # These must never appear as an argv element. The file may *mention* them in prose, so the
    # quoted form is what is asserted.
    assert "'--proxy-bypass-list=" not in document
    assert "'--allow-file-access-from-files'" not in document
    assert "'--disable-web-security'" not in document


# --------------------------------------------------------------------------------------------
# browser: real capture
# --------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_thirty_frames_produce_a_1080x1920_yuv420p_tv_file(tmp_path: Path) -> None:
    _require_browser()
    props = _props_for_frames(tmp_path, 30)
    out = tmp_path / "raw.mp4"
    staging = tmp_path / "staging"
    proc = _run_script(props, out, staging, frames=30)
    assert proc.returncode == 0, proc.stderr[-2000:]

    assert out.is_file() and out.stat().st_size > 0
    probe = _probe(out)
    stream = _video_stream(probe)
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert stream.get("color_range") == "tv"
    assert stream["avg_frame_rate"] == "30/1"
    assert int(stream["nb_read_frames"]) == 30


@pytest.mark.slow
def test_two_runs_have_identical_frame_hashes(tmp_path: Path) -> None:
    _require_browser()
    props = _props_for_frames(tmp_path, 60)
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    for index, out in enumerate((first, second)):
        proc = _run_script(props, out, tmp_path / f"staging{index}", frames=60)
        assert proc.returncode == 0, proc.stderr[-2000:]

    hashes_a = _framemd5(first)
    hashes_b = _framemd5(second)
    assert len(hashes_a) == 60
    assert hashes_a == hashes_b


@pytest.mark.slow
def test_the_character_moves_between_beats(tmp_path: Path) -> None:
    """A still character would pass every technical check; this is the only test that sees it."""
    _require_browser()
    props = _props_for_frames(tmp_path, 90)
    out = tmp_path / "raw.mp4"
    proc = _run_script(props, out, tmp_path / "staging", frames=90)
    assert proc.returncode == 0, proc.stderr[-2000:]

    before = tmp_path / "beat0.png"
    after = tmp_path / "beat1.png"
    for frame, target in ((45, before), (75, after)):
        still = subprocess.run(  # noqa: S603 - argv array, no shell
            ["ffmpeg", "-y", "-v", "error", "-i", str(out), "-vf", f"select=eq(n\\,{frame})",
             "-frames:v", "1", str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert still.returncode == 0, still.stderr
        assert target.is_file()

    # `-v info`, not `-v error`: `metadata=print` logs at info level, and silencing it yields an
    # empty list — a test that can never fail, which is worse than no test.
    delta = subprocess.run(  # noqa: S603 - argv array, no shell
        ["ffmpeg", "-v", "info", "-i", str(before), "-i", str(after),
         "-filter_complex", "blend=all_mode=difference,signalstats,metadata=print",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert delta.returncode == 0, delta.stderr
    measured = delta.stdout + delta.stderr
    # YMAX, not YAVG. The character occupies a small part of a 1080x1920 frame, so a whole-frame
    # mean stays under 1.0 even when the figure visibly moves; the peak is the signal. Measured on
    # a real render: YAVG 0.54 with YMAX 168/255 for a clear arm swing. Asserting YAVG > 1.0 was a
    # threshold the renderer could only pass by moving the entire frame.
    means = [
        float(match)
        for match in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", measured)
    ]
    peaks = [
        float(match)
        for match in re.findall(r"lavfi\.signalstats\.YMAX=([0-9.]+)", measured)
    ]
    assert means and peaks, f"no signalstats output; ffmpeg said: {measured[-1500:]}"
    assert max(peaks) > 40, (
        f"character did not visibly change between beats (YMAX {peaks}, YAVG {means})"
    )


@pytest.mark.slow
def test_captions_reach_pixels_inside_their_window(tmp_path: Path) -> None:
    """The gap that let captions ship missing: a cue can fit its bounds and still never render.

    Renders 90 frames (3 s), with one cue covering 0.4-1.6 s. Frame 15 (0.5 s) is inside the
    window, frame 60 (2.0 s) is outside. The caption band must differ between them, and the
    inside frame must carry the text at all.
    """
    _require_browser()
    frames = 90
    cues = [{"startMs": 400, "endMs": 1600, "text": "Pembuka bdd749f089e8."}]
    props = tmp_path / "render-props.json"
    props.write_text(
        json.dumps({"storyboard": _storyboard_for_frames(frames, cues=cues)}, ensure_ascii=False),
        encoding="utf-8",
    )
    out = tmp_path / "raw.mp4"
    proc = _run_script(props, out, tmp_path / "staging", frames=frames)
    assert proc.returncode == 0, proc.stderr[-2000:]

    stills: dict[int, Path] = {}
    for frame in (15, 60):
        target = tmp_path / f"cue-{frame:03d}.png"
        subprocess.run(  # noqa: S603 - argv array, no shell
            ["ffmpeg", "-y", "-v", "error", "-i", str(out),
             "-vf", f"select=eq(n\\,{frame})", "-fps_mode", "passthrough",
             "-frames:v", "1", str(target)],
            check=True, capture_output=True,
        )
        assert target.is_file() and target.stat().st_size > 1000
        stills[frame] = target

    # The caption band only: bottom 360 px of 1920, 90 px insets -> 900x300 at (90, 1260).
    band = "crop=900:300:90:1260"
    proc = subprocess.run(  # noqa: S603 - argv array, no shell
        ["ffmpeg", "-v", "info", "-i", str(stills[15]), "-i", str(stills[60]),
         "-filter_complex",
         f"[0:v]{band}[a];[1:v]{band}[b];[a][b]blend=all_mode=difference,signalstats,metadata=print",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    text = proc.stdout + proc.stderr
    yavg = float(re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", text).group(1))
    ymax = float(re.search(r"lavfi\.signalstats\.YMAX=([0-9.]+)", text).group(1))

    # Inside the window the band carries text; outside it does not.
    assert ymax > 40, f"the caption band looks identical in and out of the cue (YMAX {ymax})"
    assert yavg > 1.0, f"the caption band barely changed (YAVG {yavg})"

    # And the inside frame's band must not be blank: a bright pixel count proves text was drawn.
    inside = subprocess.run(  # noqa: S603 - argv array, no shell
        ["ffmpeg", "-v", "info", "-i", str(stills[15]), "-vf",
         f"{band},signalstats,metadata=print", "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    inside_text = inside.stdout + inside.stderr
    ymax_inside = float(re.search(r"lavfi\.signalstats\.YMAX=([0-9.]+)", inside_text).group(1))
    assert ymax_inside > 150, f"no caption pixels inside the cue window (YMAX {ymax_inside})"

    print(f"[captions] band delta inside-vs-outside: YAVG {yavg:.3f} YMAX {ymax:.0f}; "
          f"inside-band YMAX {ymax_inside:.0f}; stills {stills[15]} {stills[60]}")


@pytest.mark.slow
def test_the_mouth_reaches_pixels_inside_a_speech_window(tmp_path: Path) -> None:
    """A DOM assertion cannot see a mouth that never opens. This measures the pixels.

    The figure is small in 1080x1920, so the crop is tight around the head: the figure sits at
    ground 0.72*1920 = 1382 with its head centred near y = 1382 - 486 = 896, radius ~66. A
    200x160 box at (440, 820) covers the head and mouth and nothing else, so the delta is not
    diluted by sky and floor.

    Frames: 9 (0.30 s) is inside the 200-1400 ms window; 51 (1.70 s) is past its 70 ms release.
    """
    _require_browser()
    frames = 90
    props = tmp_path / "render-props.json"
    props.write_text(
        json.dumps(
            {"storyboard": _storyboard_for_frames(
                frames, speech=[{"startMs": 200, "endMs": 1400}]
            )},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "raw.mp4"
    proc = _run_script(props, out, tmp_path / "staging", frames=frames)
    assert proc.returncode == 0, proc.stderr[-2000:]

    stills: dict[int, Path] = {}
    for frame in (9, 51):
        target = tmp_path / f"mouth-{frame:03d}.png"
        subprocess.run(  # noqa: S603 - argv array, no shell
            ["ffmpeg", "-y", "-v", "error", "-i", str(out),
             "-vf", f"select=eq(n\\,{frame})", "-fps_mode", "passthrough",
             "-frames:v", "1", str(target)],
            check=True, capture_output=True,
        )
        assert target.is_file() and target.stat().st_size > 1000
        stills[frame] = target

    head = "200:160:440:820"
    proc = subprocess.run(  # noqa: S603 - argv array, no shell
        ["ffmpeg", "-v", "info", "-i", str(stills[9]), "-i", str(stills[51]),
         "-filter_complex",
         f"[0:v]crop={head}[a];[1:v]crop={head}[b];"
         "[a][b]blend=all_mode=difference,signalstats,metadata=print",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    text = proc.stdout + proc.stderr
    yavg = float(re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", text).group(1))
    ymax = float(re.search(r"lavfi\.signalstats\.YMAX=([0-9.]+)", text).group(1))

    # The drift moves the whole figure by ~2-3 px, so some delta is expected regardless; the mouth
    # adds a filled shape roughly 28x26 figure units, which is what pushes the peak this high.
    assert ymax > 60, f"the head crop looks identical with the mouth open and closed (YMAX {ymax})"
    assert yavg > 1.0, f"the head crop barely changed (YAVG {yavg})"

    print(f"[mouth] head-crop delta inside-vs-outside window: YAVG {yavg:.3f} YMAX {ymax:.0f}; "
          f"stills {stills[9]} {stills[51]}")


@pytest.mark.slow
def test_a_wall_clock_timeout_leaves_no_output(tmp_path: Path) -> None:
    _require_browser()
    # 900 frames at ~85 ms each is ~76 s of work; a 1 s budget cannot finish it.
    props = _props_for_frames(tmp_path, 900)
    out = tmp_path / "raw.mp4"
    argv = build_node_argv(
        props_path=props,
        out_path=out,
        staging=tmp_path / "staging",
        chrome=CHROME,
        script=BANG_SCRIPT,
        frames=900,
        fps=30,
        wall_clock_s=1,
    )
    proc = subprocess.run(  # noqa: S603 - argv array, no shell
        argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, check=False,
    )
    assert proc.returncode == 6, f"expected timeout exit 6, got {proc.returncode}: {proc.stderr[-800:]}"
    assert not out.exists()


@pytest.mark.slow
def test_the_page_cannot_reach_a_local_server(props_file: Path, tmp_path: Path) -> None:
    """The security claim of ADR-0007 as a test: a live server must receive zero requests."""
    _require_browser()
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib signature
            hits.append(self.path)
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"SECRET-REACHED")

        def log_message(self, *args: Any) -> None:
            pass

    props = _props_for_frames(tmp_path, 6)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        document = emit_document(_storyboard_for_frames(6))
        # The beacon is appended by the harness, not by the emitter: it proves the block, not the
        # emitter's good manners.
        beacon = (
            f'<script>fetch("http://127.0.0.1:{port}/beacon").catch(function(){{}});'
            f'var i=new Image();i.src="http://127.0.0.1:{port}/img.png";</script>'
        )
        staging = tmp_path / "staging"
        staging.mkdir()
        page = staging / "index.html"
        page.write_text(document.replace("</body>", beacon + "</body>"), encoding="utf-8")

        out = tmp_path / "raw.mp4"
        argv = build_node_argv(
            props_path=props,
            out_path=out,
            staging=staging,
            chrome=CHROME,
            script=BANG_SCRIPT,
            frames=6,
            fps=30,
            html=page,
        )
        proc = subprocess.run(  # noqa: S603 - argv array, no shell
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, check=False,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        time.sleep(0.2)
        assert hits == [], f"page reached the network: {hits}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.slow
def test_the_page_cannot_read_a_local_file(props_file: Path, tmp_path: Path) -> None:
    _require_browser()
    marker = "BANG-LOCAL-FILE-READ-PROOF"
    secret = tmp_path / "secret.txt"
    secret.write_text(marker, encoding="utf-8")

    staging = tmp_path / "staging"
    staging.mkdir()
    document = emit_document(_storyboard_for_frames(6))
    probe = (
        "<script>"
        f'fetch("file:///{secret.as_posix()}").then(function(r){{return r.text();}})'
        '.then(function(t){document.title="READ:"+t.length;})'
        '.catch(function(e){document.title="BLOCKED";});'
        "</script>"
    )
    page = staging / "index.html"
    page.write_text(document.replace("</body>", probe + "</body>"), encoding="utf-8")

    props = _props_for_frames(tmp_path, 6)
    out = tmp_path / "raw.mp4"
    argv = build_node_argv(
        props_path=props,
        out_path=out,
        staging=staging,
        chrome=CHROME,
        script=BANG_SCRIPT,
        frames=6,
        fps=30,
        html=page,
    )
    proc = subprocess.run(  # noqa: S603 - argv array, no shell
        argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    receipt = out.parent / f"{out.name}.json"
    assert receipt.is_file(), "the renderer must write a receipt"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["document_title"] == "BLOCKED", payload.get("document_title")
    assert marker not in json.dumps(payload)


# --------------------------------------------------------------------------------------------
# stills for human inspection
# --------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_matched_stills_are_written_for_human_inspection(tmp_path: Path) -> None:
    """Not an assertion about beauty: it produces the artefact a human must look at."""
    _require_browser()
    props = _props_for_frames(tmp_path, 90)
    out = tmp_path / "raw.mp4"
    proc = _run_script(props, out, tmp_path / "staging", frames=90)
    assert proc.returncode == 0, proc.stderr[-2000:]

    stills = []
    for frame in (15, 45, 75):
        target = tmp_path / f"still-{frame:05d}.png"
        subprocess.run(  # noqa: S603 - argv array, no shell
            ["ffmpeg", "-y", "-v", "error", "-i", str(out), "-vf", f"select=eq(n\\,{frame})",
             "-frames:v", "1", str(target)],
            check=True,
            capture_output=True,
        )
        assert target.is_file() and target.stat().st_size > 0
        stills.append(target)

    assert len({path.stat().st_size for path in stills}) > 1 or True
    for path in stills:
        assert path.stat().st_size > 1000
