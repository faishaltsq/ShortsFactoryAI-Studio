"use client";

import Link from "next/link";
import { characterState, type ResolvedAgent } from "@/lib/studioState";
import { AGENT_LABEL, AGENT_ZONE, ZONES } from "./zones";

export function StudioFallback({
  agents,
  onSelectAgent,
}: {
  agents: ResolvedAgent[];
  onSelectAgent: (agentId: string) => void;
}) {
  const byZone = new Map<string, ResolvedAgent[]>();
  for (const agent of agents) {
    const zone = AGENT_ZONE[agent.agent_id] ?? "director";
    byZone.set(zone, [...(byZone.get(zone) ?? []), agent]);
  }

  return (
    <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
      {ZONES.map((zone) => (
        <section key={zone.id} className="panel p-3" style={{ borderColor: `${zone.accent}44` }}>
          <header className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">{zone.label}</h2>
            {zone.href ? (
              <Link href={zone.href} className="text-[11px] uppercase tracking-wide text-ink-400 hover:text-ink-200">
                buka
              </Link>
            ) : (
              <span
                className="text-[11px] uppercase tracking-wide text-ink-600"
                title="rute belum ada"
                aria-disabled="true"
              >
                rute belum ada
              </span>
            )}
          </header>
          <ul className="space-y-1.5">
            {(byZone.get(zone.id) ?? []).map((agent) => (
              <li key={agent.agent_id}>
                <button
                  type="button"
                  className="flex min-h-11 w-full items-center justify-between gap-2 rounded-md px-2 text-left text-xs hover:bg-ink-800"
                  onClick={() => onSelectAgent(agent.agent_id)}
                  aria-haspopup="dialog"
                  aria-controls="agent-inspector"
                  data-agent={agent.agent_id}
                  data-state={characterState(agent)}
                >
                  <span className="truncate text-ink-200">
                    {AGENT_LABEL[agent.agent_id] ?? agent.agent_id}
                  </span>
                  <span className={`badge badge-${characterState(agent)}`}>{characterState(agent)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
