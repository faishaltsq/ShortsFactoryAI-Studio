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
