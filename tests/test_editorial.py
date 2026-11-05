"""The editorial composer: deterministic checks plus one provider call, and the gate verdict.

``orchestration.editorial`` is the only place that may import both ``media`` (measurements) and
``agents`` (the vision pass). It does not write to the database and does not transition the job —
the stage builder does, through the existing runner. Keeping the decision in a pure function is
what makes the gate testable without a job store.
"""

from __future__ import annotations

import pytest

from packages.core.contracts.artifacts import QaArtifact, ReadinessArtifact
from packages.core.contracts.base import validate_artifact
from packages.core.orchestration.editorial import (
    build_qa_artifact,
    build_readiness,
    compute_inputs_hash,
    repair_record,
)

SHA = "a" * 64


def _technical(**overrides):
    payload = {
        "passed": True,
        "checks": {"resolution": True, "black_frames": True},
        "observed": {"width": 1080},
        "thresholds": {"resolution": "1080x1920"},
        "failed": [],
        "detectors": {},
        "inputs_sha256": SHA,
    }
    payload.update(overrides)
    return payload


def _creative(**overrides):
    payload = {
        "passed": True,
        "metrics": {"static_ratio": 0.12, "shot_variety": 1.0},
        "thresholds": {"static_ratio": "<= 0.45"},
        "failed": [],
    }
    payload.update(overrides)
    return payload


def _visual(**overrides):
    payload = {
        "status": "skipped_no_vision_provider",
        "provider": None,
        "frames_extracted": 4,
        "frames_inspected": 0,
        "findings": [],
        "model": "",
        "reason": "no vision provider",
    }
    payload.update(overrides)
    return payload


# -- the QA artifact ---------------------------------------------------------------------------


def test_the_qa_artifact_validates_from_real_parts():
    artifact = build_qa_artifact(
        technical=_technical(), creative=_creative(), visual=_visual(), repairs=[]
    )
    validate_artifact(QaArtifact, artifact)
    assert artifact["technical"]["passed"] is True
    assert artifact["creative"]["passed"] is True
    assert artifact["visual"]["status"] == "skipped_no_vision_provider"


def test_the_qa_artifact_carries_every_creative_and_visual_measurement():
    artifact = build_qa_artifact(
        technical=_technical(), creative=_creative(), visual=_visual(), repairs=[]
    )
    assert artifact["creative"]["metrics"]["static_ratio"] == 0.12
    assert artifact["creative"]["thresholds"]["static_ratio"] == "<= 0.45"
    assert artifact["visual"]["frames_extracted"] == 4


def test_the_technical_block_in_qc_is_a_summary_and_the_detail_stays_in_technical_qc():
    """One artifact per question. qc.json says *whether* technical passed and *what* failed;
    technical-qc.json holds the observed values, thresholds and detector logs. Duplicating the
    detail here would give the operator two copies that can disagree."""
    artifact = build_qa_artifact(
        technical=_technical(), creative=_creative(), visual=_visual(), repairs=[]
    )
    assert "observed" not in artifact["technical"]
    assert "thresholds" not in artifact["technical"]
    assert artifact["technical"]["checks"] == {"resolution": True, "black_frames": True}


def test_a_failed_technical_check_produces_a_failed_artifact_not_an_exception():
    technical = _technical(passed=False, failed=["black_frames"], checks={"resolution": True, "black_frames": False})
    artifact = build_qa_artifact(
        technical=technical, creative=_creative(), visual=_visual(), repairs=[]
    )
    validate_artifact(QaArtifact, artifact)
    assert artifact["technical"]["passed"] is False


def test_the_technical_block_is_reduced_to_its_verdict_and_failures():
    """qc.json is the operator-facing summary; the full check table lives in technical-qc.json."""
    artifact = build_qa_artifact(
        technical=_technical(), creative=_creative(), visual=_visual(), repairs=[]
    )
    assert set(artifact["technical"]) <= {"passed", "failed", "reason", "checks"}


# -- repair records ----------------------------------------------------------------------------


def test_a_blocked_repair_record_invalidates_nothing_and_says_so():
    record = repair_record(target="black_frames", reason="blackdetect found 1 interval")
    assert record == {
        "attempt": 0,
        "target": "black_frames",
        "reason": "blackdetect found 1 interval",
        "artifacts_invalidated": [],
        "action": "blocked",
    }


def test_repair_records_validate_inside_the_qa_artifact():
    artifact = build_qa_artifact(
        technical=_technical(),
        creative=_creative(passed=False, failed=["static_ratio"]),
        visual=_visual(),
        repairs=[repair_record(target="static_ratio", reason="0.91 > 0.45")],
    )
    validate_artifact(QaArtifact, artifact)


