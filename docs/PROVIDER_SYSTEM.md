# PROVIDER_SYSTEM — transports, capabilities, credentials, SSRF

## 1. Transports

| Transport | Use | Auth | Notes |
| --- | --- | --- | --- |
| `openai_compat` | OpenAI, DeepSeek, Groq, OpenRouter, llama.cpp, LM Studio, 9router, vLLM | `Authorization: Bearer` | `POST {base}/chat/completions`, `GET {base}/models` |
| `anthropic` | Claude native | `x-api-key` + `anthropic-version` | `POST {base}/v1/messages`; system is a top-level field |
| `ollama` | local daemon | none | `POST {base}/api/chat`; `GET {base}/api/tags`; requires `allow_private_hosts` |
| `cli` | Claude CLI, Codex CLI | CLI's own login | subprocess, argv array only, no shell |
| `mock` | offline tests and explicit mock jobs | none | deterministic, seeded by prompt hash |

All transports implement one Protocol:

```python
class Provider(Protocol):
    name: str
    capabilities: frozenset[Capability]
    def health(self) -> Health: ...
    def complete(self, call: ResolvedCall) -> ProviderResult: ...
    def list_models(self) -> list[str] | None: ...
```

`ResolvedCall` is frozen. A provider never mutates configuration — that was the donor's bug
(`router.py:205`: `target.model = override.model` on a shared instance, so the second agent
on the same provider silently ran the first agent's model).

## 2. Configuration schema

```jsonc
{
  "id": "worker-router",              // stable, referenced by bindings
  "label": "Local 9router",
  "transport": "openai_compat",
  "base_url": "http://localhost:20128/v1",
  "credential": { "env": "HERMES_CUSTOM_LOCALHOST_20128_API_KEY" },
  "model": "eg/deepseek-v4.1-flash",
  "capabilities": ["chat", "json_schema"],
  "timeout_s": 90,
  "max_retries": 2,
  "max_tokens": 4096,
  "temperature": 0.7,
  "allow_private_hosts": true,        // required for localhost
  "params": {},                        // transport-specific passthrough, allow-listed
  "enabled": true
}
```

Bindings:

```jsonc
{ "agent": "ScriptAgent", "primary": "worker-router",
  "fallback": ["worker-cloud"], "requires": ["chat", "json_schema"] }
```

## 3. Resolution algorithm

```
resolve(agent):
  binding = bindings[agent]
  candidates = [binding.primary] + binding.fallback
  for id in candidates:
     p = providers[id]
     if not p.enabled: continue
     if not binding.requires <= p.capabilities: record CapabilityMismatch, continue
     if not p.health().ok: record Unhealthy, continue
     return ResolvedCall(provider=p, model=binding.model or p.model, ...)
  if job.mode == "mock": return MockProvider
  raise NoProviderAvailable(agent, reasons)   # job -> BLOCKED, never a fake success
```

Capability mismatch is checked **before** any network call. A `vision` requirement with no
vision-capable provider is a configuration error surfaced in the UI, not a runtime surprise.

## 4. Capability matrix

| Transport | chat | json_schema | tools | vision | model listing |
| --- | --- | --- | --- | --- | --- |
| `openai_compat` | yes | yes (`response_format`) | yes | declared per provider | yes |
| `anthropic` | yes | yes (tool-forced) | yes | yes (image blocks) | partial |
| `ollama` | yes | yes (`format`) | yes | declared per model | yes (`/api/tags`) |
| `cli` | yes | emulated (parse + repair) | no | no | no |
| `mock` | yes | yes | no | no | yes |

Capabilities are **declared by the operator**, not inferred from the model name. Inference is
how a system ends up believing a text model can see. The UI shows a warning when a binding
requires a capability the selected provider does not declare.

## 5. Credentials

Three sources, checked in order:

1. `credential: {"dpapi": "<id>"}` — sealed with Windows DPAPI (`CryptProtectData`, current-user
   scope) in `data/secrets/<id>.bin`, DACL-locked to the user. No third-party dependency.
2. `credential: {"env": "NAME"}` — read from the process environment, falling back to the
   operator's `.env` (`$HERMES_ENV_FILE`, `%LOCALAPPDATA%\hermes\.env`, `~/.hermes/.env`).
3. None — anonymous call (Ollama, some local routers).

**Origin binding.** A credential is bound to `(scheme, host, port)`. If `base_url` is edited to
a different origin, the credential is withheld and the provider reports
`credential_origin_mismatch: true`. Without this, "editable base_url + server-side key" is an
exfiltration primitive — the donor shipped exactly that shape and had to patch it.

**Never returned:** `/api/providers` exposes `has_credential: bool`, `credential_source`, and
`credential_origin_mismatch`. No value, no prefix, no length, no hash.

**Redaction.** Error bodies from HTTP providers are useful (`[429] usage limit reached, reset
after 18m`) so they are surfaced — after replacing any known credential with `[redacted]` and
collapsing to one line ≤ 240 chars. CLI stdout/stderr is never surfaced: it can echo a token.

## 6. SSRF policy

`packages/core/security/netguard.py`, shared with research retrieval:

- Deny: `0.0.0.0/8`, `10/8`, `100.64/10`, `127/8`, `169.254/16`, `172.16/12`, `192.0.0/24`,
  `192.0.2/24`, `192.88.99/24`, `192.168/16`, `198.18/15`, `198.51.100/24`, `203.0.113/24`,
  `224/4`, `240/4`, `168.63.129.16/32`; IPv6 outside `2000::/3`, plus `2001::/23`, `2002::/16`,
  `3fff::/20`, `::1`, ULA `fc00::/7`, link-local `fe80::/10`.
- Resolve once, validate **every** returned address, connect to the validated IP with `Host`
  preserved. Closes DNS rebinding.
- No redirect following for provider calls; a 3xx is an error.
- `allow_private_hosts: true` is a per-provider opt-in, required for Ollama/local routers, and
  rendered in the UI as an explicit warning state.

Measured donor gap this closes: `packages/core/studio.py` validated scheme, hostname presence
and absence of embedded credentials only. The CIDR list already existed in
`research/retrieval.py`; it was simply never applied to provider endpoints.

## 7. CLI adapters

`argv` array, never a shell string. Fixed executable path from config, validated to exist.
No `shell=True`. Timeout kills the process tree. Working directory pinned to the job dir.
Output parsed from a documented JSON event stream; on parse failure the call fails, it does
not fall back to scraping stdout.

## 8. Usage and cost

`usage_log(id, job_id, agent, provider, model, prompt_tokens, completion_tokens,
est_cost_usd, elapsed_ms, created_at)`. Cost uses a per-provider price table, defaulting to the
tier's rough price; it is an **estimate**, labelled as such in the UI. Budget enforcement is
pre-call: if today's spend plus the worst-case cost of this call exceeds the cap, the call is
refused with `budget_exceeded`.
