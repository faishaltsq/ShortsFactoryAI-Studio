"""The mock storyboard must be able to pass an honest creative gate.

The previous fixture was three identical scenes: one template, one setting, one `data.shots`
entry with `camera: "static"`, and no character cue. That is a slideshow, and the QC gate is
right to reject it — so the fixture, not the gate, is what changes.

These tests are deliberately written against the *rendered* vocabulary (`data.shots[]`,
`data.actors[]`), because that is the only thing the adapter forwards and the only thing a pixel
can contradict.
"""

from __future__ import annotations

import pytest

from packages.core.contracts.artifacts import StoryboardArtifact
from packages.core.contracts.base import validate_artifact
from packages.core.providers.mock import MockProvider, mock_storyboard

#: Mirrors `packages/video/src/scene-data.ts` and `character/ids.ts`. A cue outside these lists
#: throws in `validateSceneData`, so the fixture would fail at render time, not at QC time.
SETTINGS = {"space", "desert", "city", "ocean", "forest", "interior", "abstract"}
TIMES_OF_DAY = {"dawn", "day", "dusk", "night"}
FRAMINGS = {"wide", "medium", "close"}
CAMERA_MOVES = {"static", "pushIn", "pullOut", "panLeft", "panRight", "tiltUp", "handheld"}
POSES = {"stand", "point", "reach", "walk", "lookUp", "shrug", "sit"}
EXPRESSIONS = {"neutral", "curious", "happy", "surprised", "concerned", "determined", "thinking", "sad"}
GESTURES = {"none", "pointForward", "openPalm", "bothOpen", "wave", "think", "shrug"}
MOTION_PRESETS = {"idle", "talk", "walk", "gesture", "react", "enter", "poseChange"}


def _payload(seed: str = "demo") -> dict:
    """The dict the provider serialises. ``_payload`` is the one definition of the fixture."""
    return MockProvider._payload("storyboard", seed, "user")


def test_the_mock_storyboard_validates_as_a_storyboard_artifact():
    art = validate_artifact(StoryboardArtifact, mock_storyboard())
    assert len(art.scenes) >= 3


def test_the_mock_storyboard_has_three_distinct_rendered_worlds():
    storyboard = mock_storyboard()
    worlds = {
        (scene["template"], scene["data"]["setting"], scene["data"]["timeOfDay"])
        for scene in storyboard["scenes"]
    }
    assert len(worlds) == len(storyboard["scenes"]), f"worlds must differ per scene: {worlds}"


def test_the_mock_storyboard_has_distinct_rendered_shots():
    storyboard = mock_storyboard()
    shots = [
        (shot["framing"], shot["camera"])
        for scene in storyboard["scenes"]
        for shot in scene["data"]["shots"]
    ]
    assert len(set(shots)) == len(shots), f"every rendered shot must differ: {shots}"
    assert len(set(shots)) / len(shots) >= 0.5


def test_every_scene_cue_uses_the_renderer_vocabulary():
    for scene in mock_storyboard()["scenes"]:
        data = scene["data"]
        assert data["setting"] in SETTINGS, data["setting"]
        assert data["timeOfDay"] in TIMES_OF_DAY, data["timeOfDay"]
        for shot in data["shots"]:
            assert shot["framing"] in FRAMINGS, shot
            assert shot["camera"] in CAMERA_MOVES, shot
            assert 0.5 <= shot["weight"] <= 3.0, shot
        for actor in data["actors"]:
            assert actor["pose"] in POSES, actor
            if "expression" in actor:
                assert actor["expression"] in EXPRESSIONS, actor
            if "gesture" in actor:
                assert actor["gesture"] in GESTURES, actor
            if "motion" in actor:
                assert actor["motion"]["preset"] in MOTION_PRESETS, actor


def test_at_least_one_scene_renders_the_character():
    characters = [
        actor.get("character")
        for scene in mock_storyboard()["scenes"]
        for actor in scene["data"]["actors"]
    ]
    assert "maya" in characters, "the character-driven scene is the Phase 2 exit requirement"


