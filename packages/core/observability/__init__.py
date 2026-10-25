"""The event log, its projection, and the stream the studio reads.

The rule this package enforces: a character in the studio can only be doing something if a
persisted event says so. There is no client-side timer that decides an agent is idle, and no
optimistic animation that shows work before it starts.
"""

from .events import (
    AgentId,
    StudioEvent,
    StudioEventStore,
    derive_status,
    project_agents,
)

__all__ = [
    "AgentId",
    "StudioEvent",
    "StudioEventStore",
    "derive_status",
    "project_agents",
]
