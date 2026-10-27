import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.STUDIO_URL ?? "http://127.0.0.1:3018",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // The wrapper (scripts/dashboard_e2e.py) is the safe path: it owns a TemporaryDirectory
      // and never deletes a fixed repository path. Ports match its API_URL/UI_URL, so servers
      // it started satisfy this probe and no second server spawns.
      command: "uv run python scripts/dashboard_e2e.py --hold",
      url: "http://127.0.0.1:8019/api/health",
      cwd: "../..",
      env: {
        SHORTS_MOCK_DELAY_MS: "1500",
      },
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:3018",
      env: { STUDIO_API_ORIGIN: "http://127.0.0.1:8019" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