def test_the_reason_is_bounded():
    record = repair_record(target="x", reason="y" * 1000)
    assert len(record["reason"]) <= 300


# -- input hash --------------------------------------------------------------------------------


def test_the_input_hash_changes_when_the_render_changes():
    first = compute_inputs_hash(render_sha256=SHA, narration_ms=10_000, storyboard={"scenes": []})
    second = compute_inputs_hash(render_sha256="b" * 64, narration_ms=10_000, storyboard={"scenes": []})
    assert first != second


def test_the_input_hash_changes_when_the_narration_changes():
    first = compute_inputs_hash(render_sha256=SHA, narration_ms=10_000, storyboard={"scenes": []})
    second = compute_inputs_hash(render_sha256=SHA, narration_ms=10_500, storyboard={"scenes": []})
    assert first != second


def test_the_input_hash_changes_when_the_storyboard_changes():
    first = compute_inputs_hash(render_sha256=SHA, narration_ms=10_000, storyboard={"scenes": [1]})
    second = compute_inputs_hash(render_sha256=SHA, narration_ms=10_000, storyboard={"scenes": [2]})
    assert first != second


def test_the_input_hash_is_stable_for_identical_inputs():
    args = {"render_sha256": SHA, "narration_ms": 10_000, "storyboard": {"scenes": [1]}}
    assert compute_inputs_hash(**args) == compute_inputs_hash(**args)


def test_the_input_hash_is_a_full_sha256():
    value = compute_inputs_hash(render_sha256=SHA, narration_ms=1, storyboard={})
    assert len(value) == 64
    int(value, 16)


# -- readiness ---------------------------------------------------------------------------------


def test_a_clean_job_is_ready():
    from tests.test_semantic_contracts import assessment
    semantic = {**assessment(), "inputs_sha256": SHA}
    readiness = build_readiness(
        technical=_technical(),
        creative=_creative(),
        visual={**_visual(status="passed", provider="fixture-vision", frames_inspected=3), "semantic": semantic},
        checksum_valid=True,
        inputs_sha256=SHA,
        job_id="fixture", render_sha256="a" * 64,
    )
    validate_artifact(ReadinessArtifact, readiness)
    assert readiness["ready"] is True
    assert readiness["blockers"] == []


def test_a_skipped_visual_pass_without_explicit_policy_blocks_readiness():
    readiness = build_readiness(
        technical=_technical(),
        creative=_creative(),
        visual=_visual(),
        checksum_valid=True,
        inputs_sha256=SHA,
    )
    assert readiness["visual_status"] == "skipped_no_vision_provider"
    assert readiness["ready"] is False


def test_a_failed_visual_pass_blocks_readiness():
    visual = _visual(status="failed", provider="vision-a", frames_inspected=4,
                     findings=[{"atMs": 0, "issue": "missing character", "severity": "blocker"}])
    readiness = build_readiness(
        technical=_technical(), creative=_creative(), visual=visual,
        checksum_valid=True, inputs_sha256=SHA,
    )
    assert readiness["ready"] is False
    assert "visual" in readiness["blockers"]


def test_a_failed_technical_check_blocks_readiness():
    technical = _technical(passed=False, failed=["black_frames"], checks={"black_frames": False})
    readiness = build_readiness(
        technical=technical, creative=_creative(), visual=_visual(),
        checksum_valid=True, inputs_sha256=SHA,
    )
    assert readiness["ready"] is False
    assert "technical" in readiness["blockers"]


def test_a_failed_creative_check_blocks_readiness():
    creative = _creative(passed=False, failed=["static_ratio"])
    readiness = build_readiness(
        technical=_technical(), creative=creative, visual=_visual(),
        checksum_valid=True, inputs_sha256=SHA,
    )
    assert readiness["ready"] is False
    assert "creative" in readiness["blockers"]


def test_a_bad_checksum_blocks_readiness():
    readiness = build_readiness(
        technical=_technical(), creative=_creative(), visual=_visual(),
        checksum_valid=False, inputs_sha256=SHA,
    )
    assert readiness["ready"] is False
    assert "checksum" in readiness["blockers"]


def test_every_blocker_is_named_at_once():
    technical = _technical(passed=False, failed=["black_frames"], checks={"black_frames": False})
    creative = _creative(passed=False, failed=["static_ratio"])
    readiness = build_readiness(
        technical=technical, creative=creative, visual=_visual(),
        checksum_valid=False, inputs_sha256=SHA,
    )
    assert set(readiness["blockers"]) == {"technical", "creative", "checksum", "visual"}


def test_readiness_records_the_input_hash_it_was_computed_from():
    readiness = build_readiness(
        technical=_technical(), creative=_creative(), visual=_visual(),
        checksum_valid=True, inputs_sha256=SHA,
    )
    assert readiness["inputs_sha256"] == SHA


