"""Persisted agent events and the projection that drives the 3D studio.

Two properties matter more than the schema:

**No fake activity.** ``status`` is written by the thing doing the work, immediately before or after
it. A resumed stage writes ``artifact_reused``/``completed`` — never ``working``. Progress is only
ever a real counter. 100 % is reserved for a validated artifact.

**Staleness is server-side.** A character whose worker died must read as ``waiting``, not as typing
forever. The projection compares the last event time against the job's live lease, so closing a
laptop lid cannot leave a phantom at the keyboard.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..security.redact import redact

AgentId = Literal[
    "DirectorAgent",
    "ResearchAgent",
    "TopicSelectionAgent",
    "ScriptAgent",
    "CreativeDirectorAgent",
    "StoryboardAgent",
    "AssetAgent",
    "AnimationAgent",
    "AudioAgent",
    "EditorAgent",
    "QualityAgent",
    "MetadataAgent",
    "PublisherAgent",
    "FactoryOrchestrator",
]

AGENT_IDS: tuple[str, ...] = (
    "DirectorAgent",
    "ResearchAgent",
    "TopicSelectionAgent",
    "ScriptAgent",
    "CreativeDirectorAgent",
    "StoryboardAgent",
    "AssetAgent",
    "AnimationAgent",
    "MotionCoderAgent",
    "AudioAgent",
    "EditorAgent",
    "QualityAgent",
    "MetadataAgent",
    "PublisherAgent",
    "FactoryOrchestrator",
)

EventType = Literal[
    "stage_started",
    "stage_completed",
    "artifact_reused",
    "progress",
    "failed",
    "blocked",
    "cancelled",
    "waiting",
]

Status = Literal["working", "waiting", "blocked", "failed", "completed"]

#: Which agent produces each state. The studio reads this, so a stage can never be attributed to an
#: agent that did not do the work. ``IDEA_DISCOVERY`` is the entry state, so the agent working while
#: the job sits there is the one that will produce the next state.
STAGE_AGENTS: dict[str, str] = {
    "IDEA_DISCOVERY": "TopicSelectionAgent",
    "TOPIC_SELECTED": "ResearchAgent",
    "RESEARCH_COMPLETE": "ScriptAgent",
    "SCRIPT_GENERATED": "CreativeDirectorAgent",
    "CREATIVE_REVIEW": "StoryboardAgent",
    "STORYBOARD_READY": "AnimationAgent",
    "ASSETS_READY": "AudioAgent",
    "AUDIO_READY": "AnimationAgent",
    "RENDERING": "EditorAgent",
    "TECHNICAL_QC": "QualityAgent",
    "EDITORIAL_QC": "QualityAgent",
    "READY_FOR_APPROVAL": "DirectorAgent",
    "APPROVED": "PublisherAgent",
    "PRIVATE_UPLOAD": "PublisherAgent",
    "SCHEDULED": "MetadataAgent",
    "PUBLISHED": "PublisherAgent",
}


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class StudioEvent:
    event_id: int
    job_id: str
    agent_id: str
    event_type: str
    status: str
    description: str
    progress: float | None
    model: str | None
    stage: str | None
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "agent_id": self.agent_id,
            "event_type": self.event_type,
            "status": self.status,
            "description": self.description,
            "progress": self.progress,
            "model": self.model,
            "stage": self.stage,
            "created_at": self.created_at,
        }


def derive_status(event_type: str, *, stale: bool = False) -> str:
    """Map an event type to a display status.

    ``stale`` overrides everything: a worker that stopped heartbeating is waiting, whatever its
    last event claimed. This is the single place that decides, so the rule cannot drift between the
    API, the SSE stream, and the scene.
    """
    if stale:
        return "waiting"
    return {
        "stage_started": "working",
        "progress": "working",
        "stage_completed": "completed",
        "artifact_reused": "completed",
        "failed": "failed",
        "blocked": "blocked",
        "cancelled": "waiting",
        "waiting": "waiting",
    }.get(event_type, "waiting")


class StudioEventStore:
    """Append-only event log with a monotonic cursor, plus the projection the studio reads."""

    def __init__(self, db_path: Path, *, secrets: tuple[str, ...] = ()) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets = secrets
        self._lock = threading.RLock()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _migrate(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS studio_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    progress REAL,
                    model TEXT,
                    stage TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_studio_job ON studio_events(job_id, event_id)"
            )

    # -- writing ---------------------------------------------------------------------------
    def emit(
        self,
        *,
        job_id: str,
        agent_id: str,
        event_type: str,
        description: str = "",
        progress: float | None = None,
        model: str | None = None,
        stage: str | None = None,
        status: str | None = None,
    ) -> StudioEvent:
        if agent_id not in AGENT_IDS:
            raise ValueError(f"unknown agent_id {agent_id!r}")
        if progress is not None and not (0.0 <= progress <= 1.0):
            raise ValueError("progress must be within 0..1")
        if progress == 1.0 and event_type not in {"stage_completed", "artifact_reused"}:
            # 100% means a validated artifact exists. Nothing else may claim it.
            raise ValueError("progress 1.0 is reserved for stage_completed/artifact_reused")
        safe_description = redact(description, secrets=self.secrets, limit=400)
        resolved_status = status or derive_status(event_type)
        now = _utc_now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO studio_events(job_id, agent_id, event_type, status, description,"
                " progress, model, stage, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    agent_id,
                    event_type,
                    resolved_status,
                    safe_description,
                    progress,
                    model,
                    stage,
                    now,
                ),
            )
            event_id = int(cursor.lastrowid or 0)
        return StudioEvent(
            event_id, job_id, agent_id, event_type, resolved_status,
            safe_description, progress, model, stage, now,
        )

    # -- reading ---------------------------------------------------------------------------
    def page(self, *, after: int = 0, limit: int = 200, job_id: str | None = None) -> list[StudioEvent]:
        query = "SELECT * FROM studio_events WHERE event_id > ?"
        params: list[Any] = [after]
        if job_id:
            query += " AND job_id = ?"
            params.append(job_id)
        query += " ORDER BY event_id LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_event(row) for row in rows]

    def latest_event_id(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(event_id),0) AS n FROM studio_events").fetchone()
        return int(row["n"])

    def latest_per_agent(self, job_id: str | None = None) -> dict[str, StudioEvent]:
        query = (
            "SELECT e.* FROM studio_events e JOIN ("
            " SELECT agent_id, MAX(event_id) AS max_id FROM studio_events"
        )
        params: list[Any] = []
        if job_id:
            query += " WHERE job_id = ?"
            params.append(job_id)
        query += " GROUP BY agent_id) m ON e.event_id = m.max_id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return {row["agent_id"]: _event(row) for row in rows}

    def recent_per_job(self, *, limit: int = 5) -> dict[str, list[StudioEvent]]:
        """The last ``limit`` events of every job, in one statement.

        ``history()`` per agent opened one SQLite connection per agent, so projecting a snapshot of
        fourteen agents cost fourteen connections for data that one query returns. Newest first, as
        ``history`` is.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT e.* FROM studio_events e JOIN ("
                " SELECT job_id, event_id FROM ("
                "  SELECT job_id, event_id, ROW_NUMBER() OVER ("
                "   PARTITION BY job_id ORDER BY event_id DESC) AS rank"
                "  FROM studio_events) WHERE rank <= ?"
                ") r ON e.event_id = r.event_id ORDER BY e.event_id DESC",
                (limit,),
            ).fetchall()
        grouped: dict[str, list[StudioEvent]] = {}
        for row in rows:
            grouped.setdefault(row["job_id"], []).append(_event(row))
        return grouped

    def history(self, job_id: str, *, limit: int = 100) -> list[StudioEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM studio_events WHERE job_id = ? ORDER BY event_id DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [_event(row) for row in reversed(rows)]


def _event(row: sqlite3.Row) -> StudioEvent:
    return StudioEvent(
        event_id=int(row["event_id"]),
        job_id=row["job_id"],
        agent_id=row["agent_id"],
        event_type=row["event_type"],
        status=row["status"],
        description=row["description"],
        progress=row["progress"],
        model=row["model"],
        stage=row["stage"],
        created_at=row["created_at"],
    )


@dataclass
class AgentView:
    agent_id: str
    status: str
    stale: bool
    task: str
    progress: float | None
    model: str | None
    stage: str | None
    job_id: str | None
    updated_at: str | None
    recent: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "stale": self.stale,
            "task": self.task,
            "progress": self.progress,
            "model": self.model,
            "stage": self.stage,
            "job_id": self.job_id,
            "updated_at": self.updated_at,
            "recent": self.recent,
        }


