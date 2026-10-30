import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { AgentView, StudioEvent } from "@/lib/api";
import { withResolvedStates } from "@/lib/studioState";
import StudioPage from "./page";

const events: StudioEvent[] = Array.from({ length: 7 }, (_, index) => ({
  event_id: index + 1,
  job_id: "job-1",
  agent_id: "ResearchAgent",
  event_type: "progress",
  status: "working",
  description: `Event ${index + 1}`,
  progress: (index + 1) / 10,
  model: "model-1",
  stage: "RESEARCH_COMPLETE",
  created_at: `2026-10-25T10:0${index}:00+00:00`,
}));

const agent: AgentView = {
  agent_id: "ResearchAgent",
  status: "working",
  stale: false,
  task: "Memeriksa sumber",
  progress: 0.7,
  model: "model-1",
  stage: "RESEARCH_COMPLETE",
  job_id: "job-1",
  updated_at: "2026-10-25T10:06:00+00:00",
  recent: events,
};

let currentAgents: AgentView[] = [agent];

/** One clock reading for the whole file, so a decay assertion cannot race the wall clock. */
const NOW = "2026-10-25T10:06:00+00:00";

vi.mock("@/lib/useStudio", () => ({
  useStudio: () => ({
    snapshot: {
      cursor: 7,
      job_id: "job-1",
      agents: currentAgents,
      generated_at: "2026-10-25T10:06:00+00:00",
    },
    // The hook resolves each agent against its single clock; the page must draw that resolution.
    agents: withResolvedStates(currentAgents, Date.parse(NOW)),
    error: null,
    connected: true,
    rendering: currentAgents.some((row) =>
      row.stage === "RENDERING" && row.status === "working" && !row.stale,
    ),
    refresh: vi.fn(),
  }),
}));

vi.mock("@/three/StudioScene", () => ({
  StudioScene: ({ onSelectAgent }: { onSelectAgent: (agentId: string) => void }) => (
    <button type="button" onClick={() => onSelectAgent("ResearchAgent")}>
      Pilih karakter 3D
    </button>
  ),
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function close() {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
});

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ jobs: [] }), { status: 200 }),
  ));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("opens an accessible inspector with persisted data and job-level last-five events", async () => {
  render(<StudioPage />);

  fireEvent.click(screen.getByRole("button", { name: /Riset.*Bekerja/i }));

  const dialog = await screen.findByRole("dialog", { name: "Riset" });
  expect(dialog.hasAttribute("open")).toBe(true);
  expect(within(dialog).getByText("Memeriksa sumber").isConnected).toBe(true);
  expect(within(dialog).getByText("model-1").isConnected).toBe(true);
  expect(within(dialog).getByRole("progressbar").getAttribute("value")).toBe("0.7");
  expect(within(dialog).getByRole("link", { name: "Buka job" }).getAttribute("href")).toBe(
    "/jobs?job_id=job-1",
  );
  expect(within(dialog).queryByText("Event 2")).toBeNull();
  expect(within(dialog).getByText("Event 3").isConnected).toBe(true);
  expect(within(dialog).getByText("Event 7").isConnected).toBe(true);

  fireEvent.keyDown(dialog, { key: "Escape" });
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  await waitFor(() => expect(dialog.hasAttribute("open")).toBe(false));
});

test("uses the interactive 2D fallback when the saved quality is off", async () => {
  window.localStorage.setItem("shorts-studio-quality", "off");
  render(<StudioPage />);

  const room = screen.getByRole("region", { name: "Ruang produksi" });
  const fallbackCharacter = await within(room).findByRole("button", { name: /Riset.*working/i });
  fireEvent.click(fallbackCharacter);

  expect((await screen.findByRole("dialog", { name: "Riset" })).hasAttribute("open")).toBe(true);
});

test("a stale working agent renders as waiting in the list and the inspector", async () => {
  currentAgents = [{ ...agent, stale: true }];
  try {
    render(<StudioPage />);

    const character = within(screen.getByRole("list", { name: "Karakter studio" }))
      .getByRole("button", { name: /Riset/i });
    expect(character.getAttribute("data-agent")).toBe("ResearchAgent");
    expect(character.getAttribute("data-state")).toBe("waiting");
    expect(within(character).getByText("Menunggu").isConnected).toBe(true);

    fireEvent.click(character);
    const dialog = await screen.findByRole("dialog", { name: "Riset" });
    // The status row, not the event log: historical events keep their own persisted status.
    const statusRow = within(dialog).getByText("Status").nextElementSibling;
    expect(statusRow).not.toBeNull();
    if (!(statusRow instanceof HTMLElement)) throw new Error("status row is not an element");
    expect(within(statusRow).getByText("Menunggu").isConnected).toBe(true);
    expect(within(statusRow).queryByText("Bekerja")).toBeNull();
    expect(within(dialog).getByText("Lease tidak aktif").isConnected).toBe(true);
  } finally {
    currentAgents = [agent];
  }
});

