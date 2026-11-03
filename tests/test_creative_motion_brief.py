from __future__ import annotations

import pytest

from packages.core.contracts.artifacts import ArtDirectionSpec, CreativeMotionBriefArtifact


def test_creative_motion_brief_validation() -> None:
    raw = {
        "visual_thesis": "Permintaan AI mengalir melalui gateway terpusat yang memilih rute tercepat dan mengalihkan kegagalan.",
        "art_direction": {
            "palette": "editorialLight",
            "primary_accent": "#0055FF",
            "secondary_accent": "#FF4400",
            "background": "#F8FAFC",
            "typography_style": "boldSans",
        },
        "narrative_arc": "Input -> Analisis Beban -> Percabangan Model -> Kegagalan Primer -> Pemulihan Sekunder -> Output Sukses",
        "primary_visual_motifs": ["network_packets", "gateway_hub", "model_nodes", "heartbeat_pulses"],
        "pacing_strategy": "Cepat dan dinamis di awal, stabil saat routing, akselerasi saat kegagalan, resolusi mulus.",
        "reusable_motifs": ["data_token", "signal_line"],
        "scene_transitions": ["cut", "wipe", "slideUp", "zoom"],
        "motion_complexity_budget": "medium",
    }
    brief = CreativeMotionBriefArtifact.model_validate(raw)
    assert brief.visual_thesis.startswith("Permintaan AI")
    assert isinstance(brief.art_direction, ArtDirectionSpec)
    assert brief.art_direction.palette == "editorialLight"
    assert "network_packets" in brief.primary_visual_motifs
    assert brief.motion_complexity_budget == "medium"


def test_creative_motion_brief_rejection_on_empty_thesis() -> None:
    with pytest.raises(ValueError):
        CreativeMotionBriefArtifact.model_validate({
            "visual_thesis": "",
            "art_direction": {"palette": "editorialLight"},
            "narrative_arc": "arc",
            "pacing_strategy": "pacing",
        })


def test_creative_director_produces_creative_motion_brief() -> None:
    from packages.core.agents import CallContext
    from packages.core.agents.concrete import CreativeDirectorAgent
    from packages.core.providers.base import Capability, ResolvedCall
    from packages.core.providers.mock import MockProvider

    call = ResolvedCall(
        provider="mock",
        transport="mock",
        base_url="",
        model="mock-1",
        temperature=None,
        max_tokens=None,
        timeout_s=1.0,
        max_retries=0,
        capabilities=frozenset({Capability.CHAT}),
        allow_private_hosts=False,
    )
    ctx = CallContext(call=call, provider=MockProvider())
    agent = CreativeDirectorAgent(ctx)
    artifact = agent.produce(
        task="creative_motion_brief",
        script={"hook": "test", "segments": [{"id": "s1", "text": "text"}]},
        topic={"title": "topic"},
        research={"topic": "research", "sources": [{"url": "http://example.com"}]},
    )
    assert artifact.kind == "creative-motion-brief"
    assert isinstance(artifact, CreativeMotionBriefArtifact)
    assert artifact.visual_thesis
    assert artifact.art_direction.palette == "editorialLight"


def test_creative_director_sanitizer_normalizes_brief() -> None:
    from packages.core.agents.concrete import CreativeDirectorAgent

    agent = CreativeDirectorAgent.__new__(CreativeDirectorAgent)
    agent.current_task = "creative_motion_brief"
    payload = {
        "reasoning": "Inferred thesis",
        "art_direction": {"palette": "spaceDark"},
    }
    sanitized = agent.sanitize_payload(payload)
    assert sanitized["visual_thesis"] == "Inferred thesis"
    assert sanitized["art_direction"]["palette"] == "spaceDark"
    assert sanitized["art_direction"]["primary_accent"] == "#0055FF"
    assert sanitized["motion_complexity_budget"] == "medium"


def test_creative_motion_brief_with_model_instance_and_string_art_direction() -> None:
    spec = ArtDirectionSpec(palette="oceanFloor", primary_accent="#00AAFF")
    brief1 = CreativeMotionBriefArtifact.model_validate({
        "visual_thesis": "Thesis with instance.",
        "art_direction": spec,
    })
    assert brief1.art_direction.palette == "oceanFloor"
    assert brief1.art_direction.primary_accent == "#00AAFF"

    brief2 = CreativeMotionBriefArtifact.model_validate({
        "visual_thesis": "Thesis with string palette.",
        "art_direction": "circuitDark",
    })
    assert brief2.art_direction.palette == "circuitDark"


def test_the_directing_fields_are_recorded_and_never_invented() -> None:
    """The brief carries the film-identity decisions, and an unstated one stays empty.

    A blank here means "the director did not decide"; filling it with a default would make a
    guess indistinguishable from a decision at every stage downstream.
    """
    brief = CreativeMotionBriefArtifact.model_validate({"visual_thesis": "Only the thesis."})
    for field in (
        "narrative_thesis",
        "visual_metaphor",
        "subject_environment",
        "palette_rationale",
        "typography_direction",
        "camera_language",
        "motion_language",
        "scene_progression",
        "transition_strategy",
        "visual_climax",
        "ending_payoff",
    ):
        assert getattr(brief, field) == "", field

    stated = CreativeMotionBriefArtifact.model_validate(
        {
            "visual_thesis": "Thesis.",
            "visual_metaphor": "The signal is a river.",
            "camera_language": ["slow push in", "hold"],  # a director answering in bullets
        }
    )
    assert stated.visual_metaphor == "The signal is a river."
    assert stated.camera_language == "slow push in, hold"


def test_creative_motion_brief_coerce_list() -> None:
    assert CreativeMotionBriefArtifact._coerce_list(",,,") == []
    assert CreativeMotionBriefArtifact._coerce_list(" , , , ") == []
    assert CreativeMotionBriefArtifact._coerce_list("a, b, c") == ["a", "b", "c"]
    assert CreativeMotionBriefArtifact._coerce_list("single") == ["single"]
    assert CreativeMotionBriefArtifact._coerce_list("") == []

    brief = CreativeMotionBriefArtifact.model_validate({
        "visual_thesis": "Coercion test thesis.",
        "primary_visual_motifs": ",,,",
        "reusable_motifs": "cube, sphere",
        "scene_transitions": "cut, wipe",
    })
    assert brief.primary_visual_motifs == []
    assert brief.reusable_motifs == ["cube", "sphere"]
    assert brief.scene_transitions == ["cut", "wipe"]


def test_creative_director_sanitizer_not_hijacked_for_visual_plan() -> None:
    from packages.core.agents.concrete import CreativeDirectorAgent

    agent = CreativeDirectorAgent.__new__(CreativeDirectorAgent)
    payload = {
        "art_direction": {"palette": "spaceDark", "primary_accent": "#000"},
        "beats": [
            {
                "narrationSegmentId": "s1",
                "conceptToExplain": "Concept",
                "visualPurpose": "Purpose",
                "visualAction": "Action",
            }
        ],
    }

    sanitized = agent.sanitize_payload(dict(payload), task="visual_plan")
    assert sanitized.get("theme") == "editorialLight"
    assert len(sanitized["beats"]) == 1
    assert "motion_complexity_budget" not in sanitized

    agent.current_task = "visual_plan"
    sanitized_task = agent.sanitize_payload(dict(payload))
    assert sanitized_task.get("theme") == "editorialLight"
    assert len(sanitized_task["beats"]) == 1
    assert "motion_complexity_budget" not in sanitized_task


