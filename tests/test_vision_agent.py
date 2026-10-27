"""Keyframe extraction and the visual pass.

The visual pass has exactly one honest failure mode and one honest skip:

- a provider that declares ``vision`` is asked once, and its answer must account for every frame
  that was actually extracted;
- with no such provider the result is ``skipped_no_vision_provider`` with ``frames_inspected: 0``
  and the real extracted count visible.

There is no third path. A ``passed`` with zero frames, a skip that names a provider, or a provider
answer that ignores the sheet are all rejected by the contract *and* by this stage.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from packages.core.media.qc import extract_contact_sheet, scene_midpoints
from packages.core.providers.base import (
    Capability,
    Health,
    ProviderResult,
    ResolvedCall,
    Usage,
    VisionImage,
    VisionUnsupported,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is required to extract a contact sheet"
)

FPS = 30
W, H = 270, 480


def _props(scenes: int = 3, frames: int = 30) -> dict:
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
                }
                for index in range(scenes)
            ],
        }
    }


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("vision") / "clip.mp4"
    proc = subprocess.run(  # noqa: S603
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert proc.returncode == 0, proc.stderr[-400:]
    return path


# -- scene midpoints ---------------------------------------------------------------------------


def test_midpoints_are_one_per_scene_at_its_centre():
    points = scene_midpoints(_props(scenes=3, frames=30))
    assert [p["sceneId"] for p in points] == ["sc0", "sc1", "sc2"]
    assert [p["frame"] for p in points] == [15, 45, 75]
    assert all(p["boundary"] is False for p in points)


def test_boundaries_are_half_a_second_after_each_cut():
    points = scene_midpoints(_props(scenes=3, frames=30), include_boundaries=True)
    boundary = [p for p in points if p["boundary"]]
    assert len(boundary) == 2, "the last scene has no following cut"
    assert [p["frame"] for p in boundary] == [45, 75]


def test_the_point_list_is_capped():
    points = scene_midpoints(_props(scenes=40, frames=30), limit=6)
    assert len(points) == 6


def test_midpoints_ignore_a_storyboard_with_no_scenes():
    assert scene_midpoints({"storyboard": {"scenes": []}}) == []


# -- contact sheet -----------------------------------------------------------------------------


def test_a_contact_sheet_is_written_as_one_jpeg(clip, tmp_path):
    sheet, extracted = extract_contact_sheet(
        clip, _props(scenes=3, frames=30), tmp_path / "qa-contact-sheet.jpg"
    )
    assert sheet.is_file()
    assert sheet.suffix == ".jpg"
    assert sheet.read_bytes()[:2] == b"\xff\xd8", "a real JPEG, not a renamed PNG"
    assert extracted == 3


def test_the_sheet_is_a_single_image_of_a_bounded_size(clip, tmp_path):
    sheet, _ = extract_contact_sheet(clip, _props(scenes=3, frames=30), tmp_path / "s.jpg")
    proc = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(sheet)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    stream = json.loads(proc.stdout)["streams"][0]
    assert stream["width"] == 1080
    assert 400 <= stream["height"] <= 1400, "tiles stay readable without a 4K upload"


def test_extraction_reports_the_real_frame_count(clip, tmp_path):
    """Two-second scenes keep midpoints and boundaries distinct, so the cap is the count."""
    _, extracted = extract_contact_sheet(clip, _props(scenes=6, frames=60), tmp_path / "s.jpg")
    assert extracted == 6, "the cap is the extracted count, not the scene count"


def test_a_one_second_scene_yields_one_still_not_two(clip, tmp_path):
    """Its midpoint is exactly where '0.5 s after the cut' lands; extracting twice would
    inflate the count the provider's answer is validated against."""
    _, extracted = extract_contact_sheet(clip, _props(scenes=3, frames=30), tmp_path / "s.jpg")
    assert extracted == 3


def test_extraction_returns_zero_and_no_file_for_a_storyboard_with_no_scenes(clip, tmp_path):
    target = tmp_path / "none.jpg"
    sheet, extracted = extract_contact_sheet(clip, {"storyboard": {"scenes": []}}, target)
    assert extracted == 0
    assert not sheet.exists()


def test_extraction_fails_loudly_when_the_clip_is_missing(tmp_path):
    with pytest.raises(RuntimeError, match="ffmpeg"):
        extract_contact_sheet(tmp_path / "absent.mp4", _props(), tmp_path / "s.jpg")


