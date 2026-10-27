import {
  isWorking,
  nextTierOnFrameTime,
  renderingActive,
  stateColor,
  WAITING_COLOR,
} from "./sceneState";

/**
 * Colour and motion rules the WebGL scene obeys. The scene itself cannot be rendered in jsdom,
 * so these are the parts of it a test can hold: a new server status must not crash the scene and
 * must not render as working.
 */
describe("scene colour", () => {
  test("covers every status the server can send", () => {
    // `waiting` and `idle` deliberately share the resting colour; every other state must be
    // distinguishable, otherwise the scene shows a blocked character as merely waiting.
    for (const status of ["working", "blocked", "failed", "completed"]) {
      expect(stateColor(status)).toMatch(/^#[0-9a-f]{6}$/);
      expect(stateColor(status)).not.toBe(WAITING_COLOR);
    }
    expect(stateColor("waiting")).toBe(WAITING_COLOR);
    expect(stateColor("idle")).toBe(WAITING_COLOR);
  });

  test("falls back to the waiting colour for an unknown key", () => {
    expect(stateColor("requeued")).toBe(WAITING_COLOR);
    expect(stateColor(null)).toBe(WAITING_COLOR);
    expect(stateColor(undefined)).toBe(WAITING_COLOR);
  });
});

describe("scene motion", () => {
  test("only a persisted working state may animate work", () => {
    for (const state of ["waiting", "idle", "blocked", "failed", "completed", "requeued"]) {
      expect(isWorking(state)).toBe(false);
    }
    expect(isWorking("working")).toBe(true);
  });
});

describe("render pause", () => {
  const rendering = { stage: "RENDERING", status: "working" as const, stale: false };

  test("a working agent at RENDERING pauses the studio", () => {
    expect(renderingActive([rendering])).toBe(true);
    // A second, unrelated agent must not mask the active render.
    expect(
      renderingActive([{ stage: "RESEARCH_COMPLETE", status: "working", stale: false }, rendering]),
    ).toBe(true);
  });

  test("a stale lease is not an active render", () => {
    expect(renderingActive([{ ...rendering, stale: true }])).toBe(false);
  });

  test("a non-RENDERING stage never pauses", () => {
    expect(renderingActive([{ stage: "COMPOSING", status: "working", stale: false }])).toBe(false);
    expect(renderingActive([{ stage: null, status: "working", stale: false }])).toBe(false);
  });

  test("an empty projection never pauses", () => {
    expect(renderingActive([])).toBe(false);
  });

  test("a settled RENDERING agent is not an active render", () => {
    expect(renderingActive([{ stage: "RENDERING", status: "completed", stale: false }])).toBe(false);
    expect(renderingActive([{ stage: "RENDERING", status: "failed", stale: false }])).toBe(false);
    expect(renderingActive([{ stage: "RENDERING", status: "blocked", stale: false }])).toBe(false);
    expect(renderingActive([{ stage: "RENDERING", status: "waiting", stale: false }])).toBe(false);
  });

  test("the resolved state wins over the raw status when both are present", () => {
    // `characterState` already turned a stale working agent into `waiting`; the predicate must
    // honour that resolution rather than resurrect the raw `working`.
    expect(
      renderingActive([{ stage: "RENDERING", status: "working", stale: true, state: "waiting" }]),
    ).toBe(false);
    expect(
      renderingActive([{ stage: "RENDERING", status: "working", stale: false, state: "working" }]),
    ).toBe(true);
  });
});

describe("quality auto-downgrade", () => {
  // 33 ms is the budget floor: at or below it the current tier stays.
  const cases: Array<{ median: number; from: "high" | "medium" | "low"; to: "high" | "medium" | "low" }> = [
    { median: 40, from: "high", to: "medium" },
    { median: 40, from: "medium", to: "low" },
    { median: 40, from: "low", to: "low" },
    { median: 33, from: "high", to: "high" },
    { median: 33, from: "medium", to: "medium" },
    { median: 33, from: "low", to: "low" },
    { median: 20, from: "high", to: "high" },
    { median: 20, from: "medium", to: "medium" },
    { median: 20, from: "low", to: "low" },
  ];

  test.each(cases)("median $median ms from $from yields $to", ({ median, from, to }) => {
    expect(nextTierOnFrameTime(from, median)).toBe(to);
  });

  test("one step at a time, so a single slow window cannot skip the low tier", () => {
    expect(nextTierOnFrameTime(nextTierOnFrameTime("high", 200), 200)).toBe("low");
  });
});
