"use client";

export function Loading({ label = "Memuat…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6 text-sm text-ink-400">
      <span className="h-3 w-3 animate-pulse rounded-full bg-teal-400" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="panel m-4 p-4">
      <div className="text-sm font-semibold text-bad-500">Terjadi kesalahan</div>
      <p className="mt-1 text-sm text-ink-300">{message}</p>
      {onRetry ? (
        <button type="button" className="btn mt-3" onClick={onRetry}>
          Coba lagi
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="panel m-4 p-8 text-center">
      <div className="text-sm font-semibold text-ink-200">{title}</div>
      {hint ? <p className="mt-1 text-sm text-ink-400">{hint}</p> : null}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const known = ["working", "waiting", "completed", "blocked", "failed", "reviewing"];
  const cls = known.includes(status) ? `badge badge-${status}` : "badge badge-waiting";
  return <span className={cls}>{status}</span>;
}
