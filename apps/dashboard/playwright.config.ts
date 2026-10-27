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
      command: "node -e \"require('fs').rmSync('../../data/e2e',{recursive:true,force:true})\" && uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8019",
      url: "http://127.0.0.1:8019/api/health",
      cwd: "../..",
      env: {
        SHORTS_DATA_DIR: "data/e2e",
        SHORTS_DB_PATH: "data/e2e/factory.db",
        SHORTS_JOBS_DIR: "data/e2e/jobs",
        SHORTS_SECRETS_DIR: "data/e2e/secrets",
        SHORTS_STUDIO_CONFIG: "data/e2e/studio.json",
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
