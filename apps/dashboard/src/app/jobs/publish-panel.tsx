"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type JobDetail, type PublishReport, type ReconcileReport } from "@/lib/api";

/**
 * Publish surface for one approved job.
 *
 * State gating mirrors the API: publishing is only possible at APPROVED and only for live jobs
 * (a mock job's video is fabricated, so `publishable` is false at the gate and the publish call
 * would be refused with 409 — the panel hides the action instead of offering a guaranteed
 * failure). `phase === "uncertain"` switches the panel to reconcile mode: the record says an
 * upload *may* have happened, so the only safe next step is asking the channel, never a retry.
 */
export function PublishPanel({
  job,
  onRefresh,
}: {
  job: JobDetail;
  onRefresh: () => Promise<void>;
}) {
  const [report, setReport] = useState<PublishReport | null>(null);
  const [reconcileReport, setReconcileReport] = useState<ReconcileReport | null>(null);
  const [busy, setBusy] = useState<"publish" | "reconcile" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  const publishable = job.state === "APPROVED" && !job.is_mock;

  const refreshPublication = useCallback(async () => {
    try {
      const publication = (await api.artifact(job.id, "publication.json")) as {
        phase?: string;
        video_id?: string | null;
        idempotency_key?: string;
      };
      setReconcileReport(
        publication.phase === "uncertain"
          ? {
              job_id: job.id,
              phase: "uncertain",
              video_id: publication.video_id ?? null,
              idempotency_key: publication.idempotency_key ?? "",
              attempt: 0,
              receipt_steps: [],
            }
          : null,
      );
    } catch {
      // 404: no publication record — the job has not published (or the phase is terminal-clean).
      setReconcileReport(null);
    }
  }, [job.id]);

  useEffect(() => {
    if (job.state === "APPROVED") void refreshPublication();
  }, [job.state, refreshPublication]);

  const publish = async () => {
    setBusy("publish");
    setMessage(null);
    try {
      const result = await api.publish(job.id);
      setReport(result);
      setIsError(!result.ok);
      if (result.ok) {
        setMessage(
          result.stages.map((stage) => `${stage.name}: ${stage.ok ? "ok" : (stage.detail ?? "gagal")}`).join(" · "),
        );
        await onRefresh();
      } else {
        setMessage(result.detail ?? result.stopped ?? "publish tidak selesai");
      }
    } catch (error) {
      setIsError(true);
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  const reconcile = async () => {
    setBusy("reconcile");
    setMessage(null);
    try {
      const result = await api.reconcile(job.id);
      setReconcileReport(result);
      setIsError(false);
      setMessage(
        result.phase === "confirmed"
          ? `Rekonsiliasi: temuan video ${result.video_id ?? ""} — status confirmed.`
          : "Rekonsiliasi: tidak ada video di kanal — boleh publish ulang.",
      );
      await onRefresh();
    } catch (error) {
      setIsError(true);
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  if (job.state !== "APPROVED" && !reconcileReport && !report) {
    return null;
  }

  return (
    <section className="panel p-4 sm:p-5" aria-labelledby="publish-heading">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="publish-heading" className="text-sm font-semibold text-ink-100">
          Publikasi (privat)
        </h3>
        <span className="text-xs text-ink-400">transport: stub</span>
      </div>

      {job.is_mock ? (
        <p className="mt-2 text-sm text-ink-400">
          Job mock tidak dapat dipublikasikan: videonya fabrikasi, publishable selalu false.
        </p>
      ) : null}

      {reconcileReport ? (
        <div className="mt-3 rounded-md border border-warn-500 p-3 text-sm text-ink-200">
          <p className="font-medium text-ink-100">Publikasi tidak pasti (uncertain)</p>
          <p className="mt-1 break-all text-xs text-ink-400">
            idempotency: {reconcileReport.idempotency_key || "—"}
          </p>
          <p className="mt-1">
            Catatan mencatat upload yang mungkin sudah terjadi. Minta channel daftar video privat
            sebelum mencoba apa pun lagi — publish ulang bisa berarti upload duplikat.
          </p>
          <button
            type="button"
            className="btn btn-primary mt-3 min-h-11 justify-center"
            disabled={busy !== null}
            onClick={() => void reconcile()}
          >
            {busy === "reconcile" ? "Memeriksa kanal…" : "Rekonsiliasi dengan channel"}
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="btn btn-primary mt-3 min-h-11 w-full justify-center"
          disabled={!publishable || busy !== null}
          onClick={() => void publish()}
        >
          {busy === "publish" ? "Mempublikasikan…" : "Publish ke private (stub)"}
        </button>
      )}

      {report ? (
        <ul className="mt-3 space-y-1 text-xs text-ink-300">
          {report.stages.map((stage) => (
            <li key={stage.name} className="break-words">
              {stage.name}: {stage.ok ? (stage.reused ? "reused" : "ok") : (stage.detail ?? "gagal")}
            </li>
          ))}
        </ul>
      ) : null}

      {message ? (
        <p
          className={`mt-3 break-words rounded-md border p-3 text-sm ${
            isError ? "border-bad-500 text-ink-100" : "border-ok-500 text-ink-100"
          }`}
          role={isError ? "alert" : "status"}
        >
          {message}
        </p>
      ) : null}
    </section>
  );
}