def test_a_ready_verdict_with_a_stale_hash_is_refused_by_the_contract():
    """The hash is what makes a pass expire when the bytes change."""
    with pytest.raises(Exception, match="inputs_sha256"):
        ReadinessArtifact(ready=True, checks={"technical": True}, technical_passed=True,
                          creative_passed=True, visual_status="passed", inputs_sha256="short")


# -- layering ----------------------------------------------------------------------------------


def test_media_qc_does_not_import_agents_providers_or_orchestration():
    """media is below agents in the dependency graph; a reverse edge is an architecture break.

    Parsed, not grepped: the module's own prose mentions agents and providers, and a substring
    check would fail on the documentation while missing a real import.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("packages/core/media/qc.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
    forbidden = {name for name in imported if name in {"agents", "providers", "orchestration"}}
    assert not forbidden, f"media.qc must not import {sorted(forbidden)}"


def test_the_editorial_module_may_import_both_sides():
    """The composer is the one place allowed to join measurements and a provider call."""
    from pathlib import Path

    source = Path("packages/core/orchestration/editorial.py").read_text(encoding="utf-8")
    assert "media" in source
    assert "agents" in source


# -- cross-job history -------------------------------------------------------------------------


def _rendered_job(root, name: str, *, setting: str, camera: str) -> None:
    import json
    from pathlib import Path

    job = Path(root) / name
    job.mkdir(parents=True)
    props = {
        "storyboard": {
            "fps": 30,
            "scenes": [
                {
                    "sceneId": "sc1",
                    "template": "ObjectExplainer",
                    "startFrame": 0,
                    "durationInFrames": 90,
                    "data": {
                        "setting": setting,
                        "timeOfDay": "dusk",
                        "shots": [{"framing": "wide", "camera": camera, "weight": 1}],
                    },
                }
            ],
        }
    }
    (job / "render-props.json").write_text(json.dumps(props), encoding="utf-8")
    (job / "render.json").write_text(json.dumps({"frames": 90}), encoding="utf-8")


def test_history_uses_the_same_signature_shape_the_comparison_reads(tmp_path):
    """A prior job must be comparable, not merely present.

    The signature is built by the same function ``evaluate_creative`` compares against, so a
    change to one cannot silently make history incomparable.
    """
    from packages.core.media.qc import _signature_tokens, _style_signature
    from packages.core.orchestration.editorial import _history

    jobs = tmp_path / "jobs"
    _rendered_job(jobs, "prior1", setting="desert", camera="pushIn")
    (jobs / "current").mkdir()

    store = type("S", (), {"job_dir": staticmethod(lambda _jid: jobs / "current")})()
    history = _history(store, "current")

    assert len(history) == 1
    assert _signature_tokens(history[0]) == _signature_tokens(_style_signature(
        {"storyboard": {"fps": 30, "scenes": [
            {"sceneId": "sc1", "template": "ObjectExplainer", "startFrame": 0,
             "durationInFrames": 90,
             "data": {"setting": "desert", "timeOfDay": "dusk",
                      "shots": [{"framing": "wide", "camera": "pushIn", "weight": 1}]}}
        ]}}
    ))


def test_history_ignores_the_current_job_and_unrendered_jobs(tmp_path):
    from packages.core.orchestration.editorial import _history

    jobs = tmp_path / "jobs"
    _rendered_job(jobs, "prior1", setting="city", camera="panLeft")
    (jobs / "current").mkdir()
    (jobs / "current" / "render-props.json").write_text("{}", encoding="utf-8")
    (jobs / "current" / "render.json").write_text("{}", encoding="utf-8")
    (jobs / "draft").mkdir()
    (jobs / "draft" / "render-props.json").write_text("{}", encoding="utf-8")

    store = type("S", (), {"job_dir": staticmethod(lambda _jid: jobs / "current")})()
    history = _history(store, "current")

    assert len(history) == 1, "the current job and an unrendered job must both be skipped"


def test_history_is_capped_at_ten(tmp_path):
    from packages.core.orchestration.editorial import _history

    jobs = tmp_path / "jobs"
    for index in range(15):
        _rendered_job(jobs, f"prior{index}", setting="desert", camera="pushIn")
    (jobs / "current").mkdir()

    store = type("S", (), {"job_dir": staticmethod(lambda _jid: jobs / "current")})()
    assert len(_history(store, "current")) == 10


def test_a_missing_jobs_root_returns_empty_history(tmp_path):
    from packages.core.orchestration.editorial import _history

    store = type("S", (), {"job_dir": staticmethod(lambda _jid: tmp_path / "nope" / "current")})()
    assert _history(store, "current") == []