test("a completed agent decays to idle in the list, the fallback and the inspector", async () => {
  window.localStorage.setItem("shorts-studio-quality", "off");
  const finished: AgentView = {
    ...agent,
    status: "completed",
    stale: false,
    updated_at: "2026-10-25T10:00:00+00:00",
    task: "Selesai menulis",
    progress: 1,
  };
  currentAgents = [finished];
  try {
    render(<StudioPage />);

    // The hook resolved `completed` 6 minutes ago, so every surface must agree on `idle`.
    const sidebar = screen.getByRole("list", { name: "Karakter studio" });
    const listed = within(sidebar).getByRole("button", { name: /Riset/i });
    expect(listed.getAttribute("data-state")).toBe("idle");
    expect(within(listed).getByText("Menganggur").isConnected).toBe(true);

    const fallback = screen.getByRole("region", { name: "Ruang produksi" })
      .querySelector('button[data-agent="ResearchAgent"]');
    expect(fallback?.getAttribute("data-state")).toBe("idle");

    fireEvent.click(listed);
    const dialog = await screen.findByRole("dialog", { name: "Riset" });
    const statusRow = within(dialog).getByText("Status").nextElementSibling;
    if (!(statusRow instanceof HTMLElement)) throw new Error("status row is not an element");
    expect(within(statusRow).getByText("Menganggur").isConnected).toBe(true);
    expect(within(statusRow).queryByText("Selesai")).toBeNull();
  } finally {
    currentAgents = [agent];
    window.localStorage.clear();
  }
});

test("pausing banner appears only while an agent is rendering", () => {
  // Nothing is rendering in the fixture, so the honest state is no banner at all.
  const { unmount } = render(<StudioPage />);
  expect(screen.queryByRole("status", { name: /studio dijeda/i })).toBeNull();
  unmount();

  const editor: AgentView = {
    ...agent,
    agent_id: "EditorAgent",
    stage: "RENDERING",
    task: "Merender video",
    status: "working",
    stale: false,
  };
  currentAgents = [editor];
  try {
    render(<StudioPage />);
    const banner = screen.getByRole("status", { name: /studio dijeda/i });
    expect(banner.textContent ?? "").toMatch(/render/i);
    // ADR-008 wants the pause gated on GPU memory, which the browser cannot observe here. The
    // banner must not imply it was measured.
    expect(banner.getAttribute("title") ?? "").toMatch(/tidak tersedia/i);
    expect(banner.textContent ?? "").not.toMatch(/memori GPU (rendah|penuh)/i);
  } finally {
    currentAgents = [agent];
  }
});

test("an empty snapshot keeps the registered crew inspectable without inventing production", async () => {
  currentAgents = [];
  try {
    window.localStorage.setItem("shorts-studio-quality", "off");
    render(<StudioPage />);
    const crew = within(screen.getByRole("list", { name: "Karakter studio" }));
    const animator = crew.getByRole("button", { name: /Animator/i });
    expect(animator.getAttribute("data-state")).toBe("idle");
    expect(crew.queryByText("Bekerja")).toBeNull();
    fireEvent.click(animator);
    const inspector = await screen.findByRole("dialog", { name: "Animator" });
    expect(within(inspector).queryByRole("progressbar")).toBeNull();
    expect(within(inspector).queryByRole("link", { name: /^Buka job$/ })).toBeNull();
    expect(within(inspector).getByRole("link", { name: /pengaturan agent/i }).getAttribute("href")).toBe("/agents");
  } finally {
    currentAgents = [agent];
  }
});

test("selecting a production zone filters the crew and resetting restores the whole team", () => {
  render(<StudioPage />);
  const crew = screen.getByRole("list", { name: "Karakter studio" });
  fireEvent.click(screen.getByRole("button", { name: "Lihat tahap Booth Audio" }));
  expect(within(crew).getByRole("button", { name: /Audio/i }).getAttribute("data-agent")).toBe("AudioAgent");
  expect(within(crew).queryByRole("button", { name: /Riset/i })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Semua ruang" }));
  expect(within(crew).getByRole("button", { name: /Riset/i }).getAttribute("data-agent")).toBe("ResearchAgent");
  expect(within(crew).getByRole("button", { name: /Audio/i }).getAttribute("data-agent")).toBe("AudioAgent");
});
