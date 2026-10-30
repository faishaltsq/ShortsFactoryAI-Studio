/** Typed client for the local API. Same-origin: the Next server proxies /api/* to FastAPI. */

export type StudioStatus =
  | "working"
  | "waiting"
  | "blocked"
  | "failed"
  | "completed";

export type AgentView = {
  agent_id: string;
  status: StudioStatus;
  stale: boolean;
  task: string;
  progress: number | null;
  model: string | null;
  stage: string | null;
  job_id: string | null;
  updated_at: string | null;
  recent: StudioEvent[];
};

export type StudioEvent = {
  event_id: number;
  job_id: string;
  agent_id: string;
  event_type: string;
  status: StudioStatus;
  description: string;
  progress: number | null;
  model: string | null;
  stage: string | null;
  created_at: string;
};

export type StudioSnapshot = {
  cursor: number;
  job_id: string | null;
  agents: AgentView[];
  generated_at: string;
};

export type JobView = {
  id: string;
  title: string;
  state: string;
  attempts: number;
  provider_mode: "live" | "mock";
  is_mock: boolean;
  created_at: string;
  updated_at: string;
  last_error: string | null;
  priority: number;
  scheduled_for: string | null;
  running: boolean;
};

export type JobDetail = JobView & {
  payload: Record<string, unknown>;
  artifacts: string[];
  events: Array<{
    id: number;
    job_id: string;
    from_state: string | null;
    to_state: string;
    detail: string | null;
    created_at: string;
  }>;
  usage: Array<{
    agent: string;
    provider: string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    est_cost_usd: number;
    elapsed_ms: number;
    created_at: string;
  }>;
  has_video: boolean;
};

export type ProviderView = {
  id: string;
  label: string;
  transport: string;
  base_url: string;
  model: string;
  capabilities: string[];
  timeout_s: number;
  max_retries: number;
  max_tokens: number | null;
  temperature: number | null;
  allow_private_hosts: boolean;
  enabled: boolean;
  credential_source: string | null;
  cli_command: string;
};

export type AgentBinding = {
  agent: string;
  primary: string | null;
  fallback: string[];
};

export type AgentModelBinding = {
  primary: string | null;
  fallback: string[];
  model: string | null;
  temperature: number | null;
  max_tokens: number | null;
  system_prompt_override: string | null;
};

