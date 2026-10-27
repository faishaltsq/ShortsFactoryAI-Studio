/**
 * Scene-side state, derived from the persisted snapshot.
 *
 * Two rules from ADR-008 that this file exists to make mechanical:
 *  - colour and motion are derived from a map that covers the union and falls back to the
 *    waiting colour for an unknown key, so a server-side status rename cannot crash the scene;
 *  - "no character may animate work unless its persisted state is working" is a single predicate
 *    (`isWorking`), used by the sampler, not re-derived per prop.
 */

import type { AgentView } from "@/lib/api";
import { characterState, type CharacterState } from "@/lib/studioState";

export type SceneState =
  | "working"
  | "waiting"
  | "idle"
  | "blocked"
  | "failed"
  | "completed";

const SCENE_STATE_COLOR: Record<SceneState, string> = {
  working: "#4a938c",
  waiting: "#8b95a6",
  idle: "#8b95a6",
  blocked: "#d9a03f",
  failed: "#c05c56",
  completed: "#4a9d7f",
};

export const WAITING_COLOR = SCENE_STATE_COLOR.waiting;

/** Colour for a state the server sent; an unknown or missing key renders as waiting. */
export function stateColor(state: string | null | undefined): string {
  if (!state) return WAITING_COLOR;
  return state in SCENE_STATE_COLOR ? SCENE_STATE_COLOR[state as SceneState] : WAITING_COLOR;
}

/** The only predicate that may enable a "doing work" animation. */
export function isWorking(state: string): boolean {
  return state === "working";
}

/** ADR-008: a `RENDERING` event owns the machine while it is active. */
export function renderingActive(
  agents: ReadonlyArray<
    Pick<AgentView, "status" | "stale" | "stage"> & { state?: CharacterState }
  >,
): boolean {
  // `state` is the page's resolution (a stale `working` becomes `waiting`); prefer it when present
  // so a dead lease cannot keep the studio paused.
  return agents.some(
    (agent) => agent.stage === "RENDERING" && (agent.state ?? characterState(agent)) === "working",
  );
}

export type QualityTier = "high" | "medium" | "low";

/** 30 fps budget from `docs/STUDIO_3D.md` §6: a median above this drops a tier. */
export const FRAME_BUDGET_MS = 33;

/**
 * One tier down at most, and `low` is the floor. Pure, so the sampler decides *when* to sample and
 * this decides *what* a slow window means.
 */
export function nextTierOnFrameTime(tier: QualityTier, medianMs: number): QualityTier {
  if (medianMs <= FRAME_BUDGET_MS) return tier;
  return tier === "high" ? "medium" : "low";
}

/**
 * Workstation motion family per zone, from `docs/STUDIO_3D.md` §2. The sampler uses this to pick
 * a motion, never to decide whether motion is allowed: `isWorking` decides that.
 */
export type MotionFamily = "type" | "operate" | "read" | "draw" | "speak" | "scrub" | "pack" | "walk";

export function motionFamilyFor(zoneId: string): MotionFamily {
  switch (zoneId) {
    case "director":
      return "walk";
    case "research":
    case "writing":
      return "type";
    case "review":
      return "read";
    case "storyboard":
      return "draw";
    case "animation":
      return "operate";
    case "audio":
      return "speak";
    case "edit":
      return "scrub";
    case "qc":
      return "read";
    case "publishing":
      return "pack";
    default:
      return "operate";
  }
}
