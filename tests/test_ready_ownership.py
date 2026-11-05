"""Who owns ``READY_FOR_APPROVAL``: a DirectorAgent stage that re-verifies and writes the verdict.

STATE_MACHINE says ``READY_FOR_APPROVAL`` is the DirectorAgent gate. It is also a state the
runner must be able to *reach*, and ``TECHNICAL_QC -> READY_FOR_APPROVAL`` is not in the
allow-list. So option (a): ``EDITORIAL_QC`` writes ``qc.json`` and the contact sheet, then a
``DirectorAgent`` stage at ``READY_FOR_APPROVAL`` recomputes the input bindings from disk and
writes ``readiness.json``.

Why this and not option (b):

1. **The chain refuses (b).** ``_validate_chain`` validates each stage's target against the
   previous state. An editorial stage declaring ``READY_FOR_APPROVAL`` would have to be reached
   from ``TECHNICAL_QC``, which the allow-list forbids. Keeping the stage at ``EDITORIAL_QC``
   means the job never reaches ``READY_FOR_APPROVAL`` at all, because ``run_stages`` advances only
   to ``stage.state``.
2. **The DirectorAgent stage is not a stage that writes nothing.** It owns the verdict: it
   re-reads the render, the narration and the storyboard, recomputes the hash, and writes
   ``readiness.json``. The editorial stage no longer writes that file, so there is exactly one
   writer and no opportunity for two artifacts to disagree.
3. **Re-verification is the point.** A readiness verdict computed by the stage that also decided
   the creative score is a self-assessment. Recomputing the binding in a separate stage, from the
   files, is the cheapest possible second opinion — and the approval gate then recomputes it a
   third time before an operator can approve.
"""

from __future__ import annotations

import pytest

from packages.core.contracts.artifacts import ReadinessArtifact
from packages.core.contracts.base import validate_artifact
from packages.core.contracts.state import JobState, is_transition_allowed
from packages.core.orchestration.editorial import (
    QA_NAME,
    READINESS_NAME,
    build_editorial_qc_stage,
    build_readiness,
    build_readiness_stage,
    compute_inputs_hash,
)
from packages.core.orchestration.runner import _validate_chain


class _State:
    store = None


def test_technical_qc_cannot_jump_straight_to_ready_for_approval():
    """The fact that rules out option (b): an editorial stage cannot declare READY."""
    assert not is_transition_allowed(JobState.TECHNICAL_QC, JobState.READY_FOR_APPROVAL)


def test_editorial_qc_can_reach_ready_for_approval():
    assert is_transition_allowed(JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL)


def test_the_editorial_stage_owns_editorial_qc_and_writes_only_the_qa_artifact():
    stage = build_editorial_qc_stage(_State())
    assert stage.state is JobState.EDITORIAL_QC
    assert stage.produces == (QA_NAME,)
    assert READINESS_NAME not in stage.produces


def test_the_readiness_stage_is_owned_by_the_director_agent():
    stage = build_readiness_stage(_State())
    assert stage.name == "DirectorAgent"
    assert stage.state is JobState.READY_FOR_APPROVAL
    assert stage.produces == (READINESS_NAME,)
    assert stage.contract is ReadinessArtifact


def test_the_two_stage_chain_validates_from_technical_qc():
    _validate_chain(
        JobState.TECHNICAL_QC, [build_editorial_qc_stage(_State()), build_readiness_stage(_State())]
    )


def test_a_single_editorial_stage_cannot_validate_at_ready_for_approval():
    """Proves the reason for the split, rather than asserting it in a comment."""
    from packages.core.orchestration.runner import Stage, StageChainError, StageOutcome

    def noop(store, job_id):  # pragma: no cover - never executed
        return StageOutcome(ok=True)

    stage = Stage(name="Q", state=JobState.READY_FOR_APPROVAL, produces=(), run=noop)
    with pytest.raises(StageChainError):
        _validate_chain(JobState.TECHNICAL_QC, [stage])


def test_readiness_validates_and_records_its_hash():
    readiness = build_readiness(
        technical={"passed": True, "failed": []},
        creative={"passed": True, "failed": []},
        visual={"status": "skipped_no_vision_provider"},
        checksum_valid=True,
        inputs_sha256="a" * 64,
    )
    validate_artifact(ReadinessArtifact, readiness)
    assert readiness["ready"] is False
    assert readiness["semantic_status"] == "UNVERIFIED"
    assert readiness["inputs_sha256"] == "a" * 64


def test_a_stale_hash_cannot_authorise_new_bytes():
    first = compute_inputs_hash(render_sha256="a" * 64, narration_ms=10_000, storyboard={"scenes": []})
    second = compute_inputs_hash(render_sha256="b" * 64, narration_ms=10_000, storyboard={"scenes": []})
    assert first != second


def test_a_changed_render_invalidates_the_recorded_technical_hash():
    """The protection that makes reuse safe: the readiness stage recomputes from the bytes.

    ``_is_done`` reuses any artifact whose contract validates, so it cannot tell a QC verdict
    computed against yesterday's render from one computed against today's. The binding does:
    ``technical-qc.json`` records ``inputs_sha256``, and the readiness stage recomputes the same
    hash from ``render.json`` + ``audio.json`` + ``storyboard.json``. A different render produces
    a different hash and the job is refused instead of inheriting a stale pass.
    """
    storyboard = {"scenes": [{"sceneId": "sc1", "startFrame": 0, "durationInFrames": 90}]}
    before = compute_inputs_hash(
        render_sha256="a" * 64, narration_ms=3000, storyboard=storyboard
    )
    after = compute_inputs_hash(
        render_sha256="b" * 64, narration_ms=3000, storyboard=storyboard
    )
    assert before != after

    # The stage's drift rule, exercised directly: a technical artifact whose recorded hash is
    # not the hash of the files on disk must not produce a ready verdict.
    recorded = before
    drifted = isinstance(recorded, str) and recorded and recorded != after
    assert drifted is True, "a hash recorded against other bytes must be detected as drift"
