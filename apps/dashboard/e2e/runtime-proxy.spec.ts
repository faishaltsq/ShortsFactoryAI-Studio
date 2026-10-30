import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

// The owner builds Next without STUDIO_API_ORIGIN, then sets it only for next start.
test("production proxy reaches the isolated backend selected at server startup", async ({ request }) => {
  const settings = await request.get("/api/settings");
  expect(settings.status()).toBe(200);
  expect((await settings.json()).storage.data_dir).toBe(process.env.STUDIO_E2E_DATA);

  const title = `Runtime proxy ${randomUUID()}`;
  const created = await request.post("/api/jobs", {
    data: { title, topic: "runtime origin isolation", provider_mode: "mock" },
  });
  expect(created.status()).toBe(201);
  const job = await created.json() as { id: string };
  const direct = await request.get(`${process.env.STUDIO_E2E_API}/api/jobs/${encodeURIComponent(job.id)}`);
  expect(direct.status()).toBe(200);
  expect((await direct.json()).title).toBe(title);
});