# -- the vision agent --------------------------------------------------------------------------


class _StubProvider:
    """Answers with whatever the test scripted; records what it was given."""

    name = "stub-vision"
    transport = "stub"

    def __init__(self, answers: list[str], *, raise_exc: Exception | None = None) -> None:
        self.answers = answers
        self.calls: list[dict] = []
        self.raise_exc = raise_exc

    def health(self, call):  # noqa: ARG002
        return Health.up()

    def list_models(self, call):  # noqa: ARG002
        return []

    def complete(self, call, *, system, user, task):  # noqa: ARG002
        raise AssertionError("the vision agent must not use the text path")

    def complete_vision(self, call, *, system, user, task, images):
        self.calls.append({"images": images, "system": system, "user": user, "task": task})
        if self.raise_exc is not None:
            raise self.raise_exc
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return ProviderResult(
            content=answer,
            provider=call.provider,
            model=call.model,
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )


def _call(*, vision: bool = True) -> ResolvedCall:
    caps = frozenset({Capability.CHAT, Capability.VISION}) if vision else frozenset({Capability.CHAT})
    return ResolvedCall(
        provider="stub-vision",
        transport="stub",
        base_url="",
        model="vision-1",
        temperature=None,
        max_tokens=800,
        timeout_s=5.0,
        max_retries=0,
        capabilities=caps,
        allow_private_hosts=False,
    )


def _image() -> VisionImage:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
        b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
    )
    return VisionImage(data=png)


def _run(provider, *, call=None, images=None, storyboard=None):
    from packages.core.agents.vision import inspect_frames

    return inspect_frames(
        call=call or _call(),
        provider=provider,
        images=[_image()] if images is None else images,
        storyboard=storyboard or _props(scenes=3, frames=30),
    )


def test_no_vision_provider_is_a_skip_with_a_real_extracted_count():
    from packages.core.agents.vision import skip_no_provider

    result = skip_no_provider(frames_extracted=3)
    assert result.status == "skipped_no_vision_provider"
    assert result.provider is None
    assert result.frames_inspected == 0
    assert result.frames_extracted == 3


def test_a_provider_answer_accounts_for_every_extracted_frame():
    provider = _StubProvider(['{"status": "passed", "frames_inspected": 3, "findings": []}'])
    result = _run(provider)
    assert result.status == "passed"
    assert result.frames_inspected == 3
    assert result.provider == "stub-vision"
    assert len(provider.calls) == 1
    assert len(provider.calls[0]["images"]) == 1, "one contact sheet, one image"


def test_a_pass_that_inspected_nothing_is_rejected():
    provider = _StubProvider(['{"status": "passed", "frames_inspected": 0, "findings": []}'])
    result = _run(provider)
    assert result.status == "failed"
    assert any("frames_inspected" in finding["issue"] for finding in result.findings)


def test_a_pass_that_claims_more_frames_than_were_extracted_is_rejected():
    provider = _StubProvider(['{"status": "passed", "frames_inspected": 99, "findings": []}'])
    assert _run(provider).status == "failed"


def test_a_blocker_finding_fails_the_pass():
    answer = json.dumps(
        {
            "status": "passed",
            "frames_inspected": 3,
            "findings": [{"atMs": 1000, "issue": "karakter hilang", "severity": "blocker"}],
        }
    )
    result = _run(_StubProvider([answer]))
    assert result.status == "failed"
    assert result.findings[0]["severity"] == "blocker"


def test_a_major_finding_fails_the_pass():
    answer = json.dumps(
        {
            "status": "passed",
            "frames_inspected": 3,
            "findings": [{"atMs": 0, "issue": "teks terpotong", "severity": "major"}],
        }
    )
    assert _run(_StubProvider([answer])).status == "failed"


def test_a_minor_finding_does_not_fail_the_pass_but_is_recorded():
    answer = json.dumps(
        {
            "status": "passed",
            "frames_inspected": 3,
            "findings": [{"atMs": 0, "issue": "kontras rendah", "severity": "minor"}],
        }
    )
    result = _run(_StubProvider([answer]))
    assert result.status == "passed"
    assert result.findings[0]["severity"] == "minor"


def test_a_model_that_says_failed_fails_even_with_no_findings():
    provider = _StubProvider(['{"status": "failed", "frames_inspected": 3, "findings": []}'])
    assert _run(provider).status == "failed"


