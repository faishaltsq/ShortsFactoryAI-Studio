"""Topic discovery: propose candidates from production history, never auto-create a job.

``propose_topics`` is pure: given recent titles, an avoid list and a request size it returns
scored candidates. The mock path is deterministic (stable ordering, no RNG); the live path sends
the same inputs through the TopicSelectionAgent prompt and parses the same candidate shape, so a
candidate's contract is identical whichever path produced it.

Proposals are metadata for the operator. Nothing here creates a job row — a scheduler that
spends money unattended stays off (product premise; ``SHORTS_SCHEDULER_ENABLED`` only claims
jobs an operator already created).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..contracts.state import JobState
from ..providers.base import Capability
from ..providers.resolve import Binding, resolve_call
from .runner import Stage, StageContext, StageError, StageOutcome

DISCOVERY_AGENT = "DirectorAgent"
DISCOVERY_STAGE = "IDEA_DISCOVERY"
TOPICS_NAME = "topics.json"
#: How many recent job titles seed the avoid list when the caller does not pass one.
AVOID_SEED = 10

TOPIC_CANDIDATE_FIELDS = frozenset({"title", "angle", "why"})

TOPIC_SYSTEM_PROMPT = (
    "You propose topics for 30-60 second vertical videos. Return ONLY JSON: "
    '{"schema_version": 1, "candidates": [{"title": str, "angle": str, "why": str}]}. '
    "Every candidate must be distinct from the titles to avoid. Keep titles under 80 characters."
)


def propose_topics(
    *,
    history: list[dict[str, Any]],
    avoid: set[str] | list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Scored, deterministic topic candidates derived from recent job titles.

    History titles are *signal*, not proposals: their salient words are counted, and each
    strong theme becomes a new candidate title the produced history has not used verbatim.
    Avoid-list titles (recent job titles and prior proposals) are excluded as candidates and
    their salient words are not re-proposed as a whole-title repeat. Scoring is deterministic:
    word frequency ranks themes, ties break by content hash.
    """
    from collections import Counter

    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "how", "why",
        "what", "di", "dan", "yang", "untuk", "dengan", "cara",
    }
    avoid_lower = {t.strip().lower() for t in avoid if isinstance(t, str) and t.strip()}

    word_freq: Counter[str] = Counter()
    for row in history:
        title = str(row.get("title") or "")
        words = [w for w in title.lower().split() if w not in stop]
        word_freq.update(words)

    # The two most frequent salient words form one theme; deterministic tie-break by word.
    # No frequency floor: a one-job history is exactly the "cold start" case discovery exists
    # for, and the avoid list already blocks repeats.
    ranked = sorted(word_freq.items(), key=lambda item: (-item[1], item[0]))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for word, count in ranked:
        if len(candidates) >= max(1, limit):
            break
        title = f"Sisi lain {word}"
        if title.lower() in seen or title.lower() in avoid_lower:
            continue
        seen.add(title.lower())
        digest = hashlib.sha256(f"{word}|{count}".encode()).hexdigest()[:8]
        candidates.append(
            {
                "title": title,
                "angle": f"tema '{word}' muncul {count}x di judul terakhir",
                "why": (
                    "sinyal historis terkuat berikutnya; belum pernah diproduksi"
                    if len(candidates) else "sinyal historis terkuat; belum pernah diproduksi"
                ),
                "score": round(count / max(1, sum(word_freq.values())), 4),
                "source": "history",
                "digest": digest,
            }
        )
    return candidates


def recent_titles(store: Any, *, limit: int = AVOID_SEED) -> list[dict[str, Any]]:
    """Newest-first title rows from the job store — the discovery history."""
    rows = store.list(limit=limit)
    out: list[dict[str, Any]] = []
    for job in rows:
        try:
            payload = json.loads(job.payload) if isinstance(job.payload, str) else job.payload
        except (TypeError, ValueError):
            payload = {}
        out.append({"title": job.title, "topic": (payload or {}).get("topic")})
    return out


def parse_candidate_list(raw: str) -> list[dict[str, Any]]:
    """Parse a live provider reply into candidates, dropping malformed rows.

    A malformed reply is not retried here: the stage records what it received and the operator
    sees the blockers, which is cheaper than inventing a repair loop for a discovery call.
    """
    try:
        payload = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        if not TOPIC_CANDIDATE_FIELDS <= set(entry):
            continue
        title = str(entry["title"]).strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "angle": str(entry.get("angle", "")).strip(),
                "why": str(entry.get("why", "")).strip(),
                "source": "model",
            }
        )
    return out


