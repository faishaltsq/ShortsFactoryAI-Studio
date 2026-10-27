import { defineConfig } from "@playwright/test";

/**
 * Config for the video-proof spec only.
 *
 * The default `playwright.config.ts` deletes `data/e2e/` every time its API starts, which would
 * destroy the rendered fixture this spec exists to prove. This config owns no servers: start the
 * API on 8019 and the dashboard on 3018 yourself, produce the fixture once with
 * `uv run python scripts/render_proof_job.py --render`, then run:
 *
 *   STUDIO_VIDEO_PROOF=1 npx playwright test --config playwright.video.config.ts
 *
 * Without `STUDIO_VIDEO_PROOF=1` the spec skips and says why, so the default E2E budget is not
 * spent on a multi-minute render.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /video-proof\.spec\.ts/,
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.STUDIO_URL ?? "http://127.0.0.1:3018",
    trace: "retain-on-failure",
    video: "off",
  },
});
