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
  objects: [
    { id: "test-object-a", label: "Object A" },
    { id: "test-object-b", label: "Object B" },
  ],
  environments: ["test-environment-a", "test-environment-b"],
  visual: { beat_kinds: ["test-beat"], camera_moves: ["test-camera"], transitions: ["test-transition"], text_roles: ["test-role"] },
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

test("the object library lists every shipped object and filters by the search box", async () => {
  render(<SkillsPage />);
  const objects = await screen.findByRole("region", { name: "Pustaka objek" });
  for (const object of catalog.objects) expect(within(objects).getByText(object.id).isConnected).toBe(true);
  fireEvent.change(screen.getByRole("searchbox", { name: "Cari kemampuan" }), { target: { value: "test-object-b" } });
  const filtered = screen.getByRole("region", { name: "Pustaka objek" });
  expect(within(filtered).getByText("test-object-b").isConnected).toBe(true);
  expect(within(filtered).queryByText("test-object-a")).toBeNull();
});

test("the visual vocabulary and backdrops are reported, and no character list is required", async () => {
  render(<SkillsPage />);
  const visual = await screen.findByRole("region", { name: "Kosakata visual" });
  for (const value of ["test-beat", "test-camera", "test-transition", "test-role", "test-environment-a"]) {
    expect(within(visual).getByText(value).isConnected).toBe(true);
  }
  expect(screen.queryByText(/manifest karakter/i)).toBeNull();
});

test("load errors retry against the API, and an empty response offers reload without inventing entries", async () => {
  vi.mocked(api.catalog).mockRejectedValueOnce(new Error("Manifest unavailable")).mockResolvedValueOnce({
    templates: [], renderers: [], objects: [], environments: [], visual: { beat_kinds: [], camera_moves: [], transitions: [], text_roles: [] },
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
