"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/states";
import { api, type ProviderView } from "@/lib/api";

const CAPABILITIES = ["chat", "json_schema", "tools", "vision"] as const;
const TRANSPORTS = ["openai_compat", "anthropic", "ollama", "cli", "mock"] as const;

type ProviderDraft = {
  id: string;
  label: string;
  transport: (typeof TRANSPORTS)[number];
  base_url: string;
  model: string;
  capabilities: string[];
  timeout_s: string;
  max_retries: string;
  max_tokens: string;
  temperature: string;
  allow_private_hosts: boolean;
  enabled: boolean;
  cli_command: string;
  credential_env: string;
  credential_secret: string;
};

const EMPTY_DRAFT: ProviderDraft = {
  id: "",
  label: "",
  transport: "openai_compat",
  base_url: "",
  model: "",
  capabilities: ["chat"],
  timeout_s: "90",
  max_retries: "2",
  max_tokens: "",
  temperature: "",
  allow_private_hosts: false,
  enabled: true,
  cli_command: "",
  credential_env: "",
  credential_secret: "",
};

function providerDraft(provider: ProviderView): ProviderDraft {
  return {
    id: provider.id,
    label: provider.label,
    transport: provider.transport as ProviderDraft["transport"],
    base_url: provider.base_url,
    model: provider.model,
    capabilities: provider.capabilities,
    timeout_s: String(provider.timeout_s),
    max_retries: String(provider.max_retries),
    max_tokens: provider.max_tokens === null ? "" : String(provider.max_tokens),
    temperature: provider.temperature === null ? "" : String(provider.temperature),
    allow_private_hosts: provider.allow_private_hosts,
    enabled: provider.enabled,
    cli_command: provider.cli_command,
    credential_env: provider.credential_source?.startsWith("env:")
      ? provider.credential_source.slice(4)
      : "",
    credential_secret: "",
  };
}

