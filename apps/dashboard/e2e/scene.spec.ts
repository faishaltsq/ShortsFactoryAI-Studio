import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { StudioStatus } from "../src/lib/api";
import { characterState, type CharacterState } from "../src/lib/studioState";
import { ZONES } from "../src/three/zones";

/**
 * The 3D tier, asserted from the DOM seam the canvas publishes.
 *
 * Playwright cannot read `userData` out of a WebGL scene, so `StudioScene` renders an `aria-hidden`
 * mirror (`[data-scene-mirror]`) with one row per character, plus `[data-studio-scene]` carrying
 * the camera and frameloop it is actually using. Without these attributes every claim about the 3D
 * path would be vacuous — the canvas would render nothing testable and still "pass".
 *
 * The 2D tier is covered by `studio.spec.ts`, which keeps the accessibility/path proof. This file
 * is the canvas proof: the mirror is a test seam and must never become the only way to reach
 * anything, which is why the sidebar assertions stay in the other spec.
 */

const API = "http://127.0.0.1:8019";
const MIRROR = "[data-scene-mirror] [data-agent]";
const SCENE = "[data-studio-scene]";
const TIER = "medium";

const STATUSES: readonly StudioStatus[] = ["working", "waiting", "blocked", "failed", "completed"];

type SnapshotAgent = { agent_id: string; status: StudioStatus; stale: boolean };
type MirrorRow = { id: string | null; state: string | null; motion: string | null };
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

async function mirror(page: Page): Promise<MirrorRow[]> {
  return page.locator(MIRROR).evaluateAll((nodes) =>
    nodes.map((node) => ({
      id: node.getAttribute("data-agent"),
      state: node.getAttribute("data-state"),
      motion: node.getAttribute("data-motion"),
    })),
  );
}

