import { expect, test } from "@playwright/test";

const API = process.env.STUDIO_E2E_API!;

test("mobile navigation saves budget policy and filters the built-in catalog", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Pengaturan studio", exact: true })).toBeVisible();
  await page.getByLabel("Batas token per hari").fill("12345");
  await page.getByLabel("Batas biaya per hari (USD)").fill("0.12");
  await page.getByRole("button", { name: "Simpan pengaturan" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Pengaturan tersimpan." })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Batas token per hari")).toHaveValue("12345");
  const persisted = await request.get(`${API}/api/settings`);
  expect((await persisted.json()).budget).toEqual({ max_daily_tokens: 12345, max_daily_cost_usd: 0.12, unlimited: false });

  await page.getByLabel("Tanpa batas (unlimited)").check();
  await page.getByRole("button", { name: "Simpan pengaturan" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Pengaturan tersimpan." })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Tanpa batas (unlimited)")).toBeChecked();
  await expect(page.getByLabel("Batas token per hari")).toHaveValue("");

  await page.locator("summary").filter({ hasText: "Menu studio" }).click();
  await page.getByRole("navigation", { name: "Navigasi utama seluler" }).getByRole("link", { name: /^Skills / }).click();
  await expect(page.getByRole("heading", { name: "Katalog kemampuan bawaan" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Renderer bawaan" })).toBeVisible();
  await page.getByLabel("Cari kemampuan").fill("not-a-real-skill");
  await expect(page.getByText("Tidak ada kemampuan yang cocok", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reset filter" }).click();
  await expect(page.getByRole("heading", { name: "Renderer bawaan" })).toBeVisible();
  await expect(page.getByLabel("Cari kemampuan")).toHaveValue("");
});

test("studio module links preserve job scope and storyboard selection follows browser history", async ({ page, request }) => {
  const created = await request.post(`${API}/api/jobs`, { data: { title: "Workspace storyboard ready", provider_mode: "mock" } });
  expect(created.status()).toBe(201);
  const first = await created.json() as { id: string };
  const pending = await request.post(`${API}/api/jobs`, { data: { title: "Workspace not started", provider_mode: "mock" } });
  expect(pending.status()).toBe(201);
  const second = await pending.json() as { id: string };
  expect((await request.post(`${API}/api/jobs/${first.id}/run`)).status()).toBe(202);
  await expect.poll(async () => {
    const response = await request.get(`${API}/api/jobs/${first.id}`);
    return (await response.json()).state as string;
  }, { timeout: 60_000 }).toBe("STORYBOARD_READY");

  await page.addInitScript(() => localStorage.setItem("shorts-studio-quality", "off"));
  await page.goto(`/?job_id=${first.id}`);
  const station = page.getByRole("region", { name: "Meja Storyboard", exact: true });
  await station.getByRole("link", { name: "buka", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/storyboard\\?job_id=${first.id}$`));
  await expect(page.getByRole("heading", { name: "Timeline rencana storyboard", exact: true })).toBeVisible();
  await expect(page.getByLabel("Job tersimpan")).toHaveValue(first.id);

  await page.getByLabel("Job tersimpan").selectOption(second.id);
  await expect(page.getByRole("region", { name: "Job terpilih" })).toContainText("Workspace not started");
  await expect(page.getByRole("heading", { name: "Timeline rencana storyboard", exact: true })).toHaveCount(0);
  await expect(page.getByText("storyboard.json belum diproduksi untuk job ini.", { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("Job tersimpan")).toHaveValue(first.id);
  await expect(page.getByRole("heading", { name: "Timeline rencana storyboard", exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Periksa aset job" }).first().click();
  await expect(page).toHaveURL(new RegExp(`/assets\\?job_id=${first.id}$`));
  await expect(page.getByRole("region", { name: "Job terpilih" })).toContainText("Workspace storyboard ready");
  await expect(page.getByRole("heading", { name: "GPU", exact: true })).toBeVisible();
  await expect(page.getByText("assets.json belum diproduksi untuk job ini.", { exact: true })).toBeVisible();
});

for (const route of ["/settings", "/skills"]) {
  test(`${route} controls remain inside the tablet viewport at 200% text size`, async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto(route);
    await expect(page.locator('input[type="number"], input[type="search"]').first()).toBeVisible();
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(768);
    const bounds = await page.locator('input[type="number"], input[type="search"]').first().boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(768);
  });
}
