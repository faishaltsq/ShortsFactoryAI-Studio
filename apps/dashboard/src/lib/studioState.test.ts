import type { AgentView, StudioStatus } from "./api";
import {
  COMPLETED_VISIBLE_MS,
  characterState,
  resolveCharacterState,
} from "./studioState";



const UPDATED_AT = "2026-10-25T10:00:00+00:00";
const UPDATED_MS = Date.parse(UPDATED_AT);

test.each<[StudioStatus, StudioStatus]>([
  ["working", "working"],
  ["waiting", "waiting"],
  ["blocked", "blocked"],
  ["failed", "failed"],
  ["completed", "completed"],
])("maps persisted %s status to %s", (status, expected) => {
  expect(characterState({ status, stale: false })).toBe(expected);
});

test("downgrades stale working status to waiting", () => {
  expect(characterState({ status: "working", stale: true })).toBe("waiting");
});

test("an agent with no persisted event idles", () => {
  // ADR-008: "If there is no event for an agent, the character idles." `null` is that absence; a
  // `waiting` status with a real event is a different thing and stays `waiting`.
  expect(resolveCharacterState(null, null, UPDATED_MS)).toBe("idle");
  expect(resolveCharacterState("waiting", null, UPDATED_MS)).toBe("waiting");
});

test.each<[string, number, string]>([
  ["completed 1 ms after the event", 1, "completed"],
  ["completed 1999 ms after the event", 1999, "completed"],
  ["completed 2001 ms after the event", 2001, "idle"],
  ["completed 60 s after the event", 60_000, "idle"],
])("%s reads %s ms -> %s", (_label, offset, expected) => {
  expect(resolveCharacterState("completed", UPDATED_AT, UPDATED_MS + offset)).toBe(expected);
});

test("completed decays to idle exactly at the boundary", () => {
  expect(resolveCharacterState("completed", UPDATED_AT, UPDATED_MS + COMPLETED_VISIBLE_MS - 1)).toBe(
    "completed",
  );
  expect(resolveCharacterState("completed", UPDATED_AT, UPDATED_MS + COMPLETED_VISIBLE_MS)).toBe(
    "idle",
  );
});

test.each<[StudioStatus, number]>([
  ["blocked", 0],
  ["blocked", 60_000],
  ["failed", 0],
  ["failed", 86_400_000],
])("%s never decays (%s ms)", (status, offset) => {
  expect(resolveCharacterState(status, UPDATED_AT, UPDATED_MS + offset)).toBe(status);
});

test("working never decays to idle: staleness is the server's call", () => {
  // A client-side timer must not be able to invent staleness, and must not invent work either.
  expect(resolveCharacterState("working", UPDATED_AT, UPDATED_MS + 86_400_000)).toBe("working");
  expect(resolveCharacterState("working", UPDATED_AT, UPDATED_MS + 86_400_000, true)).toBe(
    "waiting",
  );
});

test("staleness wins over the working mapping but never resurrects a decayed completion", () => {
  expect(resolveCharacterState("working", UPDATED_AT, UPDATED_MS, true)).toBe("waiting");
  expect(resolveCharacterState("completed", null, UPDATED_MS, true)).toBe("idle");
});

test("an unparseable timestamp does not extend the completion", () => {
  expect(resolveCharacterState("completed", "not-a-date", UPDATED_MS)).toBe("idle");
});

test("the completed window is the documented two seconds", () => {
  expect(COMPLETED_VISIBLE_MS).toBe(2000);
});

test("a non-completed status with no timestamp keeps its status, never decays to idle", () => {
  // The projection emits `waiting` with `updated_at: null` for an agent it has no event for on a
  // filtered job view. Decaying that to `idle` would make the canvas disagree with the server.
  for (const status of ["waiting", "blocked", "failed", "working"] as const) {
    expect(resolveCharacterState(status, null, UPDATED_MS)).toBe(status);
  }
});

test("only `completed` and an absent event may resolve to idle", () => {
  const statuses = ["working", "waiting", "blocked", "failed", "completed"] as const;
  for (const status of statuses) {
    expect(resolveCharacterState(status, UPDATED_AT, UPDATED_MS)).not.toBe("idle");
  }
  expect(resolveCharacterState(null, null, UPDATED_MS)).toBe("idle");
});
