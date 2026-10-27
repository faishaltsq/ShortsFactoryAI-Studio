"""Technical QA, readiness, and the strengthened QA artifact.

Every rejection here is a way a job could otherwise reach ``READY_FOR_APPROVAL`` on an artifact
that does not say what happened. ``passed: true`` next to a failed check is the specific lie these
contracts exist to make impossible.
"""

from __future__ import annotations

import pytest

from packages.core.contracts.artifacts import (
    QaArtifact,
    ReadinessArtifact,
    TechnicalQaArtifact,
)
from packages.core.contracts.base import ArtifactValidationError, validate_artifact

SHA = "a" * 64


def _technical(**overrides):
    payload = {
        "passed": True,
        "checks": {"resolution": True, "frame_rate": True},
        "observed": {"width": 1080, "height": 1920, "fps": 30.0},
        "thresholds": {"resolution": "1080x1920", "frame_rate": "30 +/- 0.01"},
        "failed": [],
        "detectors": {"blackdetect": {"ran": True, "count": 0}},
        "inputs_sha256": SHA,
    }
    payload.update(overrides)
    return payload


def _creative(**overrides):
    payload = {
        "passed": True,
        "metrics": {"static_ratio": 0.12, "fade_ratio": 0.0},
        "thresholds": {"static_ratio": "<= 0.45"},
        "failed": [],
    }
    payload.update(overrides)
    return payload


def _visual(**overrides):
    payload = {
        "status": "skipped_no_vision_provider",
        "provider": None,
        "frames_extracted": 3,
        "frames_inspected": 0,
        "findings": [],
    }
    payload.update(overrides)
    return payload


def _qa(**overrides):
    payload = {
        "technical": {"passed": True, "failed": []},
        "creative": _creative(),
        "visual": _visual(),
        "repairs": [],
    }
    payload.update(overrides)
    return payload


# -- TechnicalQaArtifact ---------------------------------------------------------------------


def test_technical_qa_accepts_a_coherent_pass():
    art = validate_artifact(TechnicalQaArtifact, _technical())
    assert art.passed is True
    assert art.failed == []


def test_technical_qa_rejects_passed_true_with_a_failed_check():
    with pytest.raises(ArtifactValidationError, match="passed"):
        validate_artifact(
            TechnicalQaArtifact,
            _technical(checks={"resolution": False, "frame_rate": True}),
        )


def test_technical_qa_rejects_passed_true_with_a_named_failure():
    with pytest.raises(ArtifactValidationError, match="naming failures"):
        validate_artifact(
            TechnicalQaArtifact,
            _technical(failed=["black_frames"]),
        )


def test_technical_qa_rejects_a_non_boolean_check():
    """A string 'false' is not a pass. Only a real bool may enter the checks map."""
    with pytest.raises(ArtifactValidationError):
        validate_artifact(TechnicalQaArtifact, _technical(checks={"resolution": "yes"}))


def test_technical_qa_requires_a_full_input_hash():
    with pytest.raises(ArtifactValidationError):
        validate_artifact(TechnicalQaArtifact, _technical(inputs_sha256="short"))


def test_technical_qa_requires_the_thresholds_it_was_judged_against():
    with pytest.raises(ArtifactValidationError):
        validate_artifact(TechnicalQaArtifact, _technical(thresholds={}))


# -- ReadinessArtifact -----------------------------------------------------------------------


def _readiness(**overrides):
    payload = {
        "ready": True,
        "checks": {"technical": True, "creative": True, "visual": True, "checksum": True},
        "blockers": [],
        "technical_passed": True,
        "creative_passed": True,
        "visual_status": "passed",
        "inputs_sha256": SHA,
    }
    payload.update(overrides)
    return payload


def test_readiness_accepts_a_ready_job():
    art = validate_artifact(ReadinessArtifact, _readiness())
    assert art.ready is True


def test_readiness_rejects_ready_true_with_blockers():
    with pytest.raises(ArtifactValidationError, match="blockers remain"):
        validate_artifact(ReadinessArtifact, _readiness(blockers=["checksum"]))


def test_readiness_rejects_ready_true_when_a_check_is_false():
    with pytest.raises(ArtifactValidationError, match="failing checks"):
        validate_artifact(
            ReadinessArtifact,
            _readiness(checks={"technical": True, "creative": False, "visual": True, "checksum": True}),
        )


