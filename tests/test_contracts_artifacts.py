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


def test_audio_contract_rejects_subtitles_past_narration():
    from packages.core.contracts import AudioArtifact

    with pytest.raises(ValidationError, match="narration duration"):
        AudioArtifact(
            narration={"src": "narration.wav", "durationMs": 100, "voice": "system-default"},
            scenes=[{"sceneId": "sc1", "startMs": 0, "endMs": 100}],
            subtitles=[{"startMs": 0, "endMs": 101, "text": "late"}],
            mix={"music": None, "ducking": False, "loudness_lufs": -16},
        )


def test_audio_contract_requires_one_timing_per_scene_and_no_gaps():
    from packages.core.contracts import AudioArtifact

    with pytest.raises(ValidationError, match="scene timings"):
        AudioArtifact(
            narration={"src": "narration.wav", "durationMs": 1000, "voice": "system-default"},
            scenes=[{"sceneId": "sc1", "startMs": 0, "endMs": 400}],
            subtitles=[],
            mix={"music": None, "ducking": False, "loudness_lufs": -16},
        )
    with pytest.raises(ValidationError, match="scene timings"):
        AudioArtifact(
            narration={"src": "narration.wav", "durationMs": 1000, "voice": "system-default"},
            scenes=[
                {"sceneId": "sc1", "startMs": 0, "endMs": 400},
                {"sceneId": "sc2", "startMs": 500, "endMs": 1000},
            ],
            subtitles=[],
            mix={"music": None, "ducking": False, "loudness_lufs": -16},
        )


def test_audio_contract_rejects_overlapping_or_unordered_subtitles():
    from packages.core.contracts import AudioArtifact

    with pytest.raises(ValidationError, match="subtitle"):
        AudioArtifact(
            narration={"src": "narration.wav", "durationMs": 1000, "voice": "system-default"},
            scenes=[{"sceneId": "sc1", "startMs": 0, "endMs": 1000}],
            subtitles=[
                {"startMs": 0, "endMs": 600, "text": "first"},
                {"startMs": 500, "endMs": 900, "text": "overlap"},
            ],
            mix={"music": None, "ducking": False, "loudness_lufs": -16},
        )

def _qa_minimal(**overrides):
    payload = {
        "technical": {"passed": True, "failed": []},
        "creative": {"passed": True, "metrics": {"static_ratio": 0.1}, "failed": []},
        "visual": {
            "status": "skipped_no_vision_provider",
            "provider": None,
            "frames_extracted": 2,
            "frames_inspected": 0,
            "findings": [],
        },
        "repairs": [],
    }
    payload.update(overrides)
    return payload


def test_qa_visual_status_has_no_default():
    with pytest.raises(ValidationError) as exc:
        QaArtifact(**_qa_minimal(visual={}))
    assert "visual.status must be one of" in str(exc.value)


def test_qa_accepts_skipped_vision_as_a_distinct_state():
    art = QaArtifact(**_qa_minimal())
    assert art.visual["status"] == "skipped_no_vision_provider"


def test_rejection_requires_a_reason():
    with pytest.raises(ValidationError) as exc:
        ApprovalArtifact(decision="rejected", operator="op")
    assert "must state a reason" in str(exc.value)


def test_publishable_requires_the_check_flag():
    art = ApprovalArtifact(decision="approved", operator="op", checks={"publishable": False})
    assert art.publishable is False


def test_an_approval_can_record_the_render_it_decided_about():
    """The field exists so a stale approval cannot authorise a different file.

    Optional in the contract because an artifact written before this field existed must still
    parse; ``JobStore.transition`` refuses such an artifact at the transition instead.
    """
    art = ApprovalArtifact(
        decision="approved",
        operator="op",
        checks={"publishable": True},
        render_sha256="a" * 64,
    )
    assert art.render_sha256 == "a" * 64
    assert art.publishable is True


def test_an_approval_without_a_render_hash_still_parses():
    """Backwards compatibility is a contract property, not a transition property."""
    art = ApprovalArtifact(decision="approved", operator="op", checks={"publishable": True})
    assert art.render_sha256 is None


