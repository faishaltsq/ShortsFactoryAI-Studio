import { defineConfig } from "@playwright/test";
import config from "./playwright.config";

/** Run through npm run test:e2e -- --config=playwright.video.config.ts with STUDIO_VIDEO_PROOF=1. */
export default defineConfig({
  ...config,
  testMatch: /video-proof\.spec\.ts/,
  timeout: 120_000,
  use: { ...config.use, video: "off" },
});
