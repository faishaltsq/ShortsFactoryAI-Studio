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

_TASKS = (
    "script",
    "review",
    "visual_plan",
    "creative_motion_brief",
    "storyboard",
    "research",
    "metadata",
    "claim",
    "motion",
    "motion_code",
    "vision",
)

#: The shortest scene the mock script can produce once the audio stage has re-timed it, in frames.
#: Derived from a real render: the mock segments are 21-23 characters and SAPI's default voice speaks
#: them in 3.70-4.25 s, so the floor is 3.7 s = 111 frames at 30 fps. The ceiling below is set at
#: 90 (3.0 s) so a slightly faster voice cannot push a declared beat past its scene's end.
MOCK_BEAT_CEILING_FRAMES = 90

#: Three scenes, three worlds, three distinct rendered shots, one character with a visible
#: action. The previous fixture was three copies of one static desert scene, which is a slideshow:
#: a creative gate that accepted it would be measuring nothing. Every cue below is from the
#: renderer's own vocabulary (`packages/video/src/scene-data.ts`, `art/object-kinds.ts`) because
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
        "environment": "dataCenter",
        "objects": [
            {"kind": "serverRack", "x": 0.5, "y": 0.36, "size": 0.4, "at": 0, "label": "Rak Server"},
            {"kind": "coolingFan", "x": 0.26, "y": 0.64, "size": 0.24, "at": 18},
            {"kind": "gpu", "x": 0.74, "y": 0.64, "size": 0.24, "at": 30},
        ],
        "camera": {"shot": "wide", "move": "push", "amplitude": 0.1, "ease": "power2.out"},
        "beats": [
            {"atFrame": 0, "kind": "enter", "subject": "TITLE"},
            {"atFrame": 30, "kind": "action", "subject": "TITLE"},
            {"atFrame": 66, "kind": "emphasis", "subject": "TITLE"},
        ],
    },
    {
        "environment": "circuit",
        "objects": [
            {"kind": "gpu", "x": 0.5, "y": 0.34, "size": 0.44, "at": 0, "label": "Akselerator"},
            {"kind": "wafer", "x": 0.3, "y": 0.66, "size": 0.24, "at": 16},
            {"kind": "neuralNet", "x": 0.72, "y": 0.66, "size": 0.26, "at": 28},
        ],
        "camera": {"shot": "medium", "move": "pan", "amplitude": 0.12, "ease": "sine.inOut"},
        "beats": [
            {"atFrame": 0, "kind": "enter", "subject": "TITLE"},
            {"atFrame": 48, "kind": "reveal", "subject": "TITLE"},
        ],
    },
    {
        "environment": "grid",
        "objects": [
            {"kind": "database", "x": 0.5, "y": 0.36, "size": 0.38, "at": 0, "label": "Data"},
            {"kind": "antenna", "x": 0.26, "y": 0.66, "size": 0.24, "at": 14},
            {"kind": "neuralNet", "x": 0.74, "y": 0.66, "size": 0.26, "at": 26},
        ],
        "camera": {"shot": "close", "move": "pull", "amplitude": 0.08, "ease": "power1.out"},
        "beats": [
            {"atFrame": 0, "kind": "enter", "subject": "TITLE"},
            {"atFrame": 42, "kind": "emphasis", "subject": "TITLE"},
        ],
    },
)


