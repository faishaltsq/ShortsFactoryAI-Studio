"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/states";
import type { StudioEvent, StudioStatus } from "@/lib/api";
import type { ResolvedAgent } from "@/lib/studioState";
import { characterState, type CharacterState } from "@/lib/studioState";
import { useStudio } from "@/lib/useStudio";
import { StudioFallback } from "@/three/StudioFallback";
import { StudioScene } from "@/three/StudioScene";
import { renderingActive } from "@/three/sceneState";
import { AGENT_LABEL } from "@/three/zones";

type StudioQuality = "high" | "medium" | "low" | "off";

const QUALITY_KEY = "shorts-studio-quality";
const QUALITY_OPTIONS: Array<{ value: StudioQuality; label: string }> = [
  { value: "high", label: "3D tinggi" },
  { value: "medium", label: "3D sedang" },
  { value: "low", label: "3D rendah" },
  { value: "off", label: "2D" },
];


const STATUS_LABEL: Record<CharacterState, string> = {
  working: "Bekerja",
  waiting: "Menunggu",
  idle: "Menganggur",
  blocked: "Diblokir",
  failed: "Gagal",
  completed: "Selesai",
};

function isStudioQuality(value: string | null): value is StudioQuality {
  return QUALITY_OPTIONS.some((option) => option.value === value);
}

function agentName(agentId: string): string {
  return AGENT_LABEL[agentId] ?? agentId;
}

function eventTime(event: StudioEvent): string {
  const date = new Date(event.created_at);
  if (Number.isNaN(date.getTime())) return event.created_at;
  return new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function Status({ status }: { status: CharacterState }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status]}</span>;
}