def project_agents(
    store: StudioEventStore,
    *,
    job_id: str | None = None,
    live_agents: set[str] | None = None,
    stale_after_s: int = 300,
) -> list[AgentView]:
    """Build the studio view: one entry per known agent, honest about staleness.

    ``live_agents`` is the set of agents whose worker currently holds a live lease. An agent whose
    last event says ``working`` but who is not in that set reads as ``waiting`` — the phantom-typing
    case.
    """
    latest = store.latest_per_agent(job_id)
    recent = store.recent_per_job(limit=5)
    now = dt.datetime.now(dt.UTC)
    views: list[AgentView] = []
    for agent_id in AGENT_IDS:
        event = latest.get(agent_id)
        if event is None:
            views.append(
                AgentView(agent_id, "waiting", False, "", None, None, None, None, None)
            )
            continue
        stale = False
        if event.status == "working":
            age = (now - dt.datetime.fromisoformat(event.created_at)).total_seconds()
            if age > stale_after_s:
                stale = True
            if live_agents is not None and agent_id not in live_agents:
                stale = True
        views.append(
            AgentView(
                agent_id=agent_id,
                status=derive_status(event.event_type, stale=stale),
                stale=stale,
                task=event.description,
                progress=event.progress,
                model=event.model,
                stage=event.stage,
                job_id=event.job_id,
                updated_at=event.created_at,
                recent=[item.to_json() for item in recent.get(event.job_id, [])],
            )
        )
    return views