def test_public_publication_needs_a_confirm_receipt():
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(
            phase="confirmed",
            privacy="public",
            video_id="abc",
            idempotency_key="k" * 32,
        )
    assert "public_confirm receipt" in str(exc.value)


def test_private_publication_needs_no_confirm_receipt():
    art = PublicationArtifact(
        phase="confirmed", privacy="private", video_id="abc", idempotency_key="k" * 32
    )
    assert art.privacy == "private"


# -- publication idempotency: the contract carries what makes a retry safe ---------------------


def test_a_publication_requires_an_idempotency_key():
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(phase="initiating", privacy="private")
    assert "idempotency_key" in str(exc.value)


def test_a_short_idempotency_key_is_refused():
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(phase="initiating", privacy="private", idempotency_key="short")
    assert "idempotency_key" in str(exc.value)


def test_an_uncertain_publication_must_record_that_the_request_left():
    """An uncertain record that cannot say what it did is not actionable.

    Reconciliation needs to know an insert may have been created, so the receipt must name the
    step, when it happened, and what was sent.
    """
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(phase="uncertain", privacy="private", idempotency_key="k" * 32)
    message = str(exc.value)
    assert "insert_sent" in message
    assert "uncertain" in message


def test_an_uncertain_receipt_without_a_timestamp_is_refused():
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(
            phase="uncertain",
            privacy="private",
            idempotency_key="k" * 32,
            receipts=[{"step": "insert_sent", "sent": {"bytes": 10}}],
        )
    assert "at" in str(exc.value)


def test_an_uncertain_receipt_without_a_payload_is_refused():
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(
            phase="uncertain",
            privacy="private",
            idempotency_key="k" * 32,
            receipts=[{"step": "insert_sent", "at": "2026-01-01T00:00:00+00:00"}],
        )
    assert "sent" in str(exc.value)


def test_an_uncertain_publication_with_a_full_receipt_parses():
    art = PublicationArtifact(
        phase="uncertain",
        privacy="private",
        idempotency_key="k" * 32,
        attempt=1,
        receipts=[
            {
                "step": "insert_sent",
                "at": "2026-01-01T00:00:00+00:00",
                "sent": {"bytes": 2852953, "privacy": "private"},
                "ok": False,
                "detail": "timeout after 30s",
            }
        ],
    )
    assert art.phase == "uncertain"
    assert art.attempt == 1


def test_a_confirmed_publication_must_carry_a_video_id():
    with pytest.raises(ValidationError) as exc:
        PublicationArtifact(phase="confirmed", privacy="private", idempotency_key="k" * 32)
    assert "video_id" in str(exc.value)


def test_an_uncertain_publication_needs_no_video_id():
    """The whole point: the id is unknown, which is why the record blocks retries."""
    art = PublicationArtifact(
        phase="uncertain",
        privacy="private",
        idempotency_key="k" * 32,
        receipts=[
            {
                "step": "insert_sent",
                "at": "2026-01-01T00:00:00+00:00",
                "sent": {"bytes": 10},
            }
        ],
    )
    assert art.video_id is None


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


def test_a_silent_render_has_no_audio_codec():
    """An MP4 with no audio stream has no audio codec; claiming 'aac' would be a false claim."""
    from packages.core.contracts import RenderArtifact

    render = RenderArtifact(
        sha256="a" * 64,
        bytes=1024,
        width=1080,
        height=1920,
        fps=30,
        frames=900,
        duration_ms=30000,
        audio_codec=None,
    )
    assert render.audio_codec is None


def test_video_codec_is_still_required():
    from packages.core.contracts import RenderArtifact

    with pytest.raises(ValidationError) as exc:
        RenderArtifact(
            sha256="a" * 64,
            bytes=1024,
            width=1080,
            height=1920,
            fps=30,
            frames=900,
            duration_ms=30000,
            video_codec=None,
        )
    assert "video_codec" in str(exc.value)
