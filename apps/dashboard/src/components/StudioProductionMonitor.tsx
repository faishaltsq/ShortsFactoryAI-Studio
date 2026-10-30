"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, type JobDetail, type JobView } from "@/lib/api";
import styles from "./StudioProductionMonitor.module.css";

type DetailState = {
  jobId: string | undefined;
  job: JobDetail | null;
  error: string | null;
  missing: boolean;
};

function eventTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function StudioProductionMonitor({
  jobId,
  onSelectJob,
}: {
  jobId: string | undefined;
  onSelectJob: (jobId: string | undefined) => void;
}) {
  const [jobs, setJobs] = useState<JobView[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailState | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    setDetail({ jobId, job: null, error: null, missing: false });
    setListError(null);

    const loadList = async () => {
      try {
        const result = await api.jobs();
        if (cancelled) return;
        setJobs(result.jobs);
        setListError(null);
      } catch (error) {
        if (cancelled) return;
        setListError(error instanceof Error ? error.message : "Permintaan daftar job gagal.");
      }
    };

    const loadDetail = async () => {
      if (jobId === undefined) return;
      try {
        const job = await api.job(jobId);
        if (cancelled) return;
        setDetail({ jobId, job, error: null, missing: false });
      } catch (error) {
        if (cancelled) return;
        setDetail({
          jobId,
          job: null,
          error: error instanceof Error ? error.message : "Permintaan detail job gagal.",
          missing: error instanceof ApiError && error.status === 404,
        });
      }
    };

    const poll = async () => {
      await Promise.all([loadList(), loadDetail()]);
      if (!cancelled) timer = window.setTimeout(() => void poll(), 2000);
    };
    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId, retry]);

  // Scope the rendered data too: effects run after the first render of a new selection.
  const selected = detail?.jobId === jobId ? detail : null;
  const job = selected?.job && selected.job.id === jobId ? selected.job : null;
  const selectedInList = jobs?.some((item) => item.id === jobId);
  const missingOption = selected?.missing
    ? "tidak ditemukan"
    : jobs === null ? "memuat daftar" : listError ? "daftar tidak tersedia" : "di luar daftar";
  const transitions = job ? [...job.events].sort((a, b) => b.id - a.id).slice(0, 4) : [];

  return (
    <section className={styles.monitor} aria-labelledby="production-monitor-heading">
      <div className={styles.header}>
        <div>
          <h2 id="production-monitor-heading">Monitor produksi</h2>
          <p>Hanya baca. Pilihan job menentukan aktivitas studio yang ditampilkan.</p>
        </div>
        <div className={styles.selector}>
          <label htmlFor="production-monitor-job">Pantau produksi</label>
          <select
            id="production-monitor-job"
            value={jobId ?? ""}
            onChange={(event) => onSelectJob(event.target.value || undefined)}
          >
            <option value="">Semua job</option>
            {jobId !== undefined && !selectedInList ? (
              <option value={jobId}>{job?.title ?? jobId} ({missingOption})</option>
            ) : null}
            {jobs?.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
        </div>
      </div>

      {listError ? (
        <div className={styles.notice} role="alert">
          <p>Daftar produksi gagal dimuat: {listError}. {jobs ? "Pilihan berasal dari daftar terakhir yang berhasil dimuat." : "Coba muat ulang daftar."}</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>Muat ulang daftar</button>
        </div>
      ) : jobs === null ? <p role="status" className={styles.message}>Memuat daftar produksi…</p> : null}

      {jobs?.length === 0 ? (
        <div className={styles.notice}>
          <p>Belum ada job dalam daftar produksi. Buat brief untuk menambahkan produksi.</p>
          <Link href="/create">Buat brief produksi</Link>
        </div>
      ) : null}

      {jobId === undefined ? (
        <div className={styles.aggregate}>
          <h3>Aktivitas semua job</h3>
          <p>Studio menggabungkan aktivitas tersimpan dari seluruh job. Agen dapat menampilkan job yang berbeda. Pilih satu produksi untuk melihat state, riwayat transisi, dan artefaknya secara terpisah.</p>
        </div>
      ) : (
        <div className={styles.production}>
          <div className={styles.productionHeading}>
            <div>
              <p className={styles.scope}>Produksi terpilih</p>
              <p className={styles.identifier}>ID: {jobId}</p>
            </div>
            <Link href={`/jobs?job_id=${encodeURIComponent(jobId)}`}>Buka detail produksi</Link>
          </div>

          {selected?.error ? (
            <div className={styles.notice} role="alert">
              <p>{selected.missing
                ? "Produksi terpilih tidak ditemukan. Job mungkin telah dihapus atau ID tidak dikenal. Pilihan tetap dipertahankan; pilih Semua job untuk kembali."
                : `Detail produksi gagal dimuat: ${selected.error}. Coba muat ulang detail.`}</p>
              <button type="button" onClick={() => setRetry((value) => value + 1)}>Muat ulang detail</button>
            </div>
          ) : !job ? <p role="status" className={styles.message}>Memuat detail produksi terpilih…</p> : (
            <>
              <h3 className={styles.title}>{job.title}</h3>
              <dl className={styles.facts}>
                <div><dt>State tersimpan</dt><dd>{job.state}</dd></div>
                <div><dt>Eksekusi</dt><dd>{job.running ? "Sedang berjalan" : "Idle (tidak berjalan)"}</dd></div>
                <div><dt>Mode provider</dt><dd>{job.is_mock || job.provider_mode === "mock" ? "Mock · tidak dapat dipublikasikan" : "Live · menggunakan provider nyata"}</dd></div>
                <div><dt>Video tersimpan</dt><dd>{job.has_video ? "Ada, lihat di detail produksi" : "Belum ada"}</dd></div>
              </dl>
              {job.last_error ? (
                <div className={styles.historyError} role="note">
                  <strong>Catatan error historis</strong>
                  <p>{job.last_error}</p>
                  <p>Ini last_error tersimpan, bukan kepastian bahwa eksekusi saat ini gagal.</p>
                </div>
              ) : null}
              <details className={styles.recordDisclosure}>
                <summary>Riwayat dan artefak produksi</summary>
              <div className={styles.records}>
                <div>
                  <h4>Transisi state terbaru</h4>
                  {transitions.length ? (
                    <ol className={styles.transitions}>
                      {transitions.map((event) => (
                        <li key={event.id}>
                          <span>{event.from_state ?? "Awal"} → {event.to_state}</span>
                          <time dateTime={event.created_at}>{eventTime(event.created_at)}</time>
                          {event.detail ? <p>{event.detail}</p> : null}
                        </li>
                      ))}
                    </ol>
                  ) : <p>Belum ada transisi state tersimpan untuk produksi ini.</p>}
                </div>
                <div>
                  <h4>Artefak tersimpan</h4>
                  {job.artifacts.length ? (
                    <>
                      <ul className={styles.artifacts}>
                        {job.artifacts.slice(0, 6).map((name) => <li key={name}>{name}</li>)}
                      </ul>
                      {job.artifacts.length > 6 ? <p>{job.artifacts.length - 6} artefak lainnya di detail produksi.</p> : null}
                    </>
                  ) : <p>Belum ada artefak tersimpan.</p>}
                </div>
              </div>
              </details>
            </>
          )}
        </div>
      )}
    </section>
  );
}