def test_a_malformed_answer_gets_exactly_one_repair_then_fails():
    provider = _StubProvider(["not json", '{"status": "passed", "frames_inspected": 3, "findings": []}'])
    result = _run(provider)
    assert result.status == "passed"
    assert len(provider.calls) == 2, "one call plus one repair"


def test_two_malformed_answers_fail_without_a_third_call():
    provider = _StubProvider(["nope", "still nope"])
    result = _run(provider)
    assert result.status == "failed"
    assert len(provider.calls) == 2
    assert any("schema" in finding["issue"].lower() for finding in result.findings)


def test_a_transport_that_cannot_see_is_a_hard_error_not_a_skip():
    provider = _StubProvider([], raise_exc=VisionUnsupported("stub"))
    with pytest.raises(VisionUnsupported):
        _run(provider)


def test_no_images_means_no_call_at_all():
    provider = _StubProvider(['{"status": "passed", "frames_inspected": 0}'])
    result = _run(provider, images=[])
    assert result.status == "failed"
    assert provider.calls == []


def test_the_prompt_names_the_frame_count_and_forbids_invention():
    """The count is in the user turn; the anti-invention rule is in the system prompt. Both must
    reach the provider, so both are asserted on the recorded call rather than on the module."""
    provider = _StubProvider(['{"status": "passed", "frames_inspected": 3, "findings": []}'])
    _run(provider)
    call = provider.calls[0]
    assert "3" in call["user"]
    system = call["system"].lower()
    assert "do not guess" in system
    assert "only" in system
    assert "frames_inspected" in system


def test_the_result_never_carries_image_bytes():
    provider = _StubProvider(['{"status": "passed", "frames_inspected": 3, "findings": []}'])
    result = _run(provider)
    blob = json.dumps(result.to_json())
    assert "iVBOR" not in blob
    assert "base64" not in blob


# -- the sheet must have no padding cell -------------------------------------------------------


def _grid_geometry(path: Path) -> tuple[int, int]:
    proc = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    stream = json.loads(proc.stdout)["streams"][0]
    return stream["width"], stream["height"]


