"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { JobDetail } from "@/lib/api";
import { useJobSelection, type ArtifactResult } from "./useArtifactJob";
import styles from "./workspace.module.css";

export function Workspace({ title, description, children, library }: {
  title: string; description: string; children: (id: string) => ReactNode; library?: ReactNode;
}) {
  const { selectedId, jobs, error, select, reload } = useJobSelection();
  return <div className={styles.workspace}>
    <header className={styles.header}><h1>{title}</h1><p>{description}</p></header>
    <section className={styles.selection} aria-label="Pilihan job">
      <label htmlFor="artifact-job">Job tersimpan
        <select id="artifact-job" value={selectedId} onChange={(event) => select(event.target.value)}>
          <option value="">Pilih job</option>
          {selectedId && !jobs?.some((job) => job.id === selectedId) && <option value={selectedId}>{selectedId} (tautan langsung)</option>}
          {jobs?.map((job) => <option key={job.id} value={job.id}>{job.title} · {job.provider_mode} · {job.state}</option>)}
        </select>
      </label>
      <button type="button" onClick={reload}>Muat ulang daftar</button>
    </section>
    {error && <Notice error onRetry={reload}>Daftar job gagal dimuat: {error}</Notice>}
    {!jobs && !error && <p role="status">Memuat daftar job tersimpan…</p>}
    {jobs?.length === 0 && <Notice>Belum ada job tersimpan. <Link href="/create">Buat produksi</Link> untuk menghasilkan storyboard dan aset.</Notice>}
    {selectedId ? <div key={selectedId}>{children(selectedId)}</div> : <Notice>Pilih job untuk membaca artefak produksinya. Tidak ada pratinjau atau aset contoh.</Notice>}
    {library}
  </div>;
}

export function JobHeading({ detail, reload }: { detail: JobDetail; reload: () => void }) {
  const query = `?job_id=${encodeURIComponent(detail.id)}`;
  return <section className={styles.jobHeading} aria-label="Job terpilih">
    <div><h2>{detail.title}</h2><p>{detail.id} · {detail.provider_mode} · {detail.state}</p>
      {detail.is_mock && <p>Produksi mock, bukan hasil yang dapat dipublikasikan.</p>}
    </div>
    <nav aria-label="Tautan produksi" className={styles.links}>
      <Link href={`/jobs${query}`}>Detail job</Link><Link href={`/${query}`}>Studio</Link>
      {detail.has_video && <a href={`/api/jobs/${encodeURIComponent(detail.id)}/video`}>Buka video hasil</a>}
      <button type="button" onClick={reload}>Muat ulang artefak</button>
    </nav>
  </section>;
}

export function Notice({ children, error = false, onRetry }: { children: ReactNode; error?: boolean; onRetry?: () => void }) {
  return <div className={styles.notice} role={error ? "alert" : undefined}>
    <div>{children}</div>{onRetry && <button type="button" onClick={onRetry}>Coba lagi</button>}
  </div>;
}

export function ArtifactNotice({ name, result, onRetry }: { name: string; result?: ArtifactResult; onRetry: () => void }) {
  if (result?.data) return null;
  return <Notice error={!!result?.error} onRetry={result?.error ? onRetry : undefined}>
    {result?.error ? `${name} tidak dapat dibaca: ${result.error}` : `${name} belum diproduksi untuk job ini.`}
  </Notice>;
}

export function JsonDetails({ label, value }: { label: string; value: unknown }) {
  return <details className={styles.disclosure}><summary>{label}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}

export function Metadata({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([, item]) => item !== undefined && item !== null);
  return <dl className={styles.metadata}>{entries.map(([key, item]) => <div key={key}><dt>{key}</dt><dd>{
    typeof item === "object" ? <JsonDetails label="Lihat rincian" value={item} /> : String(item)
  }</dd></div>)}</dl>;
}
