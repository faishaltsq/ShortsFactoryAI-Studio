"""The render boundary's pure logic: argv shape, path rules, and QC's verdicts.

No ffprobe, no node, no packages/video. Those are integration concerns; these tests pin the
decisions that must never drift.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from packages.core.media.render import (
    free_tcp_port,
    mux_argv,
    mux_narration,
    render_argv,
    update_storyboard_from_audio,
    validate_render,
)


def _probe(*, audio: bool = True, width: int = 1080, height: int = 1920, frames: int = 900,
           codec: str = "h264", pix_fmt: str = "yuv420p", fps: str = "30/1") -> dict:
    streams = [
        {
            "codec_type": "video",
            "codec_name": codec,
            "pix_fmt": pix_fmt,
            "width": width,
            "height": height,
            "avg_frame_rate": fps,
            "nb_read_frames": str(frames),
        }
    ]
    if audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return {
        "streams": streams,
        "format": {"duration": str(frames / 30)},
    }


def test_a_perfect_probe_has_no_failed_checks():
    assert validate_render(_probe(), expected_frames=900) == []


def test_zero_audio_streams_fails_both_audio_checks():
    assert validate_render(_probe(audio=False), expected_frames=900) == [
        "audio_streams",
        "audio_codec",
    ]


def test_wrong_dimensions_fail_width_and_height():
    failed = validate_render(_probe(width=720, height=1280), expected_frames=900)
    assert failed == ["width", "height"]


def test_a_missing_format_block_fails_duration_without_raising():
    probe = _probe()
    del probe["format"]
    assert validate_render(probe, expected_frames=900) == ["duration"]



def test_narration_duration_mismatch_is_reported():
    assert validate_render(
        _probe(frames=900), expected_frames=900, expected_duration_ms=29_000
    ) == ["duration"]
def test_a_frame_count_mismatch_is_reported():
    assert validate_render(_probe(frames=450), expected_frames=900) == ["frame_count", "duration"]


def test_a_wrong_codec_and_pixel_format_are_reported():
    failed = validate_render(_probe(codec="vp9", pix_fmt="yuv444p"), expected_frames=900)
    assert failed == ["video_codec", "pix_fmt"]


def test_two_video_streams_are_rejected():
    probe = _probe()
    probe["streams"].append(dict(probe["streams"][0]))
    assert "video_streams" in validate_render(probe, expected_frames=900)


def test_render_argv_shape_and_order():
    argv = render_argv(
        video_dir=Path("C:/repo/packages/video"),
        props_path=Path("C:/repo/data/jobs/j1/render-props.json"),
        out_path=Path("C:/repo/data/jobs/j1/output.mp4"),
        port=4321,
    )
    assert argv[1] == str(Path("C:/repo/packages/video/node_modules/@remotion/cli/remotion-cli.js"))
    assert argv[2:] == [
        "render",
        "src/index.ts",
        "Short",
        "C:\\repo\\data\\jobs\\j1\\output.mp4",
        "--props=C:\\repo\\data\\jobs\\j1\\render-props.json",
        "--overwrite",
        "--log=error",
        "--pixel-format=yuv420p",
        "--color-space=bt709",
        "--port=4321",
        "--concurrency=1",
    ]
    assert argv[0].lower().endswith("node.exe") or argv[0].endswith("node")


def test_render_argv_can_render_the_thumbnail_composition():
    """The composition is a parameter, not a module constant.

    ``COMPOSITION_ID`` was pinned to ``"Short"``, so the ``Thumbnail`` composition that already
    exists in ``packages/video/src/Root.tsx`` could never be rendered by any code path.
    """
    argv = render_argv(
        video_dir=Path("C:/repo/packages/video"),
        props_path=Path("C:/repo/data/jobs/j1/render-props.json"),
        out_path=Path("C:/repo/data/jobs/j1/thumb.png"),
        port=4321,
        composition="Thumbnail",
    )
    assert "Thumbnail" in argv
    assert "Short" not in argv


def test_render_argv_defaults_to_the_short_composition():
    argv = render_argv(
        video_dir=Path("C:/repo/packages/video"),
        props_path=Path("C:/repo/data/jobs/j1/render-props.json"),
        out_path=Path("C:/repo/data/jobs/j1/output.mp4"),
        port=4321,
    )
    assert "Short" in argv


def test_render_argv_refuses_an_unknown_composition():
    with pytest.raises(ValueError, match="composition"):
        render_argv(
            video_dir=Path("C:/repo/packages/video"),
            props_path=Path("C:/repo/data/jobs/j1/render-props.json"),
            out_path=Path("C:/repo/data/jobs/j1/output.mp4"),
            port=4321,
            composition="NotAComposition",
        )


def test_render_argv_pins_the_pixel_format_exactly_once():
    """yuvj420p is full range; the contract and the media gate both require yuv420p."""
    argv = render_argv(
        video_dir=Path("C:/repo/packages/video"),
        props_path=Path("C:/repo/data/jobs/j1/render-props.json"),
        out_path=Path("C:/repo/data/jobs/j1/output.mp4"),
        port=4321,
    )
    pixel_flags = [item for item in argv if item.startswith("--pixel-format")]
    assert pixel_flags == ["--pixel-format=yuv420p"]
    assert argv.index("--pixel-format=yuv420p") < argv.index("--port=4321")


def test_render_argv_pins_a_limited_range_color_space():
    """--pixel-format alone leaves the range untagged, so libx264 emits yuvj420p (full range)."""
    argv = render_argv(
        video_dir=Path("C:/repo/packages/video"),
        props_path=Path("C:/repo/data/jobs/j1/render-props.json"),
        out_path=Path("C:/repo/data/jobs/j1/output.mp4"),
        port=4321,
    )
    color_flags = [item for item in argv if item.startswith("--color-space")]
    assert color_flags == ["--color-space=bt709"]
    assert argv.index("--color-space=bt709") < argv.index("--port=4321")


def test_render_argv_refuses_a_relative_path():
    with pytest.raises(ValueError, match="absolute"):
        render_argv(
            video_dir=Path("C:/repo/packages/video"),
            props_path=Path("render-props.json"),
            out_path=Path("C:/repo/data/jobs/j1/output.mp4"),
            port=4321,
        )


def test_free_port_is_usable():
    port = free_tcp_port()
    assert isinstance(port, int)
    assert 1024 <= port <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))

def test_audio_timings_replace_storyboard_timeline_and_subtitles():
    storyboard = {
        "fps": 30,
        "scenes": [
            {"sceneId": "sc1", "startFrame": 0, "durationInFrames": 300},
            {"sceneId": "sc2", "startFrame": 300, "durationInFrames": 300},
        ],
        "subtitles": [],
    }
    audio = {
        "narration": {"durationMs": 2100},
        "scenes": [
            {"sceneId": "sc1", "startMs": 0, "endMs": 900},
            {"sceneId": "sc2", "startMs": 900, "endMs": 2100},
        ],
        "subtitles": [{"startMs": 0, "endMs": 900, "text": "hello"}],
    }

    timed = update_storyboard_from_audio(storyboard, audio)

    assert [(s["startFrame"], s["durationInFrames"]) for s in timed["scenes"]] == [(0, 27), (27, 36)]
    assert timed["subtitles"] == audio["subtitles"]


def _timeline(*, speech: list[dict] | None = None) -> tuple[dict, dict]:
    storyboard = {
        "fps": 30,
        "scenes": [
            {"sceneId": "sc1", "startFrame": 0, "durationInFrames": 300, "text": []},
            {"sceneId": "sc2", "startFrame": 300, "durationInFrames": 300, "text": []},
        ],
        "subtitles": [],
    }
    audio = {
        "narration": {"durationMs": 2100},
        "scenes": [
            {"sceneId": "sc1", "startMs": 0, "endMs": 900},
            {"sceneId": "sc2", "startMs": 900, "endMs": 2100},
        ],
        "subtitles": [],
    }
    if speech is not None:
        audio["scenes"][0]["speech"] = speech
    return storyboard, audio


def test_measured_word_windows_reach_the_timed_storyboard():
    """The mouth is driven from these windows, so they have to survive the retime.

    They were previously computed by ``rebase_boundaries`` and thrown away, which is why the
    renderer had no speech timing and the character's mouth was animated from a sine wave.
    """
    storyboard, audio = _timeline(
        speech=[{"startMs": 0, "endMs": 400}, {"startMs": 520, "endMs": 880}]
    )
    timed = update_storyboard_from_audio(storyboard, audio)
    assert timed["scenes"][0]["speech"] == [
        {"startMs": 0, "endMs": 400},
        {"startMs": 520, "endMs": 880},
    ]
    # A scene with no measured speech must not gain an empty list: the renderer distinguishes
    # "not measured" from "measured and silent", and only the first may leave the mouth closed.
    assert "speech" not in timed["scenes"][1]


def test_absent_speech_stays_absent_rather_than_becoming_a_synthetic_clock():
    storyboard, audio = _timeline()
    timed = update_storyboard_from_audio(storyboard, audio)
    assert all("speech" not in scene for scene in timed["scenes"])


@pytest.mark.parametrize(
    ("speech", "problem"),
    [
        ([{"startMs": 400, "endMs": 300}], "non-empty"),
        ([{"startMs": 500, "endMs": 400}], "ordered"),
        ([{"startMs": 0, "endMs": 400}, {"startMs": 300, "endMs": 600}], "ordered"),
        ([{"startMs": 0, "endMs": 1200}], "inside the scene"),
        ([{"startMs": 0}], "integers"),
        ([{"startMs": 0, "endMs": "400"}], "integers"),
    ],
)
def test_a_malformed_speech_window_is_rejected(speech, problem):
    """A window that is out of order or out of range opens the mouth at the wrong frame and still
    looks plausible in a still, which is the exact failure this feature exists to prevent."""
    storyboard, audio = _timeline(speech=speech)
    with pytest.raises(ValueError, match=problem):
        update_storyboard_from_audio(storyboard, audio)


def test_mux_argv_does_not_truncate_the_picture(tmp_path: Path):
    """``-shortest`` deleted the last frame of every render.

    ``update_storyboard_from_audio`` rounds each scene end *up* (``math.ceil``), so the picture is
    deliberately a fraction of a frame longer than the narration. ``-shortest`` then cut the
    output back to the narration length, which dropped that frame: a 434-frame render muxed
    against 14450 ms of narration produced 433 frames, and ``TECHNICAL_QC`` correctly blocked it
    on ``frame_count``. The video is the master timeline; the audio is padded by the container.
    """
    argv = mux_argv(tmp_path / "video.mp4", tmp_path / "narration.wav", tmp_path / "output.mp4")
    assert "-shortest" not in argv


def test_mux_keeps_every_rendered_frame(tmp_path: Path):
    """The measured property, not just the flag: muxing must not change the frame count."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe are required")

    video = tmp_path / "video.mp4"
    narration = tmp_path / "narration.wav"
    out = tmp_path / "output.mp4"
    # 30 frames at 30 fps = exactly 1000 ms of picture, against 900 ms of narration.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=270x480:r=30:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:sample_rate=48000:duration=0.9", str(narration)],
        check=True, capture_output=True,
    )
    mux_narration(video, narration, out)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    )
    assert int(probe.stdout.strip()) == 30