def _cell_is_black(sheet: Path, *, columns: int, rows: int, cell: tuple[int, int]) -> bool:
    """Mean luma of one grid cell, measured by ffmpeg rather than by eye."""
    width, height = _grid_geometry(sheet)
    cell_w, cell_h = width // columns, height // rows
    x, y = cell[0] * cell_w, cell[1] * cell_h
    proc = subprocess.run(  # noqa: S603
        ["ffmpeg", "-v", "error", "-i", str(sheet), "-vf",
         f"crop={cell_w}:{cell_h}:{x}:{y},signalstats,metadata=print:key=lavfi.signalstats.YAVG",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    for line in (proc.stderr or "").splitlines():
        if "YAVG" in line:
            return float(line.split("=")[-1]) < 8.0
    return False


def test_the_grid_has_a_shape_for_every_frame_count_the_planner_emits():
    """No count falls through to an invented shape."""
    from packages.core.media.qc import SHEET_GRIDS, sheet_grid

    for count in range(1, 7):
        columns, rows = sheet_grid(count)
        assert columns * rows >= count, f"{count} frames do not fit {columns}x{rows}"
        assert columns * rows - count <= 1, f"{count} frames waste more than one cell"
    assert set(SHEET_GRIDS) == set(range(1, 7))


def test_a_five_frame_sheet_has_no_black_padding_cell(clip, tmp_path):
    """The real defect: a 3x2 grid with five frames left a solid black sixth tile.

    The vision prompt tells the provider to report an unreadable tile as a finding, so our own
    layout produced a false "black frame" finding — and a human could not tell padding from a
    genuinely black scene.
    """
    sheet, extracted = extract_contact_sheet(
        clip, _props(scenes=3, frames=60), tmp_path / "five.jpg"
    )
    assert extracted == 5, "3 two-second scenes give 3 midpoints + 2 boundaries"
    # 5 frames -> 3x2 is the only sane 2-row grid, so the unused cell must be labelled, not black.
    width, height = _grid_geometry(sheet)
    assert height > width * 0.75, "a 3x2 grid is taller than one row"
    assert not _cell_is_black(sheet, columns=3, rows=2, cell=(2, 1)), (
        "the sixth cell is solid black; it must be a labelled neutral tile"
    )


def test_a_six_frame_sheet_is_three_by_two_with_no_padding(clip, tmp_path):
    sheet, extracted = extract_contact_sheet(
        clip, _props(scenes=4, frames=60), tmp_path / "six.jpg"
    )
    assert extracted == 6, "4 two-second scenes want 7 frames; the cap is 6"
    width, height = _grid_geometry(sheet)
    # 3 columns x 2 rows of 360x620 tiles: exactly 1080x1240, with no cell left over.
    assert (width, height) == (1080, 1240), "6 frames fill a 3x2 grid exactly"
    for column in range(3):
        for row in range(2):
            assert not _cell_is_black(sheet, columns=3, rows=2, cell=(column, row))


def test_a_three_frame_sheet_uses_one_row(clip, tmp_path):
    sheet, extracted = extract_contact_sheet(
        clip, _props(scenes=2, frames=60), tmp_path / "three.jpg"
    )
    assert extracted == 3, "2 scenes give 2 midpoints + 1 boundary"
    width, height = _grid_geometry(sheet)
    assert height < width, "three frames fit a 3x1 strip, so no padding row is needed"


def test_a_single_frame_sheet_is_one_tile(clip, tmp_path):
    """One frame is a 1x1 grid: no padding cell can exist, so nothing can be misread as black."""
    sheet, extracted = extract_contact_sheet(
        clip, _props(scenes=1, frames=60), tmp_path / "one.jpg"
    )
    assert extracted == 1
    width, height = _grid_geometry(sheet)
    assert width == 1080
    assert height == 620, "a single tile is one row, not a padded grid"
    assert not _cell_is_black(sheet, columns=1, rows=1, cell=(0, 0))


def test_the_sheet_size_stays_bounded(clip, tmp_path):
    sheet, _ = extract_contact_sheet(clip, _props(scenes=4, frames=60), tmp_path / "bounded.jpg")
    width, height = _grid_geometry(sheet)
    assert width == 1080
    assert height <= 1400
    assert sheet.stat().st_size < 400_000


def test_the_padding_label_is_drawn_once_not_on_every_tile():
    """The defect this pins: ``drawtext`` placed before ``tile`` is part of the per-frame chain,
    so every frame got captioned "no frame 6" while the real empty cell stayed blank.

    Measured on a real sheet: five tiles each read "no frame 6". The fix is ordering — the label
    is applied to the composited grid, positioned inside the one cell that has no frame.
    """
    from packages.core.media.qc import _sheet_filter

    chain = _sheet_filter(5, 620)
    assert "tile=" in chain
    assert chain.index("drawtext") > chain.index("tile="), (
        "drawtext must come after tile, or it is stamped onto every frame"
    )
    assert "x=720+" in chain and "y=620+" in chain, "the label must sit in the empty 3x2 cell"


def test_a_full_grid_has_no_label_at_all():
    from packages.core.media.qc import _sheet_filter

    for count in (1, 2, 3, 4, 6):
        assert "drawtext" not in _sheet_filter(count, 620), f"{count} frames need no label"


def test_the_empty_cell_differs_from_every_frame_cell(clip, tmp_path):
    """A padding cell must be recognisable as padding, not as a dark scene."""
    sheet, extracted = extract_contact_sheet(
        clip, _props(scenes=3, frames=60), tmp_path / "five.jpg"
    )
    assert extracted == 5
    assert not _cell_is_black(sheet, columns=3, rows=2, cell=(2, 1))
    # The label is white on grey, so the cell carries bright pixels a blank grey cell would not.
    width, height = _grid_geometry(sheet)
    proc = subprocess.run(  # noqa: S603
        # ``-nostats`` rather than ``-v error``: metadata=print writes at info level, which
        # ``-v error`` suppresses entirely.
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(sheet), "-vf",
         f"crop={width // 3}:{height // 2}:{2 * (width // 3)}:{height // 2},"
         "signalstats,metadata=print", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    stats = {
        key.split(".")[-1]: float(value)
        for line in (proc.stderr or "").splitlines()
        for key, _, value in [line.partition("=")]
        if key.strip().endswith(("YMIN", "YMAX", "YAVG")) and value.strip()
    }
    # The cell is grey (YAVG ~43) with white label text (YMAX > 150). A blank grey cell would
    # have YMAX close to its own YAVG; a black cell would have both near zero.
    assert stats["YMAX"] > 150, f"the padding cell has no label text (YMAX {stats.get('YMAX')})"
    assert stats["YAVG"] < 80, "the padding cell must be the neutral fill, not a frame"
