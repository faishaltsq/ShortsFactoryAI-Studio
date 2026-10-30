import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { JobDetail } from "@/lib/api";
import { StudioProductionMonitor } from "./StudioProductionMonitor";

function job(id: string, title: string): JobDetail {
  return {
    id, title, state: "CREATED", attempts: 0, provider_mode: "mock", is_mock: true,
    created_at: "2026-10-29T10:00:00+00:00", updated_at: "2026-10-29T10:00:00+00:00",
    last_error: null, priority: 0, scheduled_for: null, running: false,
    payload: {}, artifacts: [], events: [], usage: [], has_video: false,
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("switching selection immediately removes the previous detail, artifacts, and historical error", async () => {
  const first = {
    ...job("first", "Produksi pertama"), has_video: true,
    artifacts: ["first-video.mp4"], last_error: "Error milik produksi pertama",
  };
  const second = job("second", "Produksi kedua");
  const pending = deferred<Response>();
  fetchMock.mockImplementation((path: string) => {
    if (path === "/api/jobs") return Promise.resolve(response({ jobs: [first, second] }));
    if (path === "/api/jobs/first") return Promise.resolve(response(first));
    if (path === "/api/jobs/second") return pending.promise;
    throw new Error(`Unexpected request: ${path}`);
  });
  const onSelectJob = vi.fn();
  const view = render(<StudioProductionMonitor jobId="first" onSelectJob={onSelectJob} />);
  await screen.findByRole("heading", { name: first.title });
  expect(screen.getByText("first-video.mp4")).toBeTruthy();
  expect(screen.getByText(first.last_error)).toBeTruthy();

  view.rerender(<StudioProductionMonitor jobId="second" onSelectJob={onSelectJob} />);
  expect(screen.queryByRole("heading", { name: first.title })).toBeNull();
  expect(screen.queryByText("first-video.mp4")).toBeNull();
  expect(screen.queryByText(first.last_error)).toBeNull();
  expect(screen.queryByText("Ada, lihat di detail produksi")).toBeNull();
  expect(screen.getByText("Memuat detail produksi terpilih…")).toBeTruthy();
  expect((screen.getByLabelText("Pantau produksi") as HTMLSelectElement).value).toBe("second");

  await act(async () => pending.resolve(response(second)));
  expect(await screen.findByRole("heading", { name: second.title })).toBeTruthy();
});

test.each(["success", "failure"])("a late %s for the old selection cannot replace the new production", async (outcome) => {
  const first = job("first", "Hasil lama");
  const second = job("second", "Hasil terpilih");
  const pending = deferred<Response>();
  fetchMock.mockImplementation((path: string) => {
    if (path === "/api/jobs") return Promise.resolve(response({ jobs: [first, second] }));
    if (path === "/api/jobs/first") return pending.promise;
    if (path === "/api/jobs/second") return Promise.resolve(response(second));
    throw new Error(`Unexpected request: ${path}`);
  });
  const onSelectJob = vi.fn();
  const view = render(<StudioProductionMonitor jobId="first" onSelectJob={onSelectJob} />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/jobs/first", expect.anything()));
  view.rerender(<StudioProductionMonitor jobId="second" onSelectJob={onSelectJob} />);
  await screen.findByRole("heading", { name: second.title });

  await act(async () => {
    if (outcome === "success") pending.resolve(response(first));
    else pending.reject(new Error("Koneksi lama gagal"));
  });
  expect(screen.getByRole("heading", { name: second.title })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: first.title })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("an unknown deep-linked job is fetched before the list loads and stays selected after not-found", async () => {
  const list = deferred<Response>();
  fetchMock.mockImplementation((path: string) => {
    if (path === "/api/jobs") return list.promise;
    if (path === "/api/jobs/missing") return Promise.resolve(response({ detail: "not found" }, 404));
    throw new Error(`Unexpected request: ${path}`);
  });
  const onSelectJob = vi.fn();
  const view = render(<StudioProductionMonitor jobId="missing" onSelectJob={onSelectJob} />);
  expect((screen.getByLabelText("Pantau produksi") as HTMLSelectElement).value).toBe("missing");
  await screen.findByText(/Produksi terpilih tidak ditemukan/);
  expect((screen.getByLabelText("Pantau produksi") as HTMLSelectElement).value).toBe("missing");
  expect(screen.getByRole("option", { name: /missing \(tidak ditemukan\)/ })).toBeTruthy();
  expect(onSelectJob).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText("Pantau produksi"), { target: { value: "" } });
  expect(onSelectJob).toHaveBeenCalledWith(undefined);
  view.rerender(<StudioProductionMonitor jobId={undefined} onSelectJob={onSelectJob} />);
  expect(screen.getByRole("heading", { name: "Aktivitas semua job" })).toBeTruthy();
  expect(screen.queryByText(/Produksi terpilih tidak ditemukan/)).toBeNull();
  await act(async () => list.resolve(response({ jobs: [] })));
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/undefined"))).toBe(false);
});

test("a deleted selected production loses its old details after the next poll without changing selection", async () => {
  const first = { ...job("first", "Produksi yang dihapus"), artifacts: ["old-script.json"] };
  let deleted = false;
  fetchMock.mockImplementation((path: string) => {
    if (path === "/api/jobs") return Promise.resolve(response({ jobs: deleted ? [] : [first] }));
    if (path === "/api/jobs/first") return Promise.resolve(deleted
      ? response({ detail: "not found" }, 404) : response(first));
    throw new Error(`Unexpected request: ${path}`);
  });
  const onSelectJob = vi.fn();
  vi.useFakeTimers();
  render(<StudioProductionMonitor jobId="first" onSelectJob={onSelectJob} />);
  await act(async () => {});
  expect(screen.getByRole("heading", { name: first.title })).toBeTruthy();
  expect(screen.getByText("old-script.json")).toBeTruthy();
  deleted = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByText(/Produksi terpilih tidak ditemukan/)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: first.title })).toBeNull();
  expect(screen.queryByText("old-script.json")).toBeNull();
  expect((screen.getByLabelText("Pantau produksi") as HTMLSelectElement).value).toBe("first");
  expect(onSelectJob).not.toHaveBeenCalled();
});

