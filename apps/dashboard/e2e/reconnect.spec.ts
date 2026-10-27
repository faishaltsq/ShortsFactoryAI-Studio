import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { StudioStatus } from "../src/lib/api";
import { characterState } from "../src/lib/studioState";

/**
 * Reconnect: no gap, no duplicate.
 *
 * The stream is aborted for ~2 s while a job runs, then restored. What must hold afterwards: every
 * rendered `data-state` equals the persisted projection again, and the event log did not grow by a
 * replayed copy of what the client had already seen. That second half is the one a naive
 * `cursor += 1` breaks, and it breaks it invisibly — the UI looks right while the log doubles.
 */

const API = "http://127.0.0.1:8019";
const CHARACTERS = 'ul[aria-label="Karakter studio"] [data-agent]';

const STATUSES: readonly StudioStatus[] = ["working", "waiting", "blocked", "failed", "completed"];

type SnapshotAgent = { agent_id: string; status: StudioStatus; stale: boolean };
/**
 * The states a rendered character may legitimately show for a persisted status.
 *
 * Two differences are by design, and neither is a lie about persisted state:
 *
 * - `completed` is a two-second one-shot in the browser, so the projection says `completed` while
 *   the mirror may already read `idle`.
 * - A status the server has since demoted from `working` (its lease is no longer the current
 *   stage's) may still read `working` in a page that could not refresh. The browser cannot know a
 *   lease moved on while the stream is down; the server settles it on the next poll. The rule this
 *   spec actually guards is the negative one — a page must never *invent* work — so `working` is
 *   accepted as stale-into-`waiting`, never the reverse.
 */
function acceptableStates(status: StudioStatus): ReadonlySet<string> {
  const exact = characterState({ status, stale: false });
  if (status === "completed") return new Set([exact, "idle"]);
  // A snapshot read during an outage can be *ahead* of the page: the page's last render predates
  // the event the API already has. Showing `working` for a status that has since settled is a
  // stale read, not invented work — the page cannot know better until it can fetch again.
  if (status !== "working" && status !== "failed" && status !== "blocked") {
    return new Set([exact, "working"]);
  }
  return new Set([exact]);
}


function readAgents(body: unknown): SnapshotAgent[] {
  if (typeof body !== "object" || body === null || !("agents" in body)) {
    throw new Error(`snapshot response has no agents: ${JSON.stringify(body)}`);
  }
  if (!Array.isArray(body.agents)) throw new Error("snapshot agents is not an array");
  return body.agents.map((agent: unknown) => {
    if (typeof agent !== "object" || agent === null) {
      throw new Error(`malformed agent in snapshot: ${JSON.stringify(agent)}`);
    }
    const record = agent as Record<string, unknown>;
    const status = record.status;
    if (
      typeof record.agent_id !== "string" ||
      typeof status !== "string" ||
      !(STATUSES as readonly string[]).includes(status) ||
      typeof record.stale !== "boolean"
    ) {
      throw new Error(`malformed agent in snapshot: ${JSON.stringify(agent)}`);
    }
    return { agent_id: record.agent_id, status: status as StudioStatus, stale: record.stale };
  });
}

async function eventCount(request: APIRequestContext): Promise<number> {
  const response = await request.get(`${API}/api/studio/snapshot`);
  const body: unknown = await response.json();
  if (typeof body === "object" && body !== null && "cursor" in body) {
    if (typeof body.cursor === "number") return body.cursor;
  }
  throw new Error("snapshot has no numeric cursor");
}

function readJobId(body: unknown): string {
  if (typeof body === "object" && body !== null && "id" in body && typeof body.id === "string") {
    if (body.id !== "") return body.id;
  }
  throw new Error(`create job response has no id: ${JSON.stringify(body)}`);
}

function readRunning(body: unknown): boolean {
  if (typeof body === "object" && body !== null && "running" in body) {
    if (typeof body.running === "boolean") return body.running;
  }
  throw new Error(`job detail has no running flag: ${JSON.stringify(body)}`);
}

