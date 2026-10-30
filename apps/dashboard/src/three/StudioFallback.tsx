"use client";

import Link from "next/link";
import { useState } from "react";
import { characterState, type ResolvedAgent } from "@/lib/studioState";
import { stateColor } from "./sceneState";
import { AGENT_LABEL, AGENT_ZONE, ZONES, zoneHref, type WorkstationProp, type ZoneId } from "./zones";
import styles from "./StudioFallback.module.css";

function StationMotif({ prop }: { prop: WorkstationProp }) {
  switch (prop) {
    case "mic":
      return (
        <g>
          <rect x="100" y="40" width="12" height="26" rx="6" fill="#e2d7c6" />
          <path d="M96 53v7a10 10 0 0 0 20 0v-7M106 70v19m-10 0h20" />
          <path d="M121 39v42" stroke="#b08454" strokeWidth="5" />
        </g>
      );
    case "drafting":
      return (
        <g>
          <path d="m77 62 45-12 9 26-45 12Z" fill="#e2d7c6" stroke="#b08454" strokeWidth="4" />
          <path d="m89 64 22-6 5 13-22 6Z" stroke="#4a4038" />
          <path d="m84 88-4 15m43-24 5 24m-10-46-15 24" stroke="#b08454" strokeWidth="4" />
        </g>
      );
    case "armchair":
      return (
        <g>
          <rect x="88" y="52" width="34" height="39" rx="10" fill="#b08454" />
          <path d="M85 73v18h41V73m-34 19v10m27-10v10" stroke="#cbb99f" strokeWidth="5" />
          <rect x="97" y="60" width="16" height="23" rx="2" fill="#e2d7c6" transform="rotate(12 105 72)" />
        </g>
      );
    case "typewriter":
      return (
        <g>
          <path d="M88 79h38l-5-17H94Z" fill="#b08454" />
          <path d="M96 61V43h23v18" fill="#e2d7c6" />
          <path d="M101 51h13m-14 5h12m-15 15h20m-23 5h28" stroke="#4a4038" />
        </g>
      );
    case "chute":
      return (
        <g>
          <path d="m87 68 20-10 21 10v25l-21 10-20-10Z" fill="#b08454" />
          <path d="m87 68 20 10 21-10m-21 10v25m-10-40 21 10" stroke="#e2d7c6" />
          <path d="M88 45h35m-35 7h25" stroke="#cbb99f" />
        </g>
      );
    case "desk-storyboard":
      return (
        <g>
          <rect x="81" y="33" width="48" height="34" rx="3" fill="#b08454" />
          <path d="M88 40h13v9H88Zm20 0h13v9h-13Zm-20 15h13v6H88Zm20 0h13v6h-13Z" fill="#e2d7c6" stroke="none" />
          <path d="M84 83h45m-39 0v20m33-20v20" stroke="#cbb99f" strokeWidth="5" />
        </g>
      );
    default:
      return (
        <g>
          {prop === "dual-monitor" || prop === "preview-wall" ? (
            <>
              <rect x="78" y="42" width="25" height="27" rx="3" fill="#2f6f6a" />
              <rect x="107" y="42" width="25" height="27" rx="3" fill="#2f6f6a" />
              <path d="M90 69v10m29-10v10" />
              {prop === "preview-wall" && <path d="m85 50 9 6-9 6m29-12 9 6-9 6" stroke="#e2d7c6" />}
            </>
          ) : (
            <>
              <rect x="82" y="40" width="48" height="33" rx="4" fill="#2f6f6a" />
              <path d="M106 74v7" />
              {prop === "timeline" ? (
                <path d="M88 49h13m4 0h18M88 56h24m4 0h7M88 63h8m4 0h23" stroke="#e2d7c6" />
              ) : (
                <g stroke="#e2d7c6">
                  <circle cx="102" cy="54" r="7" />
                  <path d="m107 60 8 7" strokeWidth="3" />
                </g>
              )}
            </>
          )}
          <path d="M78 83h56m-49 0v20m42-20v20" stroke="#b08454" strokeWidth="5" />
        </g>
      );
  }
}

