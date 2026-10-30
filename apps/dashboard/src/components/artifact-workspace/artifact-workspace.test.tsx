import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { JobDetail } from "@/lib/api";
import StoryboardPage from "@/app/storyboard/page";
import AssetsPage from "@/app/assets/page";
import { readAudio, readStoryboard } from "./artifacts";

const apiMock = vi.hoisted(() => ({ jobs: vi.fn(), job: vi.fn(), artifact: vi.fn(), catalog: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock }));
const job = (id: string): JobDetail => ({
  id, title: `Production ${id}`, state: "STORYBOARD_READY", attempts: 0, provider_mode: "mock", is_mock: true,
  created_at: "2026-10-29T00:00:00Z", updated_at: "2026-10-29T00:00:00Z", last_error: null,
  priority: 0, scheduled_for: null, running: false, payload: {}, artifacts: ["storyboard.json", "assets.json"],
  events: [], usage: [], has_video: false,
});
const storyboard = (id: string, duration = 90) => ({ fps: 30, scenes: [{
  sceneId: `scene-${id}`, template: "IllustratedStory", segment: "s1", startFrame: 0,
  durationInFrames: duration, assetRefs: [`character:${id}`], text: [{ id: "t1", text: `Narrative ${id}` }],
  camera: { shot: "wide", move: "static" }, motion: { beats: [] }, transition: { kind: "cut" },
}] });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((release) => { resolve = release; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState({ retained: true }, "", "/storyboard?job_id=A");
  apiMock.jobs.mockResolvedValue({ jobs: [job("A"), job("B")] });
  apiMock.job.mockImplementation(async (id: string) => job(id));
  apiMock.artifact.mockImplementation(async (id: string, name: string) => name === "assets.json" ? { characters: [{ id }], backgrounds: [], audio: [] } : storyboard(id));
  apiMock.catalog.mockResolvedValue({ characters: [] });
});
afterEach(cleanup);

test("late storyboard replies cannot replace the newly selected job and popstate restores the selection", async () => {
  const late = deferred<Record<string, unknown>>();
  apiMock.artifact.mockImplementation((id: string) => id === "A" ? late.promise : Promise.resolve(storyboard(id)));
  render(<StoryboardPage />);
  await waitFor(() => expect(apiMock.artifact).toHaveBeenCalledWith("A", "storyboard.json"));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "B" } });
  await screen.findByText("Narrative B");
  expect(new URLSearchParams(window.location.search).get("job_id")).toBe("B");
  expect(window.history.state).toEqual({ retained: true });
  await act(async () => { late.resolve(storyboard("A")); await late.promise; });
  expect(screen.queryByText("Narrative A")).toBeNull();
  expect(screen.getByText("Narrative B")).toBeTruthy();
  await act(async () => {
    window.history.replaceState(window.history.state, "", "/storyboard?job_id=A");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await screen.findByText("Narrative A");
  expect(screen.queryByText("Narrative B")).toBeNull();
});

test("late job detail does not trigger old artifact requests after an assets job switch", async () => {
  const late = deferred<JobDetail>();
  apiMock.job.mockImplementation((id: string) => id === "A" ? late.promise : Promise.resolve(job(id)));
  render(<AssetsPage />);
  await waitFor(() => expect(apiMock.job).toHaveBeenCalledWith("A"));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "B" } });
  await screen.findByRole("heading", { name: "Production B" });
  await act(async () => { late.resolve(job("A")); await late.promise; });
  expect(apiMock.artifact.mock.calls.some(([id]) => id === "A")).toBe(false);
  expect(screen.queryByRole("heading", { name: "Production A" })).toBeNull();
});

test("a missing deep-linked job stays selected even with an empty store and a later list refresh", async () => {
  window.history.replaceState(null, "", "/storyboard?job_id=missing");
  apiMock.jobs.mockResolvedValue({ jobs: [] });
  apiMock.job.mockRejectedValue(new Error("HTTP 404"));
  render(<StoryboardPage />);
  await screen.findByRole("alert");
  expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("missing");
  fireEvent.click(screen.getByRole("button", { name: "Muat ulang daftar" }));
  await waitFor(() => expect(apiMock.jobs).toHaveBeenCalledTimes(2));
  expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("missing");
  expect(apiMock.artifact).not.toHaveBeenCalled();
});

test("unreadable artifacts offer retry and malformed scenes are rejected without rendering previous data", async () => {
  apiMock.artifact.mockRejectedValueOnce(new Error("HTTP 503"));
  render(<StoryboardPage />);
  await screen.findByRole("alert");
  apiMock.artifact.mockResolvedValue(storyboard("A", -1));
  fireEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
  await waitFor(() => expect(apiMock.artifact).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Timing"));
  expect(screen.queryByText("Narrative A")).toBeNull();
  expect(() => readStoryboard({ ...storyboard("A"), scenes: [null] })).toThrow();
  expect(() => readStoryboard({ ...storyboard("A"), fps: 0 })).toThrow();
});

test("persisted timed render props take precedence over the planned storyboard", async () => {
  apiMock.job.mockResolvedValue({ ...job("A"), artifacts: ["storyboard.json", "render-props.json"] });
  apiMock.artifact.mockImplementation(async (_id: string, name: string) => name === "render-props.json" ? { storyboard: storyboard("timed", 45) } : storyboard("plan", 300));
  render(<StoryboardPage />);
  await screen.findByText("Narrative timed");
  expect(screen.queryByText("Narrative plan")).toBeNull();
  expect(screen.getAllByText(/1\.50 s/).length).toBeGreaterThan(0);
});

test("audio timing outside narration or out of order is not presented as measured timing", () => {
  const audio = { narration: { src: "narration.wav", durationMs: 1000 }, mix: {}, scenes: [{ sceneId: "sc1", startMs: 0, endMs: 1100 }] };
  expect(() => readAudio(audio)).toThrow();
  expect(() => readAudio({ ...audio, scenes: [{ sceneId: "sc1", startMs: 0, endMs: 700 }, { sceneId: "sc2", startMs: 600, endMs: 900 }] })).toThrow();
});
