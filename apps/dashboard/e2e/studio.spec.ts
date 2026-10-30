import { expect, test, type Page } from "@playwright/test";
import type { StudioStatus } from "../src/lib/api";
import { characterState } from "../src/lib/studioState";

const API = process.env.STUDIO_E2E_API!;
const CHARACTERS = 'ul[aria-label="Karakter studio"] [data-agent]';

const STATUSES: readonly StudioStatus[] = [
  "working",
  "waiting",
  "blocked",
  "failed",
  "completed",
];

type SnapshotAgent = { agent_id: string; status: StudioStatus; stale: boolean };
type RenderedCharacter = { id: string | null; state: string | null };
/**
 * The states a rendered character may legitimately show for a persisted status.
 *
 * `completed` is a two-second one-shot in the browser, so the projection says `completed` while the
 * mirror may already read `idle`. Every other status is exact: a mismatch there is a real lie about
 * persisted state, not a decay.
 */
function acceptableStates(status: StudioStatus): ReadonlySet<string> {
  const exact = characterState({ status, stale: false });
  return status === "completed" ? new Set([exact, "idle"]) : new Set([exact]);
}


function isStudioStatus(value: unknown): value is StudioStatus {
  return typeof value === "string" && (STATUSES as readonly string[]).includes(value);
}

function readJobId(body: unknown): string {
  if (typeof body !== "object" || body === null || !("id" in body)) {
    throw new Error(`create job response has no id: ${JSON.stringify(body)}`);
  }
  if (typeof body.id !== "string" || body.id === "") {
    throw new Error(`create job response id is not a non-empty string: ${JSON.stringify(body)}`);
  }
  return body.id;
}

function readRunning(body: unknown): boolean {
  if (
    typeof body !== "object" ||
    body === null ||
    !("running" in body) ||
    typeof body.running !== "boolean"
  ) {
    throw new Error(`job detail has no running flag: ${JSON.stringify(body)}`);
  }
  return body.running;
}

function readAgents(body: unknown): SnapshotAgent[] {
  if (typeof body !== "object" || body === null || !("agents" in body)) {
    throw new Error(`snapshot response has no agents: ${JSON.stringify(body)}`);
  }
  if (!Array.isArray(body.agents)) {
    throw new Error(`snapshot agents is not an array: ${JSON.stringify(body)}`);
  }
  return body.agents.map((agent: unknown) => {
    if (typeof agent !== "object" || agent === null) {
      throw new Error(`malformed agent in snapshot: ${JSON.stringify(agent)}`);
    }
    if (
      !("agent_id" in agent) ||
      !("status" in agent) ||
      !("stale" in agent) ||
      typeof agent.agent_id !== "string" ||
      !isStudioStatus(agent.status) ||
      typeof agent.stale !== "boolean"
    ) {
      throw new Error(`malformed agent in snapshot: ${JSON.stringify(agent)}`);
    }
    return { agent_id: agent.agent_id, status: agent.status, stale: agent.stale };
  });
}

async function readRendered(page: Page): Promise<RenderedCharacter[]> {
  return page.locator(CHARACTERS).evaluateAll((nodes) =>
    nodes.map((node) => ({
      id: node.getAttribute("data-agent"),
      state: node.getAttribute("data-state"),
    })),
  );
}

