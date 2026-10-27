import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { JobDetail } from "@/lib/api";
import { PublishPanel } from "./publish-panel";

/**
 * The publish panel's contract is state gating plus the uncertain → reconcile flow:
 *
 * - mock jobs must never see an enabled publish button (the API would refuse with 409, and the
 *   refusal is a product invariant — "no silent mock", AGENTS.md §3.2 — not a UI nicety);
 * - a `publication.json` with `phase: "uncertain"` replaces the publish button with the reconcile
 *   action, because a retry after an unknown-outcome upload is the duplicate upload the whole
 *   idempotency machinery exists to prevent.
 */

const noop = async () => {};

function detail(overrides: Partial<JobDetail>): JobDetail {
  return {
    id: "job-1",
    title: "Demul",
    state: "APPROVED",
    attempts: 0,
    provider_mode: "live",
    is_mock: false,
    created_at: "2026-10-27T10:00:00+00:00",
    updated_at: "2026-10-27T10:05:00+00:00",
    last_error: null,
    priority: 5,
    scheduled_for: null,
    running: false,
    payload: {},
    artifacts: [],
    events: [],
    usage: [],
    has_video: true,
    ...overrides,
  };
}

const apiMock = vi.hoisted(() => ({
  publish: vi.fn(),
  reconcile: vi.fn(),
  artifact: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.artifact.mockRejectedValue(new Error("404"));
});

afterEach(cleanup);

test("a mock job renders the panel but never an enabled publish button", async () => {
  render(<PublishPanel job={detail({ provider_mode: "mock", is_mock: true })} onRefresh={noop} />);

  await screen.findByText(/tidak dapat dipublikasikan/);
  const button = screen.getByRole("button", { name: /Publish ke private/ });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(apiMock.publish).not.toHaveBeenCalled();
});

test("a live approved job shows an enabled publish button and reports stage outcomes", async () => {
  apiMock.publish.mockResolvedValue({
    job_id: "job-1",
    ok: true,
    stopped: null,
    transport: "stub",
    stages: [
      { name: "thumbnail", ok: true },
      { name: "publish", ok: true },
    ],
  });

  render(<PublishPanel job={detail({})} onRefresh={noop} />);

  const button = await screen.findByRole("button", { name: /Publish ke private/ });
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
  button.click();
  await screen.findByText(/thumbnail: ok · publish: ok/);
  expect(apiMock.publish).toHaveBeenCalledWith("job-1");
});

test("an uncertain publication swaps the publish button for the reconcile action", async () => {
  apiMock.artifact.mockResolvedValue({
    phase: "uncertain",
    video_id: null,
    idempotency_key: "key-123",
    attempt: 1,
  });
  apiMock.reconcile.mockResolvedValue({
    job_id: "job-1",
    phase: "initiating",
    video_id: null,
    idempotency_key: "key-123",
    attempt: 1,
    receipt_steps: ["reconciled_not_found"],
  });

  render(<PublishPanel job={detail({})} onRefresh={noop} />);

  const reconcile = await screen.findByRole("button", { name: /Rekonsiliasi/ });
  await waitFor(() => expect((reconcile as HTMLButtonElement).disabled).toBe(false));
  expect(screen.queryByRole("button", { name: /Publish ke private/ })).toBeNull();

  reconcile.click();
  await screen.findByText(/tidak ada video di kanal/);
  expect(apiMock.reconcile).toHaveBeenCalledWith("job-1");
});

test("a non-approved job with no publication record renders nothing", () => {
  const { container } = render(
    <PublishPanel job={detail({ state: "RUNNING" })} onRefresh={noop} />,
  );
  expect(container.querySelector("section")).toBeNull();
});
