import { act, cleanup, renderHook } from "@testing-library/react";
import type { StudioSnapshot } from "./api";
import { useStudio } from "./useStudio";

class FakeEventSource {
  readonly url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    sources.push(this);
    queueMicrotask(() => {
      if (!this.closed) this.onopen?.();
    });
  }

  close(): void {
    this.closed = true;
  }

  emit(id: number | ""): void {
    if (!this.closed) {
      this.onmessage?.(new MessageEvent("message", { data: "{}", lastEventId: String(id) }));
    }
  }

  fail(): void {
    if (!this.closed) this.onerror?.();
  }
}

type PendingRead = {
  url: URL;
  claimed: boolean;
  respond: (body: StudioSnapshot, global?: StudioSnapshot) => void;
  reject: (error: Error) => void;
};

let sources: FakeEventSource[];
let reads: PendingRead[];

const snapshot = (cursor: number, jobId?: string, task = "persisted task"): StudioSnapshot => ({
  cursor,
  job_id: jobId ?? null,
  generated_at: "2026-10-25T10:00:00+00:00",
  agents: [{
    agent_id: "scriptwriter",
    status: "working",
    stale: false,
    task,
    progress: 0.4,
    model: null,
    stage: "script",
    job_id: jobId ?? "global-job",
    updated_at: "2026-10-25T10:00:00+00:00",
    recent: [],
  }],
});

function takeRead(jobId?: string): PendingRead {
  const read = reads.find((candidate) => !candidate.claimed &&
    candidate.url.searchParams.get("job_id") === (jobId ?? null));
  if (!read) throw new Error(`No pending snapshot for ${jobId ?? "all jobs"}`);
  read.claimed = true;
  if (jobId === undefined) return read;
  const global = takeRead();
  return {
    ...read,
    respond: (body, globalBody) => {
      read.respond(body);
      global.respond(globalBody ?? { ...body, job_id: null });
    },
    reject: (error) => {
      read.reject(error);
      global.reject(error);
    },
  };
}

async function respond(read: PendingRead, body: StudioSnapshot, global?: StudioSnapshot) {
  await act(async () => read.respond(body, global));
}

async function advanceUntil(predicate: () => boolean) {
  for (let step = 0; step < 30 && !predicate(); step++) {
    await act(async () => {
      await vi.advanceTimersToNextTimerAsync();
    });
  }
  expect(predicate()).toBe(true);
}

function liveSource(): FakeEventSource {
  const source = sources.find((candidate) => !candidate.closed);
  if (!source) throw new Error("No live studio stream");
  return source;
}

async function openStream() {
  await advanceUntil(() => sources.some((source) => !source.closed));
  return liveSource();
}

