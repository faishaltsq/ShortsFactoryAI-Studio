import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.STUDIO_URL ?? "http://127.0.0.1:3018",
    trace: "retain-on-failure",
  },
});
