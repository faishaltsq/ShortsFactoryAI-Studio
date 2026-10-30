import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import AgentsPage from "./page";

const mocks = vi.hoisted(() => ({
  agents: vi.fn(),
  providers: vi.fn(),
  saveAgentBinding: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    agents: mocks.agents,
    providers: mocks.providers,
    saveAgentBinding: mocks.saveAgentBinding,
  },
}));

const llmAgent = {
  id: "ResearchAgent",
  kind: "llm" as const,
  requires: ["chat", "json_schema"],
  binding: {
    primary: "local-json",
    fallback: ["mock"],
    model: "research-model",
    temperature: 0.2,
    max_tokens: 4096,
    system_prompt_override: null,
  },
  capability_gaps: [],
};

const deterministicAgent = {
  id: "AudioAgent",
  kind: "deterministic" as const,
  requires: [],
  binding: {
    primary: null,
    fallback: [],
    model: null,
    temperature: null,
    max_tokens: null,
    system_prompt_override: null,
  },
  capability_gaps: [],
};

const providers = [
  {
    id: "local-json",
    label: "Local JSON",
    transport: "ollama",
    base_url: "http://127.0.0.1:11434",
    model: "provider-default",
    capabilities: ["chat", "json_schema"],
    timeout_s: 90,
    max_retries: 2,
    max_tokens: null,
    temperature: null,
    allow_private_hosts: true,
    enabled: true,
    credential_source: null,
    cli_command: "",
  },
  {
    id: "mock",
    label: "Mock",
    transport: "mock",
    base_url: "",
    model: "mock-1",
    capabilities: ["chat"],
    timeout_s: 1,
    max_retries: 0,
    max_tokens: null,
    temperature: null,
    allow_private_hosts: false,
    enabled: true,
    credential_source: null,
    cli_command: "",
  },
];

beforeEach(() => {
  mocks.agents.mockReset().mockResolvedValue({ agents: [llmAgent, deterministicAgent] });
  mocks.providers.mockReset().mockResolvedValue({ providers, vision_available: false, bindings: [] });
  mocks.saveAgentBinding.mockReset().mockResolvedValue({ agent: "ResearchAgent", binding: llmAgent.binding });
});

afterEach(cleanup);

test("shows every agent and states which ones do not use a model", async () => {
  render(<AgentsPage />);

  expect(await screen.findByRole("heading", { name: "Agent", level: 1 })).toBeTruthy();
  const research = screen.getByRole("article", { name: "ResearchAgent" });
  expect(within(research).getAllByText("Local JSON").length).toBeGreaterThan(0);
  expect(within(research).getByText("research-model")).toBeTruthy();

  const audio = screen.getByRole("article", { name: "AudioAgent" });
  expect(within(audio).getByText("Tidak memakai model")).toBeTruthy();
  expect(within(audio).queryByRole("button", { name: /Simpan/ })).toBeNull();
});

test("saves an LLM agent binding through the per-agent endpoint", async () => {
  render(<AgentsPage />);

  const research = await screen.findByRole("article", { name: "ResearchAgent" });
  fireEvent.change(within(research).getByLabelText("Model override"), {
    target: { value: "mock-special" },
  });
  fireEvent.click(within(research).getByRole("button", { name: "Simpan ResearchAgent" }));

  await waitFor(() => expect(mocks.saveAgentBinding).toHaveBeenCalledTimes(1));
  expect(mocks.saveAgentBinding).toHaveBeenCalledWith("ResearchAgent", {
    primary: "local-json",
    fallback: ["mock"],
    model: "mock-special",
    temperature: 0.2,
    max_tokens: 4096,
    system_prompt_override: null,
  });
});
