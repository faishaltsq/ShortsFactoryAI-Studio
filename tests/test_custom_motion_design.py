"""Custom-motion uses the shipped design modules and loads vendored fonts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.core.media import render


@pytest.mark.parametrize("registered", [False, True])
def test_custom_motion_bootstraps_fonts_and_design_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registered: bool,
) -> None:
    video_dir = tmp_path / "video"
    cli = video_dir / render.CLI_RELATIVE
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    modules = {
        "fonts.ts": "export const loaded = true;",
        "types.ts": "export interface ThemeSpec {}",
        "themes/brand.ts": "export const brand = true;",
        "themes/tokens.ts": "export const tokens = true;",
        "themes/type.ts": "export const typeScale = true;",
        "components/Typography.tsx": "export const Title = () => null;",
        "components/motion.ts": "export const motion = true;",
    }
    for name, content in modules.items():
        path = video_dir / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    font = video_dir / "public/fonts/example.woff2"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"test-font")
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    root = code_dir / "RootComposition.tsx"
    root.write_text(
        "import React from 'react';\nexport const RootComposition = () => <div />;\n"
        + ("registerRoot(RootComposition);\n" if registered else ""),
        encoding="utf-8",
    )
    props = tmp_path / "props.json"
    props.write_text(json.dumps({"storyboard": {"scenes": [{"durationInFrames": 2}]}}))
    output = tmp_path / "output.mp4"
    calls: list[list[str]] = []

    class Process:
        pid = 0
        returncode = 0

        def communicate(self, *, timeout: int) -> tuple[str, str]:
            output.write_bytes(b"unit-test-output-not-real-video")
            return "", ""

    def popen(argv: list[str], **kwargs: Any) -> Process:
        calls.append(argv)
        assert "import './fonts';" in root.read_text(encoding="utf-8")
        for name, content in modules.items():
            assert (code_dir / name).read_text(encoding="utf-8") == content
        assert (code_dir / "public/fonts/example.woff2").read_bytes() == b"test-font"
        assert f"--public-dir={code_dir.resolve() / 'public'}" in argv
        return Process()

    monkeypatch.setattr(render.shutil, "which", lambda _: "node")
    monkeypatch.setattr(render.subprocess, "Popen", popen)
    monkeypatch.setattr(render.WindowsJobSandbox, "assign_process", lambda *_: True)
    for _ in range(2):
        render.render_custom_motion(
            video_dir=video_dir, code_dir=code_dir, props_path=props, out_path=output,
        )
    assert len(calls) == 2
    assert root.read_text(encoding="utf-8").count("import './fonts';") == 1


def test_custom_motion_renders_with_loaded_vendored_fonts(tmp_path: Path) -> None:
    """Exercise the real bundler, browser font loading and encoded output, without providers."""
    import shutil

    video_dir = Path(__file__).resolve().parents[1] / "packages/video"
    if not shutil.which("node") or not shutil.which("ffprobe"):
        pytest.skip("requires Node and ffprobe")
    if not (video_dir / render.CLI_RELATIVE).is_file():
        pytest.skip("requires installed packages/video dependencies")
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    shutil.copy2(video_dir / "fixtures/custom-motion/RootComposition.tsx", code_dir)
    props = tmp_path / "props.json"
    props.write_text(
        json.dumps({"storyboard": {"scenes": [{"durationInFrames": 3}]}}), encoding="utf-8",
    )
    output = tmp_path / "proof.mp4"
    render.render_custom_motion(
        video_dir=video_dir, code_dir=code_dir, props_path=props,
        out_path=output, timeout_s=180,
    )
    probe = render.probe_media(output)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert int(video["nb_read_frames"]) == 3
    assert video["pix_fmt"] == "yuv420p"
