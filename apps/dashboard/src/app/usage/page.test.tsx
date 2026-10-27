import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, test, vi } from "vitest";
import { api, type UsageSummary } from "@/lib/api";
import UsagePage from "./page";

afterEach(cleanup);

/** One summary the tests reshape per case; the spy below swaps it via `current`. */
const baseSummary: UsageSummary = {
  days: [{ day: "2026-10-27", tokens: 1500, calls: 3, cost_usd: 0.0021 }],
  by_agent: [
    { day: "2026-10-27", agent: "ScriptAgent", tokens: 900, calls: 1, cost_usd: 0.0014 },
    { day: "2026-10-27", agent: "ResearchAgent", tokens: 600, calls: 2, cost_usd: 0.0007 },
  ],
  by_model: [
    {
      day: "2026-10-27",
      provider: "mock",
      model: "mock-1",
      tokens: 1500,
      calls: 3,
      cost_usd: 0.0021,
    },
  ],
  price_configured: true,
};

let current: UsageSummary = baseSummary;

vi.spyOn(api, "usageSummary").mockImplementation(() => Promise.resolve(current));

test("renders per-day, per-agent and per-model tables when prices are configured", async () => {
  current = baseSummary;
  render(<UsagePage />);

  await screen.findAllByRole("table"); // all three tables render once loaded
  screen.getAllByRole("columnheader", { name: "Tanggal" });
  // A priced row shows a formatted cost, and no unpriced banner is present.
  screen.getAllByText(/US\$0[.,]0021/); // day total and model total happen to be equal
  if (screen.queryByRole("note")) throw new Error("priced page must not show the unpriced banner");
});

test("an unpriced zero renders 'belum dikonfigurasi', never a bare 0", async () => {
  current = {
    ...baseSummary,
    price_configured: false,
    days: [{ day: "2026-10-27", tokens: 1500, calls: 3, cost_usd: 0 }],
  };
  render(<UsagePage />);

  // The banner explains the 0; every cost cell says the price is missing — none shows "$0.0000".
  await screen.findByRole("note");
  const cells = await screen.findAllByText("belum dikonfigurasi");
  // One per table row: 1 day row + 2 agent rows + 1 model row.
  if (cells.length !== 4) throw new Error(`expected 4 unpriced cells, got ${cells.length}`);
  const zeroCost = document.body.textContent?.match(/\$\s*0[.,]0+/);
  if (zeroCost) throw new Error(`unpriced zero leaked a formatted cost: ${zeroCost[0]}`);
});