def mock_storyboard(*, seed: str = "demo", frames_per_scene: int = 300) -> dict[str, Any]:
    """The storyboard the mock provider serves, and the one the regression tests assert on.

    One definition, so the fixture the pipeline renders and the fixture the tests prove cannot
    drift apart. Every scene names real objects from the shipped library, so
    `object_consistency` has something concrete to resolve, and every backdrop differs so
    `repeated_world` has three distinct worlds to count.
    """
    scenes: list[dict[str, Any]] = []
    cursor = 0
    for index, world in enumerate(_MOCK_WORLDS, start=1):
        title_id = f"t{index}"
        segment_text = f"Pembuka {seed}." if index == 1 else (
            f"Isi utama {seed}." if index == 2 else f"Penutup {seed}."
        )
        objects = [dict(item) for item in world["objects"]]
        scenes.append(
            {
                "sceneId": f"sc{index}",
                "template": "ObjectExplainer",
                "segment": f"s{index}",
                "startFrame": cursor,
                "durationInFrames": frames_per_scene,
                "assetRefs": [],
                "text": [
                    {
                        "id": title_id,
                        "text": f"{segment_text} Adegan {index}."[:60],
                        "role": "title",
                        "atFrame": 0,
                    }
                ],
                # Every non-static move names the title element it is about, which is what
                # `SceneSpec._camera_target_exists` demands.
                "camera": {**world["camera"], "target": title_id},
                "motion": {
                    "energy": 0.55,
                    "continuity": "cut",
                    # Beats are scene-local; each one sits inside the shortest scene this mock
                    # script can produce after the audio stage retimes it.
                    "beats": [
                        {**beat, "subject": title_id if beat["subject"] == "TITLE" else beat["subject"]}
                        for beat in world["beats"]
                    ],
                },
                "transition": {"kind": "cut", "frames": 0},
                # `data` is what the renderer reads: the composition draws these objects on this
                # backdrop, and the declared camera above owns the movement.
                "data": {
                    "environment": world["environment"],
                    "objects": objects,
                    "callouts": [],
                    "flows": [
                        {"from": i, "to": 0, "at": 40 + i * 8}
                        for i in range(1, len(objects))
                    ],
                },
            }
        )
        cursor += frames_per_scene
    return {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "editorialLight",
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
        if task.startswith("creative_motion_brief") or task.startswith("creative-motion-brief"):
            return {
                "schema_version": 1,
                "visual_thesis": f"Permintaan AI mengalir melalui gateway terpusat yang memilih rute tercepat untuk {seed}.",
                "art_direction": {
                    "palette": "editorialLight",
                    "primary_accent": "#0055FF",
                    "secondary_accent": "#FF4400",
                    "background": "#F8FAFC",
                    "typography_style": "boldSans",
                },
                "narrative_arc": f"Input {seed} -> Analisis Beban -> Pemrosesan Model -> Hasil Optimal",
                "primary_visual_motifs": ["network_packets", "gateway_hub", "model_nodes", "heartbeat_pulses"],
                "pacing_strategy": "Cepat dan dinamis di awal, stabil saat routing, akselerasi saat resolusi.",
                "reusable_motifs": ["data_token", "signal_line"],
                "scene_transitions": ["cut", "wipe", "slideUp", "zoom"],
                "motion_complexity_budget": "medium",
            }
        if task.startswith("visual_plan"):
            return {
                "schema_version": 1,
                "style_intent": {
                    "style_name": "editorial_technical",
                    "theme": "editorialLight",
                    "color_mood": "Clean technical slate with amber accent",
                    "motion_character": "crisp_editorial",
                    "lighting_intent": "High contrast studio lighting",
                },
                "beats": [
                    {
                        "scene_id": "s1",
                        "concept": f"Introduction to {seed}",
                        "primary_subject": "serverRack",
                        "secondary_elements": ["coolingFan"],
                        "environment": "dataCenter",
                        "metaphor_grounding": "Physical data center infrastructure",
                        "camera_intent": {
                            "movement": "push",
                            "target": "serverRack",
                            "motivation": "Focus on the primary hardware core",
                        },
                        "mandatory_assets": ["serverRack"],
                        "visual_density": "clean",
                        "key_action": "Rack units illuminate sequentially",
                    },
                    {
                        "scene_id": "s2",
                        "concept": f"Processing mechanics of {seed}",
                        "primary_subject": "gpu",
                        "secondary_elements": ["wafer", "neuralNet"],
                        "environment": "circuit",
                        "metaphor_grounding": "Parallel silicon acceleration",
                        "camera_intent": {
                            "movement": "pan",
                            "target": "gpu",
                            "motivation": "Track data flow across circuit traces",
                        },
                        "mandatory_assets": ["gpu"],
                        "visual_density": "medium",
                        "key_action": "Silicon wafer emits computation pulse",
                    },
                    {
                        "scene_id": "s3",
                        "concept": f"Conclusion and persistence of {seed}",
                        "primary_subject": "database",
                        "secondary_elements": ["antenna"],
                        "environment": "grid",
                        "metaphor_grounding": "Global synchronized storage state",
                        "camera_intent": {
                            "movement": "pull",
                            "target": "database",
                            "motivation": "Reveal the broad distributed network",
                        },
                        "mandatory_assets": ["database"],
                        "visual_density": "clean",
                        "key_action": "Database clusters settle into steady state",
                    },
                ],
                "reasoning": f"Progression from hardware core to distributed state for {seed}",
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
        if task in ("motion_code", "motion-code") or task.startswith("motion_code") or task.startswith("motion-code"):
            return {
                "schema_version": 1,
                "kind": "motion-code",
                "entry_component": "RootComposition",
                "files": {
                    "RootComposition.tsx": (
                        "import React from 'react';\n"
                        "import { Composition } from 'remotion';\n"
                        "import { Scene01 } from './Scene01';\n\n"
                        "export const RootComposition: React.FC = () => (\n"
                        "  <Composition\n"
                        "    id=\"Short\"\n"
                        "    component={Scene01}\n"
                        "    durationInFrames={150}\n"
                        "    fps={30}\n"
                        "    width={1080}\n"
                        "    height={1920}\n"
                        "  />\n"
                        ");\n"
                    ),
                    "Scene01.tsx": (
                        "import React from 'react';\n"
                        "import { AbsoluteFill } from 'remotion';\n\n"
                        "export const Scene01: React.FC = () => (\n"
                        "  <AbsoluteFill style={{ backgroundColor: '#111827', justifyContent: 'center', alignItems: 'center' }}>\n"
                        "    <h1 style={{ color: '#F9FAFB', fontSize: 64 }}>Safe Motion</h1>\n"
                        "  </AbsoluteFill>\n"
                        ");\n"
                    ),
                },
                "dependencies": ["react", "remotion"],
                "skill_hashes": [],
                "validated_by_codeguard": True,
                "issues": [],
            }
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
