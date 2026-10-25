"""Artifact contracts: the rules that make honesty structural."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.contracts import (
    ApprovalArtifact,
    AssetsArtifact,
    PublicationArtifact,
    QaArtifact,
    ResearchArtifact,
    ReviewArtifact,
    ScriptArtifact,
)
from packages.core.contracts.base import ArtifactValidationError, validate_artifact


def test_factual_research_without_sources_is_rejected():
    with pytest.raises(ValidationError) as exc:
        ResearchArtifact(topic="x", content_kind="factual", sources=[])
    assert "at least one source" in str(exc.value)


def test_fictional_research_may_have_no_sources():
    art = ResearchArtifact(topic="x", content_kind="fictional", sources=[])
    assert art.content_kind == "fictional"


def test_revise_verdict_must_state_a_finding():
    with pytest.raises(ValidationError) as exc:
        ReviewArtifact(verdict="revise", findings=[])
    assert "at least one finding" in str(exc.value)


def test_accept_verdict_needs_no_findings():
    assert ReviewArtifact(verdict="accept").verdict == "accept"


def test_script_segment_ids_must_be_unique():
    with pytest.raises(ValidationError) as exc:
        ScriptArtifact(
            hook="h",
            segments=[{"id": "s1", "text": "a"}, {"id": "s1", "text": "b"}],
        )
    assert "duplicate segment id" in str(exc.value)


def test_asset_without_license_is_rejected():
    with pytest.raises(ValidationError) as exc:
        AssetsArtifact(backgrounds=[{"id": "desert", "path": "d.png"}])
    assert "has no license" in str(exc.value)


def test_asset_with_license_is_accepted():
    art = AssetsArtifact(backgrounds=[{"id": "desert", "path": "d.png", "license": "CC0"}])
    assert art.backgrounds[0]["license"] == "CC0"


def test_qa_visual_status_has_no_default():
    with pytest.raises(ValidationError) as exc:
        QaArtifact(technical={"passed": True}, creative={}, visual={})
    assert "visual.status must be one of" in str(exc.value)


def test_qa_accepts_skipped_vision_as_a_distinct_state():
    art = QaArtifact(visual={"status": "skipped_no_vision_provider"})
    assert art.visual["status"] == "skipped_no_vision_provider"


def test_rejection_requires_a_reason():
    with pytest.raises(ValidationError) as exc:
        ApprovalArtifact(decision="rejected", operator="op")
    assert "must state a reason" in str(exc.value)


def test_publishable_requires_the_check_flag():
    art = ApprovalArtifact(decision="approved", operator="op", checks={"publishable": False})
    assert art.publishable is False


def test_public_publication_needs_a_confirm_receipt():
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(phase="confirmed", privacy="public", video_id="abc")
    assert "public_confirm receipt" in str(exc.value)


def test_private_publication_needs_no_confirm_receipt():
    art = PublicationArtifact(phase="confirmed", privacy="private", video_id="abc")
    assert art.privacy == "private"


def test_validate_artifact_reports_every_problem():
    with pytest.raises(ArtifactValidationError) as exc:
        validate_artifact(
            ScriptArtifact,
            {"hook": "", "segments": [], "unexpected": 1},
        )
    problems = exc.value.problems
    assert len(problems) >= 2, problems
    assert any("hook" in p for p in problems)


def test_content_hash_ignores_created_at():
    a = ReviewArtifact(verdict="accept", created_at="2020-01-01T00:00:00+00:00")
    b = ReviewArtifact(verdict="accept", created_at="2026-10-25T00:00:00+00:00")
    assert a.content_hash() == b.content_hash()


def test_content_hash_changes_with_content():
    a = ReviewArtifact(verdict="accept", attempt=0)
    b = ReviewArtifact(verdict="accept", attempt=1)
    assert a.content_hash() != b.content_hash()