#: One entry, keyed on everything a snapshot's content depends on: which store it came from, the
#: cursor, the job filter and the live-agent set. The store identity is not optional — two event
#: logs can share a cursor number while holding completely different rows, and a key without it
#: would serve one database's agents to a caller asking about another (which is exactly what a test
#: suite with two `tmp_path` stores does). A single slot, because the studio polls one view.
_SNAPSHOT_MEMO: dict[
    tuple[str, int, str | None, frozenset[str] | None], dict[str, Any]
] = {}


def snapshot(
    store: StudioEventStore,
    *,
    job_id: str | None = None,
    live_agents: set[str] | None = None,
) -> dict[str, Any]:
    """A consistent snapshot: the cursor is read before the projection, so a client that resumes
    from it cannot miss an event that arrived during the projection.

    Memoised on ``(cursor, job_id, live_agents)`` only. Those three are the whole input, so a
    repeat poll between two events is a dict lookup instead of three queries. ``generated_at`` is
    deliberately part of the memoised value: two identical requests must not differ, or a client
    diffing snapshots would see a change the event log never made.
    """
    cursor = store.latest_event_id()
    key = (
        str(store.db_path),
        cursor,
        job_id,
        None if live_agents is None else frozenset(live_agents),
    )
    cached = _SNAPSHOT_MEMO.get(key)
    if cached is not None:
        return cached
    agents = project_agents(store, job_id=job_id, live_agents=live_agents)
    fresh = {
        "cursor": cursor,
        "job_id": job_id,
        "agents": [view.to_json() for view in agents],
        "generated_at": _utc_now(),
    }
    _SNAPSHOT_MEMO.clear()
    _SNAPSHOT_MEMO[key] = fresh
    return fresh