test("list and detail failures have usable retries and recover independently", async () => {
  const selected = job("selected", "Produksi pulih");
  let listFails = true;
  let detailFails = true;
  fetchMock.mockImplementation((path: string) => {
    if (path === "/api/jobs") return Promise.resolve(listFails
      ? response({ detail: "Daftar offline" }, 503) : response({ jobs: [selected] }));
    if (path === "/api/jobs/selected") return Promise.resolve(detailFails
      ? response({ detail: "Detail offline" }, 503) : response(selected));
    throw new Error(`Unexpected request: ${path}`);
  });
  render(<StudioProductionMonitor jobId="selected" onSelectJob={vi.fn()} />);
  await screen.findByRole("button", { name: "Muat ulang daftar" });
  await screen.findByRole("button", { name: "Muat ulang detail" });
  listFails = false;
  fireEvent.click(screen.getByRole("button", { name: "Muat ulang daftar" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Muat ulang daftar" })).toBeNull());
  await screen.findByRole("button", { name: "Muat ulang detail" });
  expect(screen.getByRole("option", { name: selected.title })).toBeTruthy();
  detailFails = false;
  fireEvent.click(screen.getByRole("button", { name: "Muat ulang detail" }));
  await screen.findByRole("heading", { name: selected.title });
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a fragment in an unknown job id cannot alias a real job and leave the monitor loading", async () => {
  const existing = job("selected", "Bukan produksi terpilih");
  fetchMock.mockImplementation((path: string) => {
    const url = new URL(path, "http://localhost");
    if (url.pathname === "/api/jobs") return Promise.resolve(response({ jobs: [existing] }));
    if (url.pathname === "/api/jobs/selected") return Promise.resolve(response(existing));
    if (decodeURIComponent(url.pathname) === "/api/jobs/selected#missing") {
      return Promise.resolve(response({ detail: "not found" }, 404));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  render(<StudioProductionMonitor jobId="selected#missing" onSelectJob={vi.fn()} />);
  await screen.findByText(/Produksi terpilih tidak ditemukan/);
  expect(screen.queryByRole("heading", { name: existing.title })).toBeNull();
  expect(screen.queryByText("Memuat detail produksi terpilih…")).toBeNull();
  expect((screen.getByLabelText("Pantau produksi") as HTMLSelectElement).value).toBe("selected#missing");
});
