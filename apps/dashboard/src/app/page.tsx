"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorState, Loading } from "@/components/states";
import { StudioProductionMonitor } from "@/components/StudioProductionMonitor";
import type { StudioEvent } from "@/lib/api";
import type { ResolvedAgent } from "@/lib/studioState";
import { characterState, type CharacterState } from "@/lib/studioState";
import { useStudio } from "@/lib/useStudio";
import { StudioFallback } from "@/three/StudioFallback";
import { StudioScene } from "@/three/StudioScene";
import { StudioViewport } from "@/three/StudioViewport";
import { AGENT_LABEL, AGENT_ZONE, ZONES, type ZoneId } from "@/three/zones";

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

const AGENT_ROLE: Record<string, string> = {
  DirectorAgent: "Mengarahkan ide dan brief produksi.",
  FactoryOrchestrator: "Mengatur urutan tahap dan eksekusi job.",
  ResearchAgent: "Menelusuri sumber dan memeriksa klaim konten.",
  TopicSelectionAgent: "Memilih topik dan sudut cerita.",
  ScriptAgent: "Menulis hook, alur cerita, dan penutup.",
  CreativeDirectorAgent: "Menilai naskah dan memberi arahan revisi.",
  StoryboardAgent: "Menyusun adegan dan komposisi visual.",
  AssetAgent: "Menyiapkan aset karakter, latar, dan audio.",
  AnimationAgent: "Merencanakan gerak karakter dan kamera.",
  AudioAgent: "Menyiapkan narasi dan waktu subtitle.",
  EditorAgent: "Merangkai adegan dan merender video.",
  QualityAgent: "Memeriksa kualitas teknis dan kreatif.",
  MetadataAgent: "Menyiapkan judul, deskripsi, dan metadata.",
  PublisherAgent: "Menangani publikasi setelah persetujuan operator.",
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
  const [jobId, setJobId] = useState<string | undefined>();
  const [scopeReady, setScopeReady] = useState(false);
  const { snapshot, agents: persistedAgents, error, connected, refresh, rendering: paused } = useStudio({ jobId });
  const [quality, setQuality] = useState<StudioQuality>("medium");
  const [qualityReady, setQualityReady] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [focusZoneId, setFocusZoneId] = useState<ZoneId | null>(null);
  const [rendererUnavailable, setRendererUnavailable] = useState(false);
  const inspectorRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  // A known workstation occupant without an event is a resting character, not a worker.
  const agents = useMemo<ResolvedAgent[]>(() => {
    const known = new Map(persistedAgents.map((agent) => [agent.agent_id, agent]));
    const roster = ZONES.flatMap((zone) => zone.agents).map((agentId) => {
      const recorded = known.get(agentId);
      known.delete(agentId);
      return recorded ?? {
        agent_id: agentId, status: "waiting", state: "idle", stale: false,
        task: "", progress: null, model: null, stage: null, job_id: null,
        updated_at: null, recent: [],
      } satisfies ResolvedAgent;
    });
    return [...roster, ...known.values()];
  }, [persistedAgents]);

  const selectedAgent = agents.find((agent) => agent.agent_id === selectedAgentId) ?? null;
  const focusZone = ZONES.find((zone) => zone.id === focusZoneId);
  const visibleAgents = focusZoneId
    ? agents.filter((agent) => AGENT_ZONE[agent.agent_id] === focusZoneId)
    : agents;
  const workingCount = agents.filter((agent) => characterState(agent) === "working").length;
  const attentionCount = agents.filter((agent) =>
    ["blocked", "failed"].includes(characterState(agent)),
  ).length;

  useEffect(() => {
    const readScope = () => {
      setJobId(new URLSearchParams(window.location.search).get("job_id") || undefined);
      setSelectedAgentId(null);
      setScopeReady(true);
    };
    readScope();
    window.addEventListener("popstate", readScope);
    return () => window.removeEventListener("popstate", readScope);
  }, []);

  const selectJob = (nextJobId: string | undefined) => {
    setSelectedAgentId(null);
    setJobId(nextJobId);
    const url = new URL(window.location.href);
    if (nextJobId) url.searchParams.set("job_id", nextJobId);
    else url.searchParams.delete("job_id");
    window.history.replaceState(window.history.state, "", url);
  };

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
    setRendererUnavailable(false);
    window.localStorage.setItem(QUALITY_KEY, next);
  };


  const flatRoom = (
    <StudioFallback
      agents={agents}
      jobId={jobId}
      onSelectAgent={openInspector}
      focusZoneId={focusZoneId}
      onFocusZone={setFocusZoneId}
    />
  );

  return (
    <div className="studio-workbench min-h-dvh p-3 sm:p-5 lg:p-6">
      <header className="studio-heading">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-ink-100 sm:text-3xl">
            Studio produksi Shorts
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-300">
            Dari ide sampai video, kenali tim dan ikuti pekerjaan di setiap ruang.
          </p>
          <p className="mt-2 text-xs text-ink-400" role="status" aria-live="polite">
            {connected ? "Pembaruan langsung aktif." : "Menghubungkan pembaruan langsung."}
            {" "}Status diambil dari event tersimpan, bukan simulasi.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/agents" className="btn min-h-11">Atur model agent</Link>
          <Link href="/create" className="btn btn-primary min-h-11">Buat video</Link>
        </div>
      </header>

      {scopeReady ? <StudioProductionMonitor jobId={jobId} onSelectJob={selectJob} /> : null}

      {!scopeReady || !snapshot ? (
        scopeReady && error
          ? <ErrorState message={error} onRetry={() => void refresh()} />
          : <Loading label="Memuat proyeksi studio dari event tersimpan…" />
      ) : (
      <>

      {error ? <div className="mb-4"><ErrorState message={error} onRetry={() => void refresh()} /></div> : null}

      <div className="studio-summary" aria-label="Ringkasan tim studio">
        <span><strong>{agents.length}</strong> agent di studio</span>
        <span><strong>{workingCount}</strong> sedang bekerja</span>
        <span className={attentionCount ? "text-amber-500" : ""}>
          <strong>{attentionCount}</strong> perlu perhatian
        </span>
        <span className="text-xs text-ink-400">{jobId ? "Aktivitas job terpilih" : "Aktivitas seluruh job"}</span>
      </div>

      <section aria-labelledby="workflow-heading" className="mb-5">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="workflow-heading" className="text-sm font-semibold">Alur produksi</h2>
          <p className="text-xs text-ink-400">Pilih tahap untuk memfokuskan ruang dan timnya.</p>
        </div>
        <ol className="studio-workflow">
          {ZONES.map((zone, index) => {
            const crew = agents.filter((agent) => AGENT_ZONE[agent.agent_id] === zone.id);
            const active = crew.filter((agent) => characterState(agent) === "working").length;
            const needsAttention = crew.some((agent) => ["blocked", "failed"].includes(characterState(agent)));
            return (
              <li key={zone.id}>
                <button
                  type="button"
                  className="studio-stage"
                  aria-pressed={focusZoneId === zone.id}
                  aria-label={`Lihat tahap ${zone.label}`}
                  onClick={() => setFocusZoneId((current) => current === zone.id ? null : zone.id)}
                >
                  <span className="studio-stage-number">{String(index + 1).padStart(2, "0")}</span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{zone.label}</span>
                    <span className={`mt-1 block text-xs ${needsAttention ? "text-amber-500" : "text-ink-300"}`}>
                      {needsAttention ? "Perlu perhatian" : active ? `${active} sedang bekerja` : `${crew.length} agent`}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </section>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <section className="studio-room min-w-0" aria-labelledby="room-heading">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-700 p-4">
            <div>
              <h2 id="room-heading" className="text-base font-semibold text-ink-100">Ruang produksi</h2>
              <p className="mt-1 text-xs text-ink-300">
                {focusZone ? `Fokus: ${focusZone.label}` : "Seluruh ruang"}.
                {" "}Pilih karakter untuk melihat tugasnya.
              </p>
            </div>
            <div className="flex items-end gap-2">
              {focusZoneId ? (
                <button type="button" className="btn min-h-11" onClick={() => setFocusZoneId(null)}>
                  Semua ruang
                </button>
              ) : null}
              <div>
                <label className="mb-1 block text-xs text-ink-300" htmlFor="studio-quality">Tampilan studio</label>
                <select
                  id="studio-quality"
                  className="field min-h-11"
                  value={quality}
                  onChange={(event) => changeQuality(event.target.value as StudioQuality)}
                >
                  {QUALITY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </div>
            </div>
          </div>
          {paused ? (
            <p
              role="status"
              aria-label="Studio dijeda: render sedang berjalan"
              title="Memori GPU tidak tersedia di browser, jadi jeda ini dipicu oleh event RENDERING yang aktif saja."
              className="studio-notice m-3 text-xs"
            >
              Render sedang berjalan. Studio dijeda selama event <code>RENDERING</code> aktif.
            </p>
          ) : null}
          {rendererUnavailable ? (
            <div role="status" className="studio-notice m-3 text-sm">
              <span>
                Tampilan 3D tidak tersedia atau koneksi GPU terputus.
                Tim tetap dapat dipilih di tampilan 2D.
              </span>
              <button type="button" className="btn min-h-11" onClick={() => setRendererUnavailable(false)}>
                Coba 3D lagi
              </button>
            </div>
          ) : null}
          <div className="studio-room-viewport">
            {!qualityReady ? <Loading label="Memuat preferensi tampilan…" /> : quality === "off" || rendererUnavailable ? (
              flatRoom
            ) : (
              <StudioViewport fallback={flatRoom} onUnavailable={() => setRendererUnavailable(true)}>
                <StudioScene
                  agents={agents}
                  jobId={jobId}
                  quality={quality}
                  paused={paused}
                  onSelectAgent={openInspector}
                  focusZoneId={focusZoneId}
                  onFocusZone={setFocusZoneId}
                  onUnavailable={() => setRendererUnavailable(true)}
                />
              </StudioViewport>
            )}
          </div>
          <div className="flex flex-wrap justify-between gap-2 border-t border-ink-700 px-4 py-3 text-xs text-ink-300">
            <span>{quality === "off" || rendererUnavailable ? "Pilih agent atau zona pada denah." : "Geser untuk memutar, scroll untuk zoom. Pilih tahap untuk memperjelas nama kru."}</span>
            <span>Animasi kerja hanya saat tugas aktif.</span>
          </div>
        </section>

        <section className="studio-crew min-w-0" aria-labelledby="characters-heading">
          <div className="border-b border-ink-700 p-4">
            <h2 id="characters-heading" className="text-base font-semibold text-ink-100">
              {focusZone ? `Tim ${focusZone.label}` : "Karakter"}
            </h2>
            <p className="mt-1 text-xs text-ink-300">Pilih agent untuk membuka inspector.</p>
          </div>
          <ul className="studio-crew-list" aria-label="Karakter studio">
            {visibleAgents.map((agent) => (
              <li key={agent.agent_id}>
                <button
                  type="button"
                  className="studio-crew-button"
                  onClick={() => openInspector(agent.agent_id)}
                  aria-haspopup="dialog"
                  aria-controls="agent-inspector"
                  data-agent={agent.agent_id}
                  data-state={characterState(agent)}
                >
                  <span className="flex items-start justify-between gap-2">
                    <span className="min-w-0 text-sm font-medium text-ink-100">{agentName(agent.agent_id)}</span>
                    <Status status={characterState(agent)} />
                  </span>
                  <span className="mt-2 block text-xs text-ink-300">
                    {agent.task || "Belum bertugas"}
                  </span>
                  <span className="mt-1 block text-xs text-ink-400">
                    {agent.model ? `Model tercatat: ${agent.model}` : "Belum ada model tercatat"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <AgentInspector dialogRef={inspectorRef} agent={selectedAgent} onClose={closeInspector} />
      </>
      )}
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

              <dt className="text-ink-400">Peran produksi</dt>
              <dd className="min-w-0 text-ink-200">
                {AGENT_ROLE[agent.agent_id] ?? "Agent pada alur produksi."}
              </dd>

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
            <Link className="btn mb-2 min-h-11 w-full justify-center" href="/agents">
              Buka pengaturan agent
            </Link>
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
