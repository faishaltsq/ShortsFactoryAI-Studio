import { renderHook, waitFor } from "@testing-library/react";
import { useStudio } from "./useStudio";

type FakeSource = {
  url: string;
  lastEventId: string;
  onopen: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  close: () => void;
  emit: (id: number) => void;
  fail: () => void;
};

let sources: FakeSource[] = [];

class FakeEventSource implements FakeSource {
  url: string;
  lastEventId = "";
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    sources.push(this);
    queueMicrotask(() => this.onopen?.());
  }

  close(): void {
    this.onmessage = null;
    this.onerror = null;
  }

  emit(id: number): void {
    this.lastEventId = String(id);
    this.onmessage?.(new MessageEvent("message", { data: "{}", lastEventId: String(id) }));
  }

  fail(): void {
    this.onerror?.();
  }
}

const snapshot = (cursor: number) => ({
  cursor,
  job_id: null,
  agents: [],
  generated_at: "2026-10-25T10:00:00+00:00",
});

const fetchMock = vi.fn(async () => new Response(JSON.stringify(snapshot(1)), { status: 200 }));

beforeEach(() => {
  sources = [];
  fetchMock.mockClear();
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("a reconnect resumes from the server's last event id, not from a message count", async () => {
  const { unmount } = renderHook(() => useStudio(60_000));
  // The stream opens only after the snapshot has established the resume point.
  await waitFor(() => expect(sources).toHaveLength(1), { timeout: 2000 });
  const live = sources[0];
  if (live === undefined) throw new Error("the stream never opened");
  expect(live.url).toBe("/api/studio/stream?after=1");

  live.emit(4);
  live.emit(7);
  // Each message refreshes the snapshot; two messages means two more reads than the initial one.
  await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3));

  vi.useFakeTimers();
  live.fail();
  await vi.advanceTimersByTimeAsync(2000);

  vi.useRealTimers();
  await waitFor(() => expect(sources.length).toBeGreaterThanOrEqual(2), { timeout: 3000 });
  expect(sources.at(-1)?.url).toBe("/api/studio/stream?after=7");
  unmount();
});

test("a keepalive without an id never rewinds the cursor", async () => {
  const { unmount } = renderHook(() => useStudio(60_000));
  await waitFor(() => expect(sources).toHaveLength(1), { timeout: 2000 });
  const live = sources[0];
  if (live === undefined) throw new Error("the stream never opened");
  live.emit(9);
  // A comment frame carries no id; the hook must not treat it as event 0.
  live.onmessage?.(new MessageEvent("message", { data: "", lastEventId: "" }));
  vi.useFakeTimers();
  live.fail();
  await vi.advanceTimersByTimeAsync(2000);
  vi.useRealTimers();
  await waitFor(() => expect(sources.length).toBeGreaterThanOrEqual(2), { timeout: 3000 });
  expect(sources.at(-1)?.url).toBe("/api/studio/stream?after=9");
  unmount();
});