export type AgentConfigView = {
  id: string;
  kind: "llm" | "deterministic";
  requires: string[];
  binding: AgentModelBinding;
  capability_gaps: string[];
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export type UsageSummaryRow = {
  /** Group key, meaning depends on the table: `day`, `day+agent` or `day+provider+model`. */
  day: string;
  agent?: string;
  provider?: string;
  model?: string;
  tokens: number;
  calls: number;
  cost_usd: number;
};

export type UsageSummary = {
  days: UsageSummaryRow[];
  by_agent: UsageSummaryRow[];
  by_model: UsageSummaryRow[];
  /** False when every row's cost is an unpriced 0.0 — "belum dikonfigurasi", not "free". */
  price_configured: boolean;
};

export type PublishReport = {
  job_id: string;
  ok: boolean;
  /** Per-stage outcomes in run order; the publish chain is thumbnail then upload. */
  stages: Array<{ name: string; ok: boolean; reused?: boolean; detail?: string }>;
  stopped: string | null;
  detail?: string;
  transport: string;
};

export type ReconcileReport = {
  job_id: string;
  phase: string;
  video_id: string | null;
  idempotency_key: string;
  attempt: number;
  receipt_steps: string[];
};

export type StudioBudget = {
  max_daily_tokens: number | null;
  max_daily_cost_usd: number | null;
  unlimited: boolean;
};

export type StudioRenderSettings = {
  min_free_ram_mib: number;
  min_free_vram_mib: number;
  allow_unmeasured_gpu: boolean;
};

export type StudioSettings = {
  budget: StudioBudget;
  render: StudioRenderSettings;
  storage: { data_dir: string; jobs_dir: string; secrets_dir: string };
};

export type StudioCatalog = {
  templates: string[];
  characters: Array<{
    id: string;
    version: string;
    displayName: string;
    artStyle: string;
    poses: string[];
    expressions: string[];
    gestures: string[];
    clothingVariants: string[];
    mouthShapes: string[];
    license: string;
    provenance: string;
  }>;
  motion: {
    poses: string[];
    expressions: string[];
    presets: string[];
    beat_kinds: string[];
    camera_moves: string[];
    transitions: string[];
  };
  renderers: Array<{ id: string; label: string; description: string }>;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () =>
    request<{ ok: boolean; version: string; jobs: number; vision_available: boolean }>("/api/health"),

  catalog: () => request<StudioCatalog>("/api/catalog"),
  settings: () => request<StudioSettings>("/api/settings"),
  saveSettings: (body: { budget?: StudioBudget; render?: StudioRenderSettings }) =>
    request<Pick<StudioSettings, "budget" | "render">>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  jobs: () => request<{ jobs: JobView[] }>("/api/jobs"),
  job: (id: string) => request<JobDetail>(`/api/jobs/${encodeURIComponent(id)}`),
  createJob: (body: Record<string, unknown>) =>
    request<JobView>("/api/jobs", { method: "POST", body: JSON.stringify(body) }),
  runJob: (id: string) => request<{ started: boolean }>(`/api/jobs/${id}/run`, { method: "POST" }),
  cancelJob: (id: string, reason = "") =>
    request<{ cancel_requested: boolean }>(`/api/jobs/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  deleteJob: (id: string) => request<{ deleted: string }>(`/api/jobs/${id}`, { method: "DELETE" }),
  approve: (id: string, operator: string) =>
    request<{ decision: string; checks: Record<string, boolean> }>(`/api/jobs/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ operator }),
    }),
  reject: (id: string, operator: string, reason: string) =>
    request<{ decision: string }>(`/api/jobs/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ operator, reason }),
    }),

  snapshot: (jobId?: string) =>
    request<StudioSnapshot>(`/api/studio/snapshot${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""}`),
  history: (jobId: string, limit = 100) =>
    request<{ events: StudioEvent[] }>(`/api/studio/history?job_id=${jobId}&limit=${limit}`),

  providers: () =>
    request<{ providers: ProviderView[]; vision_available: boolean; bindings: AgentBinding[] }>(
      "/api/providers",
    ),
  saveBindings: (bindings: AgentBinding[]) =>
    request<{ status: string; bindings: AgentBinding[] }>("/api/providers/bindings", {
      method: "PUT",
      body: JSON.stringify({ bindings }),
    }),
  saveProvider: (body: Record<string, unknown>) =>
    request<{ provider: ProviderView }>("/api/providers", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  testProvider: (id: string) =>
    request<{ id: string; ok: boolean; detail: string; latency_ms: number; note: string }>(
      "/api/providers/test",
      { method: "POST", body: JSON.stringify({ id }) },
    ),
  providerModels: (id: string) => request<{ models: string[] }>(`/api/providers/${id}/models`),
  agents: () => request<{ agents: AgentConfigView[] }>("/api/agents"),
  saveAgentBinding: (id: string, binding: AgentModelBinding) =>
    request<{ agent: string; binding: AgentModelBinding }>(
      `/api/agents/${encodeURIComponent(id)}/binding`,
      { method: "PUT", body: JSON.stringify(binding) },
    ),

  usageToday: () => request<{ tokens: number; cost_usd: number; calls: number }>("/api/usage/today"),
  usageSummary: () => request<UsageSummary>("/api/usage/summary"),
  usageJob: (id: string) =>
    request<JobDetail["usage"]>(`/api/usage/job/${id}`),

  metadata: (id: string) => request<Record<string, unknown>>(`/api/jobs/${id}/metadata`),
  artifact: (id: string, name: string) =>
    request<Record<string, unknown>>(`/api/jobs/${encodeURIComponent(id)}/artifact/${encodeURIComponent(name)}`),
  saveMetadata: (id: string, patch: { title?: string; description?: string; tags?: string[] }) =>
    request<Record<string, unknown>>(`/api/jobs/${id}/metadata`, {
      method: "POST",
      body: JSON.stringify(patch),
    }),
  publish: (id: string, transport = "stub") =>
    request<PublishReport>(`/api/jobs/${id}/publish`, {
      method: "POST",
      body: JSON.stringify({ transport }),
    }),
  reconcile: (id: string, transport = "stub") =>
    request<ReconcileReport>(`/api/jobs/${id}/publish/reconcile`, {
      method: "POST",
      body: JSON.stringify({ transport }),
    }),

  upcoming: () =>
    request<{ now: string; upcoming: JobView[]; awaiting_schedule: JobView[] }>(
      "/api/jobs/upcoming",
    ),

  discoverTopics: (body: { avoid?: string[]; limit?: number }) =>
    request<{
      discovery_id: string;
      status: string;
      provider_mode: string | null;
      candidates: Array<{ title: string; angle: string; why: string; score: number }>;
      avoid: string[];
    }>("/api/topics/discover", { method: "POST", body: JSON.stringify(body) }),
};

export function videoUrl(jobId: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/video`;
}

export function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 5) return "baru saja";
  if (seconds < 60) return `${seconds} detik lalu`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} menit lalu`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} jam lalu`;
  return `${Math.floor(seconds / 86400)} hari lalu`;
}
