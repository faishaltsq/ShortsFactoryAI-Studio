import { expect, test } from "@playwright/test";
import { ZONES } from "../src/three/zones";

/** Every module linked by a studio zone must be reachable with WebGL disabled. */
const IMPLEMENTED = new Map<string, string>([
  ["/", "Studio"],
  ["/jobs", "Produksi"],
  ["/agents", "Agent"],
  ["/storyboard", "Storyboard"],
  ["/assets", "Aset produksi"],
]);

/** The fallback headings are the zone labels, not the 3D overlay's short ones. */
const ZONE_HEADING: Record<string, string> = {
  "/": "Ruang Direktur", "/jobs": "Suite Editing", "/agents": "Meja Riset",
  "/storyboard": "Meja Storyboard", "/assets": "Bay Animasi",
};

const COVERED = [...new Set(ZONES.map((zone) => zone.href))];


for (const href of COVERED) {
  const heading = IMPLEMENTED.get(href) ?? "";

  test(`the fallback navigates to ${href} and the page renders "${heading}"`, async ({ page }) => {
    await page.goto("/");
    const quality = page.getByLabel("Tampilan studio");
    await expect(quality).toBeVisible();
    await quality.selectOption("off");
    await expect(page.getByRole("heading", { name: "Ruang Direktur" })).toBeVisible();

    const heading = ZONE_HEADING[href];
    if (heading === undefined) throw new Error(`no zone heading recorded for ${href}`);
    // `getByRole(heading)` matches ancestors too, so a plain `section` filter resolves to three
    // elements (the page panels plus the card). Scope to the fallback grid's direct children.
    const card = page
      .locator("section")
      .filter({ has: page.locator(":scope > header > h2", { hasText: heading }) });
    await expect(card).toHaveCount(1);
    await card.getByRole("link", { name: "buka" }).click();

    await expect(page).toHaveURL(new RegExp(`${href.replace(/[/]/g, "\\/")}$`));
    await expect(page.getByRole("heading", { level: 1, name: IMPLEMENTED.get(href) ?? "" })).toBeVisible();
  });
}

// `/usage` is reachable from the sidebar, not from a 3D zone, so it cannot ride the zone-walk
// above; its contract is direct navigation rendering the usage tables.
test("the usage page renders its tables from the sidebar route", async ({ page }) => {
  await page.goto("/usage");
  await expect(page.getByRole("heading", { level: 1, name: "Pemakaian" })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(3);
});

test("the agent page lists every configured workflow agent", async ({ page }) => {
  await page.goto("/agents");
  await expect(page.getByRole("heading", { level: 1, name: "Agent" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(14);
  await expect(page.getByRole("article", { name: "ResearchAgent" })).toContainText("Model");
  await expect(page.getByRole("article", { name: "AudioAgent" })).toContainText("Kode lokal");
});
