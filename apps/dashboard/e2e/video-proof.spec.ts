import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

/**
 * The Phase 2.6 browser gate: a real rendered MP4, played by a real Chromium.
 *
 * Gated behind `STUDIO_VIDEO_PROOF=1` because the fixture is a genuine Remotion render — minutes,
 * not seconds — and the default E2E budget is three minutes. When the flag is set and no fixture
 * pointer exists yet, this spec provisions its own: it runs
 * `uv run python scripts/render_proof_job.py --render` against the already-running E2E API with a
 * 900-second budget, which writes the pointer into that server's data dir. A requested proof with
 * no fixture afterwards is a failure, not a skip.
 *
 * What it proves that a DOM assertion cannot:
 * - the element is a `<video>` with `controls` and `preload="metadata"`, no autoplay, not muted;
 * - the browser actually decoded it: `readyState >= 1`, `videoWidth/Height` are the render's;
 * - `duration` matches `audio.json` narration within 120 ms — the media gate's own tolerance;
 * - `currentTime` advances after `play()`, and the audio decoder consumed bytes, so the narration
 *   is a real AAC track rather than a silent placeholder.
 */

const API = process.env.STUDIO_E2E_API!;
const DATA_DIR = process.env.STUDIO_E2E_DATA!;
const FLAG = process.env.STUDIO_VIDEO_PROOF;

const NARRATION_TOLERANCE_MS = 120;

type JobDetail = { id: string; state: string; has_video: boolean; is_mock: boolean };

function readJobId(): string | null {
  const file = path.join(DATA_DIR, "proof-job.json");
  if (!fs.existsSync(file)) return null;
  const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as { job_id?: unknown };
  return typeof parsed.job_id === "string" && parsed.job_id !== "" ? parsed.job_id : null;
}

/**
 * Provision the render fixture through the real pipeline if it does not exist yet.
 * Runs from repo root so `uv` resolves the project environment; the script talks to the API
 * this Playwright run already started, and writes the pointer into the same STUDIO_E2E_DATA.
 */
function ensureProofJob(): string {
  const existing = readJobId();
  if (existing !== null) {
    const detailPath = path.join(DATA_DIR, "jobs", existing, "state.json");
    if (fs.existsSync(detailPath)) return existing;
  }
  const repoRoot = path.resolve(import.meta.dirname, "../../..");
  execFileSync("uv", ["run", "python", "scripts/render_proof_job.py", "--render"], {
    cwd: repoRoot,
    env: {
      ...process.env,
      STUDIO_API_ORIGIN: API,
      SHORTS_DATA_DIR: DATA_DIR,
      SHORTS_DB_PATH: path.join(DATA_DIR, "factory.db"),
      SHORTS_JOBS_DIR: path.join(DATA_DIR, "jobs"),
      SHORTS_SECRETS_DIR: path.join(DATA_DIR, "secrets"),
      SHORTS_STUDIO_CONFIG: path.join(DATA_DIR, "studio.json"),
    },
    stdio: "inherit",
    timeout: 900_000,
  });
  const provisioned = readJobId();
  if (provisioned === null) {
    throw new Error("render_proof_job.py --render completed but wrote no proof-job.json");
  }
  return provisioned;
}

