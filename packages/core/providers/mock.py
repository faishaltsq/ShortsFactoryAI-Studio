"""Deterministic offline provider.

Two jobs: exercise the whole pipeline with no network, and make tests reproducible. Output is
seeded by the prompt hash, so the same input always produces the same text — a mock that varies is
a mock that makes flaky tests.

A mock provider is never a silent fallback. A live job that cannot reach a provider fails; only a
job created in explicit mock mode may use this.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .base import Health, ProviderResult, ResolvedCall, Usage, VisionImage, VisionUnsupported, now_ms

_TASKS = ("script", "review", "storyboard", "research", "metadata", "claim", "motion", "vision")

#: The shortest scene the mock script can produce once the audio stage has re-timed it, in frames.
#: Derived from a real render: the mock segments are 21-23 characters and SAPI's default voice speaks
#: them in 3.70-4.25 s, so the floor is 3.7 s = 111 frames at 30 fps. The ceiling below is set at
#: 90 (3.0 s) so a slightly faster voice cannot push a declared beat past its scene's end.
MOCK_BEAT_CEILING_FRAMES = 90

#: Three scenes, three worlds, three distinct rendered shots, one character with a visible
#: action. The previous fixture was three copies of one static desert scene, which is a slideshow:
#: a creative gate that accepted it would be measuring nothing. Every cue below is from the
#: renderer's own vocabulary (`packages/video/src/scene-data.ts`, `character/ids.ts`) because
#: `validateSceneData` throws on anything else at render time.
#:
#: Each world also declares a **camera** and **beats**, which are no longer decorative: the adapter
#: forwards both (`packages/video/src/product-adapter.ts`), `src/camera.ts` turns the camera into a
#: stage transform and `src/motion-beats.ts` turns each beat into a pose/gesture/expression the rig
#: performs. `data.shots[]` is kept because it is the renderer's own vocabulary and still selects
#: the shot and its cut; a declared camera takes over the *movement* only.
#:
#: Beat subjects are real names: `sc1`/`sc2` name the scene's title element (so the beat is about
#: that line) and `sc3` names the actor selector `actor:0`, which is the explicit form.
_MOCK_WORLDS: tuple[dict[str, Any], ...] = (
    {
        "setting": "desert",
        "timeOfDay": "dusk",
        "shot": {"framing": "wide", "camera": "pushIn", "weight": 1},
        "pose": "stand",
        "facing": "right",
        "expression": "curious",
        "motion": {"preset": "enter", "durationInFrames": 24, "intensity": 0.5},
        "camera": {"shot": "wide", "move": "push", "amplitude": 0.1, "ease": "power2.out"},
        # Mid-scene `action`: the character goes from `stand` to `point` and the pose change is
        # visible for the rest of the scene. This is the Phase 2 exit criterion.
        #
        # Beat frames are absolute and must survive the audio re-time. `update_storyboard_from_audio`
        # rewrites every scene's `durationInFrames` from measured narration, and the mock script's
        # segments are 21-23 characters — 3.7-4.3 s, i.e. 111-128 frames at 30 fps, against the 300
        # the storyboard declares. A beat authored against the declared timeline (the old fixture had
        # one at 150) is past the retimed end and disappears without a word.
        #
        # So every beat here sits inside `MOCK_BEAT_CEILING_FRAMES`, the shortest scene this script
        # can produce at SAPI's default rate. `tests/test_mock_storyboard.py` asserts that, and
        # `planBeats` reports anything past the end in `BeatPlan.dropped` instead of dropping it.
        "beats": [
            {"atFrame": 0, "kind": "enter", "subject": "TITLE"},
            {"atFrame": 30, "kind": "action", "subject": "TITLE"},
            {"atFrame": 66, "kind": "emphasis", "subject": "TITLE"},
        ],
    },
    {
        "setting": "city",
        "timeOfDay": "night",
        "shot": {"framing": "medium", "camera": "panLeft", "weight": 1},
        "pose": "point",
        "facing": "left",
        "expression": "determined",
        "gesture": "pointForward",
        "motion": {"preset": "gesture", "durationInFrames": 30, "intensity": 0.7},
        "camera": {"shot": "medium", "move": "pan", "amplitude": 0.12, "ease": "sine.inOut"},
        "beats": [
            {"atFrame": 0, "kind": "enter", "subject": "TITLE"},
            {"atFrame": 48, "kind": "reveal", "subject": "TITLE"},
        ],
    },
    {
        "setting": "ocean",
        "timeOfDay": "dawn",
        "shot": {"framing": "close", "camera": "pullOut", "weight": 1},
        "pose": "reach",
        "facing": "right",
        "expression": "happy",
        "gesture": "openPalm",
        "motion": {"preset": "react", "durationInFrames": 20, "intensity": 0.6},
        "camera": {"shot": "close", "move": "pull", "amplitude": 0.08, "ease": "power1.out"},
        "beats": [
            {"atFrame": 0, "kind": "enter", "subject": "actor:0"},
            {"atFrame": 42, "kind": "emphasis", "subject": "actor:0"},
        ],
    },
)


def mock_storyboard(*, seed: str = "demo", frames_per_scene: int = 300) -> dict[str, Any]:
    """The storyboard the mock provider serves, and the one the regression tests assert on.

    One definition, so the fixture the pipeline renders and the fixture the tests prove cannot
    drift apart. Text stays well inside the 42 chars/s budget; the character appears in every
    scene with the same id so `character_consistency` has something real to resolve.
    """
    scenes: list[dict[str, Any]] = []
    cursor = 0
    for index, world in enumerate(_MOCK_WORLDS, start=1):
        actor: dict[str, Any] = {
            "character": "maya",
            "pose": world["pose"],
            "x": 0.5 if index != 2 else 0.42,
            "ground": 0.72,
            "scale": 1,
            "facing": world["facing"],
            "tone": "primary",
            "silhouette": False,
            "expression": world["expression"],
            "motion": dict(world["motion"]),
        }
        if "gesture" in world:
            actor["gesture"] = world["gesture"]
        title_id = f"t{index}"
        segment_text = f"Pembuka {seed}." if index == 1 else (
            f"Isi utama {seed}." if index == 2 else f"Penutup {seed}."
        )
        scenes.append(
            {
                "sceneId": f"sc{index}",
                "template": "IllustratedStory",
                "segment": f"s{index}",
                "startFrame": cursor,
                "durationInFrames": frames_per_scene,
                "assetRefs": ["character:maya", f"bg:{world['setting']}"],
                "text": [
                    {
                        "id": title_id,
                        "text": f"{segment_text} Adegan {index}."[:60],
                        "role": "title",
                        "atFrame": 0,
                    }
                ],
                # Every non-static move names the title element it is about, which is what
                # `SceneSpec._camera_target_exists` demands. `shot` here and `data.shots[].framing`
                # agree on purpose: the declared shot sets the base scale, the shot table sets the
                # cut, and a disagreement would mean two framings for one scene.
                "camera": {**world["camera"], "target": title_id},
                "motion": {
                    "energy": 0.55,
                    "continuity": "cut",
                    # Beats are scene-local; `frames_per_scene // 2` is the mid-scene accent that
                    # a 30 fps render puts at the halfway mark of the picture.
                    "beats": [
                        {**beat, "subject": title_id if beat["subject"] == "TITLE" else beat["subject"]}
                        for beat in world["beats"]
                    ],
                },
                "transition": {"kind": "cut", "frames": 0},
                # `data` is what the renderer reads: `IllustratedStory` draws from
                # `setting`/`timeOfDay`/`actors`/`shots`. The declared camera above owns the
                # movement; `shots[]` still selects the shot and its cut.
                "data": {
                    "setting": world["setting"],
                    "timeOfDay": world["timeOfDay"],
                    "actors": [actor],
                    "props": [],
                    "fx": [],
                    "shots": [dict(world["shot"])],
                },
            }
        )
        cursor += frames_per_scene
    return {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "dusk",
        "scenes": scenes,
        "subtitles": [],
    }



class MockProvider:
    name = "mock"
    transport = "mock"

    def __init__(self, *, delay_ms: int = 0) -> None:
        self.delay_ms = delay_ms

    def health(self, call: ResolvedCall) -> Health:  # noqa: ARG002 - protocol shape
        return Health.up(detail="mock")

    def list_models(self, call: ResolvedCall) -> list[str]:  # noqa: ARG002
        return ["mock-1"]

    def complete(
        self, call: ResolvedCall, *, system: str, user: str, task: str
    ) -> ProviderResult:
        started = now_ms()
        # One seed per *job*, not per call. The storyboard prompt embeds the script, so hashing
        # the prompt here gave the storyboard a different seed than the script that produced it —
        # and a render then showed scene titles quoting a job id that matched nothing on screen.
        # The script's segments are the content a viewer must agree with, so the seed is read out
        # of the prompt the script agent actually saw.
        seed = self._seed_for(task, user)
        content = json.dumps(self._payload(task, seed, user), ensure_ascii=False)
        if self.delay_ms:
            import time

            time.sleep(self.delay_ms / 1000)
        return ProviderResult(
            content=content,
            provider=call.provider or "mock",
            model=call.model or "mock-1",
            usage=Usage(prompt_tokens=len(user) // 4, completion_tokens=len(content) // 4),
            elapsed_ms=max(0, now_ms() - started),
            raw={"mock": True, "seed": seed},
        )

    def complete_vision(
        self,
        call: ResolvedCall,  # noqa: ARG002 - protocol shape
        *,
        system: str,  # noqa: ARG002
        user: str,  # noqa: ARG002
        task: str,  # noqa: ARG002
        images: list[VisionImage],  # noqa: ARG002
    ) -> ProviderResult:
        """The mock cannot see, so it refuses instead of answering.

        There is a ``vision`` branch in ``_payload`` that returns a canned pass. It exists for a
        caller that constructs the payload directly; the transport never reaches it, because
        ``vision`` is not in this provider's declared capabilities and this method raises.
        """
        raise VisionUnsupported("mock")

    @staticmethod
    def _seed_for(task: str, user: str) -> str:
        """Derive the mock's deterministic seed for one call.

        For the storyboard task the user prompt carries the script JSON; reusing the seed the
        *script* call derived keeps every artifact in a job quoting the same identifier. Any other
        task keeps the original prompt-hash behaviour.
        """
        import re as _re

        if task.startswith("storyboard"):

            match = _re.search(r"Pembuka ([0-9a-f]{12})\.", user)
            if match:
                return match.group(1)
        return hashlib.sha256(f"{task}\x00mock-system\x00{user}".encode()).hexdigest()[:12]

    @staticmethod
    def _payload(task: str, seed: str, user: str) -> dict[str, Any]:
        if task.startswith("script"):
            return {
                "hook": f"Fakta singkat tentang {seed}",
                "segments": [
                    {"id": "s1", "text": f"Pembuka {seed}.", "purpose": "hook"},
                    {"id": "s2", "text": f"Isi utama {seed}.", "purpose": "build"},
                    {"id": "s3", "text": f"Penutup {seed}.", "purpose": "payoff"},
                ],
                "cta": "Ikuti untuk bagian berikutnya.",
                "content_kind": "fictional",
            }
        if task.startswith("review"):
            return {
                "verdict": "accept",
                "scores": {"hook": 4, "coherence": 4, "pacing": 4, "originality": 4, "payoff": 4},
                "findings": [],
            }
        if task.startswith("research") or task.startswith("topic"):
            return {
                "topic": f"topik-{seed}",
                "content_kind": "fictional",
                "candidates": [{"title": f"Kandidat {seed}", "angle": "sudut", "score": 0.8}],
                "sources": [],
                "claims": [],
            }
        if task.startswith("metadata"):
            return {
                "title": f"Judul {seed}",
                "description": f"Deskripsi untuk {seed}.",
                "tags": ["shorts", "animasi"],
                "category_id": "22",
                "made_for_kids": False,
                "synthetic_media": True,
            }
        if task.startswith("storyboard"):
            return mock_storyboard(seed=seed)
        if task.startswith("motion"):
            return {
                "schema_version": 1,
                "renderer": "remotion",
                "style_brief": {
                    "palette": ["#2f6f6a", "#f4bc68", "#e8e0d4"],
                    "fonts": ["Archivo", "IBM Plex Mono"],
                    "signature_move": "push into the subject on each reveal",
                },
                "scenes": [],
                "anti_patterns_checked": ["static_slideshow", "generic_fade", "text_wall"],
            }
        if task.startswith("vision"):
            return {"status": "passed", "findings": [], "frames_inspected": 0}
        return {"seed": seed, "echo_len": len(user), "tasks": list(_TASKS)}
