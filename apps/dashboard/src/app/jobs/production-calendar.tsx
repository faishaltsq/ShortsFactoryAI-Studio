"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type JobView } from "@/lib/api";

/**
 * Calendar view for production scheduling (M5): jobs with a future `scheduled_for` start,
 * plus the unscheduled backlog. Read-only projection — the schedule decides when production
 * may start, never the approval gate (a scheduled job still waits for a human decision).
 */
export function ProductionCalendar() {
  const [now, setNow] = useState<string>("");
  const [upcoming, setUpcoming] = useState<JobView[]>([]);
  const [backlog, setBacklog] = useState<JobView[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await api.upcoming();
      setNow(result.now);
      setUpcoming(result.upcoming);
      setBacklog(result.awaiting_schedule);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "gagal memuat kalender");
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(interval);
  }, [load]);

  return (
    <section className="panel mb-4 p-3" aria-labelledby="calendar-heading">
      <div className="flex items-baseline justify-between gap-3 px-1 pb-3">
        <h2 id="calendar-heading" className="text-sm font-semibold text-ink-100">
          Kalender produksi
        </h2>
        <span className="text-xs text-ink-400">{upcoming.length} terjadwal</span>
      </div>
      {error ? <p className="px-1 text-sm text-warn-500">{error}</p> : null}
      {!error && upcoming.length === 0 ? (
        <p className="px-1 text-sm text-ink-300">Belum ada jadwal produksi.</p>
      ) : null}
      <ul className="space-y-2" aria-label="Jadwal produksi mendatang">
        {upcoming.map((job) => (
          <li
            key={job.id}
            className="flex min-h-11 items-center justify-between gap-3 rounded-md border border-ink-700 bg-ink-800 px-3 py-2"
          >
            <span className="min-w-0 truncate text-sm text-ink-100">
              <span className="mr-2 rounded bg-ink-700 px-1.5 py-0.5 text-xs text-ink-300">
                P{job.priority}
              </span>
              {job.title}
            </span>
            <time className="shrink-0 text-xs text-ink-300" dateTime={job.scheduled_for ?? undefined}>
              {job.scheduled_for?.replace("T", " ")}
            </time>
          </li>
        ))}
      </ul>
      {backlog.length > 0 ? (
        <p className="px-1 pt-3 text-xs text-ink-400">
          {backlog.length} job menunggu penjadwalan · server {now.replace("T", " ")}
        </p>
      ) : null}
    </section>
  );
}