function CrewPortrait({
  agent,
  prop,
  zoneId,
  alternate,
}: {
  agent: ResolvedAgent;
  prop: WorkstationProp;
  zoneId: ZoneId;
  alternate: boolean;
}) {
  const glasses = zoneId === "research" || zoneId === "qc";
  return (
    <svg viewBox="0 0 144 112" className={styles.portrait} aria-hidden="true" focusable="false">
      <ellipse cx="71" cy="104" rx="62" ry="5" fill="#0e1117" />
      <g stroke="#cbb99f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <StationMotif prop={prop} />
      </g>
      <path d="M35 86v15m22-15v15" stroke="#4a4038" strokeWidth="11" strokeLinecap="round" />
      <path d="M28 69q0-17 18-17t18 17v20H28Z" fill={stateColor(characterState(agent))} />
      <path d="m27 67-5 17m43-17 5 17" stroke="#cbb99f" strokeWidth="8" strokeLinecap="round" />
      <path d="M40 48v10q6 6 12 0V48" fill="#b08454" />
      <rect x="29" y="19" width="34" height="34" rx="15" fill={alternate ? "#b08454" : "#e2d7c6"} />
      <path
        d={alternate ? "M28 35V24q2-16 20-15 19 2 17 25l-9-10-13 4-9-2Z" : "M28 33q-5-25 18-25 23 0 19 27l-10-13-22 6Z"}
        fill="#4a4038"
      />
      <g fill="#302a26">
        <circle cx="39" cy="36" r="1.7" />
        <circle cx="53" cy="36" r="1.7" />
      </g>
      <path d="M42 45q4 3 8 0" fill="none" stroke="#4a4038" strokeWidth="1.5" strokeLinecap="round" />
      {glasses && (
        <g fill="none" stroke="#4a4038" strokeWidth="2">
          <rect x="32" y="31" width="12" height="10" rx="4" />
          <rect x="48" y="31" width="12" height="10" rx="4" />
          <path d="M44 35h4" />
        </g>
      )}
      {zoneId === "audio" && (
        <g fill="none" stroke="#cbb99f" strokeWidth="5" strokeLinecap="round">
          <path d="M26 34v-9a20 20 0 0 1 40 0v9" />
          <path d="M26 32v10m40-10v10" stroke="#2f6f6a" strokeWidth="7" />
        </g>
      )}
      {(zoneId === "storyboard" || zoneId === "animation") && (
        <path d="m57 68 3 13" stroke="#f4bc68" strokeWidth="3" strokeLinecap="round" />
      )}
      {zoneId === "director" && <path d="m40 59 6 6 6-6-6 20Z" fill="#e2d7c6" />}
    </svg>
  );
}

export function StudioFallback({
  agents,
  onSelectAgent,
  focusZoneId,
  onFocusZone,
  jobId,
}: {
  agents: ResolvedAgent[];
  onSelectAgent: (agentId: string) => void;
  focusZoneId?: ZoneId | null;
  onFocusZone?: (id: ZoneId | null) => void;
  jobId?: string;
}) {
  const [localFocusId, setLocalFocusId] = useState<ZoneId | null>(null);
  const selectedZone = focusZoneId === undefined ? localFocusId : focusZoneId;
  const selectZone = (id: ZoneId | null) => {
    if (focusZoneId === undefined) setLocalFocusId(id);
    onFocusZone?.(id);
  };
  const byZone = new Map<ZoneId, ResolvedAgent[]>();
  for (const agent of agents) {
    const zone = AGENT_ZONE[agent.agent_id] ?? "director";
    const crew = byZone.get(zone);
    if (crew) crew.push(agent);
    else byZone.set(zone, [agent]);
  }

  return (
    <div
      className={styles.room}
      data-studio-scene
      data-quality="off"
      data-camera="flat"
      data-camera-target={selectedZone ?? "room"}
    >
      <div className={styles.roomHeader}>
        <div>
          <p className={styles.roomTitle}>Lantai produksi</p>
          <p className={styles.roomHint}>Pilih zona untuk fokus. Pilih kru untuk melihat detail.</p>
        </div>
        {selectedZone !== null && (
          <button type="button" className={styles.reset} onClick={() => selectZone(null)}>
            Semua zona
          </button>
        )}
      </div>
      {agents.length === 0 && (
        <p className={styles.empty}>Belum ada kru pada snapshot studio. Zona dan modul tetap dapat dibuka.</p>
      )}
      <div className={styles.floor}>
        {ZONES.map((zone, index) => {
          const selected = selectedZone === zone.id;
          const crew = byZone.get(zone.id) ?? [];
          return (
            <section
              key={zone.id}
              className={styles.zone}
              data-zone={zone.id}
              data-selected={selected}
              aria-label={zone.label}
            >
              <header className={styles.zoneHeader}>
                <h2>
                  <button
                    type="button"
                    className={styles.zoneFocus}
                    aria-label={`Fokus zona ${zone.label}`}
                    aria-pressed={selected}
                    onClick={() => selectZone(selected ? null : zone.id)}
                  >
                    <span className={styles.zoneNumber} aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                    <span>{zone.label}</span>
                    {selected && <span className={styles.selectedMark}>Dipilih</span>}
                  </button>
                </h2>
                <Link href={zoneHref(zone, jobId)} className={styles.moduleLink}>buka</Link>
              </header>
              {crew.length > 0 ? (
                <ul className={styles.crew}>
                  {crew.map((agent) => {
                    const state = characterState(agent);
                    return (
                      <li key={agent.agent_id}>
                        <button
                          type="button"
                          className={styles.character}
                          onClick={() => {
                            selectZone(zone.id);
                            onSelectAgent(agent.agent_id);
                          }}
                          aria-haspopup="dialog"
                          aria-controls="agent-inspector"
                          data-agent={agent.agent_id}
                          data-state={state}
                        >
                          <CrewPortrait
                            agent={agent}
                            prop={zone.prop}
                            zoneId={zone.id}
                            alternate={zone.agents.indexOf(agent.agent_id) > 0}
                          />
                          <span className={styles.agentLabel}>{AGENT_LABEL[agent.agent_id] ?? agent.agent_id}</span>
                          <span className={styles.state}>{state}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className={styles.emptyZone}>Tidak ada kru pada snapshot ini.</p>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
