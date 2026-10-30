import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api, type StudioSettings } from "@/lib/api";
import SettingsPage from "./page";

let persisted: StudioSettings;

beforeEach(() => {
  persisted = {
    budget: { max_daily_tokens: 24000, max_daily_cost_usd: 1.75, unlimited: false },
    render: { min_free_ram_mib: 2048, min_free_vram_mib: 1024, allow_unmeasured_gpu: false },
    storage: { data_dir: "C:/studio/data", jobs_dir: "C:/studio/data/jobs", secrets_dir: "C:/studio/data/secrets" },
  };
  vi.spyOn(api, "settings").mockImplementation(async () => structuredClone(persisted));
  vi.spyOn(api, "saveSettings").mockImplementation(async (body) => {
    persisted = { ...persisted, ...body };
    return { budget: persisted.budget, render: persisted.render };
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("unlimited removes both caps from the submitted budget and reload keeps accepted render edits", async () => {
  const view = render(<SettingsPage />);
  const tokens = await screen.findByLabelText("Batas token per hari") as HTMLInputElement;
  const cost = screen.getByLabelText("Batas biaya per hari (USD)") as HTMLInputElement;
  fireEvent.click(screen.getByRole("checkbox", { name: "Tanpa batas (unlimited)" }));
  expect(tokens.value).toBe("");
  expect(cost.value).toBe("");
  expect(tokens.matches(":disabled")).toBe(true);
  expect(cost.matches(":disabled")).toBe(true);
  fireEvent.change(screen.getByLabelText("Minimum RAM bebas (MiB)"), { target: { value: "4096" } });
  fireEvent.click(screen.getByRole("button", { name: "Simpan pengaturan" }));
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalledWith({
    budget: { max_daily_tokens: null, max_daily_cost_usd: null, unlimited: true },
    render: { min_free_ram_mib: 4096, min_free_vram_mib: 1024, allow_unmeasured_gpu: false },
  }));
  view.unmount();
  render(<SettingsPage />);
  const reloadedRam = await screen.findByLabelText("Minimum RAM bebas (MiB)") as HTMLInputElement;
  expect(reloadedRam.value).toBe("4096");
  expect((screen.getByRole("checkbox", { name: "Tanpa batas (unlimited)" }) as HTMLInputElement).checked).toBe(true);
  expect((screen.getByLabelText("Batas token per hari") as HTMLInputElement).value).toBe("");
});

test("rejected save leaves the persisted summary and editable draft intact", async () => {
  vi.mocked(api.saveSettings).mockRejectedValueOnce(new Error("Config write refused"));
  render(<SettingsPage />);
  const ram = await screen.findByLabelText("Minimum RAM bebas (MiB)") as HTMLInputElement;
  const summary = screen.getByRole("region", { name: "Nilai tersimpan" });
  const previous = summary.textContent;
  fireEvent.change(ram, { target: { value: "8192" } });
  fireEvent.click(screen.getByRole("button", { name: "Simpan pengaturan" }));
  await screen.findByRole("alert");
  expect(ram.value).toBe("8192");
  expect(summary.textContent).toBe(previous);
  expect(persisted.render.min_free_ram_mib).toBe(2048);
  expect(ram.matches(":disabled")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Simpan pengaturan" }));
  await waitFor(() => expect(persisted.render.min_free_ram_mib).toBe(8192));
});

test("blank caps become null while blank required memory and fractional tokens never submit", async () => {
  render(<SettingsPage />);
  const ram = await screen.findByLabelText("Minimum RAM bebas (MiB)") as HTMLInputElement;
  const tokens = screen.getByLabelText("Batas token per hari") as HTMLInputElement;
  fireEvent.change(ram, { target: { value: "" } });
  fireEvent.change(tokens, { target: { value: "1.5" } });
  fireEvent.submit(screen.getByRole("form", { name: "Pengaturan studio" }));
  expect(api.saveSettings).not.toHaveBeenCalled();
  expect(ram.getAttribute("aria-invalid")).toBe("true");
  expect(tokens.getAttribute("aria-invalid")).toBe("true");
  expect(ram.value).toBe("");
  fireEvent.change(ram, { target: { value: "3072" } });
  fireEvent.change(tokens, { target: { value: "" } });
  fireEvent.change(screen.getByLabelText("Batas biaya per hari (USD)"), { target: { value: "" } });
  fireEvent.submit(screen.getByRole("form", { name: "Pengaturan studio" }));
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalledWith({
    budget: { max_daily_tokens: null, max_daily_cost_usd: null, unlimited: false },
    render: { min_free_ram_mib: 3072, min_free_vram_mib: 1024, allow_unmeasured_gpu: false },
  }));
});

test("a pending save locks mutations and duplicate submissions until the response arrives", async () => {
  let finish!: (value: { budget: StudioSettings["budget"]; render: StudioSettings["render"] }) => void;
  vi.mocked(api.saveSettings).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  render(<SettingsPage />);
  const ram = await screen.findByLabelText("Minimum RAM bebas (MiB)") as HTMLInputElement;
  fireEvent.change(ram, { target: { value: "3072" } });
  const form = screen.getByRole("form", { name: "Pengaturan studio" });
  fireEvent.submit(form);
  expect(ram.matches(":disabled")).toBe(true);
  expect(within(form).getByRole("button", { name: "Batalkan perubahan" }).matches(":disabled")).toBe(true);
  fireEvent.submit(form);
  expect(api.saveSettings).toHaveBeenCalledTimes(1);
  await act(async () => finish({ budget: persisted.budget, render: { ...persisted.render, min_free_ram_mib: 3072 } }));
  expect(ram.matches(":disabled")).toBe(false);
  fireEvent.change(ram, { target: { value: "6144" } });
  expect(ram.value).toBe("6144");
  expect((screen.getByRole("button", { name: "Simpan pengaturan" }) as HTMLButtonElement).disabled).toBe(false);
});

test("a failed initial load can retry without presenting editable fabricated defaults", async () => {
  vi.mocked(api.settings).mockRejectedValueOnce(new Error("Config unavailable"));
  render(<SettingsPage />);
  await screen.findByRole("alert");
  expect(screen.queryByRole("form")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
  const tokens = await screen.findByLabelText("Batas token per hari") as HTMLInputElement;
  expect(tokens.value).toBe(String(persisted.budget.max_daily_tokens));
  expect(api.settings).toHaveBeenCalledTimes(2);
});
