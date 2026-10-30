"""Per-agent contract behaviour: the fixture path and the bounded-repair path.

Phase 2.1 requires, for every agent, a contract test with a recorded fixture response *and* a
negative test: malformed JSON -> one bounded repair -> ``BLOCKED``. The repair machinery in
``Agent.produce`` had no direct coverage at all, which is how a second unbounded retry or a
silently-accepted prose answer would go unnoticed.

These tests drive the real ``Agent`` subclasses with a fake provider, so what is under test is the
agent's own parse/validate/repair logic - not a mock of it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from packages.core.agents import ModelOutputError
from packages.core.agents.registry import AGENTS
from packages.core.providers.base import (
    Capability,
    Health,
    ProviderError,
    ProviderResult,
    ResolvedCall,
    Usage,
)


def _call() -> ResolvedCall:
    return ResolvedCall(
        provider="fake",
        transport="mock",
        base_url="",
        model="fake-1",
        temperature=None,
        max_tokens=None,
        timeout_s=1.0,
        max_retries=0,
        capabilities=frozenset({Capability.CHAT, Capability.JSON_SCHEMA}),
        allow_private_hosts=False,
    )


class FakeProvider:
    """Answers from a scripted list, recording every prompt it was sent."""

    transport = "mock"

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.sent: list[dict[str, str]] = []

    def health(self, call: ResolvedCall):  # noqa: ARG002 - protocol shape
        return Health.up()

    def complete(self, call: ResolvedCall, *, system: str, user: str, task: str) -> ProviderResult:
        self.sent.append({"system": system, "user": user, "task": task})
        if not self.answers:
            raise AssertionError("the agent called the provider more times than scripted")
        content = self.answers.pop(0)
        if content.startswith("!error"):
            raise ProviderError("provider_bad_response", content.removeprefix("!error"))
        return ProviderResult(
            content=content,
            provider=call.provider,
            model=call.model,
            usage=Usage(prompt_tokens=1, completion_tokens=1),
        )


def _ctx(provider: FakeProvider) -> Any:
    from packages.core.agents import CallContext

    return CallContext(call=_call(), provider=provider)


# -- fixtures, one per agent ----------------------------------------------------------------

RESEARCH_OK = {
    "schema_version": 1,
    "topic": "Sejarah kereta bawah tanah",
    "content_kind": "fictional",
    "candidates": [{"title": "Sudut satu", "angle": "sisi tersembunyi", "why": "baru"}],
    "sources": [],
    "claims": [],
}

SCRIPT_OK = {
    "schema_version": 1,
    "hook": "Pembuka tentang kereta bawah tanah",
    "segments": [{"id": "s1", "text": "Segmen pembuka", "purpose": "hook"}],
    "cta": "Komentar ya",
    "content_kind": "fictional",
}

STORYBOARD_OK = {
    "schema_version": 1,
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "theme": "dusk",
    "scenes": [
        {
            "sceneId": "sc1",
            "template": "IllustratedStory",
            "segment": "s1",
            "startFrame": 0,
            "durationInFrames": 120,
            "text": [{"id": "t1", "text": "Kereta bawah tanah", "role": "title", "atFrame": 0}],
            "camera": {"shot": "wide", "move": "push", "target": "t1", "amplitude": 0.1},
            "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
            "transition": {"kind": "cut", "frames": 0},
            "data": {"world": "stasiun"},
        }
    ],
    "subtitles": [],
}

REVIEW_OK = {
    "schema_version": 1,
    "verdict": "accept",
    "scores": {"hook": 0.8},
    "findings": [],
    "attempt": 0,
}

METADATA_OK = {
    "schema_version": 1,
    "title": "Sejarah kereta bawah tanah",
    "description": "Ringkasan singkat",
    "tags": ["sejarah"],
    "category_id": "27",
    "made_for_kids": False,
    "synthetic_media": True,
    "thumbnail": {},
}

MOTION_OK = {
    "schema_version": 1,
    "renderer": "remotion",
    "style_brief": {"palette": ["#112233"], "fonts": ["Inter"], "signature_move": "push"},
    "scenes": [{"sceneId": "sc1", "camera": {"shot": "wide", "move": "push", "target": "t1"}, "beats": []}],
    "anti_patterns_checked": ["text-wall"],
}

#: agent -> (contract-valid payload, the kwargs its ``build_user_prompt`` reads)
AGENT_FIXTURES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "ResearchAgent": (RESEARCH_OK, {"topic": "kereta", "genre": "sejarah", "avoid": []}),
    "TopicSelectionAgent": (RESEARCH_OK, {"research": RESEARCH_OK}),
    "ScriptAgent": (SCRIPT_OK, {"topic": RESEARCH_OK, "duration_s": 45, "language": "id"}),
    "CreativeDirectorAgent": (REVIEW_OK, {"script": SCRIPT_OK, "attempt": 0}),
    "StoryboardAgent": (STORYBOARD_OK, {"script": SCRIPT_OK, "fps": 30}),
    "AnimationAgent": (MOTION_OK, {"storyboard": STORYBOARD_OK}),
    "MetadataAgent": (METADATA_OK, {"script": SCRIPT_OK, "language": "id"}),
    # QualityAgent's text pass is the same shape as the creative review: a verdict plus findings.
    "QualityAgent": (REVIEW_OK, {"storyboard": STORYBOARD_OK, "attempt": 0}),
}


@pytest.mark.parametrize("agent_id", sorted(AGENT_FIXTURES))
def test_a_valid_fixture_produces_a_validated_artifact(agent_id):
    payload, kwargs = AGENT_FIXTURES[agent_id]
    provider = FakeProvider([json.dumps(payload)])
    agent = AGENTS[agent_id](_ctx(provider))

    artifact = agent.produce(task="test", **kwargs)

    assert artifact.kind == agent.contract().kind
    assert len(provider.sent) == 1, "a valid answer must not trigger a repair"


@pytest.mark.parametrize("agent_id", sorted(AGENT_FIXTURES))
def test_malformed_json_gets_exactly_one_repair_then_blocks(agent_id):
    """The Phase 2.1 negative test: prose -> one repair -> ``BLOCKED``.

    ``produce`` raises ``ModelOutputError("schema_violation")``, which the stage maps to a
    non-retryable ``StageError`` and the job to ``BLOCKED``. What must never happen is a second
    repair, or a prose answer being pattern-matched into an artifact.
    """
    payload, kwargs = AGENT_FIXTURES[agent_id]
    provider = FakeProvider(["I am not JSON at all.", "Still not JSON."])
    agent = AGENTS[agent_id](_ctx(provider))

    with pytest.raises(ModelOutputError) as excinfo:
        agent.produce(task="test", **kwargs)

    assert "repair failed" in str(excinfo.value)
    assert len(provider.sent) == 2, "exactly one repair attempt, never a second"
    assert provider.sent[1]["task"].endswith(":repair")
    assert "rejected" in provider.sent[1]["user"]


@pytest.mark.parametrize("agent_id", sorted(AGENT_FIXTURES))
def test_a_valid_repair_answer_is_accepted(agent_id):
    """The repair is a real second chance, not a formality that always fails."""
    payload, kwargs = AGENT_FIXTURES[agent_id]
    provider = FakeProvider(["not json", json.dumps(payload)])
    agent = AGENTS[agent_id](_ctx(provider))

    artifact = agent.produce(task="test", **kwargs)

    assert artifact.kind == agent.contract().kind
    assert len(provider.sent) == 2


@pytest.mark.parametrize("agent_id", sorted(AGENT_FIXTURES))
def test_a_provider_error_is_not_retried_as_a_schema_violation(agent_id):
    """A transport failure is a different failure class from a schema violation.

    Retrying it as a repair would spend a second paid call on a network problem and report the
    wrong cause. The original error code must survive.
    """
    payload, kwargs = AGENT_FIXTURES[agent_id]
    provider = FakeProvider(["!errorprovider_unreachable"])
    agent = AGENTS[agent_id](_ctx(provider))

    with pytest.raises(ModelOutputError) as excinfo:
        agent.produce(task="test", **kwargs)

    assert "provider_unreachable" in str(excinfo.value)
    assert len(provider.sent) == 1, "a provider error must not trigger a repair call"


def test_every_llm_agent_has_a_fixture():
    """Phase 2.1 says *each* agent. A new agent with no fixture must fail here, not silently."""
    missing = sorted(set(AGENTS) - set(AGENT_FIXTURES))
    assert missing == [], f"agents without a contract fixture: {missing}"
