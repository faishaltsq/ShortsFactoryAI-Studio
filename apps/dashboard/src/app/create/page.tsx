"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ErrorState, Loading } from "@/components/states";
import { api } from "@/lib/api";

/**
 * Job creation with topic discovery (R1.4, M3).
 *
 * Discovery first: candidates come from production history and are metadata only — the route
 * never creates a job. Picking a candidate (or typing a topic) CreateJobBody's way into
 * `POST /api/jobs`, which stays the only path that spends provider budget. Live mode is offered
 * but the mock default is what a first-run operator should keep.
 */

type Candidate = { title: string; angle: string; why: string; score: number };

export default function CreatePage() {
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [providerMode, setProviderMode] = useState<"mock" | "live">("mock");
  const [renderVideo, setRenderVideo] = useState(false);
  const [priority, setPriority] = useState(5);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  const discover = useCallback(async () => {
    setDiscovering(true);
    setDiscoverError(null);
    try {
      const result = await api.discoverTopics({ limit: 5 });
      setCandidates(result.candidates);
    } catch (error) {
      setDiscoverError(error instanceof Error ? error.message : "discovery gagal");
    } finally {
      setDiscovering(false);
    }
  }, []);

  useEffect(() => {
    void discover();
  }, [discover]);

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreating(true);
    setMessage(null);
    setCreatedId(null);
    try {
      const job = await api.createJob({
        title,
        topic,
        provider_mode: providerMode,
        priority,
        render_video: renderVideo,
        ...(renderVideo ? { voice: "system-default" } : {}),
      });
      setCreatedId(job.id);
      setIsError(false);
      setMessage(`Job dibuat: ${job.id}.`);
      setTitle("");
      setTopic("");
    } catch (error) {
      setIsError(true);
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="mx-auto max-w-3xl space-y-4 p-4" aria-labelledby="create-heading">
      <h1 id="create-heading" className="text-xl font-semibold text-ink-100">Buat Video</h1>
      <p className="text-sm text-ink-300">
        Tema diusulkan dari riwayat produksi. Usulan tidak membuat job — job baru ada setelah
        formulir dikirim.
      </p>

      <section className="panel p-4" aria-labelledby="topics-heading">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="topics-heading" className="text-sm font-semibold text-ink-100">
            Usulan topik
          </h2>
          <button
            type="button"
            className="btn min-h-9 px-3 text-xs"
            disabled={discovering}
            onClick={() => void discover()}
          >
            {discovering ? "Menyimak riwayat…" : "Segarkan usulan"}
          </button>
        </div>
        {discoverError ? <ErrorState message={discoverError} /> : null}
        {candidates === null && !discoverError ? <Loading /> : null}
        {candidates !== null && candidates.length === 0 ? (
          <p className="mt-3 text-sm text-ink-400">
            Belum ada usulan — riwayat judul masih kosong. Tulis topik sendiri di bawah.
          </p>
        ) : null}
        {candidates && candidates.length > 0 ? (
          <ul className="mt-3 space-y-2">
            {candidates.map((candidate) => (
              <li key={candidate.title} className="panel-raised p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-ink-100">{candidate.title}</span>
                  <button
                    type="button"
                    className="btn min-h-9 px-3 text-xs"
                    onClick={() => {
                      setTitle(candidate.title);
                      setTopic(candidate.angle);
                    }}
                  >
                    Pakai
                  </button>
                </div>
                <p className="mt-1 text-xs text-ink-400">
                  {candidate.why} · skor {candidate.score}
                </p>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <form onSubmit={create} className="panel space-y-4 p-4" aria-labelledby="form-heading">
        <h2 id="form-heading" className="text-sm font-semibold text-ink-100">Detail video</h2>
        <div>
          <label className="label" htmlFor="create-title">Judul</label>
          <input
            id="create-title"
            className="field"
            value={title}
            maxLength={200}
            required
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="create-topic">Topik</label>
          <textarea
            id="create-topic"
            className="field min-h-20 resize-y"
            value={topic}
            maxLength={400}
            onChange={(event) => setTopic(event.target.value)}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="create-mode">Mode provider</label>
            <select
              id="create-mode"
              className="field"
              value={providerMode}
              onChange={(event) => setProviderMode(event.target.value as "mock" | "live")}
            >
              <option value="mock">mock (tanpa biaya)</option>
              <option value="live">live</option>
            </select>
          </div>
          <div>
            <label className="label" htmlFor="create-priority">Prioritas (1 = didahulukan)</label>
            <input
              id="create-priority"
              className="field"
              type="number"
              min={1}
              max={9}
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value))}
            />
          </div>
        </div>
        <label className="flex items-start gap-3 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={renderVideo}
            onChange={(event) => setRenderVideo(event.target.checked)}
          />
          <span>
            Render video dengan suara sistem lokal
            <span className="block text-xs text-ink-400">
              Memerlukan renderer dan suara Windows yang tersedia; proses dapat memakan beberapa menit.
              Tanpa pilihan ini, produksi berhenti setelah storyboard.
            </span>
          </span>
        </label>
        <button
          type="submit"
          className="btn btn-primary min-h-11 w-full justify-center"
          disabled={creating || !title.trim()}
        >
          {creating ? "Membuat…" : "Buat job"}
        </button>
      </form>

      {message ? (
        <p
          className={`break-words rounded-md border p-3 text-sm ${
            isError ? "border-bad-500 text-ink-100" : "border-ok-500 text-ink-100"
          }`}
          role={isError ? "alert" : "status"}
        >
          {message}
          {createdId ? (
            <>{" "}<Link className="underline" href={`/jobs?job_id=${encodeURIComponent(createdId)}`}>Buka job di Produksi</Link></>
          ) : null}
        </p>
      ) : null}
    </main>
  );
}
