"""Real fixture frames plus scripted vision; no claims about a real model's accuracy."""

import json

import pytest

from packages.core.agents.vision import inspect_frames
from packages.core.contracts.semantic import SEMANTIC_CATEGORIES
from packages.core.media.qc import extract_visual_evidence, sha256_file
from packages.core.providers.base import ProviderError, VisionImage
from tests.test_vision_agent import _call, _props, _StubProvider
from tests.test_vision_agent import clip as _clip_fixture

clip = _clip_fixture


@pytest.fixture
def evidence(clip, tmp_path):
    props = _props()["storyboard"]
    manifest = extract_visual_evidence(
        clip,
        props,
        tmp_path,
        job_id="fixture",
        render_sha256=sha256_file(clip),
        inputs_sha256="b" * 64,
        context_sha256="c" * 64,
        requirements={
            s["sceneId"]: "Narration describes fixture subject transformation" for s in props["scenes"]
        },
    )
    assert manifest.complete
    images = [
        VisionImage(data=(tmp_path / frame.file).read_bytes(), label=frame.frame_id)
        for frame in manifest.frames
    ]
    return manifest, images, props


def answer(manifest, *, failure=False):
    criteria = []
    for scene in manifest.scene_ids:
        for category in SEMANTIC_CATEGORIES:
            failed = failure and category == "subject_fidelity"
            criteria.append(
                {
                    "scene_id": scene,
                    "category": category,
                    "status": "FAIL" if failed else "PASS",
                    "frame_ids": [f.frame_id for f in manifest.frames if f.scene_id == scene],
                    "reason": "Actual fixture pixels show an abstract test pattern, not the narrated machine"
                    if failed
                    else "Inspected visible fixture states with uncertainty",
                    "observation": "Colour test pattern occupies the scene",
                    "confidence": 0.9,
                    "severity": "major" if failed else "info",
                    "repair_scope": "storyboard" if failed else "none",
                }
            )
    return {"criteria": criteria}


def inspect(evidence, provider, images=None):
    manifest, originals, props = evidence
    return inspect_frames(
        call=_call(),
        provider=provider,
        images=originals if images is None else images,
        storyboard=props,
        manifest=manifest,
    )


def test_inspected_subject_failure_is_actionable_and_never_hidden_by_other_passes(evidence):
    provider = _StubProvider([json.dumps(answer(evidence[0], failure=True))])
    result = inspect(evidence, provider)
    assert result.status == "failed"
    assert result.semantic["status"] == "FAIL"
    assert result.findings[0]["scene_id"] in evidence[0].scene_ids
    assert result.findings[0]["evidence_timestamps_ms"]
    assert result.findings[0]["repair_scope"] == "storyboard"
    assert result.findings[0]["affected_artifact"] == "storyboard.json"
    assert len(provider.calls) == 1


def test_model_cannot_certify_science_from_url_declarations(evidence):
    provider = _StubProvider([json.dumps(answer(evidence[0]))])
    result = inspect(evidence, provider)
    assert result.status == "unverified"
    assert result.semantic["status"] == "UNVERIFIED"
    science = [c for c in result.semantic["criteria"] if c["category"] == "scientific_accuracy"]
    assert all(c["status"] == "UNVERIFIED" and c["repair_scope"] == "none" for c in science)


def test_interpretation_receipt_is_not_part_of_frame_request_identity(evidence):
    manifest = evidence[0]
    annotated = manifest.model_copy(
        update={"inspection_status": "FAIL", "provider": "served", "model": "actual"}
    )
    assert manifest.evidence_hash() == annotated.evidence_hash()


def test_missing_narration_context_cannot_be_reported_as_aligned(evidence):
    provider = _StubProvider([json.dumps(answer(evidence[0]))])
    result = inspect(evidence, provider)
    alignment = [item for item in result.semantic["criteria"] if item["category"] == "narration_alignment"]
    assert all(item["status"] == "UNVERIFIED" for item in alignment)


@pytest.mark.parametrize("damage", ["missing_category", "invented_frame", "bare_pass", "malformed"])
def test_unsupported_model_answers_are_unverified_without_paid_repair(evidence, damage):
    payload = answer(evidence[0])
    if damage == "missing_category":
        payload["criteria"].pop()
    if damage == "invented_frame":
        payload["criteria"][0]["frame_ids"] = ["invented"]
    if damage == "bare_pass":
        payload = {"status": "PASS", "frames_inspected": 999}
    provider = _StubProvider(["not JSON" if damage == "malformed" else json.dumps(payload)])
    result = inspect(evidence, provider)
    assert result.status == "unverified"
    assert not result.findings
    assert len(provider.calls) == 1


def test_missing_or_different_image_does_not_dispatch(evidence):
    provider = _StubProvider([json.dumps(answer(evidence[0]))])
    assert inspect(evidence, provider, images=[]).status == "unverified"
    assert provider.calls == []


def test_provider_uncertain_failure_is_unknown_not_semantic_failure(evidence):
    provider = _StubProvider(
        [], raise_exc=ProviderError("provider_timeout", "uncertain fixture", retryable=True)
    )
    result = inspect(evidence, provider)
    assert result.status == "unverified"
    assert result.findings == []
    assert len(provider.calls) == 1


def test_semantic_restart_replays_across_manifest_clock_changes_and_exhausted_budget(evidence, tmp_path):
    from tests.test_vision_journal import setup

    manifest, images, props = evidence
    inner = _StubProvider([json.dumps(answer(manifest))])
    recorder, journal, call = setup(tmp_path, inner)
    first = inspect_frames(call=call, provider=recorder, images=images, storyboard=props, manifest=manifest)
    assert first.frames_inspected == len(images)
    restarted, _, _ = setup(tmp_path, inner)
    restarted.tracker.set_limits(max_daily_tokens=1, max_daily_cost_usd=None, unlimited=False)
    regenerated = manifest.model_copy(update={"created_at": "different-clock"})
    second = inspect_frames(
        call=call, provider=restarted, images=images, storyboard=props, manifest=regenerated
    )
    assert second.frames_inspected == len(images)
    assert len(inner.calls) == 1
    assert len(journal.statuses("job")) == 1


def test_uncertain_semantic_call_is_not_reissued_after_restart(evidence, tmp_path):
    from tests.test_vision_journal import setup

    manifest, images, props = evidence
    inner = _StubProvider([], raise_exc=SystemExit("fixture process crash"))
    recorder, _, call = setup(tmp_path, inner)
    with pytest.raises(SystemExit):
        inspect_frames(call=call, provider=recorder, images=images, storyboard=props, manifest=manifest)
    restarted, journal, _ = setup(tmp_path, inner)
    journal.reconcile()
    result = inspect_frames(call=call, provider=restarted, images=images, storyboard=props, manifest=manifest)
    assert result.status == "unverified"
    assert len(inner.calls) == 1
    assert len(journal.uncertain("job")) == 1