beforeEach(() => {
  sources = [];
  reads = [];
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  vi.setSystemTime(new Date("2026-10-25T10:00:00Z"));
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", (input: string) => new Promise<Response>((resolve, reject) => {
    reads.push({
      url: new URL(input, "http://localhost"),
      claimed: false,
      respond: (body) => resolve(new Response(JSON.stringify(body), { status: 200 })),
      reject,
    });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("no-argument usage waits for a snapshot and reconnects from server event ids, including keepalives", async () => {
  const { result, unmount } = renderHook(() => useStudio());
  expect(result.current.snapshot).toBeNull();
  expect(sources.some((source) => !source.closed)).toBe(false);
  await respond(takeRead(), snapshot(1));
  const live = await openStream();
  expect(live.url).toBe("/api/studio/stream?after=1");
  expect(result.current.connected).toBe(true);

  act(() => {
    live.emit(4);
    live.emit(9);
    live.emit("");
  });
  await respond(takeRead(), snapshot(2));
  act(() => live.fail());
  expect(result.current.connected).toBe(false);
  const resumed = await openStream();
  expect(resumed.url).toBe("/api/studio/stream?after=9");
  expect(result.current.snapshot?.cursor).toBe(2);
  unmount();
});

test.each(["response", "error"] as const)(
  "switching A to B masks A immediately and ignores its late %s",
  async (outcome) => {
    const rendered: Array<{
      jobId: string;
      snapshot: StudioSnapshot | null;
      connected: boolean;
      error: string | null;
      rendering: boolean;
    }> = [];
    const { result, rerender, unmount } = renderHook(({ jobId }) => {
      const studio = useStudio({ jobId, pollMs: 60_000 });
      rendered.push({
        jobId,
        snapshot: studio.snapshot,
        connected: studio.connected,
        error: studio.error,
        rendering: studio.rendering,
      });
      return studio;
    }, { initialProps: { jobId: "A" } });
    const renderingA = snapshot(10, "A", "A is working");
    renderingA.agents = renderingA.agents.map((agent) => ({ ...agent, stage: "RENDERING" }));
    await respond(takeRead("A"), renderingA);
    expect(result.current.rendering).toBe(true);
    const oldStream = await openStream();
    act(() => oldStream.emit(12));
    const lateA = takeRead("A");
    const firstBRender = rendered.length;

    rerender({ jobId: "B" });
    expect(rendered[firstBRender]).toEqual({
      jobId: "B", snapshot: null, connected: false, error: null, rendering: false,
    });
    expect(result.current.agents).toEqual([]);
    expect(oldStream.closed).toBe(true);
    expect(sources.some((source) => !source.closed)).toBe(false);
    await respond(takeRead("B"), snapshot(20, "B", "B is working"));
    const bStream = await openStream();

    await act(async () => {
      if (outcome === "response") lateA.respond(snapshot(99, "A", "A finished later"));
      else lateA.reject(new Error("A is unavailable"));
    });
    expect(result.current.snapshot?.job_id).toBe("B");
    expect(result.current.agents[0]?.task).toBe("B is working");
    expect(result.current.error).toBeNull();
    act(() => bStream.fail());
    expect((await openStream()).url).toBe("/api/studio/stream?after=20");
    unmount();
  },
);

test("a selection change cancels pending reconnects and keeps the global resume cursor", async () => {
  const { result, rerender, unmount } = renderHook(({ jobId }) => useStudio({ jobId, pollMs: 60_000 }), {
    initialProps: { jobId: "A" },
  });
  await respond(takeRead("A"), snapshot(10, "A"));
  const old = await openStream();
  const lateOpen = old.onopen;
  const lateMessage = old.onmessage;
  const lateError = old.onerror;
  act(() => {
    old.emit(40);
    old.fail();
  });
  const lateRead = takeRead("A");
  rerender({ jobId: "B" });
  await respond(takeRead("B"), snapshot(30, "B"));
  const selected = await openStream();
  expect(selected.url).toBe("/api/studio/stream?after=40");
  expect(new URL(selected.url, "http://localhost").searchParams.has("job_id")).toBe(false);
  await act(async () => {
    lateRead.respond(snapshot(90, "A"));
    lateOpen?.();
    lateMessage?.(new MessageEvent("message", { data: "{}", lastEventId: "100" }));
    lateError?.();
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(sources.filter((source) => !source.closed)).toEqual([selected]);
  expect(result.current.snapshot?.job_id).toBe("B");
  expect(result.current.connected).toBe(true);
  act(() => selected.fail());
  expect((await openStream()).url).toBe("/api/studio/stream?after=40");
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

test("out-of-order same-scope responses cannot rewind the projection", async () => {
  const { result, unmount } = renderHook(() => useStudio({ jobId: "A", pollMs: 60_000 }));
  await respond(takeRead("A"), snapshot(1, "A"));
  const live = await openStream();
  act(() => {
    live.emit(10);
    live.emit(20);
  });
  const older = takeRead("A");
  const newer = takeRead("A");
  await respond(newer, snapshot(20, "A", "latest projection"));
  await respond(older, snapshot(10, "A", "obsolete projection"));
  expect(result.current.snapshot?.cursor).toBe(20);
  expect(result.current.agents[0]?.task).toBe("latest projection");

  act(() => live.emit(21));
  const laterButStale = takeRead("A");
  await respond(laterButStale, snapshot(19, "A", "stale read"));
  expect(result.current.agents[0]?.task).toBe("latest projection");
  act(() => live.fail());
  expect((await openStream()).url).toBe("/api/studio/stream?after=21");
  unmount();
});

test("a same-cursor older response or error cannot replace a newer result", async () => {
  const { result, unmount } = renderHook(() => useStudio({ jobId: "A", pollMs: 60_000 }));
  await respond(takeRead("A"), snapshot(1, "A"));
  const live = await openStream();
  act(() => {
    live.emit(2);
    live.emit(2);
    live.emit(2);
  });
  const oldResponse = takeRead("A");
  const oldError = takeRead("A");
  const latest = takeRead("A");
  await respond(latest, snapshot(2, "A", "current lease projection"));
  await respond(oldResponse, snapshot(2, "A", "older lease projection"));
  await act(async () => oldError.reject(new Error("old failure")));
  expect(result.current.agents[0]?.task).toBe("current lease projection");
  expect(result.current.error).toBeNull();
  unmount();
});

test("unmount cancels reconnects, closes the stream, and ignores late network completion", async () => {
  const { result, unmount } = renderHook(() => useStudio({ pollMs: 60_000 }));
  await respond(takeRead(), snapshot(1));
  const live = await openStream();
  act(() => {
    live.emit(8);
    live.fail();
  });
  const late = takeRead();
  const finalView = result.current;
  unmount();
  expect(live.closed).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
  await act(async () => {
    late.respond(snapshot(100));
    await vi.advanceTimersByTimeAsync(120_000);
  });
  expect(sources.some((source) => !source.closed)).toBe(false);
  expect(result.current).toBe(finalView);
});

test("a silent global stream resumes after watchdog expiry", async () => {
  const { unmount } = renderHook(() => useStudio({ pollMs: 60_000 }));
  await respond(takeRead(), snapshot(6));
  const silent = await openStream();
  await advanceUntil(() => silent.closed);
  expect(liveSource()).not.toBe(silent);
  expect(liveSource().url).toBe("/api/studio/stream?after=6");
  unmount();
});

test("snapshot selection safely round-trips query delimiters without filtering the stream", async () => {
  const jobId = "job & #/with?details=1";
  const { result, unmount } = renderHook(() => useStudio({ jobId, pollMs: 60_000 }));
  const read = takeRead(jobId);
  expect([...read.url.searchParams.keys()]).toEqual(["job_id"]);
  await respond(read, snapshot(3, jobId));
  expect(result.current.snapshot?.job_id).toBe(jobId);
  expect((await openStream()).url).toBe("/api/studio/stream?after=3");
  unmount();
});

test.each([false, true])("selected B stays idle while global render safety honors stale=%s", async (stale) => {
  const { result, unmount } = renderHook(() => useStudio({ jobId: "B", pollMs: 60_000 }));
  const selected = snapshot(10, "B");
  selected.agents = selected.agents.map((agent) => ({
    ...agent, status: "waiting", task: "", stage: null, job_id: null, updated_at: null,
  }));
  const global = snapshot(10, undefined, "A is rendering");
  global.agents = global.agents.map((agent) => ({
    ...agent, stage: "RENDERING", job_id: "A", stale,
  }));
  await respond(takeRead("B"), selected, global);
  expect(result.current.rendering).toBe(!stale);
  expect(result.current.snapshot?.job_id).toBe("B");
  expect(result.current.agents[0]?.status).toBe("waiting");
  expect(result.current.agents.some((agent) => agent.job_id === "A")).toBe(false);
  unmount();
});

test("a stale global half cannot rewind render safety even when the selected half advances", async () => {
  const { result, unmount } = renderHook(() => useStudio({ jobId: "B", pollMs: 60_000 }));
  const renderingA = snapshot(40, undefined, "A is rendering");
  renderingA.agents = renderingA.agents.map((agent) => ({ ...agent, stage: "RENDERING", job_id: "A" }));
  await respond(takeRead("B"), snapshot(30, "B"), renderingA);
  const live = await openStream();
  expect(result.current.rendering).toBe(true);
  act(() => live.emit(41));
  await respond(takeRead("B"), snapshot(41, "B"), snapshot(39));
  expect(result.current.rendering).toBe(true);
  expect(result.current.snapshot?.cursor).toBe(30);
  act(() => live.emit(42));
  await respond(takeRead("B"), snapshot(42, "B"), snapshot(42));
  expect(result.current.rendering).toBe(false);
  expect(result.current.snapshot?.cursor).toBe(42);
  unmount();
});

test("unmount immediately after switching during reconnect clears both generations' timers", async () => {
  const { rerender, unmount } = renderHook(({ jobId }) => useStudio({ jobId, pollMs: 60_000 }), {
    initialProps: { jobId: "A" },
  });
  await respond(takeRead("A"), snapshot(1, "A"));
  const previous = await openStream();
  act(() => previous.fail());
  rerender({ jobId: "B" });
  const pendingB = takeRead("B");
  unmount();
  expect(vi.getTimerCount()).toBe(0);
  await act(async () => {
    pendingB.respond(snapshot(20, "B"));
    await vi.advanceTimersByTimeAsync(120_000);
  });
  expect(sources.some((source) => !source.closed)).toBe(false);
});