function readNarrationMs(jobId: string): number | null {
  const file = path.join(DATA_DIR, "jobs", jobId, "audio.json");
  if (!fs.existsSync(file)) return null;
  const audio = JSON.parse(fs.readFileSync(file, "utf8")) as {
    narration?: { durationMs?: unknown };
  };
  const value = audio.narration?.durationMs;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

async function detail(request: APIRequestContext, jobId: string): Promise<JobDetail> {
  const response = await request.get(`${API}/api/jobs/${jobId}`);
  expect(response.status(), `GET /api/jobs/${jobId}`).toBe(200);
  return (await response.json()) as JobDetail;
}

type MediaFacts = {
  tag: string;
  controls: boolean;
  preload: string | null;
  autoplay: boolean;
  muted: boolean;
  paused: boolean;
  readyState: number;
  width: number;
  height: number;
  duration: number;
  currentTime: number;
  audioBytes: number;
  videoBytes: number;
  error: number | null;
};

const readMedia = (page: Page): Promise<MediaFacts> =>
  page.locator("video").first().evaluate((node) => {
    // Chromium's non-standard decoded-byte counters. They are the only in-page evidence that the
    // audio track was actually decoded rather than merely declared in the container.
    const video = node as HTMLVideoElement & {
      webkitAudioDecodedByteCount?: number;
      webkitVideoDecodedByteCount?: number;
    };
    return {
      tag: video.tagName.toLowerCase(),
      controls: video.controls,
      preload: video.getAttribute("preload"),
      autoplay: video.hasAttribute("autoplay"),
      muted: video.muted,
      paused: video.paused,
      readyState: video.readyState,
      width: video.videoWidth,
      height: video.videoHeight,
      duration: video.duration,
      currentTime: video.currentTime,
      audioBytes: video.webkitAudioDecodedByteCount ?? 0,
      videoBytes: video.webkitVideoDecodedByteCount ?? 0,
      error: video.error ? video.error.code : null,
    };
  });

test.describe("job detail video surface", () => {
  test.skip(FLAG !== "1", "set STUDIO_VIDEO_PROOF=1 (fixture is a real Remotion render)");

  // Provisioning a fresh render can take minutes; the 900s budget lives in ensureProofJob.
  test.setTimeout(960_000);

  test("a real rendered job plays in the browser with synced narration", async ({
    page,
    request,
  }) => {
    // STUDIO_VIDEO_PROOF=1 means: prove it. No fixture after provisioning is a failure.
    const id = ensureProofJob();

    const narrationMs = readNarrationMs(id);
    expect(narrationMs, `audio.json narration duration for ${id}`).not.toBeNull();

    const before = await detail(request, id);
    expect(before.has_video, `job ${id} has no output.mp4`).toBe(true);
    expect(before.is_mock, "the fixture is a mock job; the surface must say so").toBe(true);

    await page.goto(`/jobs?job_id=${id}`);
    await expect(page.getByRole("heading", { name: "Phase 2.6 browser proof" })).toBeVisible();

    // The mock note is not decoration: a mock render is never publishable.
    await expect(page.getByRole("note")).toContainText("tidak dapat dipublikasikan");

    const surface = page.locator('[data-video-state]');
    await expect(surface).toHaveAttribute("data-video-state", "ready", { timeout: 30_000 });

    const video = page.locator("video");
    await expect(video).toHaveCount(1);

    // Wait for the browser's own metadata, not for a fixed sleep.
    await expect
      .poll(async () => (await readMedia(page)).readyState, { timeout: 30_000 })
      .toBeGreaterThanOrEqual(1);

    const facts = await readMedia(page);
    expect(facts.tag).toBe("video");
    expect(facts.controls).toBe(true);
    expect(facts.preload).toBe("metadata");
    expect(facts.autoplay).toBe(false);
    expect(facts.muted).toBe(false);
    expect(facts.error).toBeNull();
    expect(facts.width).toBe(1080);
    expect(facts.height).toBe(1920);

    // 9:16 portrait, not a letterboxed landscape file.
    expect(facts.height / facts.width).toBeCloseTo(16 / 9, 3);

    const durationMs = facts.duration * 1000;
    expect(Math.abs(durationMs - (narrationMs as number))).toBeLessThanOrEqual(
      NARRATION_TOLERANCE_MS,
    );

    // Play through the visible control surface, then prove the clock moved.
    await video.click();
    await expect.poll(async () => (await readMedia(page)).paused, { timeout: 10_000 }).toBe(false);
    const startedAt = (await readMedia(page)).currentTime;
    await expect
      .poll(async () => (await readMedia(page)).currentTime, { timeout: 10_000 })
      .toBeGreaterThan(startedAt + 0.25);

    const playing = await readMedia(page);
    expect(playing.paused).toBe(false);
    // The audio decoder consumed bytes: the narration is a real AAC track, not a silent one.
    expect(playing.audioBytes).toBeGreaterThan(0);
    expect(playing.videoBytes).toBeGreaterThan(0);

    await page.screenshot({ path: "test-results/video-proof-surface.png", fullPage: false });

    // The byte-serving contract: a Range request answers 206 with a matching Content-Range.
    const head = await request.get(`${API}/api/jobs/${id}/video`, {
      headers: { Range: "bytes=0-1023" },
    });
    expect(head.status()).toBe(206);
    const contentRange = head.headers()["content-range"] ?? "";
    expect(contentRange).toMatch(/^bytes 0-1023\/\d+$/);
    const body = await head.body();
    expect(body.byteLength).toBe(1024);
    const total = Number(contentRange.split("/")[1]);
    expect(total).toBeGreaterThan(1024);

    // A whole-file GET reports the same length the range header did.
    const whole = await request.get(`${API}/api/jobs/${id}/video`);
    expect(whole.status()).toBe(200);
    expect((await whole.body()).byteLength).toBe(total);
    expect(whole.headers()["accept-ranges"]).toBe("bytes");
    expect(whole.headers()["content-type"]).toBe("video/mp4");
  });
});