def test_readiness_rejects_ready_true_when_creative_did_not_pass():
    with pytest.raises(ArtifactValidationError, match="creative"):
        validate_artifact(ReadinessArtifact, _readiness(creative_passed=False))


def test_readiness_rejects_ready_true_when_visual_failed():
    with pytest.raises(ArtifactValidationError, match="visual"):
        validate_artifact(ReadinessArtifact, _readiness(visual_status="failed"))


def test_readiness_allows_a_skip_to_be_ready():
    """A skip is visible and non-passing, but it is not a blocker. STATE_MACHINE invariant 3."""
    art = validate_artifact(
        ReadinessArtifact, _readiness(visual_status="skipped_no_vision_provider")
    )
    assert art.ready is True


def test_readiness_rejects_an_unknown_visual_status():
    with pytest.raises(ArtifactValidationError):
        validate_artifact(ReadinessArtifact, _readiness(visual_status="probably_fine"))


# -- QaArtifact ------------------------------------------------------------------------------


def test_qa_accepts_a_complete_artifact():
    art = validate_artifact(QaArtifact, _qa())
    assert art.creative["passed"] is True
    assert art.visual["status"] == "skipped_no_vision_provider"


def test_qa_rejects_a_missing_visual_status():
    with pytest.raises(ArtifactValidationError, match="visual.status"):
        validate_artifact(QaArtifact, _qa(visual={"provider": None, "findings": []}))


def test_qa_rejects_technical_without_an_explicit_pass():
    with pytest.raises(ArtifactValidationError, match="technical.passed"):
        validate_artifact(QaArtifact, _qa(technical={"failed": []}))


def test_qa_rejects_creative_without_an_explicit_pass():
    with pytest.raises(ArtifactValidationError, match="creative.passed"):
        validate_artifact(
            QaArtifact, _qa(creative={"metrics": {"static_ratio": 0.1}, "failed": []})
        )


def test_qa_rejects_creative_without_metrics():
    """A pass with no measured value is a claim, not a result."""
    with pytest.raises(ArtifactValidationError, match="metrics"):
        validate_artifact(
            QaArtifact, _qa(creative={"passed": True, "thresholds": {}, "failed": []})
        )


def test_qa_rejects_a_repair_record_without_its_required_fields():
    with pytest.raises(ArtifactValidationError, match="repairs"):
        validate_artifact(
            QaArtifact,
            _qa(repairs=[{"attempt": 0, "target": "black_frames"}]),
        )


def test_qa_accepts_a_blocked_repair_record_that_invalidated_nothing():
    art = validate_artifact(
        QaArtifact,
        _qa(
            creative=_creative(passed=False, failed=["static_ratio"]),
            repairs=[
                {
                    "attempt": 0,
                    "target": "static_ratio",
                    "reason": "static_ratio 0.91 > 0.45",
                    "artifacts_invalidated": [],
                    "action": "blocked",
                }
            ],
        ),
    )
    assert art.repairs[0]["action"] == "blocked"
    assert art.repairs[0]["artifacts_invalidated"] == []


def test_qa_rejects_an_unknown_repair_action():
    with pytest.raises(ArtifactValidationError, match="action"):
        validate_artifact(
            QaArtifact,
            _qa(
                repairs=[
                    {
                        "attempt": 0,
                        "target": "static_ratio",
                        "reason": "x",
                        "artifacts_invalidated": [],
                        "action": "auto_fixed",
                    }
                ]
            ),
        )


def test_qa_rejects_a_visual_pass_with_no_frames_inspected():
    """The guard against a provider that answers 'passed' without seeing anything."""
    with pytest.raises(ArtifactValidationError, match="frames_inspected"):
        validate_artifact(
            QaArtifact,
            _qa(visual=_visual(status="passed", provider="vision-a", frames_inspected=0)),
        )


def test_qa_rejects_a_skip_that_claims_inspected_frames():
    with pytest.raises(ArtifactValidationError, match="frames_inspected"):
        validate_artifact(
            QaArtifact,
            _qa(visual=_visual(status="skipped_no_vision_provider", frames_inspected=4)),
        )


def test_qa_rejects_a_skip_that_names_a_provider():
    with pytest.raises(ArtifactValidationError, match="provider"):
        validate_artifact(
            QaArtifact,
            _qa(visual=_visual(status="skipped_no_vision_provider", provider="vision-a")),
        )