def test_at_least_one_scene_shows_a_meaningful_action():
    """A pose change plus a gesture is an action; a static `stand` is a placeholder."""
    acted = [
        scene["sceneId"]
        for scene in mock_storyboard()["scenes"]
        if any(
            actor.get("gesture") not in (None, "none")
            or actor.get("motion", {}).get("preset") in {"gesture", "react", "walk", "poseChange"}
            or actor.get("pose") in {"point", "reach", "walk"}
            for actor in scene["data"]["actors"]
        )
    ]
    assert acted, "at least one scene must show a visible action"


def test_the_storyboard_carries_no_camera_move_that_the_renderer_cannot_honour():
    """A non-static move without a target is the "unmotivated camera movement" the brief forbids,
    and the adapter now re-checks it, so the fixture must not lean on the Python validator alone."""
    for scene in mock_storyboard()["scenes"]:
        camera = scene["camera"]
        if camera["move"] != "static":
            assert camera.get("target"), scene["sceneId"]
            assert camera["target"] in {t["id"] for t in scene["text"]}, scene["sceneId"]


def test_every_declared_camera_move_is_one_the_adapter_can_render():
    """The fixture must exercise the moves that actually reach a pixel, not just validate."""
    moves = [scene["camera"]["move"] for scene in mock_storyboard()["scenes"]]
    assert all(move in {"static", "push", "pull", "pan", "tilt", "orbit"} for move in moves), moves
    assert len(set(moves)) >= 3, f"the fixture should vary the camera, got {moves}"


def test_every_beat_subject_names_something_real():
    """A beat whose subject names nothing still performs (on the primary actor), but a fixture
    that relies on that fallback is not proving the resolution path works."""
    for scene in mock_storyboard()["scenes"]:
        ids = {element["id"] for element in scene["text"]}
        actors = len(scene["data"]["actors"])
        for beat in scene["motion"]["beats"]:
            subject = beat["subject"]
            selector = subject.startswith("actor:") and subject[6:].isdigit()
            assert subject in ids or selector, f"{scene['sceneId']}: {subject}"
            if selector:
                assert int(subject[6:]) < actors, f"{scene['sceneId']}: {subject} out of range"


def test_at_least_one_beat_lands_mid_scene_after_the_entrance():
    """The Phase 2 exit criterion, stated as a property of the fixture.

    A beat at frame 0 of kind `enter` is a transition: the actor is at zero opacity there, so a
    still taken at that frame is an empty stage. What has to exist is a *later* beat that changes
    the pose while the actor is already on screen.
    """
    mid_scene = [
        (scene["sceneId"], beat)
        for scene in mock_storyboard()["scenes"]
        for beat in scene["motion"]["beats"]
        if beat["atFrame"] > 0 and beat["kind"] != "exit"
    ]
    assert mid_scene, "no beat lands inside a scene after the entrance"
    assert any(beat["kind"] in {"action", "reveal"} for _, beat in mid_scene), (
        f"no mid-scene beat changes the pose, only accents: {mid_scene}"
    )


