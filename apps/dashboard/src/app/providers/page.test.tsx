import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ProviderView } from "@/lib/api";
import ProvidersPage from "./page";

const mocks = vi.hoisted(() => ({
  providers: vi.fn(),
  saveProvider: vi.fn(),
  testProvider: vi.fn(),
  providerModels: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    providers: mocks.providers,
    saveProvider: mocks.saveProvider,
    testProvider: mocks.testProvider,
    providerModels: mocks.providerModels,
  },
}));

const provider: ProviderView = {
  id: "local-provider",
  label: "Provider Lokal",
  transport: "ollama",
  base_url: "http://127.0.0.1:11434",
  model: "model-a",
  capabilities: ["chat"],
  timeout_s: 90,
  max_retries: 2,
  max_tokens: null,
  temperature: null,
  allow_private_hosts: true,
  enabled: true,
  credential_source: "env:LOCAL_PROVIDER_KEY",
  cli_command: "",
};

beforeEach(() => {
  mocks.providers.mockReset().mockResolvedValue({ providers: [provider], vision_available: false });
  mocks.saveProvider.mockReset().mockResolvedValue({ provider });
  mocks.testProvider.mockReset().mockResolvedValue({
    id: provider.id,
    ok: true,
    detail: "reachable",
    latency_ms: 12,
    note: "reachability only; a completion is what proves the credential and model",
  });
  mocks.providerModels.mockReset().mockResolvedValue({ models: ["model-a", "model-b"] });
});

afterEach(cleanup);

async function editProvider() {
  render(<ProvidersPage />);
  fireEvent.click(await screen.findByRole("button", { name: /Provider Lokal/ }));
  return screen.getByRole("form", { name: "Edit Provider Lokal" });
}

test("shows credential references without exposing a credential value", async () => {
  const form = await editProvider();

  expect(within(form).getByText(/Sumber tersimpan: env:LOCAL_PROVIDER_KEY/).isConnected).toBe(true);
  const secret = within(form).getByLabelText("Secret baru (write-only)") as HTMLInputElement;
  expect(secret.type).toBe("password");
  expect(secret.value).toBe("");
  expect(document.body.textContent?.includes("credential-secret-value")).toBe(false);
});

test("states reachability limits and shows the private-host warning", async () => {
  const form = await editProvider();

  expect(within(form).getByRole("alert", { name: "" }).textContent).toContain("Akses host privat aktif");
  expect(within(form).getByText(/hanya mengukur keterjangkauan endpoint/i).isConnected).toBe(true);
  expect(within(form).getByText(/bukan bukti bahwa kredensial atau model/i).isConnected).toBe(true);

  fireEvent.click(within(form).getByRole("button", { name: "Uji koneksi" }));
  await waitFor(() => expect(mocks.testProvider).toHaveBeenCalledWith("local-provider"));
  expect(await within(form).findByText(/reachability only; a completion is what proves/)).toBeTruthy();
});

test("fetches models and saves selected capabilities", async () => {
  const form = await editProvider();

  fireEvent.click(within(form).getByRole("button", { name: "Ambil daftar model" }));
  await waitFor(() => expect(mocks.providerModels).toHaveBeenCalledWith("local-provider"));
  expect(await within(form).findByText("2 model ditemukan.")).toBeTruthy();

  fireEvent.change(within(form).getByLabelText("Model"), { target: { value: "model-b" } });
  fireEvent.click(within(form).getByLabelText("vision"));
  fireEvent.click(within(form).getByRole("button", { name: "Simpan provider" }));

  await waitFor(() => expect(mocks.saveProvider).toHaveBeenCalledTimes(1));
  const body = mocks.saveProvider.mock.calls[0]?.[0] as Record<string, unknown>;
  expect(body.model).toBe("model-b");
  expect(body.capabilities).toEqual(["chat", "vision"]);
  expect(body.credential_env).toBe("LOCAL_PROVIDER_KEY");
  expect(body.credential_secret).toBe("");
});
