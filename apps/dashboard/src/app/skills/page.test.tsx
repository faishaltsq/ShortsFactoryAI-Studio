import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api, type StudioCatalog } from "@/lib/api";
import SkillsPage from "./page";

const catalog: StudioCatalog = {
  templates: ["test-template-a", "test-template-b"],
  renderers: [
    { id: "renderer-a", label: "Renderer A", description: "First test renderer" },
    { id: "renderer-b", label: "Renderer B", description: "Second test renderer" },
  ],
  motion: { poses: ["test-pose"], expressions: ["test-expression"], presets: ["test-preset"], beat_kinds: ["test-beat"], camera_moves: ["test-camera"], transitions: ["test-transition"] },
  characters: [
    { id: "character-a", displayName: "Character A", version: "fixture-a", artStyle: "test-style-a", poses: ["pose-a"], expressions: ["expression-a"], gestures: ["gesture-a"], clothingVariants: ["clothing-a"], mouthShapes: ["mouth-a"], license: "test-license-a", provenance: "test-provenance-a" },
    { id: "character-b", displayName: "Character B", version: "fixture-b", artStyle: "test-style-b", poses: ["pose-b"], expressions: ["expression-b"], gestures: ["gesture-b"], clothingVariants: ["clothing-b"], mouthShapes: ["mouth-b"], license: "test-license-b", provenance: "test-provenance-b" },
  ],
};

beforeEach(() => { vi.spyOn(api, "catalog").mockResolvedValue(structuredClone(catalog)); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("search and category filters change results and reset restores the returned catalog", async () => {
  render(<SkillsPage />);
  const search = await screen.findByRole("searchbox", { name: "Cari kemampuan" });
  fireEvent.change(search, { target: { value: "test-camera" } });
  expect(screen.getByText("test-camera").isConnected).toBe(true);
  expect(screen.queryByText("test-template-a")).toBeNull();
  expect(screen.queryByText("test-preset")).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: "Kelompok" }), { target: { value: "templates" } });
  expect(screen.queryByText("test-camera")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Reset filter" }));
  const templates = screen.getByRole("region", { name: "ID template" });
  expect(within(templates).getAllByRole("listitem").map((item) => item.textContent)).toEqual(catalog.templates);
  expect(screen.getByText("test-camera").isConnected).toBe(true);
  const renderers = screen.getByRole("region", { name: "Renderer bawaan" });
  for (const renderer of catalog.renderers) expect(within(renderers).getByText(renderer.description).isConnected).toBe(true);
});

test("character selection shows that manifest's actual motion and provenance rather than the prior character", async () => {
  render(<SkillsPage />);
  const select = await screen.findByRole("combobox", { name: "Pilih karakter" });
  expect(screen.getByRole("article", { name: "Manifest character-a" }).isConnected).toBe(true);
  fireEvent.change(select, { target: { value: "character-b" } });
  const manifest = screen.getByRole("article", { name: "Manifest character-b" });
  for (const value of ["pose-b", "expression-b", "gesture-b", "clothing-b", "mouth-b", "test-license-b", "test-provenance-b"]) {
    expect(within(manifest).getByText(value).isConnected).toBe(true);
  }
  expect(within(manifest).queryByText("pose-a")).toBeNull();
  fireEvent.change(screen.getByRole("searchbox", { name: "Cari kemampuan" }), { target: { value: "gesture-a" } });
  const filtered = screen.getByRole("article", { name: "Manifest character-a" });
  expect(within(filtered).getByText("gesture-a").isConnected).toBe(true);
  expect(screen.queryByRole("article", { name: "Manifest character-b" })).toBeNull();
});

test("load errors retry against the API, and an empty response offers reload without inventing entries", async () => {
  vi.mocked(api.catalog).mockRejectedValueOnce(new Error("Manifest unavailable")).mockResolvedValueOnce({
    templates: [], renderers: [], characters: [], motion: { poses: [], expressions: [], presets: [], beat_kinds: [], camera_moves: [], transitions: [] },
  });
  render(<SkillsPage />);
  await screen.findByRole("alert");
  expect(screen.queryByRole("searchbox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
  fireEvent.click(await screen.findByRole("button", { name: "Muat ulang katalog" }));
  await screen.findByRole("searchbox");
  expect(api.catalog).toHaveBeenCalledTimes(3);
  expect(screen.getByText("test-template-a").isConnected).toBe(true);
});