test("mock production reaches storyboard, cancels a running job, and never fakes work", async ({
  page,
  request,
}) => {
  // 1. Create a mock job in the UI and run it to STORYBOARD_READY.
  await page.goto("/jobs");
  await page.getByLabel("Judul").fill("E2E mock pipeline");
  await page.getByLabel("Topik").fill("alur uji deterministik");
  await page.getByRole("button", { name: "Buat job mock" }).click();
  await expect(page.getByRole("heading", { name: "E2E mock pipeline" })).toBeVisible();
  await page.getByRole("button", { name: "Jalankan job" }).click();
  await expect(page.getByText("STORYBOARD_READY").first()).toBeVisible({ timeout: 45_000 });

  // 2. Open the studio in 2D mode: the 3D canvas renders no DOM state.
  await page.goto("/");
  // The select only exists after the client component hydrates and the saved quality preference
  // resolves; acting before that is the flake this replaces. Assertions, not sleeps.
  const qualitySelect = page.getByLabel("Tampilan studio");
  await expect(qualitySelect).toBeVisible();
  await expect(qualitySelect).toBeEnabled();
  await qualitySelect.selectOption("off");
  await expect(qualitySelect).toHaveValue("off");
  // Only the 2D fallback renders zone headings; StudioScene is a canvas and renders none of
  // these, so this assertion cannot pass on the 3D path.
  await expect(page.getByRole("heading", { name: "Ruang Direktur" })).toBeVisible();
  await expect(page.locator(CHARACTERS)).toHaveCount(14);

  // 3. Start a second job and prove the studio can show work at all. Without this positive
  //    control, a permanently broken projection would also pass the "no fake work" check.
  const created = await request.post(`${API}/api/jobs`, {
    data: { title: "E2E cancel", topic: "cancel", provider_mode: "mock" },
  });
  expect(created.status()).toBe(201);
  const cancelJobId = readJobId(await created.json());
  const started = await request.post(`${API}/api/jobs/${cancelJobId}/run`);
  expect(started.status()).toBe(202);

  await expect(page.locator('[data-agent][data-state="working"]').first()).toBeVisible({
    timeout: 30_000,
  });

  // 4. Cancel that job while it is still running.
  await page.goto(`/jobs?job_id=${cancelJobId}`);
  await expect(page.getByRole("heading", { name: "E2E cancel" })).toBeVisible();
  const cancel = page.getByRole("button", { name: "Batalkan job" });
  await expect(cancel).toBeEnabled({ timeout: 15_000 });
  await cancel.click();
  await expect(page.getByText("Pembatalan diminta.")).toBeVisible();
  await expect(page.getByText("CANCELLED").first()).toBeVisible({ timeout: 30_000 });

  // 5. Wait for the worker to actually leave, so the projection stops moving before it is
  //    compared. A cancel is cooperative: the flag is only read at a stage boundary.
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/api/jobs/${cancelJobId}`);
        return readRunning(await response.json());
      },
      { timeout: 30_000, message: "the cancelled job must stop running" },
    )
    .toBe(false);

  // 6. Every rendered character must equal the persisted projection, and nothing may animate
  //    work when the log has none. The page polls on its own, so both sides are re-read inside
  //    the same attempt until they agree; a one-shot comparison would race the poller.
  await page.goto("/");
  await expect(page.locator(CHARACTERS)).toHaveCount(14);

  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/api/studio/snapshot`);
        const agents = readAgents(await response.json());
        const rendered = await readRendered(page);
        if (rendered.length !== agents.length) {
          return `rendered ${rendered.length} characters, projection has ${agents.length}`;
        }
        const expected = new Map(
          agents.map((agent) => [agent.agent_id, acceptableStates(agent.status)] as const),
        );
        const mismatches = rendered.filter((item) => {
          const allowed = item.id === null ? undefined : expected.get(item.id);
          return allowed === undefined || item.state === null || !allowed.has(item.state);
        });
        return mismatches.length === 0 ? "ok" : `mismatch ${JSON.stringify(mismatches)}`;
      },
      { timeout: 30_000, message: "rendered characters must match the persisted projection" },
    )
    .toBe("ok");

  // 7. The specific rule: no character may show work the event log does not claim.
  const snapshot = await request.get(`${API}/api/studio/snapshot`);
  const agents = readAgents(await snapshot.json());
  if (!agents.some((agent) => characterState(agent) === "working")) {
    await expect(page.locator('[data-agent][data-state="working"]')).toHaveCount(0);
  }
});
