"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ErrorState, Loading } from "@/components/states";
import {
  api,
  type AgentConfigView,
  type AgentModelBinding,
  type ProviderView,
} from "@/lib/api";
import { AGENT_LABEL } from "@/three/zones";

function displayName(id: string): string {
  return AGENT_LABEL[id] ?? id;
}

function effectiveModel(agent: AgentConfigView, providers: ProviderView[]): string {
  if (agent.kind === "deterministic") return "Tidak memakai model";
  if (agent.binding.model) return agent.binding.model;
  const provider = providers.find((item) => item.id === agent.binding.primary);
  return provider?.model || "Belum diatur";
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentConfigView[] | null>(null);
  const [providers, setProviders] = useState<ProviderView[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [agentResult, providerResult] = await Promise.all([api.agents(), api.providers()]);
      setAgents(agentResult.agents);
      setProviders(providerResult.providers);
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "gagal memuat agent");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!agents && error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!agents) return <Loading label="Memuat agent dan model…" />;

  const llmCount = agents.filter((agent) => agent.kind === "llm").length;
  return (
    <main className="min-h-dvh p-3 sm:p-5 lg:p-6" aria-labelledby="agents-heading">
      <header className="mb-4 border-b border-ink-700 pb-4">
        <h1 id="agents-heading" className="text-2xl font-semibold tracking-tight text-ink-100">
          Agent
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-300">
          Semua unit kerja produksi. Hanya agent LLM yang memakai provider dan model; agent
          deterministik menjalankan kode lokal.
        </p>
        <p className="mt-2 text-xs text-ink-400">
          {agents.length} agent · {llmCount} memakai model · {agents.length - llmCount} deterministik
        </p>
      </header>

      {error ? <div className="mb-4"><ErrorState message={error} onRetry={() => void load()} /></div> : null}

      <div className="grid gap-3 lg:grid-cols-2">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            providers={providers}
            model={effectiveModel(agent, providers)}
          />
        ))}
      </div>
    </main>
  );
}

function AgentCard({
  agent,
  providers,
  model,
}: {
  agent: AgentConfigView;
  providers: ProviderView[];
  model: string;
}) {
  const [binding, setBinding] = useState<AgentModelBinding>(agent.binding);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const deterministic = agent.kind === "deterministic";
  const primary = providers.find((provider) => provider.id === binding.primary);

  const patch = (next: Partial<AgentModelBinding>) => {
    setBinding((current) => ({ ...current, ...next }));
    setMessage(null);
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const result = await api.saveAgentBinding(agent.id, binding);
      setBinding(result.binding);
      setFailed(false);
      setMessage("Binding tersimpan.");
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="panel p-4 sm:p-5" aria-label={agent.id}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-ink-100">{displayName(agent.id)}</h2>
          <p className="mt-1 break-all text-xs text-ink-400">{agent.id}</p>
        </div>
        <span className="badge badge-waiting">{deterministic ? "deterministik" : "LLM"}</span>
      </div>

      <dl className="mt-4 grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
        <dt className="text-ink-400">Model</dt>
        <dd className="break-words font-medium text-ink-100">{model}</dd>
        <dt className="text-ink-400">Provider</dt>
        <dd className="break-words text-ink-200">
          {deterministic ? "Kode lokal" : primary?.label || "Belum diikat"}
        </dd>
        <dt className="text-ink-400">Kemampuan</dt>
        <dd className="flex flex-wrap gap-1.5">
          {(agent.requires.length ? agent.requires : ["tidak ada"]).map((capability) => (
            <span key={capability} className="badge badge-waiting">{capability}</span>
          ))}
        </dd>
      </dl>

      {agent.capability_gaps.length > 0 ? (
        <p className="mt-4 rounded-md border border-warn-500 p-3 text-sm text-ink-200" role="alert">
          Provider aktif belum memenuhi: {agent.capability_gaps.join(", ")}.
        </p>
      ) : null}

      {deterministic ? (
        <p className="mt-4 text-sm text-ink-400">Kontrak ini dijalankan oleh kode lokal.</p>
      ) : (
        <details className="mt-4 border-t border-ink-700 pt-4">
          <summary className="cursor-pointer text-sm font-medium text-ink-200">Atur model</summary>
          <form className="mt-4 space-y-4" onSubmit={save} aria-label={`Binding ${agent.id}`}>
            <label className="block text-sm text-ink-300">
              <span className="label">Provider utama</span>
              <select
                className="field"
                value={binding.primary ?? ""}
                onChange={(event) => patch({ primary: event.target.value || null })}
              >
                <option value="">Belum diikat</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.label || provider.id}
                  </option>
                ))}
              </select>
            </label>

            <fieldset>
              <legend className="label">Provider fallback</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {providers.map((provider) => {
                  const checked = binding.fallback.includes(provider.id);
                  return (
                    <label key={provider.id} className="flex min-h-10 items-center gap-2 text-sm text-ink-300">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={provider.id === binding.primary}
                        onChange={(event) =>
                          patch({
                            fallback: event.target.checked
                              ? [...binding.fallback, provider.id]
                              : binding.fallback.filter((id) => id !== provider.id),
                          })
                        }
                      />
                      {provider.label || provider.id}
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-3">
              <label className="block text-sm text-ink-300">
                <span className="label">Model override</span>
                <input
                  className="field"
                  value={binding.model ?? ""}
                  placeholder={primary?.model || "ikuti provider"}
                  onChange={(event) => patch({ model: event.target.value || null })}
                />
              </label>
              <label className="block text-sm text-ink-300">
                <span className="label">Temperature</span>
                <input
                  className="field"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={binding.temperature ?? ""}
                  onChange={(event) => patch({ temperature: event.target.value === "" ? null : Number(event.target.value) })}
                />
              </label>
              <label className="block text-sm text-ink-300">
                <span className="label">Max token</span>
                <input
                  className="field"
                  type="number"
                  min={1}
                  max={200000}
                  value={binding.max_tokens ?? ""}
                  onChange={(event) => patch({ max_tokens: event.target.value === "" ? null : Number(event.target.value) })}
                />
              </label>
            </div>

            <label className="block text-sm text-ink-300">
              <span className="label">System prompt override</span>
              <textarea
                className="field min-h-20 resize-y"
                value={binding.system_prompt_override ?? ""}
                placeholder="Kosong berarti memakai prompt bawaan."
                onChange={(event) => patch({ system_prompt_override: event.target.value || null })}
              />
            </label>

            <button type="submit" className="btn btn-primary min-h-11" disabled={saving}>
              {saving ? "Menyimpan…" : `Simpan ${agent.id}`}
            </button>
            {message ? (
              <p className={failed ? "text-sm text-bad-500" : "text-sm text-ok-500"} role={failed ? "alert" : "status"}>
                {message}
              </p>
            ) : null}
          </form>
        </details>
      )}
    </article>
  );
}