def build_discovery_stage(state: Any, *, limit: int = 5) -> Stage:
    """``IDEA_DISCOVERY`` outside any job: persist one discovery run's candidates.

    The stage shape reuses the runner's types, but this stage is invoked directly by the API
    route with a discovery id (not a job id): the store methods it calls are the additive
    ``topic_discoveries`` ones. ``limit`` caps candidate count regardless of provider path.
    """

    def run(ctx: StageContext) -> StageOutcome:
        store, discovery_id = ctx.store, ctx.job_id
        titles = recent_titles(store)
        avoid = store.topic_avoid_list(limit=AVOID_SEED)
        events = getattr(state, "events", None)
        if events is not None:
            events.emit(
                job_id=discovery_id,
                agent_id=DISCOVERY_AGENT,
                event_type="stage_started",
                stage=DISCOVERY_STAGE,
                description=f"discovery mulai: {len(titles)} judul histori, {len(avoid)} avoid",
            )
        # Live providers first, mock only as a documented fallback: a discovery is still real
        # work worth accounting, and NoProviderAvailable-like configs must not hide behind mock.
        primary = next(
            (
                spec.id
                for spec in state.registry.enabled()
                if spec.transport != "mock"
            ),
            "mock" if state.registry.specs.get("mock") else None,
        )
        binding = Binding(
            agent=DISCOVERY_AGENT,
            primary=primary,
            fallback=(),
            requires=frozenset({Capability.CHAT}),
        )
        try:
            call, transport = resolve_call(
                binding=binding,
                registry=state.registry,
                store=state.secrets,
                transports=state.transports,
                allow_mock_fallback=True,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a blocked discovery, not a 500
            raise StageError("no_provider", str(exc), retryable=False) from exc
        mock = call.provider == "mock"

        if mock:
            candidates = propose_topics(history=titles, avoid=avoid, limit=limit)
        else:
            spec = state.registry.specs.get(call.provider)
            from ..providers.usage import RecordingProvider

            recorder = RecordingProvider(
                transport,
                tracker=state.usage,
                agent=DISCOVERY_AGENT,
                job_id=discovery_id,
                price_in=spec.price_in_per_mtok if spec else None,
                price_out=spec.price_out_per_mtok if spec else None,
            )
            user = (
                f"Recent production titles: {json.dumps([t['title'] for t in titles], ensure_ascii=False)}\n"
                f"Do not repeat: {json.dumps(avoid, ensure_ascii=False)}\n"
                "Propose distinct topics."
            )
            result = recorder.complete(call, system=TOPIC_SYSTEM_PROMPT, user=user, task="topic_discovery")
            candidates = parse_candidate_list(result.content)
            candidates = [c for c in candidates if c["title"].lower() not in {a.lower() for a in avoid}]

        payload = {
            "schema_version": 1,
            "discovery_id": discovery_id,
            "provider": call.provider,
            "provider_mode": "mock" if mock else "live",
            "avoid": avoid,
            "history_titles": [t["title"] for t in titles],
            "candidates": candidates,
        }
        store.record_topic_discovery(
            discovery_id=discovery_id,
            payload=payload,
            titles=[c["title"] for c in candidates],
        )
        if events is not None:
            events.emit(
                job_id=discovery_id,
                agent_id=DISCOVERY_AGENT,
                event_type="stage_completed",
                stage=DISCOVERY_STAGE,
                description=f"discovery selesai: {len(candidates)} kandidat ({payload['provider_mode']})",
            )
        return StageOutcome(ok=True, artifacts=[TOPICS_NAME])

    return Stage(name=DISCOVERY_STAGE, state=JobState.IDEA_DISCOVERY, produces=(TOPICS_NAME,), run=run)


__all__ = [
    "DISCOVERY_AGENT",
    "DISCOVERY_STAGE",
    "TOPICS_NAME",
    "TOPIC_SYSTEM_PROMPT",
    "build_discovery_stage",
    "parse_candidate_list",
    "propose_topics",
    "recent_titles",
]