export default function StudioPage() {
  const { snapshot, agents, error, connected, refresh } = useStudio();
  const [quality, setQuality] = useState<StudioQuality>("medium");
  const [qualityReady, setQualityReady] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const inspectorRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === selectedAgentId) ?? null,
    [selectedAgentId, agents],
  );

  // Before the fallback branches: a `RENDERING` event pauses the room whether it is 3D or 2D.
  const paused = renderingActive(agents);

  useEffect(() => {
    const saved = window.localStorage.getItem(QUALITY_KEY);
    if (isStudioQuality(saved)) setQuality(saved);
    setQualityReady(true);
  }, []);

  useEffect(() => {
    const dialog = inspectorRef.current;
    if (!dialog) return;
    if (selectedAgent && !dialog.open) dialog.showModal();
    if (!selectedAgent && dialog.open) dialog.close();
  }, [selectedAgent]);

  const openInspector = (agentId: string) => {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSelectedAgentId(agentId);
  };

  const closeInspector = () => {
    setSelectedAgentId(null);
    window.requestAnimationFrame(() => openerRef.current?.focus());
  };

  const changeQuality = (next: StudioQuality) => {
    setQuality(next);
    window.localStorage.setItem(QUALITY_KEY, next);
  };

  if (!snapshot && error) {
    return <ErrorState message={error} onRetry={() => void refresh()} />;
  }

  if (!snapshot) {
    return <Loading label="Memuat proyeksi studio dari event tersimpan…" />;
  }

  if (agents.length === 0) {
    return (
      <Empty
        title="Belum ada karakter studio"
        hint="Snapshot studio tidak memuat agent. Coba muat ulang setelah API siap."
      />
    );
  }

  return (
    <div className="min-h-dvh p-3 sm:p-5 lg:p-6">
      <header className="mb-4 flex flex-col gap-4 border-b border-ink-700 pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-100">Studio</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-300">
            Proyeksi baca-saja dari event produksi yang tersimpan.
          </p>
          <p className="mt-2 text-xs text-ink-400" role="status" aria-live="polite">
            {connected ? "Pembaruan langsung aktif." : "Menghubungkan pembaruan langsung."}
          </p>
        </div>

        <div className="w-full sm:w-44">
          <label className="label" htmlFor="studio-quality">
            Tampilan studio
          </label>
          <select
            id="studio-quality"
            className="field min-h-11"
            value={quality}
            onChange={(event) => changeQuality(event.target.value as StudioQuality)}
          >
            {QUALITY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </header>

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void refresh()} />
        </div>
      ) : null}

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="panel min-w-0 overflow-hidden" aria-labelledby="room-heading">
          <div className="flex items-center justify-between gap-3 border-b border-ink-700 px-4 py-3">
            <div>
              <h2 id="room-heading" className="text-sm font-semibold text-ink-100">
                Ruang produksi
              </h2>
              <p className="text-xs text-ink-400">
                Pilih karakter untuk membaca status dan event terakhirnya.
              </p>
            </div>
            <span className="text-xs text-ink-400">{agents.length} agent</span>
          </div>

          <div className="h-[28rem] min-h-0 overflow-auto sm:h-[34rem] xl:h-[calc(100dvh-12rem)] xl:min-h-[36rem]">
            {paused ? (
              // ADR-008 gates the pause on free GPU memory, and the browser cannot read it. The
              // banner says what is true and what is not known instead of inventing a measurement.
              <p
                role="status"
                aria-label="Studio dijeda: render sedang berjalan"
                title="Memori GPU tidak tersedia di browser, jadi jeda ini dipicu oleh event RENDERING yang aktif saja."
                className="m-3 rounded border border-ink-700 bg-ink-900/80 px-3 py-2 text-xs text-ink-200"
              >
                Render sedang berjalan — studio dijeda selama event <code>RENDERING</code> aktif.
              </p>
            ) : null}
            {!qualityReady ? (
              <Loading label="Memuat preferensi tampilan…" />
            ) : quality === "off" ? (
              <StudioFallback agents={agents} onSelectAgent={openInspector} />
            ) : (
              <StudioScene
                agents={agents}
                quality={quality}
                paused={paused}
                onSelectAgent={openInspector}
              />
            )}
          </div>
        </section>

        <section className="panel min-w-0 p-3" aria-labelledby="characters-heading">
          <div className="px-1 pb-3">
            <h2 id="characters-heading" className="text-sm font-semibold text-ink-100">
              Karakter
            </h2>
            <p className="mt-1 text-xs text-ink-400">
              Daftar ini menyediakan akses keyboard ke inspector.
            </p>
          </div>
          <ul className="scroll-area space-y-2" aria-label="Karakter studio">
            {agents.map((agent) => (
              <li key={agent.agent_id}>
                <button
                  type="button"
                  className="panel-raised min-h-11 w-full px-3 py-2 text-left transition-colors hover:border-teal-500 hover:bg-ink-700"
                  onClick={() => openInspector(agent.agent_id)}
                  aria-haspopup="dialog"
                  aria-controls="agent-inspector"
                  data-agent={agent.agent_id}
                  data-state={characterState(agent)}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium text-ink-100">
                      {agentName(agent.agent_id)}
                    </span>
                    <Status status={characterState(agent)} />
                  </span>
                  <span className="mt-1 block truncate text-xs text-ink-400">
                    {agent.task || agentName(agent.agent_id)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <AgentInspector
        dialogRef={inspectorRef}
        agent={selectedAgent}
        onClose={closeInspector}
      />
    </div>
  );
}

function AgentInspector({
  dialogRef,
  agent,
  onClose,
}: {
  dialogRef: React.RefObject<HTMLDialogElement | null>;
  agent: ResolvedAgent | null;
  onClose: () => void;
}) {
  const events = agent?.recent.slice(-5).reverse() ?? [];

  return (
    <dialog
      ref={dialogRef}
      id="agent-inspector"
      aria-labelledby="agent-inspector-title"
      className="m-0 ml-auto h-dvh max-h-dvh w-full max-w-md border-0 border-l border-ink-700 bg-ink-900 p-0 text-ink-100 shadow-2xl backdrop:bg-black/70"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={onClose}
    >
      {agent ? (
        <div className="flex h-full flex-col">
          <header className="flex items-start justify-between gap-4 border-b border-ink-700 p-4 sm:p-5">
            <div className="min-w-0">
              <p className="text-xs text-ink-400">Inspector karakter</p>
              <h2 id="agent-inspector-title" className="mt-1 text-xl font-semibold text-ink-100">
                {agentName(agent.agent_id)}
              </h2>
              <p className="mt-1 text-sm text-ink-300">
                ID agent: {agent.agent_id}
              </p>
            </div>
            <button
              type="button"
              className="btn min-h-11 min-w-11 justify-center px-3"
              onClick={onClose}
              aria-label="Tutup inspector karakter"
              autoFocus
            >
              Tutup
            </button>
          </header>

          <div className="flex-1 overflow-y-auto p-4 sm:p-5">
            <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-4 text-sm">
              <dt className="text-ink-400">Nama</dt>
              <dd className="min-w-0 break-words text-ink-100">{agentName(agent.agent_id)}</dd>

              <dt className="text-ink-400">Peran teknis / ID agent</dt>
              <dd className="min-w-0 break-words text-ink-200">{agent.agent_id}</dd>

              <dt className="text-ink-400">Status</dt>
              <dd className="flex flex-wrap items-center gap-2">
                <Status status={characterState(agent)} />
                {agent.stale ? <span className="text-xs text-warn-500">Lease tidak aktif</span> : null}
              </dd>

              <dt className="text-ink-400">Tugas</dt>
              <dd className="min-w-0 break-words text-ink-200">
                {agent.task || "Belum ada tugas tercatat."}
              </dd>

              <dt className="text-ink-400">Model</dt>
              <dd className="min-w-0 break-words text-ink-200">
                {agent.model || "Tidak tercatat."}
              </dd>

              <dt className="text-ink-400">Progres</dt>
              <dd>
                {agent.progress === null ? (
                  <span className="text-ink-300">Belum dilaporkan.</span>
                ) : (
                  <div className="flex items-center gap-3">
                    <progress
                      className="h-2 min-w-0 flex-1 accent-teal-400"
                      value={agent.progress}
                      max={1}
                      aria-label={`Progres ${Math.round(agent.progress * 100)} persen`}
                    />
                    <span className="text-ink-200">{Math.round(agent.progress * 100)}%</span>
                  </div>
                )}
              </dd>
            </dl>

            <section className="mt-7 border-t border-ink-700 pt-5" aria-labelledby="events-heading">
              <div className="flex items-baseline justify-between gap-3">
                <h3 id="events-heading" className="text-sm font-semibold text-ink-100">
                  5 event terakhir untuk job ini
                </h3>
                <span className="text-xs text-ink-400">{events.length} event</span>
              </div>

              {events.length === 0 ? (
                <p className="mt-3 text-sm text-ink-400">
                  Belum ada event tersimpan untuk job ini.
                </p>
              ) : (
                <ol className="mt-3 space-y-3">
                  {events.map((event) => (
                    <li key={event.event_id} className="panel-raised p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-medium text-ink-200">
                          {agentName(event.agent_id)}
                        </span>
                        <span className={`badge badge-${event.status}`}>{STATUS_LABEL[event.status]}</span>
                      </div>
                      <p className="mt-2 break-words text-sm text-ink-200">
                        {event.description || event.event_type}
                      </p>
                      <time className="mt-2 block text-xs text-ink-400" dateTime={event.created_at}>
                        {eventTime(event)}
                      </time>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>

          <footer className="border-t border-ink-700 p-4 sm:p-5">
            {agent.job_id ? (
              <Link
                className="btn btn-primary min-h-11 w-full justify-center"
                href={`/jobs?job_id=${encodeURIComponent(agent.job_id)}`}
              >
                Buka job
              </Link>
            ) : (
              <p className="text-center text-sm text-ink-400">Karakter belum terkait dengan job.</p>
            )}
          </footer>
        </div>
      ) : null}
    </dialog>
  );
}