async function gotoStudio(page: Page, tier: string): Promise<void> {
  await page.goto("/");
  const quality = page.getByLabel("Tampilan studio");
  await expect(quality).toBeVisible();
  await quality.selectOption(tier);
  await expect(quality).toHaveValue(tier);
  await expect(page.locator(SCENE)).toHaveAttribute("data-quality", tier);
  await expect(page.locator(SCENE)).toHaveAttribute("data-camera", "isometric");
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

async function startMockJob(request: APIRequestContext, title: string): Promise<string> {
  const created = await request.post(`${API}/api/jobs`, {
    data: { title, topic: "studio 3d", provider_mode: "mock" },
  });
  expect(created.status()).toBe(201);
  const body = await created.json();
  const jobId = readJobId(body);
  const started = await request.post(`${API}/api/jobs/${jobId}/run`);
  expect(started.status()).toBe(202);
  return jobId;
}

async function stopMockJob(request: APIRequestContext, jobId: string): Promise<void> {
  await request.post(`${API}/api/jobs/${jobId}/cancel`);
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/api/jobs/${jobId}`);
        return readRunning(await response.json());
      },
      { timeout: 30_000, message: "the job must stop running" },
    )
    .toBe(false);
}

test("the 3D tier mirrors one character per agent, and every state equals the projection", async ({
  page,
  request,
}) => {
  const jobId = await startMockJob(request, "E2E scene parity");
  try {
    await gotoStudio(page, TIER);
    await expect(page.locator(MIRROR)).toHaveCount(14);

    // Positive control: without visible work the parity check below would also pass on a
    // permanently dead projection.
    await expect(page.locator(`${MIRROR}[data-state="working"]`).first()).toBeVisible({
      timeout: 30_000,
    });

    await expect
      .poll(
        async () => {
          const response = await request.get(`${API}/api/studio/snapshot`);
          const agents = readAgents(await response.json());
          const rows = await mirror(page);
          if (rows.length !== agents.length) {
            return `mirror has ${rows.length} rows, projection has ${agents.length}`;
          }
          const expected = new Map(
            agents.map((agent) => [agent.agent_id, acceptableStates(agent.status)] as const),
          );
          const mismatches = rows.filter((row) => {
            const allowed = row.id === null ? undefined : expected.get(row.id);
            return allowed === undefined || row.state === null || !allowed.has(row.state);
          });
          return mismatches.length === 0 ? "ok" : `mismatch ${JSON.stringify(mismatches)}`;
        },
        { timeout: 30_000, message: "mirrored characters must match the persisted projection" },
      )
      .toBe("ok");
  } finally {
    await stopMockJob(request, jobId);
  }
});

test("the mirror never claims work the log does not have, and never animates a non-working state", async ({
  page,
  request,
}) => {
  const jobId = await startMockJob(request, "E2E scene no-fake-work");
  try {
    await gotoStudio(page, TIER);
    await expect(page.locator(MIRROR)).toHaveCount(14);
    await expect(page.locator(`${MIRROR}[data-state="working"]`).first()).toBeVisible({
      timeout: 30_000,
    });
  } finally {
    await stopMockJob(request, jobId);
  }

  // Settle on the persisted projection, then prove the negative control and the motion contract.
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/api/studio/snapshot`);
        const agents = readAgents(await response.json());
        return agents.some((agent) => characterState(agent) === "working") ? "working" : "quiet";
      },
      { timeout: 30_000, message: "the projection must settle after the cancel" },
    )
    .toBe("quiet");

  // Re-read both sides together until they agree. A one-shot comparison races the poller, and a
  // neighbouring spec may have started its own job in the meantime.
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/api/studio/snapshot`);
        const agents = readAgents(await response.json());
        const expected = new Map(
          agents.map((agent) => [agent.agent_id, acceptableStates(agent.status)] as const),
        );
        const rows = await mirror(page);
        const mismatches = rows.filter((row) => {
          const allowed = row.id === null ? undefined : expected.get(row.id);
          return allowed === undefined || row.state === null || !allowed.has(row.state);
        });
        if (mismatches.length > 0) return `mismatch ${JSON.stringify(mismatches)}`;
        const working = agents.filter((agent) => characterState(agent) === "working").length;
        if (working > 0) return `projection still claims ${working} working`;
        const animated = rows.filter((row) => row.state === "working").length;
        return animated === 0 ? "ok" : `mirror claims ${animated} working`;
      },
      { timeout: 30_000, message: "no character may claim work the projection does not have" },
    )
    .toBe("ok");

  // The motion contract, on a settled page: only `working` and the `completed` reaction move.
  for (const row of await mirror(page)) {
    if (row.id === null) throw new Error("a mirror row has no data-agent");
    if (row.state !== "working" && row.state !== "completed") {
      expect(row.motion, `${row.id} may not animate work while ${String(row.state)}`).toBe("idle");
    }
  }
});

test("activating a zone moves the camera target, and only existing routes are real links", async ({
  page,
}) => {
  await gotoStudio(page, "high");
  const scene = page.locator(SCENE);
  await expect(scene).toHaveAttribute("data-camera-target", "none");

  await page.getByRole("button", { name: "Fokus zona Animasi" }).click();
  await expect(scene).toHaveAttribute("data-camera-target", "animation");
  await expect(page.getByRole("button", { name: "Fokus zona Animasi" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // A different zone must move the target again rather than stay latched.
  await page.getByRole("button", { name: "Fokus zona Direktur" }).click();
  await expect(scene).toHaveAttribute("data-camera-target", "director");

  // Zone anchors exist in the 3D tier too. A route with a page is a real `<a href>`; a route with
  // no page is an honest disabled span, so the operator cannot land on a 404.
  const enabled = await page
    .locator("[data-zone-link][data-zone-link-disabled='false']")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("href")));
  // The disabled set is held to the zones whose route genuinely has no page, read from the same
  // `ZONES` table the scene renders — not to a count that drifts whenever a route is written.
  const disabled = await page
    .locator("[data-zone-link][data-zone-link-disabled='true']")
    .evaluateAll((nodes) =>
      nodes.map((node) => ({
        zone: node.getAttribute("data-zone"),
        href: node.getAttribute("href"),
        title: node.getAttribute("title"),
        label: node.getAttribute("aria-label"),
      })),
    );

  const builtRoutes = new Set(["/", "/jobs"]);
  expect(new Set(enabled)).toEqual(
    new Set(ZONES.map((zone) => zone.href).filter((href) => href !== null && builtRoutes.has(href))),
  );
  expect(new Set(disabled.map((link) => link.zone))).toEqual(
    new Set(ZONES.filter((zone) => zone.href === null || !builtRoutes.has(zone.href)).map((z) => z.id)),
  );
  for (const link of disabled) {
    expect(link.href, "a zone with no page must not be an anchor").toBeNull();
    expect(link.title).toBe("rute belum ada");
    expect(link.label, "a disabled zone link must still name itself").toBeTruthy();
  }
});

test("the frameloop runs on every tier and stops only when the document is hidden", async ({
  page,
}) => {
  // `demand` on a visible tab froze the scene: a status change cannot repaint without an
  // invalidate, and nothing invalidates on a prop change in that mode. Visible ⇒ `always`.
  await gotoStudio(page, "low");
  await expect(page.locator(SCENE)).toHaveAttribute("data-frameloop", "always");

  await gotoStudio(page, "high");
  await expect(page.locator(SCENE)).toHaveAttribute("data-frameloop", "always");

  // A hidden tab must not keep burning frames: the render job has priority (docs/STUDIO_3D.md §6).
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator(SCENE)).toHaveAttribute("data-frameloop", "demand");
});

test("the fallback and the canvas agree on every character state", async ({ page, request }) => {
  await gotoStudio(page, TIER);
  await expect(page.locator(MIRROR)).toHaveCount(14);
  const canvasRows = await mirror(page);

  await page.getByLabel("Tampilan studio").selectOption("off");
  await expect(page.getByRole("heading", { name: "Ruang Direktur" })).toBeVisible();
  const sidebar = page.locator('ul[aria-label="Karakter studio"] [data-agent]');
  await expect(sidebar).toHaveCount(14);
  const sidebarRows = await sidebar.evaluateAll((nodes) =>
    nodes.map((node) => ({
      id: node.getAttribute("data-agent"),
      state: node.getAttribute("data-state"),
    })),
  );

  const byId = new Map(
    sidebarRows.map((row) => [row.id, row.state as CharacterState | null] as const),
  );
  for (const row of canvasRows) {
    if (row.id === null) throw new Error("a mirror row has no data-agent");
    expect(byId.get(row.id), `${row.id} disagrees between canvas and fallback`).toBe(row.state);
  }

  // The snapshot is the third opinion; a state only two of three agree on is not a state.
  const response = await request.get(`${API}/api/studio/snapshot`);
  const persisted = new Map(
    readAgents(await response.json()).map(
      (agent) => [agent.agent_id, acceptableStates(agent.status)] as const,
    ),
  );
  for (const row of canvasRows) {
    if (row.id === null) continue;
    expect(
      persisted.get(row.id)?.has(row.state ?? ""),
      `${row.id} disagrees with the snapshot`,
    ).toBe(true);
  }
});