def test_mux_argv_copies_video_and_encodes_aac(tmp_path: Path):
    argv = mux_argv(tmp_path / "video.mp4", tmp_path / "narration.wav", tmp_path / "output.mp4")

    assert argv[:6] == ["ffmpeg", "-y", "-i", str(tmp_path / "video.mp4"), "-i", str(tmp_path / "narration.wav")]
    assert ["-c:v", "copy"] == argv[argv.index("-c:v"):argv.index("-c:v") + 2]
    assert ["-c:a", "aac"] == argv[argv.index("-c:a"):argv.index("-c:a") + 2]
    assert "-shortest" not in argv, "the picture must not be truncated to the narration"


def test_frame_timeline_ends_at_or_after_narration_with_less_than_one_frame_padding():
    timed = update_storyboard_from_audio(
        {
            "fps": 30,
            "scenes": [{"sceneId": "sc1", "startFrame": 0, "durationInFrames": 30}],
            "subtitles": [],
        },
        {
            "narration": {"durationMs": 13_990},
            "scenes": [{"sceneId": "sc1", "startMs": 0, "endMs": 13_990}],
            "subtitles": [],
        },
    )
    end_frames = sum(scene["durationInFrames"] for scene in timed["scenes"])
    rendered_ms = end_frames / 30 * 1000

    assert rendered_ms >= 13_990
    assert rendered_ms - 13_990 < 1000 / 30


