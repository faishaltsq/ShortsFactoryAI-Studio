"""Every status the studio can display must have a producer.

``reviewing`` was declared in ``Status``, in the dashboard union and in the badge table, and
``derive_status`` can never return it: a status with no emitter is a state machine claim nobody
can keep, and it invites a future author to "restore" an animation for it.
"""

from __future__ import annotations

import typing

from packages.core.observability.events import EventType, Status, derive_status

EMITTABLE = {derive_status(event_type) for event_type in typing.get_args(EventType)} | {
    derive_status(event_type, stale=True) for event_type in typing.get_args(EventType)
}


def test_reviewing_is_not_a_display_status():
    assert "reviewing" not in typing.get_args(Status)


def test_every_declared_status_has_an_emitter():
    declared = set(typing.get_args(Status))
    assert declared == EMITTABLE, (
        "a declared status with no emitter is dead: "
        f"{sorted(declared - EMITTABLE)}; an emitted status that is undeclared: "
        f"{sorted(EMITTABLE - declared)}"
    )
