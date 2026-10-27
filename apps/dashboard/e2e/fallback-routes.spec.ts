import { expect, test } from "@playwright/test";
import { ZONES } from "../src/three/zones";

/**
 * The 2D fallback is a route map, not decoration: every zone's "buka" link must reach a real page.
 *
 * Only three of the eleven declared routes exist today (`/`, `/jobs`, `/providers`). The rest are
 * Phase 1.8 placeholders recorded in `docs/IMPLEMENTATION_ROADMAP.md`; this spec covers the ones
 * that render and names the gap rather than silently skipping it.
 */

//: Every route the fallback can navigate to, with the heading that page renders. A route listed
//: here must exist AND be linked from a zone; a route outside it must be a recorded placeholder.
const IMPLEMENTED = new Map<string, string>([
  ["/", "Studio"],
  ["/jobs", "Produksi"],
]);

/** The fallback headings are the zone labels, not the 3D overlay's short ones. */
const ZONE_HEADING: Record<string, string> = {"/": "Ruang Direktur", "/jobs": "Suite Editing"};

const DECLARED = [
  ...new Set(ZONES.map((zone) => zone.href).filter((href): href is string => href !== null)),
];
const COVERED = DECLARED.filter((href) => IMPLEMENTED.has(href));

test("the fallback covers every implemented route and declares the rest", () => {
  for (const href of IMPLEMENTED.keys()) {
    expect(DECLARED, `${href} is implemented but no zone links to it`).toContain(href);
  }
  // Recorded, not skipped. The zone table now sets `href: null` for every zone whose module has
  // no page, so those zones render a disabled span rather than a dead anchor and the declared
  // set contains only real routes. The Phase 1.8 placeholders therefore live in `ZONES` as
  // `null`, not as dead hrefs — asserted here so re-adding a href without a page fails.
  expect(DECLARED.every((href) => IMPLEMENTED.has(href))).toBe(true);
  expect(DECLARED.filter((href) => !IMPLEMENTED.has(href))).toEqual([]);
});

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