def test_a_render_shorter_than_its_narration_fails_duration():
    """One authoritative duration check.

    ``frame_duration`` used to assert that the frame span was not shorter than the narration.
    That is the same question ``duration`` asks — and ``TECHNICAL_QC`` answers it against
    ``audio.json`` with the frame count taken from ``render-props.json``, so a second
    self-consistency check here would be a duplicate that can disagree with the gate.
    """
    probe = _probe(frames=416)
    probe["format"]["duration"] = "13.866"  # 416 frames at 30 fps

    assert validate_render(
        probe,
        expected_frames=416,
        expected_duration_ms=13_990,
    ) == ["duration"]


def test_mux_does_not_request_a_bitrate_the_format_cannot_deliver(tmp_path: Path):
    """A bitrate the encoder cannot reach is dead configuration that misrepresents intent.

    Measured on a real render: ``-b:a 192k`` on a 16 kHz mono AAC stream is refused by the encoder
    (``Too many bits 12288 > 6144 per frame requested, clamping to max``) and delivered 67 524 b/s
    — 35 % of the request. The constant said 192k and nothing enforced it.
    """
    argv = mux_argv(tmp_path / "video.mp4", tmp_path / "narration.wav", tmp_path / "output.mp4")
    requested = [argv[index + 1] for index, part in enumerate(argv) if part == "-b:a"]
    assert requested, "the mux must state a bitrate rather than leaving it to chance"
    kbps = int(requested[0].rstrip("k"))
    # AAC-LC mono at 16 kHz cannot exceed 96 kb/s (6144 bits per 1024-sample frame).
    assert kbps <= 96, f"{kbps}k is unreachable for 16 kHz mono AAC-LC"
    assert kbps >= 48, f"{kbps}k is too low for intelligible speech"


def test_mux_states_the_sample_rate_it_actually_produces(tmp_path: Path):
    """The delivered rate must be a stated decision, not whatever ffmpeg defaulted to.

    ``narration.wav`` is measured at 192 kHz mono, so ``-ar 16000`` is a real 12:1 resample, not a
    no-op. Pinning it here means a TTS voice that changes rate cannot silently change the output.
    """
    argv = mux_argv(tmp_path / "video.mp4", tmp_path / "narration.wav", tmp_path / "output.mp4")
    assert "-ar" in argv
    assert argv[argv.index("-ar") + 1] == "16000"
    assert argv[argv.index("-ac") + 1] == "1"