export default function ProvidersPage() {
  const [providers, setProviders] = useState<ProviderView[] | null>(null);
  const [visionAvailable, setVisionAvailable] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ProviderDraft>(EMPTY_DRAFT);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | "models" | null>(null);
  const [models, setModels] = useState<string[]>([]);

  const loadProviders = useCallback(async () => {
    try {
      const result = await api.providers();
      setProviders(result.providers);
      setVisionAvailable(result.vision_available);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "gagal memuat provider");
    }
  }, []);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  const editProvider = (provider: ProviderView) => {
    setSelectedId(provider.id);
    setDraft(providerDraft(provider));
    setModels([]);
    setActionMessage(null);
  };

  const addProvider = () => {
    setSelectedId(null);
    setDraft(EMPTY_DRAFT);
    setModels([]);
    setActionMessage(null);
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy("save");
    setActionMessage(null);
    try {
      const result = await api.saveProvider({
        id: draft.id,
        label: draft.label,
        transport: draft.transport,
        base_url: draft.base_url,
        model: draft.model,
        capabilities: draft.capabilities,
        timeout_s: Number(draft.timeout_s),
        max_retries: Number(draft.max_retries),
        max_tokens: draft.max_tokens ? Number(draft.max_tokens) : null,
        temperature: draft.temperature ? Number(draft.temperature) : null,
        allow_private_hosts: draft.allow_private_hosts,
        enabled: draft.enabled,
        cli_command: draft.cli_command,
        credential_env: draft.credential_env,
        credential_secret: draft.credential_secret,
      });
      setSelectedId(result.provider.id);
      setDraft(providerDraft(result.provider));
      setActionError(false);
      setActionMessage("Provider tersimpan.");
      await loadProviders();
    } catch (saveError) {
      setActionError(true);
      setActionMessage(saveError instanceof Error ? saveError.message : String(saveError));
    } finally {
      setBusy(null);
    }
  };

  const testConnection = async () => {
    setBusy("test");
    setActionMessage(null);
    try {
      const result = await api.testProvider(draft.id);
      setActionError(!result.ok);
      setActionMessage(`${result.detail} (${result.latency_ms} ms). ${result.note}`);
    } catch (testError) {
      setActionError(true);
      setActionMessage(testError instanceof Error ? testError.message : String(testError));
    } finally {
      setBusy(null);
    }
  };

  const fetchModels = async () => {
    setBusy("models");
    setActionMessage(null);
    try {
      const result = await api.providerModels(draft.id);
      setModels(result.models);
      setActionError(false);
      setActionMessage(`${result.models.length} model ditemukan.`);
    } catch (modelError) {
      setModels([]);
      setActionError(true);
      setActionMessage(modelError instanceof Error ? modelError.message : String(modelError));
    } finally {
      setBusy(null);
    }
  };

  if (!providers && error) {
    return <ErrorState message={error} onRetry={() => void loadProviders()} />;
  }

  if (!providers) {
    return <Loading label="Memuat konfigurasi provider…" />;
  }

  return (
    <div className="min-h-dvh p-3 sm:p-5 lg:p-6">
      <header className="mb-4 flex flex-col gap-3 border-b border-ink-700 pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-100">Provider</h1>
          <p className="mt-1 text-sm text-ink-300">
            Endpoint, model, kemampuan, dan referensi kredensial lokal.
          </p>
          <p className="mt-2 text-xs text-ink-400">
            Vision tersedia: {visionAvailable ? "ya" : "tidak"}
          </p>
        </div>
        <button type="button" className="btn min-h-11" onClick={addProvider}>
          Tambah provider
        </button>
      </header>

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void loadProviders()} />
        </div>
      ) : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <section className="panel min-w-0 p-3" aria-labelledby="provider-list-heading">
          <div className="flex items-baseline justify-between gap-3 px-1 pb-3">
            <h2 id="provider-list-heading" className="text-sm font-semibold text-ink-100">
              Provider tersimpan
            </h2>
            <span className="text-xs text-ink-400">{providers.length}</span>
          </div>
          {providers.length === 0 ? (
            <Empty title="Belum ada provider" hint="Gunakan Tambah provider untuk membuat konfigurasi." />
          ) : (
            <ul className="scroll-area space-y-2" aria-label="Daftar provider">
              {providers.map((provider) => (
                <li key={provider.id}>
                  <button
                    type="button"
                    className={[
                      "min-h-11 w-full rounded-md border px-3 py-2 text-left transition-colors",
                      selectedId === provider.id
                        ? "border-teal-500 bg-teal-600/20"
                        : "border-ink-700 bg-ink-800 hover:border-ink-600",
                    ].join(" ")}
                    aria-pressed={selectedId === provider.id}
                    onClick={() => editProvider(provider)}
                  >
                    <span className="block truncate text-sm font-medium text-ink-100">
                      {provider.label || provider.id}
                    </span>
                    <span className="mt-1 block truncate text-xs text-ink-400">
                      {provider.transport} · {provider.model || "model belum dipilih"}
                    </span>
                    {provider.allow_private_hosts ? (
                      <span className="mt-1 block text-xs font-semibold text-warn-500">
                        Akses host privat aktif
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <ProviderForm
          draft={draft}
          isEditing={selectedId !== null}
          credentialSource={
            selectedId ? providers.find((provider) => provider.id === selectedId)?.credential_source ?? null : null
          }
          models={models}
          busy={busy}
          actionMessage={actionMessage}
          actionError={actionError}
          onDraftChange={setDraft}
          onSave={save}
          onTest={() => void testConnection()}
          onFetchModels={() => void fetchModels()}
        />
      </div>
    </div>
  );
}

type ProviderFormProps = {
  draft: ProviderDraft;
  isEditing: boolean;
  credentialSource: string | null;
  models: string[];
  busy: "save" | "test" | "models" | null;
  actionMessage: string | null;
  actionError: boolean;
  onDraftChange: (draft: ProviderDraft) => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onTest: () => void;
  onFetchModels: () => void;
};

function ProviderForm({
  draft,
  isEditing,
  credentialSource,
  models,
  busy,
  actionMessage,
  actionError,
  onDraftChange,
  onSave,
  onTest,
  onFetchModels,
}: ProviderFormProps) {
  const setField = <K extends keyof ProviderDraft>(key: K, value: ProviderDraft[K]) => {
    onDraftChange({ ...draft, [key]: value });
  };
  const storedDpapiNeedsReplacement = isEditing && credentialSource?.startsWith("dpapi:");

  return (
    <form className="panel min-w-0 p-4 sm:p-5" onSubmit={onSave} aria-labelledby="provider-form-heading">
      <h2 id="provider-form-heading" className="text-lg font-semibold text-ink-100">
        {isEditing ? `Edit ${draft.label || draft.id}` : "Tambah provider"}
      </h2>

      {draft.allow_private_hosts ? (
        <div className="mt-4 border border-warn-500 bg-warn-500/10 p-4" role="alert">
          <p className="font-semibold text-warn-500">Akses host privat aktif</p>
          <p className="mt-1 text-sm text-ink-200">
            Provider ini dapat menghubungi alamat lokal dan jaringan privat. Aktifkan hanya untuk endpoint yang Anda kendalikan, seperti Ollama lokal.
          </p>
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="ID provider" id="provider-id">
          <input
            id="provider-id"
            className="field"
            value={draft.id}
            pattern="[a-z0-9][a-z0-9._-]*"
            maxLength={64}
            required
            readOnly={isEditing}
            onChange={(event) => setField("id", event.target.value)}
          />
        </Field>
        <Field label="Nama tampilan" id="provider-label">
          <input
            id="provider-label"
            className="field"
            value={draft.label}
            maxLength={120}
            onChange={(event) => setField("label", event.target.value)}
          />
        </Field>
        <Field label="Transport" id="provider-transport">
          <select
            id="provider-transport"
            className="field"
            value={draft.transport}
            onChange={(event) => setField("transport", event.target.value as ProviderDraft["transport"])}
          >
            {TRANSPORTS.map((transport) => (
              <option key={transport} value={transport}>{transport}</option>
            ))}
          </select>
        </Field>
        <Field label="Base URL" id="provider-base-url">
          <input
            id="provider-base-url"
            className="field"
            type="url"
            value={draft.base_url}
            maxLength={500}
            onChange={(event) => setField("base_url", event.target.value)}
          />
        </Field>
        <Field label="Model" id="provider-model">
          <input
            id="provider-model"
            className="field"
            value={draft.model}
            list="provider-models"
            maxLength={200}
            onChange={(event) => setField("model", event.target.value)}
          />
          <datalist id="provider-models">
            {models.map((model) => <option key={model} value={model} />)}
          </datalist>
        </Field>
        <Field label="Perintah CLI" id="provider-cli-command">
          <input
            id="provider-cli-command"
            className="field"
            value={draft.cli_command}
            maxLength={260}
            onChange={(event) => setField("cli_command", event.target.value)}
          />
        </Field>
        <Field label="Timeout (detik)" id="provider-timeout">
          <input
            id="provider-timeout"
            className="field"
            type="number"
            min="1"
            max="600"
            step="0.1"
            required
            value={draft.timeout_s}
            onChange={(event) => setField("timeout_s", event.target.value)}
          />
        </Field>
        <Field label="Maksimum retry" id="provider-retries">
          <input
            id="provider-retries"
            className="field"
            type="number"
            min="0"
            max="5"
            required
            value={draft.max_retries}
            onChange={(event) => setField("max_retries", event.target.value)}
          />
        </Field>
        <Field label="Maksimum token" id="provider-max-tokens">
          <input
            id="provider-max-tokens"
            className="field"
            type="number"
            min="1"
            max="200000"
            value={draft.max_tokens}
            onChange={(event) => setField("max_tokens", event.target.value)}
          />
        </Field>
        <Field label="Temperature" id="provider-temperature">
          <input
            id="provider-temperature"
            className="field"
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={draft.temperature}
            onChange={(event) => setField("temperature", event.target.value)}
          />
        </Field>
      </div>

      <fieldset className="mt-5">
        <legend className="label">Kemampuan</legend>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {CAPABILITIES.map((capability) => (
            <label key={capability} className="flex min-h-11 items-center gap-2 rounded-md border border-ink-700 px-3 text-sm text-ink-200">
              <input
                type="checkbox"
                checked={draft.capabilities.includes(capability)}
                onChange={(event) =>
                  setField(
                    "capabilities",
                    event.target.checked
                      ? [...draft.capabilities, capability]
                      : draft.capabilities.filter((item) => item !== capability),
                  )
                }
              />
              {capability}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="mt-5 grid gap-2 sm:grid-cols-2">
        <legend className="label">Kebijakan</legend>
        <label className="flex min-h-11 items-center gap-2 rounded-md border border-ink-700 px-3 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) => setField("enabled", event.target.checked)}
          />
          Provider aktif
        </label>
        <label className="flex min-h-11 items-center gap-2 rounded-md border border-warn-500/70 px-3 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={draft.allow_private_hosts}
            onChange={(event) => setField("allow_private_hosts", event.target.checked)}
          />
          Izinkan host privat
        </label>
      </fieldset>

      <section className="mt-5 border-t border-ink-700 pt-5" aria-labelledby="credential-heading">
        <h3 id="credential-heading" className="text-sm font-semibold text-ink-100">Referensi kredensial</h3>
        <p className="mt-1 text-sm text-ink-400">
          Nilai kredensial tidak pernah dibaca kembali oleh browser. Sumber tersimpan: {credentialSource || "tidak ada"}.
        </p>
        {storedDpapiNeedsReplacement ? (
          <p className="mt-2 text-sm text-warn-500">
            Edit provider dengan sumber DPAPI memerlukan secret baru; API tidak mengembalikan nilai lama untuk dipertahankan.
          </p>
        ) : null}
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Nama variabel environment" id="provider-credential-env">
            <input
              id="provider-credential-env"
              className="field"
              value={draft.credential_env}
              maxLength={120}
              autoComplete="off"
              disabled={Boolean(draft.credential_secret)}
              onChange={(event) => setField("credential_env", event.target.value)}
            />
          </Field>
          <Field label="Secret baru (write-only)" id="provider-credential-secret">
            <input
              id="provider-credential-secret"
              className="field"
              type="password"
              value={draft.credential_secret}
              maxLength={4000}
              autoComplete="new-password"
              disabled={Boolean(draft.credential_env)}
              required={Boolean(storedDpapiNeedsReplacement)}
              onChange={(event) => setField("credential_secret", event.target.value)}
            />
          </Field>
        </div>
      </section>

      <section className="mt-5 border-t border-ink-700 pt-5" aria-labelledby="diagnostic-heading">
        <h3 id="diagnostic-heading" className="text-sm font-semibold text-ink-100">Diagnostik</h3>
        <p className="mt-1 text-sm font-semibold text-warn-500">
          Uji koneksi hanya mengukur keterjangkauan endpoint. Hasilnya bukan bukti bahwa kredensial atau model dapat menyelesaikan permintaan.
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            className="btn min-h-11 justify-center"
            disabled={!isEditing || busy !== null}
            onClick={onTest}
          >
            {busy === "test" ? "Menguji…" : "Uji koneksi"}
          </button>
          <button
            type="button"
            className="btn min-h-11 justify-center"
            disabled={!isEditing || busy !== null}
            onClick={onFetchModels}
          >
            {busy === "models" ? "Mengambil…" : "Ambil daftar model"}
          </button>
        </div>
      </section>

      {actionMessage ? (
        <p
          className={`mt-4 break-words rounded-md border p-3 text-sm ${actionError ? "border-bad-500" : "border-ok-500"}`}
          role={actionError ? "alert" : "status"}
        >
          {actionMessage}
        </p>
      ) : null}

      <button type="submit" className="btn btn-primary mt-5 min-h-11 w-full justify-center" disabled={busy !== null}>
        {busy === "save" ? "Menyimpan…" : "Simpan provider"}
      </button>
    </form>
  );
}

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label" htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}
