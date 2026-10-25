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

from .base import Health, ProviderResult, ResolvedCall, Usage, now_ms

_TASKS = ("script", "review", "storyboard", "research", "metadata", "claim", "motion", "vision")


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
        seed = hashlib.sha256(f"{task}\x00{system}\x00{user}".encode()).hexdigest()[:12]
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
        if task.startswith("research"):
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
        if task.startswith("vision"):
            return {"status": "passed", "findings": [], "frames_inspected": 0}
        return {"seed": seed, "echo_len": len(user), "tasks": list(_TASKS)}
