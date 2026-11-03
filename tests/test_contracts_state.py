"""The transition allow-list is the only way a job changes state."""

from __future__ import annotations

import pytest

from packages.core.contracts import JobState, allowed_transitions, assert_transition
from packages.core.contracts.base import ArtifactValidationError
from packages.core.contracts.state import is_publishable_state


def test_happy_path_is_walkable():
    path = [
        JobState.IDEA_DISCOVERY,
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.MOTION_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
        JobState.APPROVED,
        JobState.PRIVATE_UPLOAD,
        JobState.PUBLISHED,
    ]
    for source, target in zip(path, path[1:], strict=False):
        assert_transition(source, target)


def test_illegal_shortcut_is_refused():
    with pytest.raises(ArtifactValidationError) as exc:
        assert_transition(JobState.IDEA_DISCOVERY, JobState.PUBLISHED)
    assert "IDEA_DISCOVERY -> PUBLISHED" in str(exc.value)


def test_terminal_states_have_no_exits():
    for state in (JobState.PUBLISHED, JobState.REJECTED, JobState.CANCELLED):
        assert allowed_transitions(state) == frozenset()


def test_publishing_cannot_be_reached_without_approval():
    # No state may jump straight to an upload-capable state from anywhere before approval.
    for state in JobState:
        targets = allowed_transitions(state)
        if JobState.PRIVATE_UPLOAD in targets:
            assert state in {JobState.APPROVED, JobState.PRIVATE_UPLOAD}, state


def test_publishable_states_are_only_post_approval():
    publishable = {state for state in JobState if is_publishable_state(state)}
    assert publishable == {JobState.APPROVED, JobState.PRIVATE_UPLOAD, JobState.SCHEDULED}


def test_every_state_is_in_the_table():
    # A state missing from the allow-list silently behaves as terminal.
    for state in JobState:
        allowed_transitions(state)  # raises KeyError if the table drifted


def test_storyboard_ready_cannot_skip_assets_or_audio():
    with pytest.raises(ArtifactValidationError):
        assert_transition(JobState.STORYBOARD_READY, JobState.RENDERING)


def test_rendering_cannot_go_back_to_storyboard_ready():
    with pytest.raises(ArtifactValidationError) as exc:
        assert_transition(JobState.RENDERING, JobState.STORYBOARD_READY)
    assert "RENDERING -> STORYBOARD_READY" in str(exc.value)


# -- the approval gate is a property of the data model, not of a caller -------------------------


def test_the_only_state_that_can_reach_approved_is_ready_for_approval():
    """Computed from the allow-list, not hardcoded, so an edit cannot silently reopen the hole.

    ``_approval_checks`` lives in ``apps/api/jobs.py`` and runs on the approve route only. Any
    other edge into ``APPROVED`` is therefore a gate bypass: the state would be written without
    the checks ever running, and ``APPROVED -> PRIVATE_UPLOAD`` would then open.
    """
    inbound = {state for state in JobState if JobState.APPROVED in allowed_transitions(state)}
    assert inbound == {JobState.READY_FOR_APPROVAL}


def test_approved_cannot_be_reentered_without_a_fresh_gate():
    """The round trip ``APPROVED -> BLOCKED -> APPROVED`` must pass the gate again.

    ``BLOCKED`` is an exit of ``APPROVED`` (an upload may fail after approval), so if ``BLOCKED``
    could return to ``APPROVED`` a failed publish would re-enter the approved state with no
    operator decision. The only legal way back is through ``READY_FOR_APPROVAL``.
    """
    with pytest.raises(ArtifactValidationError) as exc:
        assert_transition(JobState.BLOCKED, JobState.APPROVED)
    assert "BLOCKED -> APPROVED" in str(exc.value)

    # The gate is still reachable from BLOCKED; it is the *bypass* that is gone.
    assert_transition(JobState.BLOCKED, JobState.READY_FOR_APPROVAL)


def test_paused_is_reachable_only_from_a_running_stage():
    """``PAUSED`` was a dead state: an out-edge table and no inbound edge.

    Phase 4 adds the pause action, so the inbound edges now exist — but only from stages where a
    pause is meaningful. It must not be reachable from the approval gate (pausing a job the
    operator is deciding would hide it with no owner) or from any terminal state.
    """
    inbound = {state for state in JobState if JobState.PAUSED in allowed_transitions(state)}
    assert inbound, "PAUSED must be reachable or it is a dead state"
    assert JobState.READY_FOR_APPROVAL not in inbound
    assert JobState.APPROVED not in inbound
    assert JobState.PUBLISHED not in inbound
    assert JobState.REJECTED not in inbound
    assert JobState.CANCELLED not in inbound
    assert JobState.PAUSED not in inbound, "a paused job does not need pausing again"
