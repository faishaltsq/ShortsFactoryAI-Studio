"use client";

import Link from "next/link";
import type { AgentView } from "@/lib/api";
import { AGENT_LABEL, AGENT_ZONE, ZONES } from "./zones";

/**
 * The 2D fallback is not a degraded grid of boxes: same room layout, same state colours, same
 * click targets. Turning the 3D scene off must not remove any capability.
 */
export function StudioFallback({ agents }: { agents: AgentView[] }) {
  const byZone = new Map<string, AgentView[]>();
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
            <Link href={zone.href} className="text-[11px] uppercase tracking-wide text-ink-400 hover:text-ink-200">
              buka
            </Link>
          </header>
          <ul className="space-y-1.5">
            {(byZone.get(zone.id) ?? []).map((agent) => (
              <li key={agent.agent_id} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate text-ink-200">{AGENT_LABEL[agent.agent_id] ?? agent.agent_id}</span>
                <span className={`badge badge-${agent.status}`}>{agent.status}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
