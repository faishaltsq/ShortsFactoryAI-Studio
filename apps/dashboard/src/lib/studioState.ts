import type { AgentView, StudioStatus } from "./api";

/**
 * What a character may display. A superset of the persisted `StudioStatus`: `idle` is a visual
 * resting state the browser computes, never a status the server writes.
 */
export type CharacterState = "idle" | StudioStatus;

/**
 * A finished stage is a one-shot reaction: `completed` for two seconds, then the character rests.
 * `blocked`/`failed` do not decay — hiding a failure the operator still has to act on would be the
 * opposite of honest. `working` does not decay either: staleness is the server's call.
 */
export const COMPLETED_VISIBLE_MS = 2000;

/**
 * The one place a persisted status becomes a displayed state.
 *
 * Pure in `(status, updated_at, nowMs)`, so the clock lives in the caller and never in the snapshot:
 * a snapshot must not change without a new event, and a timer inside the projection would break
 * that invariant.
 */
export function resolveCharacterState(
  status: StudioStatus | null,
  updatedAt: string | null,
  nowMs: number,
  stale = false,
): CharacterState {
  // ADR-008: an agent with no event idles. That is not `waiting`: nothing is pending, nothing
  // happened, and a grey "waiting" badge would imply a queue position that does not exist.
  if (status === null) return "idle";
  if (status === "working") return stale ? "waiting" : "working";
  if (status !== "completed") return status;
  const updatedMs = updatedAt === null ? Number.NaN : Date.parse(updatedAt);
  if (Number.isNaN(updatedMs) || nowMs - updatedMs >= COMPLETED_VISIBLE_MS) return "idle";
  return "completed";
}

/** An agent carrying its resolved state, so badge, fallback and 3D colour cannot disagree. */
export type ResolvedAgent = AgentView & { state: CharacterState };

/** Resolve every agent against one clock reading. Call it once per render, from the page. */
export function withResolvedStates(agents: AgentView[], nowMs: number): ResolvedAgent[] {
  return agents.map((agent) => ({
    ...agent,
    state: resolveCharacterState(agent.status, agent.updated_at, nowMs, agent.stale),
  }));
}

/**
 * The state a consumer should draw.
 *
 * Prefers the state resolved by `withResolvedStates`, so every surface agrees; falls back to the
 * pure mapping for callers with no clock (tests, and the E2E projection comparison).
 */
export function characterState(
  agent: Pick<AgentView, "status" | "stale"> & { state?: CharacterState },
): CharacterState {
  if (agent.state) return agent.state;
  if (agent.status === "working" && agent.stale) return "waiting";
  return agent.status;
}
