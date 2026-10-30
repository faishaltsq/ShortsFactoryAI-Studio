"use client";

import { useCallback, useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/states";
import { api, type UsageSummary, type UsageSummaryRow } from "@/lib/api";

function formatCost(value: number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 6,
  }).format(value);
}

function formatTokens(value: number): string {
  return new Intl.NumberFormat("id-ID").format(value);
}

/**
 * The cost cell. The backend reports 0.0 for both "no price configured" and a genuinely free
 * call; it also reports which case applies, and this page must not present the first as the
 * second — an unpriced zero renders "belum dikonfigurasi", never a bare 0.
 */
function CostCell({ value, priced }: { value: number; priced: boolean }) {
  if (!priced) {
    return <span className="text-ink-400">belum dikonfigurasi</span>;
  }
  return <span className="tabular-nums">{formatCost(value)}</span>;
}

type TableProps = {
  id: string;
  title: string;
  countLabel: string;
  rows: UsageSummaryRow[];
  priced: boolean;
  columns: Array<{ key: string; label: string; value: (row: UsageSummaryRow) => string }>;
};

function SummaryTable({ id, title, countLabel, rows, priced, columns }: TableProps) {
  return (
    <section className="panel p-4 sm:p-5" aria-labelledby={`${id}-heading`}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 id={`${id}-heading`} className="text-sm font-semibold text-ink-100">
          {title}
        </h2>
        <span className="text-xs text-ink-400">{countLabel}</span>
      </div>
      {rows.length === 0 ? (
        <>
          <p className="mt-3 text-sm text-ink-400">Belum ada pemakaian tercatat.</p>
          <table className="mt-3 w-full text-left text-sm">
            <thead className="text-xs text-ink-400">
              <tr className="border-b border-ink-700">
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={`p-2 font-medium ${column.key === "cost" || column.key === "tokens" || column.key === "calls" ? "text-right" : ""}`}
                  >
                    {column.label}
                  </th>
                ))}
                <th scope="col" className="p-2 text-right font-medium">Estimasi biaya</th>
              </tr>
            </thead>
            <tbody />
          </table>
        </>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-[40rem] w-full text-left text-sm">
            <thead className="text-xs text-ink-400">
              <tr className="border-b border-ink-700">
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={`p-2 font-medium ${column.key === "cost" || column.key === "tokens" || column.key === "calls" ? "text-right" : ""}`}
                  >
                    {column.label}
                  </th>
                ))}
                <th scope="col" className="p-2 text-right font-medium">Estimasi biaya</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-700 text-ink-200">
              {rows.map((row, index) => (
                <tr key={columns.map((column) => column.value(row)).join("-") + index}>
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={`p-2 ${column.key === "cost" || column.key === "tokens" || column.key === "calls" ? "text-right tabular-nums" : ""}`}
                    >
                      {column.value(row)}
                    </td>
                  ))}
                  <td className="p-2 text-right">
                    <CostCell value={row.cost_usd} priced={priced} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function UsagePage() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSummary(await api.usageSummary());
      setError(null);
    } catch (loadFailure) {
      setError(loadFailure instanceof Error ? loadFailure.message : "gagal memuat pemakaian");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!summary && error) {
    return <ErrorState message={error} onRetry={() => void load()} />;
  }
  if (!summary) {
    return <Loading label="Memuat ringkasan pemakaian…" />;
  }

  const totalCalls = summary.days.reduce((acc, day) => acc + day.calls, 0);
  const totalTokens = summary.days.reduce((acc, day) => acc + day.tokens, 0);

  return (
    <div className="min-h-dvh p-3 sm:p-5 lg:p-6">
      <header className="mb-4 border-b border-ink-700 pb-4">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-100">Pemakaian</h1>
        <p className="mt-1 text-sm text-ink-300">
          Total {formatTokens(totalTokens)} token lewat {formatTokens(totalCalls)} panggilan model.
        </p>
      </header>

      {!summary.price_configured ? (
        <div className="mb-4 panel p-3 text-sm text-ink-300" role="note">
          Harga provider belum dikonfigurasi —kolom biaya menampilkan perkiraan 0, bukan gratis.
          Isi <code className="text-ink-100">price_in_per_mtok</code> /{" "}
          <code className="text-ink-100">price_out_per_mtok</code> pada provider untuk melihat biaya.
        </div>
      ) : null}

      <div className="space-y-4">
        <SummaryTable
          id="usage-days"
          title="Per hari"
          countLabel={`${summary.days.length} hari`}
          rows={summary.days}
          priced={summary.price_configured}
          columns={[{ key: "day", label: "Tanggal", value: (row) => row.day }]}
        />
        <SummaryTable
          id="usage-agents"
          title="Per agent"
          countLabel={`${summary.by_agent.length} agent`}
          rows={summary.by_agent}
          priced={summary.price_configured}
          columns={[
            { key: "day", label: "Tanggal", value: (row) => row.day },
            { key: "agent", label: "Agent", value: (row) => row.agent ?? "—" },
          ]}
        />
        <SummaryTable
          id="usage-models"
          title="Per model"
          countLabel={`${summary.by_model.length} model`}
          rows={summary.by_model}
          priced={summary.price_configured}
          columns={[
            { key: "day", label: "Tanggal", value: (row) => row.day },
            { key: "provider", label: "Provider", value: (row) => row.provider ?? "—" },
            { key: "model", label: "Model", value: (row) => row.model ?? "—" },
          ]}
        />
      </div>
    </div>
  );
}
