"use client";

import { ProductionCalendar } from "@/app/jobs/production-calendar";

/**
 * Production calendar (R1.4/M5): the read-only schedule projection on its own route.
 *
 *_deliberately read-only_: `scheduled_for` decides when production may start, never the
 * approval gate (invariant 7) — so there is nothing here an operator confirms; scheduling is
 * set at job creation, and the approval step stays human.
 */
export default function CalendarPage() {
  return (
    <main className="mx-auto max-w-3xl p-4" aria-labelledby="calendar-page-heading">
      <h1 id="calendar-page-heading" className="text-xl font-semibold text-ink-100">
        Kalender
      </h1>
      <p className="mb-3 mt-1 text-sm text-ink-300">
        Jadwal memutuskan kapan produksi boleh mulai. Persetujuan tetap butuh keputusan manual,
        apa pun jadwalnya.
      </p>
      <ProductionCalendar />
    </main>
  );
}
