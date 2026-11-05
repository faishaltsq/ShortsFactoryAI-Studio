"""Semantic verification is not inferred from successful encoding or a legacy visual flag."""

from packages.core.orchestration.editorial import build_readiness
from tests.test_semantic_contracts import assessment


def policy():
    return {
        "job_id": "fixture",
        "render_sha256": "a" * 64,
        "inputs_sha256": "b" * 64,
        "operator": "fixture-operator",
        "context_sha256": "c" * 64,
        "reason": "Inspect rendered video manually",
        "allow_unverified": True,
    }


def readiness(semantic=None, grant=None):
    return build_readiness(
        technical={"passed": True},
        creative={"passed": True},
        visual={"status": "passed", "semantic": semantic},
        checksum_valid=True,
        inputs_sha256="b" * 64,
        job_id="fixture",
        render_sha256="a" * 64,
        manual_review_policy=grant,
        context_sha256="c" * 64,
    )


def test_inspected_complete_semantic_pass_is_eligible_but_not_approved():
    result = readiness(assessment())
    assert result["ready"] is True
    assert result["semantic_status"] == "PASS"
    assert result["human_approved"] is False


def test_unknown_requires_render_bound_operator_policy_without_becoming_pass():
    result = readiness(grant=policy())
    assert result["ready"] is True
    assert result["semantic_status"] == "UNVERIFIED"
    assert result["review_basis"] == "operator_policy"
    assert result["human_approved"] is False


def test_manual_policy_never_waives_inspected_failure():
    assert readiness(assessment("FAIL"), policy())["ready"] is False


def test_changed_narration_or_research_context_invalidates_manual_permission():
    assert readiness(grant={**policy(), "context_sha256": "d" * 64})["ready"] is False


def test_policy_for_other_bytes_is_not_permission_for_current_render():
    grant = {**policy(), "render_sha256": "d" * 64}
    assert readiness(grant=grant)["ready"] is False


def test_uninspected_visual_evidence_is_not_ready_or_semantically_passed():
    result = build_readiness(
        technical={"passed": True},
        creative={"passed": True},
        visual={"status": "skipped_no_vision_provider"},
        checksum_valid=True,
        inputs_sha256="a" * 64,
    )
    assert result["ready"] is False
    assert result["technical_ready"] is True
    assert result["semantic_status"] == "UNVERIFIED"
    assert result["manual_review_eligible"] is False
    assert result["human_approved"] is False