def test_every_beat_survives_the_audio_retime():
    """Beats are authored against the declared timeline; the audio stage rewrites it.

    ``update_storyboard_from_audio`` replaces each scene's ``durationInFrames`` with the measured
    narration length. The mock script's segments are 21-23 characters, which SAPI speaks in
    3.70-4.25 s — 111-128 frames at 30 fps against the 300 the storyboard declares. A beat at 150
    (the previous fixture) is therefore past the end of every real scene and vanishes silently.

    This asserts against the *measured* timings from a real render, and against the fixture's own
    ceiling, so neither a slower voice nor a future edit can quietly drop a beat.
    """
    from packages.core.media.render import update_storyboard_from_audio
    from packages.core.providers.mock import MOCK_BEAT_CEILING_FRAMES

    measured_ms = [(0, 3761), (3761, 8011), (8011, 11706)]
    audio = {
        "scenes": [
            {"sceneId": scene["sceneId"], "startMs": start, "endMs": end}
            for scene, (start, end) in zip(mock_storyboard()["scenes"], measured_ms, strict=True)
        ]
    }
    retimed = update_storyboard_from_audio(mock_storyboard(), audio)
    fps = retimed["fps"]
    for scene, (start, end) in zip(retimed["scenes"], measured_ms, strict=True):
        declared = scene["durationInFrames"]
        assert declared == -(-(end - start) * fps // 1000), scene["sceneId"]
        for beat in scene["motion"]["beats"]:
            assert beat["atFrame"] < declared, (
                f"{scene['sceneId']}: beat at {beat['atFrame']} is past the retimed duration "
                f"{declared} ({end - start} ms) and would be dropped"
            )
            assert beat["atFrame"] < MOCK_BEAT_CEILING_FRAMES, (
                f"{scene['sceneId']}: beat at {beat['atFrame']} exceeds the "
                f"{MOCK_BEAT_CEILING_FRAMES}-frame floor of the shortest possible scene"
            )


def test_the_provider_payload_is_the_same_storyboard():
    """The fixture is defined once. A second copy would drift from the QC-passing one."""
    assert _payload() == mock_storyboard()


def test_the_mock_storyboard_is_deterministic():
    assert mock_storyboard() == mock_storyboard()


def test_segment_ids_line_up_with_the_mock_script():
    script = MockProvider._payload("script", "seed", "user")
    segments = [segment["id"] for segment in script["segments"]]
    scenes = [scene["segment"] for scene in mock_storyboard()["scenes"]]
    assert scenes == segments, "every scene must render exactly one script segment, in order"


def test_scene_frames_are_contiguous_from_zero():
    cursor = 0
    for scene in mock_storyboard()["scenes"]:
        assert scene["startFrame"] == cursor
        cursor += scene["durationInFrames"]


def test_text_fits_the_density_budget():
    fps = mock_storyboard()["fps"]
    for scene in mock_storyboard()["scenes"]:
        seconds = scene["durationInFrames"] / fps
        chars = sum(len(element["text"]) for element in scene["text"])
        assert chars / seconds <= 42.0, f"{scene['sceneId']}: {chars} chars in {seconds:.1f}s"
        for element in scene["text"]:
            assert len(element["text"]) <= 120


# -- the renderer adapter must accept the fixture, not just the Python contract -----------------


def _node() -> str | None:
    import shutil

    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="node is required to exercise the real adapter")
def test_the_renderer_adapter_consumes_every_cue(tmp_path):
    """The Python contract validates the shape; only the adapter proves the renderer will draw it.

    ``validateSceneData`` throws on a cue outside its vocabulary, so a fixture that passes here
    cannot fail at render time for a vocabulary reason. It also confirms the adapter forwards
    ``data`` — which is where ``shots``, ``setting`` and the actor cues live.
    """
    import json
    import subprocess
    from pathlib import Path

    video = Path("packages/video").resolve()
    script = video / "scripts" / "_tmp_mock_adapter_check.mjs"
    storyboard_path = tmp_path / "storyboard.json"
    storyboard_path.write_text(json.dumps(mock_storyboard(), ensure_ascii=False), encoding="utf-8")
    script.write_text(
        "import {register} from 'node:module';\n"
        "register('./ts-resolve-hook.mjs', import.meta.url);\n"
        "const {adaptProductStoryboard} = await import('../src/product-adapter.ts');\n"
        "const {validateSceneData} = await import('../src/scene-data.ts');\n"
        "import {readFileSync} from 'node:fs';\n"
        "const adapted = adaptProductStoryboard(JSON.parse(readFileSync(process.argv[2], 'utf8')));\n"
        "for (const scene of adapted.scenes) validateSceneData(scene);\n"
        "console.log(JSON.stringify(adapted.scenes.map((s) => ({id: s.sceneId,"
        " shots: s.data.shots, setting: s.data.setting,"
        " actor: s.data.actors[0]?.character}))));\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(  # noqa: S603 - argv array, no shell
            ["node", str(script.resolve()), str(storyboard_path.resolve())],
            cwd=str(video),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        script.unlink(missing_ok=True)
    assert proc.returncode == 0, (proc.stderr or "")[-800:]
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert [item["setting"] for item in payload] == ["desert", "city", "ocean"]
    assert [item["actor"] for item in payload] == ["maya", "maya", "maya"]
    assert len({item["shots"][0]["camera"] for item in payload}) == 3
