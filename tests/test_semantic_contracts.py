from copy import deepcopy

import pytest
from pydantic import ValidationError

from packages.core.contracts import artifacts

CATEGORIES = [
    "subject_fidelity",
    "causal_fidelity",
    "narration_alignment",
    "spatial_continuity",
    "composition",
    "scientific_accuracy",
    "typography_branding",
    "visual_repetition",
]


def assessment(status="PASS"):
    return {
        "job_id": "fixture",
        "render_sha256": "a" * 64,
        "inputs_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "scene_ids": ["s1"],
        "status": status,
        "provider": "fixture-vision",
        "model": "fixture-model",
        "criteria": [
            {
                "scene_id": "s1",
                "category": category,
                "status": status,
                "reason": "Observed fixture evidence with explicit uncertainty",
                "observation": "The labelled subject remains within the visible frame",
                "frame_ids": ["s1:0"],
                "confidence": 0.9,
                "repair_scope": "tsx" if status == "FAIL" else "none",
                "severity": "major" if status == "FAIL" else "info",
            }
            for category in CATEGORIES
        ],
    }


def model():
    result = getattr(artifacts, "SemanticInspection", None)
    assert result is not None, "semantic inspection requires an explicit contract"
    return result


def test_semantic_pass_survives_contract_roundtrip():
    value = model().model_validate(assessment())
    assert value.model_dump(mode="json")["status"] == "PASS"
    assert len(value.criteria) == 8


@pytest.mark.parametrize(
    "damage",
    [
        "missing_category",
        "duplicate_category",
        "unknown_scene",
        "empty_evidence",
        "low_confidence",
        "contradiction",
        "missing_provider",
        "failure_without_target",
    ],
)
def test_semantic_pass_rejects_unsupported_claims(damage):
    payload = deepcopy(assessment())
    first = payload["criteria"][0]
    if damage == "missing_category":
        payload["criteria"].pop()
    if damage == "duplicate_category":
        payload["criteria"][-1] = deepcopy(first)
    if damage == "unknown_scene":
        first["scene_id"] = "invented"
    if damage == "empty_evidence":
        first["frame_ids"] = []
    if damage == "low_confidence":
        first["confidence"] = 0.1
    if damage == "contradiction":
        first["status"] = "UNVERIFIED"
    if damage == "missing_provider":
        payload["provider"] = None
    if damage == "failure_without_target":
        payload = assessment("FAIL")
        payload["criteria"][0]["repair_scope"] = "none"
    with pytest.raises(ValidationError):
        model().model_validate(payload)
