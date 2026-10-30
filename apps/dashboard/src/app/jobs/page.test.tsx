import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import type { JobDetail } from "@/lib/api";
import JobsPage from "./page";

/**
 * Regression test for the polling remount bug.
 *
 * `loadDetail` set `detailLoading` and the page rendered `JobDetails` only when `!detailLoading`,
 * so every 1-second poll unmounted the whole panel. Two visible consequences: the panel blinked
 * once a second, and any transient `decisionMessage` (set by cancel/approve/reject) vanished
 * before an operator could read it. The Playwright spec caught it as
 * `getByText('Pembatalan diminta.')` not being visible.
 */

const job: JobDetail = {
  id: "job-1",
  title: "E2E cancel",
  state: "RUNNING",
  attempts: 0,
  provider_mode: "mock",
  is_mock: true,
  created_at: "2026-10-25T10:00:00+00:00",
  updated_at: "2026-10-25T10:01:00+00:00",
  last_error: null,
  priority: 5,
  scheduled_for: null,
  running: true,
  payload: {},
  artifacts: ["storyboard.json"],
  events: [],
  usage: [],
  has_video: false,
};

const jobView = {
  id: job.id,
  title: job.title,
  state: job.state,
  attempts: job.attempts,
  provider_mode: job.provider_mode,
  is_mock: job.is_mock,
  created_at: job.created_at,
  updated_at: job.updated_at,
  last_error: job.last_error,
  priority: job.priority,
  scheduled_for: job.scheduled_for,
  running: job.running,
};

/** Resolves on demand, so a refresh can be held in flight while assertions run. */
let pendingDetail: Promise<JobDetail> | null = null;
let releaseRefresh: () => void = () => {};
let jobCalls = 0;
let cancelCalls = 0;

// `vi.mock` is hoisted above the imports, so the factory's dependencies must be hoisted too.
const apiMock = vi.hoisted(() => ({
  jobs: vi.fn(),
  job: vi.fn(),
  cancelJob: vi.fn(),
  createJob: vi.fn(),
  runJob: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  deleteJob: vi.fn(),
  health: vi.fn(),
  providers: vi.fn(),
  saveProvider: vi.fn(),
  testProvider: vi.fn(),
  providerModels: vi.fn(),
  usageToday: vi.fn(),
  snapshot: vi.fn(),
  history: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
  videoUrl: (id: string) => `/api/jobs/${id}/video`,
}));

beforeEach(() => {
  pendingDetail = null;
  jobCalls = 0;
  cancelCalls = 0;
  vi.clearAllMocks();

  apiMock.jobs.mockImplementation(async () => ({ jobs: [jobView] }));
  apiMock.job.mockImplementation(() => {
    jobCalls += 1;
    // The first load resolves immediately; later refreshes hang until the test releases them.
    if (pendingDetail) return pendingDetail;
    return Promise.resolve(job);
  });
  apiMock.cancelJob.mockImplementation(async () => {
    cancelCalls += 1;
    return { cancel_requested: true, job_id: job.id, reason: "" };
  });

  window.history.replaceState(null, "", "/jobs?job_id=job-1");
});

afterEach(cleanup);

/** Hold the next detail fetch open, simulating a poll that has not returned yet. */
const holdRefresh = () => {
  // `Promise.withResolvers` needs lib ES2024; this package targets ES2022, and widening the
  // lib for a test helper is not worth it.
  pendingDetail = new Promise<JobDetail>((resolve) => {
    releaseRefresh = () => resolve(job);
  });
};

const releaseAndSettle = async () => {
  await act(async () => {
    releaseRefresh();
    pendingDetail = null;
    await Promise.resolve();
  });
};

test("the detail panel stays on screen while a refresh is in flight", async () => {
  render(<JobsPage />);

  await screen.findByRole("heading", { name: "E2E cancel" });
  expect(screen.getByText(`ID: ${job.id}`)).toBeTruthy();

  // Hold the next detail fetch open: this is what a 1-second poll looks like mid-flight.
  holdRefresh();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 1100));
  });

  expect(jobCalls).toBeGreaterThan(1);
  // The panel must NOT have been replaced by the full-page loading state.
  expect(screen.queryByText("Memuat detail job…")).toBeNull();
  expect(screen.getByRole("heading", { name: "E2E cancel" })).toBeTruthy();
  expect(screen.getByText(`ID: ${job.id}`)).toBeTruthy();
  // ...and a non-blocking indicator tells the operator a refresh is happening.
  expect(screen.getByText("memuat ulang…")).toBeTruthy();

  await releaseAndSettle();
});

test("a decision message survives a refresh", async () => {
  render(<JobsPage />);
  await screen.findByRole("heading", { name: "E2E cancel" });

  const cancel = screen.getByRole("button", { name: "Batalkan job" });
  await waitFor(() => expect(cancel.hasAttribute("disabled")).toBe(false));

  // Make the refresh triggered by the cancel hang, exactly like a slow poll.
  holdRefresh();
  await act(async () => {
    cancel.click();
    await Promise.resolve();
  });

  expect(cancelCalls).toBe(1);
  await waitFor(() => expect(screen.getByText("Pembatalan diminta.")).toBeTruthy());

  // Still visible WHILE the refresh is pending — the original bug lost it here.
  expect(screen.getByText("Pembatalan diminta.")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "E2E cancel" })).toBeTruthy();

  await releaseAndSettle();

  // And still visible after the refresh resolves.
  expect(screen.getByText("Pembatalan diminta.")).toBeTruthy();
});

test("a failed refresh keeps the panel and shows an inline banner", async () => {
  render(<JobsPage />);
  await screen.findByRole("heading", { name: "E2E cancel" });

  // A rejected promise reused across calls would be an unhandled rejection; attach the handler
  // once and let the page's own catch observe it.
  const failure = Promise.reject(new Error("gagal menyegarkan"));
  failure.catch(() => {});
  pendingDetail = failure;

  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 1100));
  });

  // Panel survives.
  expect(screen.getByRole("heading", { name: "E2E cancel" })).toBeTruthy();
  // Error is surfaced inline with a retry, not by replacing the panel.
  await waitFor(() => expect(screen.getByText("gagal menyegarkan")).toBeTruthy());
  expect(screen.getByRole("button", { name: "Coba lagi" })).toBeTruthy();

  pendingDetail = null;
});

test.each(["success", "failure"])("a late %s for another job cannot replace selected production controls", async (outcome) => {
  const other = { ...job, id: "job-2", title: "Produksi terpilih", running: false };
  apiMock.jobs.mockResolvedValue({ jobs: [jobView, other] });
  let resolve!: (detail: JobDetail) => void;
  let reject!: (error: Error) => void;
  const delayed = new Promise<JobDetail>((yes, no) => { resolve = yes; reject = no; });
  apiMock.job.mockImplementation((id: string) => id === job.id ? delayed : Promise.resolve(other));
  render(<JobsPage />);
  await waitFor(() => expect(apiMock.job).toHaveBeenCalledWith(job.id));

  act(() => screen.getByRole("button", { name: /Produksi terpilih/ }).click());
  await screen.findByRole("heading", { name: other.title });
  await act(async () => {
    if (outcome === "success") resolve(job);
    else reject(new Error("Respons job lama gagal"));
  });

  expect(screen.getByRole("heading", { name: other.title })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: job.title })).toBeNull();
  expect(screen.queryByText("Respons job lama gagal")).toBeNull();
});
