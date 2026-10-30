import { defineConfig } from "@playwright/test";

if (process.env.STUDIO_E2E_OWNED !== "1" || !process.env.STUDIO_URL ||
    !process.env.STUDIO_E2E_API || !process.env.STUDIO_E2E_DATA) {
  throw new Error("Run npm run test:e2e so the isolated API and production dashboard are started first.");
}

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.STUDIO_URL,
    trace: "retain-on-failure",
  },
});
