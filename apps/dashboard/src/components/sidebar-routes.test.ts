import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Sidebar ⇔ page parity, without a browser.
 *
 * Every sidebar route must have a page module, and every top-level route page must be in the
 * sidebar (or in INTENTIONALLY_HIDDEN). This is the fast half of the fallback-routes contract:
 * a link that 404s, or a page nobody can reach, fails here before Playwright ever runs.
 */

const APP_DIR = path.resolve(__dirname, "..", "app");
const ROUTES_FILE = path.join(APP_DIR, "..", "components", "Sidebar.tsx");

/** Pages that exist on disk but are deliberately not sidebar entries. */
const INTENTIONALLY_HIDDEN: Record<string, true> = {};

/**
 * Sidebar entries whose pages are Phase 1.8+ placeholders. Recorded here instead of deleting the
 * links: R1.4 built `/create` and `/calendar`; the remaining five wait for their phase. Turning
 * one into a real page means removing it from this list, which this test then enforces.
 */
const PLACEHOLDER_ROUTES: Record<string, true> = {
  "/storyboard": true,
  "/assets": true,
  "/agents": true,
  "/skills": true,
  "/settings": true,
};

const sidebarHrefs = [
  ...readFileSync(ROUTES_FILE, "utf-8").matchAll(/href: "([^"]+)"/g),
].flatMap((match) => (match[1] === undefined ? [] : [match[1]]));

const onDisk = readdirSync(APP_DIR, { withFileTypes: true })
  .filter(
    (entry) =>
      entry.isDirectory() &&
      entry.name !== "api" &&
      existsSync(path.join(APP_DIR, entry.name, "page.tsx")),
  )
  .map((entry) => `/${entry.name}`);
if (existsSync(path.join(APP_DIR, "page.tsx"))) onDisk.unshift("/");

describe("sidebar and page routes agree", () => {
  it("every sidebar route has a page module or is a recorded placeholder", () => {
    for (const href of sidebarHrefs) {
      if (PLACEHOLDER_ROUTES[href]) continue;
      const pagePath = path.join(APP_DIR, href === "/" ? "page.tsx" : path.join(href, "page.tsx"));
      expect(existsSync(pagePath), `sidebar links ${href} but ${pagePath} is missing`).toBe(true);
    }
  });

  it("placeholder routes are still real sidebar links awaiting their phase", () => {
    for (const href of Object.keys(PLACEHOLDER_ROUTES)) {
      expect(sidebarHrefs, `recorded placeholder ${href} is no longer in the sidebar`).toContain(
        href,
      );
    }
  });

  it("every page module is reachable from the sidebar", () => {
    for (const href of onDisk) {
      if (INTENTIONALLY_HIDDEN[href]) continue;
      expect(sidebarHrefs, `page ${href} exists but no sidebar link reaches it`).toContain(href);
    }
  });
});