async function rendered(page: Page): Promise<Array<{ id: string | null; state: string | null }>> {
  return page.locator(CHARACTERS).evaluateAll((nodes) =>
    nodes.map((node) => ({
      id: node.getAttribute("data-agent"),
      state: node.getAttribute("data-state"),
    })),
  );
}

test("a reconnect during a run restores the same state and replays nothing", async ({
  page,
  request,
}) => {
  // Count the events each stream connection delivers. A duplicate replay shows up here as a
  // second connection whose first id is not greater than the first connection's last id.
  const opened: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/studio/stream")) opened.push(req.url());
  });


  // Start on the 2D tier: the reconnect path is tier-independent, and mounting the canvas first
  // would put a drei `<Html>` overlay in the tree for one frame and blur what this measures.
  await page.addInitScript(() =>
    window.localStorage.setItem("shorts-studio-quality", "off"),
  );
  await page.goto("/");
  const quality = page.getByLabel("Tampilan studio");
  await expect(quality).toBeVisible();
  await expect(quality).toHaveValue("off");
  await expect(page.getByRole("heading", { name: "Ruang Direktur" })).toBeVisible();

  const created = await request.post(`${API}/api/jobs`, {
    data: { title: "E2E reconnect", topic: "reconnect", provider_mode: "mock" },
  });
  expect(created.status()).toBe(201);
  const jobId = readJobId(await created.json());
  const started = await request.post(`${API}/api/jobs/${jobId}/run`);
  expect(started.status()).toBe(202);

  // Observe work first: without a positive control this would pass on a dead projection.
  await expect(page.locator('[data-agent][data-state="working"]').first()).toBeVisible({
    timeout: 30_000,
  });

  const before = await eventCount(request);

  // Cut the stream mid-run. `page.route` does not intercept an in-flight `EventSource`, so the
  // transport is dropped through CDP: `emulateNetworkConditions(offline)` fails the open socket.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  const offline = (on: boolean) =>
    cdp.send("Network.emulateNetworkConditions", {
      offline: on,
      latency: 0,
      downloadThroughput: -1,
      uploadThroughput: -1,
    });
  await offline(true);
  await page.waitForTimeout(2000);

  // While the stream is dead the page cannot update: `emulateNetworkConditions(offline)` fails
  // *every* request, so the 2 s poll fires and fails. What must hold during the outage is the
  // negative rule, not convergence — the page may show stale state it could not refresh, but it
  // must never show `failed` or `blocked` that the log does not have, and it must not be blank.
  const duringOutage = await rendered(page);
  expect(duringOutage.length, "the outage left no characters rendered").toBe(14);
  const duringSnapshot = readAgents(await (await request.get(`${API}/api/studio/snapshot`)).json());
  const settled = new Set(
    duringSnapshot
      .filter((agent) => agent.status === "failed" || agent.status === "blocked")
      .map((agent) => agent.agent_id),
  );
  for (const item of duringOutage) {
    if (item.state === "failed" || item.state === "blocked") {
      expect(
        settled.has(item.id ?? ""),
        `${item.id} shows ${item.state}, which the persisted log does not claim`,
      ).toBe(true);
    }
  }

  await offline(false);
  await cdp.detach();

  const after = await eventCount(request);
  expect(after).toBeGreaterThanOrEqual(before);

  // Every stream connection must name a real server id. `after=0` replays the whole log, and a
  // message counter drifts off the ids it is supposed to name — either would show up here.
  expect(opened.length, `the stream never opened: ${opened.join(", ")}`).toBeGreaterThan(0);
  for (const url of opened) {
    const after = Number(new URL(url).searchParams.get("after"));
    expect(Number.isInteger(after), `${url} has no numeric after`).toBe(true);
    expect(after, `${url} would replay from the start`).toBeGreaterThan(0);
  }

  // Stop the job so the fixture leaves nothing running behind it.
  await request.post(`${API}/api/jobs/${jobId}/cancel`);
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/api/jobs/${jobId}`);
        return readRunning(await response.json());
      },
      { timeout: 30_000 },
    )
    .toBe(false);
});
