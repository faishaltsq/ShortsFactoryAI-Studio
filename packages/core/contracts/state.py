"""Job states, studio statuses, and the transition allow-list.

The allow-list is the only way a job changes state. Anything not listed raises; there is no
"force" parameter, because a force parameter is how a failed job becomes a successful one.
"""

from __future__ import annotations

from enum import Enum

from .base import ArtifactValidationError


class JobState(str, Enum):
    IDEA_DISCOVERY = "IDEA_DISCOVERY"
    TOPIC_SELECTED = "TOPIC_SELECTED"
    RESEARCH_COMPLETE = "RESEARCH_COMPLETE"
    SCRIPT_GENERATED = "SCRIPT_GENERATED"
    CREATIVE_REVIEW = "CREATIVE_REVIEW"
    STORYBOARD_READY = "STORYBOARD_READY"
    ASSETS_READY = "ASSETS_READY"
    AUDIO_READY = "AUDIO_READY"
    RENDERING = "RENDERING"
    TECHNICAL_QC = "TECHNICAL_QC"
    EDITORIAL_QC = "EDITORIAL_QC"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PRIVATE_UPLOAD = "PRIVATE_UPLOAD"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    # side states
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


class StudioStatus(str, Enum):
    """What a character in the studio may display. Derived from events, never asserted."""

    WORKING = "working"
    WAITING = "waiting"
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


SIDE_STATES = frozenset(
    {JobState.FAILED, JobState.BLOCKED, JobState.CANCELLED, JobState.PAUSED}
)

TERMINAL_STATES = frozenset({JobState.PUBLISHED, JobState.REJECTED, JobState.CANCELLED})

# The forward path, plus the legal side exits. Every entry is deliberate.
_ALLOWED: dict[JobState, frozenset[JobState]] = {
    JobState.IDEA_DISCOVERY: frozenset(
        {JobState.TOPIC_SELECTED, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.TOPIC_SELECTED: frozenset(
        {JobState.RESEARCH_COMPLETE, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.RESEARCH_COMPLETE: frozenset(
        {JobState.SCRIPT_GENERATED, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.SCRIPT_GENERATED: frozenset(
        {JobState.CREATIVE_REVIEW, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    # A revise verdict returns to SCRIPT_GENERATED; that loop is bounded by MAX_REPAIRS upstream.
    JobState.CREATIVE_REVIEW: frozenset(
        {
            JobState.STORYBOARD_READY,
            JobState.SCRIPT_GENERATED,
            JobState.BLOCKED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.STORYBOARD_READY: frozenset(
        {JobState.ASSETS_READY, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.ASSETS_READY: frozenset(
        {JobState.AUDIO_READY, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.AUDIO_READY: frozenset(
        {JobState.RENDERING, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.RENDERING: frozenset(
        {JobState.TECHNICAL_QC, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    # A failed technical gate may re-render; that is the bounded repair path.
    JobState.TECHNICAL_QC: frozenset(
        {
            JobState.EDITORIAL_QC,
            JobState.RENDERING,
            JobState.BLOCKED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.EDITORIAL_QC: frozenset(
        {
            JobState.READY_FOR_APPROVAL,
            JobState.REJECTED,
            JobState.BLOCKED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.READY_FOR_APPROVAL: frozenset(
        {JobState.APPROVED, JobState.REJECTED, JobState.CANCELLED}
    ),
    JobState.APPROVED: frozenset(
        {JobState.PRIVATE_UPLOAD, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.PRIVATE_UPLOAD: frozenset(
        {JobState.SCHEDULED, JobState.PUBLISHED, JobState.BLOCKED, JobState.FAILED}
    ),
    JobState.SCHEDULED: frozenset(
        {JobState.PUBLISHED, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}
    ),
    # Terminal: nothing follows.
    JobState.PUBLISHED: frozenset(),
    JobState.REJECTED: frozenset(),
    JobState.CANCELLED: frozenset(),
    # A blocked job can be resumed by an operator decision into the stage that blocked it.
    JobState.BLOCKED: frozenset(
        {
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
            JobState.CANCELLED,
        }
    ),
    # A failed job is not silently retried; it may only be resumed deliberately or cancelled.
    JobState.FAILED: frozenset(
        {
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
            JobState.CANCELLED,
        }
    ),
    JobState.PAUSED: frozenset(
        {
            JobState.IDEA_DISCOVERY,
            JobState.RESEARCH_COMPLETE,
            JobState.SCRIPT_GENERATED,
            JobState.STORYBOARD_READY,
            JobState.AUDIO_READY,
            JobState.RENDERING,
            JobState.CANCELLED,
        }
    ),
}


def allowed_transitions(state: JobState) -> frozenset[JobState]:
    return _ALLOWED.get(state, frozenset())


def is_transition_allowed(source: JobState, target: JobState) -> bool:
    return target in allowed_transitions(source)


def assert_transition(source: JobState, target: JobState) -> None:
    """Raise on an illegal transition, naming both states."""
    if target not in allowed_transitions(source):
        raise ArtifactValidationError(
            "transition",
            [f"{source.value} -> {target.value} is not allowed"],
        )


def is_publishable_state(state: JobState) -> bool:
    """Publishing requires approval and an upload-capable state; nothing else qualifies."""
    return state in {JobState.APPROVED, JobState.PRIVATE_UPLOAD, JobState.SCHEDULED}
