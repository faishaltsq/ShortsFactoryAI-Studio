"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/states";
import { VideoSurface } from "@/components/VideoSurface";
import { api, type JobDetail, type JobView } from "@/lib/api";
import { ProductionCalendar } from "@/app/jobs/production-calendar";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatCost(value: number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 6,
  }).format(value);
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobView[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [createTitle, setCreateTitle] = useState("");
  const [createTopic, setCreateTopic] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadJobs = useCallback(async () => {
    try {
      const result = await api.jobs();
      setJobs(result.jobs);
      setListError(null);
      const requested = new URLSearchParams(window.location.search).get("job_id");
      setSelectedId((current) => current ?? requested ?? result.jobs[0]?.id ?? null);
    } catch (error) {
      setListError(error instanceof Error ? error.message : "gagal memuat job");
    }
  }, []);

  const loadDetail = useCallback(async (jobId: string) => {
    setDetailLoading(true);
    try {
      setDetail(await api.job(jobId));
      setDetailError(null);
    } catch (error) {
      // A failed refresh must not erase a panel the operator is already reading: keep the last
      // good detail and surface the failure as a banner instead.
      setDetailError(error instanceof Error ? error.message : "gagal memuat detail job");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    // Switching jobs must not leave the previous job's panel on screen, so drop a detail that
    // belongs to another job. A same-job poll keeps it.
    setDetail((current) => (current && current.id !== selectedId ? null : current));
    setDetailError(null);
    void loadDetail(selectedId);
  }, [loadDetail, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    const interval = window.setInterval(() => {
      void loadJobs();
      void loadDetail(selectedId);
    }, 1000);
    return () => window.clearInterval(interval);
  }, [loadDetail, loadJobs, selectedId]);

  const selectJob = (jobId: string) => {
    setSelectedId(jobId);
    const url = new URL(window.location.href);
    url.searchParams.set("job_id", jobId);
    window.history.replaceState(null, "", url);
  };

  const refreshSelected = async () => {
    await loadJobs();
    if (selectedId) await loadDetail(selectedId);
  };

  const createMockJob = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createJob({
        title: createTitle,
        topic: createTopic,
        provider_mode: "mock",
      });
      setCreateTitle("");
      setCreateTopic("");
      setSelectedId(created.id);
      const url = new URL(window.location.href);
      url.searchParams.set("job_id", created.id);
      window.history.replaceState(null, "", url);
      await loadJobs();
    } catch (createFailure) {
      setCreateError(createFailure instanceof Error ? createFailure.message : String(createFailure));
    } finally {
      setCreating(false);
    }
  };

  if (!jobs && listError) {
    return <ErrorState message={listError} onRetry={() => void loadJobs()} />;
  }

  if (!jobs) {
    return <Loading label="Memuat antrean produksi…" />;
  }

  if (jobs.length === 0) {
    return (
      <div className="min-h-dvh p-3 sm:p-5 lg:p-6">
        <CreateMockJobForm
          title={createTitle}
          topic={createTopic}
          creating={creating}
          error={createError}
          onTitleChange={setCreateTitle}
          onTopicChange={setCreateTopic}
          onSubmit={createMockJob}
        />
        <Empty title="Belum ada job produksi" hint="Buat job mock eksplisit untuk menguji pipeline lokal." />
      </div>
    );
  }

  return (
    <div className="min-h-dvh p-3 sm:p-5 lg:p-6">
      <header className="mb-4 border-b border-ink-700 pb-4">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-100">Produksi</h1>
        <p className="mt-1 text-sm text-ink-300">
          Antrean, hasil, dan keputusan operator untuk job yang tersimpan.
        </p>
      </header>

      <CreateMockJobForm
        title={createTitle}
        topic={createTopic}
        creating={creating}
        error={createError}
        onTitleChange={setCreateTitle}
        onTopicChange={setCreateTopic}
        onSubmit={createMockJob}
      />

      <ProductionCalendar />

      {listError ? (
        <div className="mb-4">
          <ErrorState message={listError} onRetry={() => void loadJobs()} />
        </div>
      ) : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <section className="panel min-w-0 p-3" aria-labelledby="job-list-heading">
          <div className="flex items-baseline justify-between gap-3 px-1 pb-3">
            <h2 id="job-list-heading" className="text-sm font-semibold text-ink-100">
              Job tersimpan
            </h2>
            <span className="text-xs text-ink-400">{jobs.length} job</span>
          </div>
          <ul className="scroll-area space-y-2" aria-label="Daftar job produksi">
            {jobs.map((job) => (
              <li key={job.id}>
                <button
                  type="button"
                  className={[
                    "min-h-11 w-full rounded-md border px-3 py-2 text-left transition-colors",
                    selectedId === job.id
                      ? "border-teal-500 bg-teal-600/20"
                      : "border-ink-700 bg-ink-800 hover:border-ink-600",
                  ].join(" ")}
                  aria-pressed={selectedId === job.id}
                  onClick={() => selectJob(job.id)}
                >
                  <span className="block truncate text-sm font-medium text-ink-100">{job.title}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-400">
                    <span>{job.state}</span>
                    <span>{job.provider_mode}</span>
                    {job.running ? <span className="text-teal-400">berjalan</span> : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <div className="min-w-0">
          {/* The panel stays mounted while a refresh is in flight: unmounting it on every poll
              destroyed transient operator messages and made the panel blink once a second. */}
          {detailLoading ? (
            <p className="mb-2 text-xs text-ink-400" role="status">
              memuat ulang…
            </p>
          ) : null}
          {detailError && detail ? (
            <div
              className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-bad-500 p-3 text-sm text-ink-200"
              role="alert"
            >
              <span className="break-words">{detailError}</span>
              <button
                type="button"
                className="btn btn-primary min-h-9"
                onClick={() => selectedId && void loadDetail(selectedId)}
              >
                Coba lagi
              </button>
            </div>
          ) : null}
          {!detail && detailLoading ? <Loading label="Memuat detail job…" /> : null}
          {!detail && !detailLoading && detailError ? (
            <ErrorState
              message={detailError}
              onRetry={selectedId ? () => void loadDetail(selectedId) : undefined}
            />
          ) : null}
          {detail ? <JobDetails key={detail.id} job={detail} onRefresh={refreshSelected} /> : null}
        </div>
      </div>
    </div>
  );
}

function CreateMockJobForm({
  title,
  topic,
  creating,
  error,
  onTitleChange,
  onTopicChange,
  onSubmit,
}: {
  title: string;
  topic: string;
  creating: boolean;
  error: string | null;
  onTitleChange: (value: string) => void;
  onTopicChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form className="panel mb-4 p-4" onSubmit={onSubmit} aria-labelledby="create-job-heading">
      <h2 id="create-job-heading" className="text-sm font-semibold text-ink-100">
        Buat job mock
      </h2>
      <p className="mt-1 text-xs text-ink-400">
        Mode mock eksplisit untuk menguji pipeline lokal. Job ini tidak dapat dipublikasikan.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <div>
          <label className="label" htmlFor="create-job-title">Judul</label>
          <input
            id="create-job-title"
            className="field"
            value={title}
            maxLength={200}
            required
            onChange={(event) => onTitleChange(event.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="create-job-topic">Topik</label>
          <input
            id="create-job-topic"
            className="field"
            value={topic}
            maxLength={400}
            onChange={(event) => onTopicChange(event.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-primary min-h-11 justify-center" disabled={creating}>
          {creating ? "Membuat…" : "Buat job mock"}
        </button>
      </div>
      {error ? <p className="mt-3 text-sm text-bad-500" role="alert">{error}</p> : null}
    </form>
  );
}

function JobDetails({ job, onRefresh }: { job: JobDetail; onRefresh: () => Promise<void> }) {
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [decisionMessage, setDecisionMessage] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState(false);
  const [submitting, setSubmitting] = useState<"approve" | "reject" | "run" | "cancel" | null>(null);
  const decisionAvailable = job.state === "READY_FOR_APPROVAL";

  const approve = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting("approve");
    setDecisionMessage(null);
    try {
      const result = await api.approve(job.id, operator);
      setDecisionError(false);
      setDecisionMessage(result.decision);
      await onRefresh();
    } catch (error) {
      setDecisionError(true);
      setDecisionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(null);
    }
  };

  const reject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting("reject");
    setDecisionMessage(null);
    try {
      const result = await api.reject(job.id, operator, reason);
      setDecisionError(false);
      setDecisionMessage(result.decision);
      setReason("");
      await onRefresh();
    } catch (error) {
      setDecisionError(true);
      setDecisionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(null);
    }
  };

  const runJob = async () => {
    setSubmitting("run");
    setDecisionMessage(null);
    try {
      await api.runJob(job.id);
      setDecisionError(false);
      setDecisionMessage("Job dimulai.");
      await onRefresh();
    } catch (error) {
      setDecisionError(true);
      setDecisionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(null);
    }
  };

  const cancelJob = async () => {
    setSubmitting("cancel");
    setDecisionMessage(null);
    try {
      await api.cancelJob(job.id, "dibatalkan operator dari dashboard");
      setDecisionError(false);
      setDecisionMessage("Pembatalan diminta.");
      await onRefresh();
    } catch (error) {
      setDecisionError(true);
      setDecisionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <article className="space-y-4" aria-labelledby="job-detail-heading">
      <section className="panel p-4 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h2 id="job-detail-heading" className="break-words text-xl font-semibold text-ink-100">
              {job.title}
            </h2>
            <p className="mt-1 break-all text-xs text-ink-400">ID: {job.id}</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="badge badge-waiting">{job.state}</span>
            <span className="badge badge-waiting">{job.provider_mode}</span>
          </div>
        </div>
        {job.last_error ? (
          <p className="mt-4 rounded-md border border-bad-500 p-3 text-sm text-ink-200" role="alert">
            {job.last_error}
          </p>
        ) : null}
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            className="btn btn-primary min-h-11 justify-center"
            disabled={job.running || submitting !== null}
            onClick={() => void runJob()}
          >
            {submitting === "run" ? "Memulai…" : "Jalankan job"}
          </button>
          <button
            type="button"
            className="btn btn-danger min-h-11 justify-center"
            disabled={!job.running || submitting !== null}
            onClick={() => void cancelJob()}
          >
            {submitting === "cancel" ? "Membatalkan…" : "Batalkan job"}
          </button>
        </div>
      </section>

      <VideoSurface
        jobId={job.id}
        title={job.title}
        hasVideo={job.has_video}
        isMock={job.is_mock}
      />

      <DecisionPanel
        operator={operator}
        reason={reason}
        decisionAvailable={decisionAvailable}
        decisionMessage={decisionMessage}
        decisionError={decisionError}
        submitting={submitting}
        onOperatorChange={setOperator}
        onReasonChange={setReason}
        onApprove={approve}
        onReject={reject}
      />

      <section className="panel p-4 sm:p-5" aria-labelledby="artifacts-heading">
        <div className="flex items-baseline justify-between gap-3">
          <h3 id="artifacts-heading" className="text-sm font-semibold text-ink-100">
            Artefak
          </h3>
          <span className="text-xs text-ink-400">{job.artifacts.length}</span>
        </div>
        {job.artifacts.length === 0 ? (
          <p className="mt-3 text-sm text-ink-400">Belum ada artefak tersimpan.</p>
        ) : (
          <ul className="mt-3 divide-y divide-ink-700 text-sm text-ink-200">
            {job.artifacts.map((artifact) => (
              <li key={artifact} className="break-all py-2">
                {artifact}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel p-4 sm:p-5" aria-labelledby="events-heading">
        <div className="flex items-baseline justify-between gap-3">
          <h3 id="events-heading" className="text-sm font-semibold text-ink-100">
            Event job
          </h3>
          <span className="text-xs text-ink-400">{job.events.length}</span>
        </div>
        {job.events.length === 0 ? (
          <p className="mt-3 text-sm text-ink-400">Belum ada event tersimpan.</p>
        ) : (
          <ol className="mt-3 space-y-3">
            {job.events.map((event) => (
              <li key={event.id} className="panel-raised p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-ink-100">{event.to_state}</span>
                  <time className="text-xs text-ink-400" dateTime={event.created_at}>
                    {formatDate(event.created_at)}
                  </time>
                </div>
                {event.from_state ? (
                  <p className="mt-1 text-xs text-ink-400">Dari {event.from_state}</p>
                ) : null}
                {event.detail ? <p className="mt-2 break-words text-sm text-ink-200">{event.detail}</p> : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="panel p-4 sm:p-5" aria-labelledby="usage-heading">
        <div className="flex items-baseline justify-between gap-3">
          <h3 id="usage-heading" className="text-sm font-semibold text-ink-100">
            Penggunaan model
          </h3>
          <span className="text-xs text-ink-400">{job.usage.length} panggilan</span>
        </div>
        {job.usage.length === 0 ? (
          <p className="mt-3 text-sm text-ink-400">Belum ada penggunaan model tercatat.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-[48rem] w-full text-left text-sm">
              <thead className="text-xs text-ink-400">
                <tr className="border-b border-ink-700">
                  <th className="p-2 font-medium" scope="col">Agent</th>
                  <th className="p-2 font-medium" scope="col">Provider / model</th>
                  <th className="p-2 text-right font-medium" scope="col">Token masuk</th>
                  <th className="p-2 text-right font-medium" scope="col">Token keluar</th>
                  <th className="p-2 text-right font-medium" scope="col">Estimasi biaya</th>
                  <th className="p-2 text-right font-medium" scope="col">Durasi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-700 text-ink-200">
                {job.usage.map((row, index) => (
                  <tr key={`${row.agent}-${row.created_at}-${index}`}>
                    <td className="p-2">{row.agent}</td>
                    <td className="p-2">
                      <span className="block">{row.provider}</span>
                      <span className="block text-xs text-ink-400">{row.model}</span>
                    </td>
                    <td className="p-2 text-right tabular-nums">{row.prompt_tokens}</td>
                    <td className="p-2 text-right tabular-nums">{row.completion_tokens}</td>
                    <td className="p-2 text-right tabular-nums">{formatCost(row.est_cost_usd)}</td>
                    <td className="p-2 text-right tabular-nums">{row.elapsed_ms} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </article>
  );
}

type DecisionPanelProps = {
  operator: string;
  reason: string;
  decisionAvailable: boolean;
  decisionMessage: string | null;
  decisionError: boolean;
  submitting: "approve" | "reject" | "run" | "cancel" | null;
  onOperatorChange: (value: string) => void;
  onReasonChange: (value: string) => void;
  onApprove: (event: FormEvent<HTMLFormElement>) => void;
  onReject: (event: FormEvent<HTMLFormElement>) => void;
};

function DecisionPanel({
  operator,
  reason,
  decisionAvailable,
  decisionMessage,
  decisionError,
  submitting,
  onOperatorChange,
  onReasonChange,
  onApprove,
  onReject,
}: DecisionPanelProps) {
  return (
    <section className="panel p-4 sm:p-5" aria-labelledby="decision-heading">
      <h3 id="decision-heading" className="text-sm font-semibold text-ink-100">
        Keputusan operator
      </h3>
      {!decisionAvailable ? (
        <p className="mt-2 text-sm text-ink-400">
          Persetujuan dan penolakan tersedia saat state READY_FOR_APPROVAL.
        </p>
      ) : null}

      <div className="mt-4">
        <label className="label" htmlFor="decision-operator">
          Nama operator
        </label>
        <input
          id="decision-operator"
          className="field"
          value={operator}
          maxLength={120}
          required
          disabled={!decisionAvailable || submitting !== null}
          onChange={(event) => onOperatorChange(event.target.value)}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <form onSubmit={onApprove}>
          <button
            type="submit"
            className="btn btn-primary min-h-11 w-full justify-center"
            disabled={!decisionAvailable || !operator.trim() || submitting !== null}
          >
            {submitting === "approve" ? "Menyetujui…" : "Setujui job"}
          </button>
        </form>

        <form onSubmit={onReject}>
          <label className="label" htmlFor="rejection-reason">
            Alasan penolakan
          </label>
          <textarea
            id="rejection-reason"
            className="field min-h-24 resize-y"
            value={reason}
            maxLength={600}
            required
            disabled={!decisionAvailable || submitting !== null}
            onChange={(event) => onReasonChange(event.target.value)}
          />
          <button
            type="submit"
            className="btn btn-danger mt-3 min-h-11 w-full justify-center"
            disabled={!decisionAvailable || !operator.trim() || !reason.trim() || submitting !== null}
          >
            {submitting === "reject" ? "Menolak…" : "Tolak job"}
          </button>
        </form>
      </div>

      {decisionMessage ? (
        <p
          className={`mt-4 break-words rounded-md border p-3 text-sm ${
            decisionError ? "border-bad-500 text-ink-100" : "border-ok-500 text-ink-100"
          }`}
          role={decisionError ? "alert" : "status"}
        >
          {decisionMessage}
        </p>
      ) : null}
    </section>
  );
}
