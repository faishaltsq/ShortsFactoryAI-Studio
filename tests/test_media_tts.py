from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from packages.core.media.tts import (
    WordBoundary,
    build_mix_argv,
    group_subtitles,
    parse_boundaries,
    parse_loudness_lufs,
    synthesize_sapi,
)


def test_subtitles_group_punctuation_without_exceeding_duration():
    words = [
        WordBoundary("Halo", 0, 180),
        WordBoundary("dunia.", 190, 430),
        WordBoundary("Apa", 500, 650),
        WordBoundary("kabar?", 660, 900),
    ]

    cues = group_subtitles(words, duration_ms=900, max_chars=20)

    assert [(cue.text, cue.startMs, cue.endMs) for cue in cues] == [
        ("Halo dunia.", 0, 430),
        ("Apa kabar?", 500, 900),
    ]


def test_subtitles_keep_a_long_word_and_reject_empty_or_unordered_boundaries():
    long_word = "supercalifragilisticexpialidocious"
    assert [cue.text for cue in group_subtitles(
        [WordBoundary(long_word, 10, 200)], duration_ms=200, max_chars=12
    )] == [long_word]
    assert group_subtitles([], duration_ms=200) == []
    with pytest.raises(ValueError, match="ordered"):
        group_subtitles(
            [WordBoundary("later", 100, 150), WordBoundary("earlier", 50, 90)],
            duration_ms=200,
        )


def test_sapi_passes_text_by_file_and_removes_partial_outputs(tmp_path: Path, monkeypatch):
    """Two real properties: the narration never travels in argv, and a failed run cleans up.

    The arguments are located by suffix, not by position. Inserting ``-NonInteractive`` moved
    every later index by one, and a positional assertion silently started checking the wrong
    argument — which is worse than failing, because it kept passing for a while.
    """
    output = tmp_path / "scene.wav"
    seen: list[list[str]] = []

    captured: dict[str, str] = {}

    def fail(argv, **kwargs):
        seen.append(argv)
        output.write_bytes(b"partial")
        text_arg = next(arg for arg in argv if str(arg).endswith(".txt"))
        # Read while the file still exists: the adapter deletes it in ``finally``.
        captured["text"] = Path(text_arg).read_text(encoding="utf-8")
        captured["words"] = next(arg for arg in argv if str(arg).endswith(".words.json"))
        Path(text_arg).write_text("[]", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 7, "", "voice missing")

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="voice missing"):
        synthesize_sapi("rahasia di file", output, voice="id-ID-ArdiNeural", script_path=tmp_path / "tts.ps1")

    argv = seen[0]
    # Property 1: the narration is passed through a file, never as an argument.
    assert "rahasia di file" not in argv
    assert not any("rahasia" in str(arg) for arg in argv)

    assert captured["text"] == "rahasia di file"
    assert Path(captured["words"]) == output.with_suffix(".words.json")

    # Property 2: a failed run leaves nothing behind — not the partial WAV, not the text file,
    # not the boundary file.
    assert not output.exists()
    assert not Path(captured["words"]).exists()
    assert not any(tmp_path.glob("narration-*.txt"))


def test_music_mix_argv_ducks_only_when_music_exists(tmp_path: Path):
    narration = tmp_path / "narration.wav"
    music = tmp_path / "music.wav"
    output = tmp_path / "mix.wav"

    narration_only = build_mix_argv(narration, output, gain_db=12.5)
    with_music = build_mix_argv(narration, output, music_path=music, gain_db=12.5)

    assert "sidechaincompress" not in " ".join(narration_only)
    assert "sidechaincompress" in " ".join(with_music)
    assert str(music) in with_music
    assert all(isinstance(arg, str) for arg in with_music)
    assert narration_only[narration_only.index("-ar") + 1] == "16000"
    # The gain is a measured number, not a constant: it appears in the argv that ships.
    assert "volume=12.50dB" in " ".join(narration_only)
    # A fixed loudnorm pass is what failed to reach -16 LUFS; it must not come back.
    assert "loudnorm" not in " ".join(narration_only)


def test_pcm_concat_accepts_scene_wavs_with_different_frame_counts(tmp_path: Path):
    from packages.core.media.tts import _concat_pcm_wavs

    inputs = [tmp_path / "one.wav", tmp_path / "two.wav"]
    for frames, path in zip((160, 320), inputs, strict=True):
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x00\x00" * frames)

    output = tmp_path / "joined.wav"
    _concat_pcm_wavs(inputs, output)

    with wave.open(str(output), "rb") as joined:
        assert joined.getnframes() == 480


@pytest.mark.serial
def test_real_sapi_boundaries_preserve_source_punctuation(tmp_path: Path):
    words, _ = synthesize_sapi(
        "Halo dunia. Apa kabar?",
        tmp_path / "punctuation.wav",
        voice="system-default",
    )

    assert [word.text for word in words] == ["Halo", "dunia.", "Apa", "kabar?"]


@pytest.mark.serial
def test_real_sapi_boundaries_never_emit_empty_text_for_alphanumeric_token(tmp_path: Path):
    words, _ = synthesize_sapi(
        "Pembuka ec839dc444b9.",
        tmp_path / "alphanumeric.wav",
        voice="system-default",
    )

    assert all(word.text for word in words)


def test_voice_selector_cannot_be_parsed_as_a_powershell_argument(tmp_path: Path):
    for voice in ("-NoProfile", 'Zira" ; Remove-Item C:\\ -Recurse', "a\nb", "x" * 101):
        with pytest.raises(ValueError, match="voice"):
            synthesize_sapi("text", tmp_path / "scene.wav", voice=voice)


def test_boundaries_are_clamped_to_the_measured_duration():
    raw = [
        {"text": "Halo", "startMs": 0, "endMs": 430},
        {"text": "dunia.", "startMs": 430, "endMs": 4_121},
    ]

    words = parse_boundaries(raw, duration_ms=4_120)

    assert words[-1].end_ms == 4_120
    assert [word.text for word in words] == ["Halo", "dunia."]


def test_boundaries_outside_the_measured_duration_are_dropped():
    raw = [
        {"text": "Halo", "startMs": 0, "endMs": 430},
        {"text": "late", "startMs": 4_500, "endMs": 4_600},
    ]

    assert [word.text for word in parse_boundaries(raw, duration_ms=4_120)] == ["Halo"]


def test_sapi_uses_noninteractive_profile_free_powershell(tmp_path: Path, monkeypatch):
    output = tmp_path / "scene.wav"
    seen: list[str] = []

    def fail(argv, **kwargs):
        seen.extend(argv)
        return subprocess.CompletedProcess(argv, 1, "", "stop")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError):
        synthesize_sapi("text", output, voice="system-default", script_path=tmp_path / "tts.ps1")

    assert seen[1:4] == ["-NoLogo", "-NoProfile", "-NonInteractive"]


def test_loudness_parser_reports_measured_not_target_value():
    log = 'prefix\n{\n  "input_i" : "-17.23",\n  "target_offset" : "1.20"\n}\nsuffix'
    assert parse_loudness_lufs(log) == -17.23
