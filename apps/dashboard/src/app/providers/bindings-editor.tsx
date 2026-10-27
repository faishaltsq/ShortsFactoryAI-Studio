"use client";

import { useState } from "react";
import { api, type AgentBinding } from "@/lib/api";

/// Bindable agents: every event-emitting completion agent. `FactoryOrchestrator` is the
/// runner's own identity and never picks a provider, so it is not offered.
const AGENTS = [
  "DirectorAgent",
  "ResearchAgent",
  "TopicSelectionAgent",
  "ScriptAgent",
  "CreativeDirectorAgent",
  "StoryboardAgent",
  "AssetAgent",
  "AnimationAgent",
  "AudioAgent",
  "EditorAgent",
  "QualityAgent",
  "MetadataAgent",
  "PublisherAgent",
] as const;

type Props = {
  bindings: AgentBinding[];
  providerIds: string[];
  onChanged: () => void;
};

export function BindingsEditor({ bindings, providerIds, onChanged }: Props) {
  const [rows, setRows] = useState<AgentBinding[]>(bindings);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  const update = (agent: string, patch: Partial<AgentBinding>) => {
    setRows((current) => {
      const next = current.some((row) => row.agent === agent)
        ? current.map((row) => (row.agent === agent ? { ...row, ...patch } : row))
        : [...current, { agent, primary: null, fallback: [], ...patch }];
      return next;
    });
    setDirty(true);
    setMessage(null);
  };

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const compact = rows
        .filter((row) => row.primary !== null || row.fallback.length > 0)
        .map((row) => ({ agent: row.agent, primary: row.primary, fallback: row.fallback }));
      const result = await api.saveBindings(compact);
      setRows(result.bindings.length > 0 ? result.bindings : []);
      setDirty(false);
      setError(false);
      setMessage("Binding tersimpan.");
      onChanged();
    } catch (saveError) {
      setError(true);
      setMessage(saveError instanceof Error ? saveError.message : String(saveError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel mt-4 p-4" aria-labelledby="bindings-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="bindings-heading" className="text-sm font-semibold text-ink-100">
          Binding agent
        </h2>
        <p className="text-xs text-ink-400">
          Agent tanpa binding memakai provider aktif pertama. Urutan fallback = urutan dicoba.
        </p>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {AGENTS.map((agent) => {
          const row = rows.find((entry) => entry.agent === agent);
          return (
            <div key={agent} className="rounded-md border border-ink-700 bg-ink-800 p-2">
              <label className="block text-xs font-medium text-ink-200" htmlFor={`primary-${agent}`}>
                {agent}
              </label>
              <select
                id={`primary-${agent}`}
                className="mt-1 min-h-9 w-full rounded border border-ink-600 bg-ink-900 px-2 text-sm text-ink-100"
                value={row?.primary ?? ""}
                onChange={(event) =>
                  update(agent, { primary: event.target.value === "" ? null : event.target.value })
                }
              >
                <option value="">— otomatis —</option>
                {providerIds.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
              <label className="mt-2 block text-xs text-ink-400" htmlFor={`fallback-${agent}`}>
                Fallback (urutan coba; Ctrl+klik untuk beberapa)
              </label>
              <select
                id={`fallback-${agent}`}
                multiple
                size={2}
                aria-label={`Fallback ${agent}`}
                className="mt-1 min-h-14 w-full rounded border border-ink-600 bg-ink-900 px-2 text-sm text-ink-100"
                value={row?.fallback ?? []}
                onChange={(event) =>
                  update(agent, {
                    fallback: Array.from(event.target.selectedOptions).map((opt) => opt.value),
                  })
                }
              >
                {providerIds.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className="btn min-h-11"
          disabled={busy || !dirty}
          onClick={() => void save()}
        >
          {busy ? "Menyimpan…" : "Simpan binding"}
        </button>
        {message ? (
          <p role="status" className={error ? "text-sm text-warn-500" : "text-sm text-ink-300"}>
            {message}
          </p>
        ) : null}
      </div>
    </section>
  );
}
