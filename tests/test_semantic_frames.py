"""Fixture MP4 extraction; these pixels test provenance, not production/model quality."""

import subprocess

from packages.core.media import qc


def test_actual_mp4_samples_cover_every_scene_and_bind_real_png_bytes(tmp_path):
    video = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=90x160:rate=10:duration=2",
            "-c:v",
            "libx264",
            str(video),
        ],
        check=True,
    )
    props = {
        "fps": 10,
        "scenes": [
            {
                "sceneId": "s1",
                "segment": "n1",
                "startFrame": 0,
                "durationInFrames": 10,
                "motion": {"beats": [{"atFrame": 3, "kind": "action", "subject": "fixture"}]},
            },
            {"sceneId": "s2", "segment": "n2", "startFrame": 10, "durationInFrames": 10},
        ],
    }
    extract = getattr(qc, "extract_visual_evidence", None)
    assert extract is not None, "semantic QA needs actual per-scene rendered evidence"
    manifest = extract(
        video,
        props,
        tmp_path / "frames",
        job_id="fixture",
        render_sha256=qc.sha256_file(video),
        inputs_sha256="a" * 64,
        context_sha256="b" * 64,
        requirements={"s1": "Fixture first narration", "s2": "Fixture second narration"},
    )
    assert manifest.complete is True
    assert manifest.render_sha256 == qc.sha256_file(video)
    assert {2, 3, 4} <= {frame.frame for frame in manifest.frames if "action" in frame.roles}
    for scene in ["s1", "s2"]:
        samples = [frame for frame in manifest.frames if frame.scene_id == scene]
        assert {role for frame in samples for role in frame.roles} >= {"begin", "middle", "end", "action"}
    assert any("transition_before" in f.roles for f in manifest.frames)
    assert any("transition_after" in f.roles for f in manifest.frames)
    for frame in manifest.frames:
        image = tmp_path / "frames" / frame.file
        assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert qc.sha256_file(image) == frame.sha256
        assert frame.at_ms == frame.frame * 100
