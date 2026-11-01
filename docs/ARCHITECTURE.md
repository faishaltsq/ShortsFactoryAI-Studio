# ARCHITECTURE — ShortsFactoryAI Studio

Status: accepted for Phase 1. Supersedes nothing; this repository starts empty.

## 1. Starting position (measured, not assumed)

Before designing, the existing tree at `C:\Users\cubeb\OneDrive\Documents\coding\projects\ShortsFactoryAI`
was measured. It is not a prototype:

| Fact | Measured value |
| --- | --- |
| Python | 22,538 LOC under `packages/core`, `apps/api`, `scripts` |
| TypeScript | 11,281 LOC under `apps/dashboard/src`, `packages/video/src` |
| Tests | 735 collected, 735 passing (one observed flake, see RISK_REGISTER R-02) |
| Video | real 1080×1920 / 30 FPS / H.264+AAC MP4, 1098 frames, −16.01 LUFS |
| Renderers | one (Remotion); 9 templates wired into `SCENE_RENDERERS` |
| Visual engine | 15 animated objects across 7 backdrops; no character rig (ADR 0013) |
| Orchestration | SQLite WAL, state allow-list, token-owned leases, bounded retries |
| Publishing | implemented, unit-tested, never exercised against a live account |

That tree is the *donor*. This repository is the *product*.

## 2. ADR-001 — New repository, donor as reference, port by module

**Decision.** Build in this repository with the architecture below. Port donor modules
one at a time, carrying their tests, only after the module passes the donor's own suite
*and* the new contract tests.

**Rejected: from-scratch rewrite of the video engine.** `packages/video` is 5,374 LOC of
React/Remotion reaching the OS through exactly one subprocess call. Rewriting gradients,
`clip-path`, transforms and inline SVG by hand in canvas/SVG means visual regression on
every template and buys nothing the brief asks for.

**Rejected: fork the donor and mutate it in place.** The donor carries four months of
accumulated decisions, 51 uncommitted files on its working branch, a provider layer whose
per-agent override *mutates shared provider instances* (see ADR-003), and dead declared
dependencies (`sqlalchemy`, `apscheduler`: zero imports). Mutating it in place means
inheriting every one of those without the ability to say no.

**Trade-off.** Slower first week; a period where two trees exist and can drift. Accepted
because the alternative is either a months-long rewrite or an architecture we cannot defend.

**Consequence.** Every ported module must be re-argued against this brief. "The donor does
it this way" is not a justification.

## 3. ADR-002 — Layering and dependency direction

```
apps/api            composition root: HTTP only, no domain logic
apps/dashboard      presentation only: no business rules, no direct provider access
        |
        v
packages/core/orchestration     state machine, jobs, leases, scheduler, budgets
        |            \
        v             v
packages/core/agents   packages/core/motion      (MotionSkillRegistry)
        |                      |
        v                      v
packages/core/providers   packages/core/media    (ffmpeg/ffprobe, TTS, render bridge)
        |                      |
        v                      v
packages/core/contracts   packages/video         (Remotion, Node — subprocess boundary)
```

Rules, enforced by an import-linter test rather than by convention:

- `contracts` imports nothing from this project. It is Pydantic models and JSON Schema only.
- `providers` may import `contracts`. Nothing imports `providers` except `agents` and `apps/api`.
- `agents` may import `contracts`, `providers`. Never `orchestration`, never `media`.
- `orchestration` may import `contracts`, `agents`, `media`, `motion`. Never `apps`.
- `apps/*` may import everything; nothing may import `apps/*`.
- No module under `packages/` may import `fastapi`, `starlette`, or `next`.

## 4. ADR-003 — Provider resolution is immutable and capability-checked

The donor's per-agent override works by mutating the selected provider:

```python
target.model = override.model          # donor: packages/core/providers/router.py:205
target.temperature = override.temperature
```

With two agents bound to the same provider object, the second call silently runs the first
agent's model. This is not a theoretical race: `ResearchAgent` and `ScriptAgent` both resolve
through the worker chain.

**Decision.** Providers are configuration, not mutable singletons. `resolve(agent)` returns a
frozen `ResolvedCall` carrying `(provider_id, transport, base_url, model, temperature,
credential_ref, capabilities)`. Adapters receive that value and are stateless with respect to
configuration. Any per-call field is passed as an argument, never assigned.

Resolution order per agent: `primary` → `fallback[]` → `MockProvider` (only when the job is in
explicit mock mode; a live job never silently degrades to mock).

**Capability validation happens before the call, not after the failure.** Each provider
declares `capabilities: set[Capability]` where `Capability = {chat, json_schema, tools, vision}`.
Each binding declares `requires: set[Capability]`. A binding whose requirement is not satisfied
by every candidate provider fails at validation time with `CapabilityMismatch`, naming the
agent, the provider and the missing capability. This is what stops a text-only model being
asked to inspect frames (brief §11) and stops a JSON-only call being sent to a model that
cannot do structured output.

## 5. ADR-004 — Credentials are references, never values

Two storage modes, both local:

1. **Environment reference (default).** A provider stores `credential: {env: "NAME"}`. The
   value is read at call time from the process environment or the operator's `.env`. It never
   enters SQLite, job artifacts, API responses, logs, or the browser.
2. **DPAPI-sealed local secret (Windows).** For operators who do not want keys in `.env`,
   `packages/core/security/secretstore.py` seals values with `CryptProtectData` (current-user
   scope) into `data/secrets/<id>.bin`, DACL-locked to the current user. Zero third-party
   dependencies: `ctypes` to `crypt32.dll`.

**Rejected: plaintext JSON store.** A file we write is a file that ends up in a backup, a
screenshot, or a commit.

**Rejected: hardcoded key in config.** Non-negotiable per brief §4.

**Consequence.** `/api/providers` returns `has_credential: bool` and `credential_source:
"env:NAME" | "dpapi" | null` — never a value, never a prefix, never a length.

**Origin binding.** A credential is bound to the exact `(scheme, host, port)` it was created
for. If `base_url` is edited to a different origin, the credential is withheld and the provider
reports `credential_origin_mismatch: true`. The donor learned this the hard way: a key in the
environment plus an editable `base_url` is an exfiltration primitive.

## 6. ADR-005 — SSRF policy is per transport, and explicit

Measured donor gap: `packages/core/studio.py` validates `base_url` for scheme, hostname
presence and absence of embedded credentials — and nothing else. The operator UI can therefore
point a provider at `http://169.254.169.254/` or `http://127.0.0.1:<admin-port>/` and the server
will POST to it with an `Authorization` header attached. The donor already owns a correct CIDR
denial list in `packages/core/research/retrieval.py` (`10/8`, `127/8`, `169.254/16`, `100.64/10`,
`::1`, ULA, …); it is simply not applied to provider endpoints.

**Decision.** One shared `netguard` module, used by both research retrieval and provider
transports:

- Default: only public unicast addresses. Deny loopback, link-local, private, CGNAT, multicast,
  unspecified, and the Azure/platform metadata address.
- Resolution is pinned: resolve the hostname once, validate every returned address, connect to
  the validated IP with `Host` preserved. This closes DNS-rebinding between validation and use.
- `allow_private_hosts: true` is a per-provider opt-in, required for `ollama` and for any local
  router, and it is surfaced in the UI as a warning state, not a hidden default.
- Redirects are not followed for provider calls. A 3xx is an error.
- **One narrow exception, opt-in per call.** A resumable upload endpoint answers `308 Resume
  Incomplete` to mean "keep sending from here", not "go elsewhere". `PinnedHTTP.request(...,
  allow_resume_308=True)` returns that 308 to the caller as a `ResumeInfo` (status, `Range`,
  `Location`) instead of raising. This does not weaken the rule: the flag is off by default, it
  applies to exactly one status code, and every other 3xx — including `302` and `307` — still raises
  even when the flag is set. A redirect is not a resume. Tests:
  `tests/test_http_base.py::test_a_308_raises_when_resume_is_not_allowed`,
  `::test_a_308_returns_resume_information_when_allowed`,
  `::test_a_302_still_raises_even_when_resume_is_allowed`,
  `::test_a_307_also_still_raises_when_resume_is_allowed`. The address policy is untouched: a
  blocked target is still blocked with the flag on
  (`::test_resume_308_does_not_apply_to_a_blocked_target`).
- **Form and streamed bodies go through the same path.** `data=` (a form POST, which an OAuth code
  exchange needs) and `body=UploadBody` (a chunked file upload) are encoded by this module and sent
  through the same resolve-then-pin, no-redirect, redacted-error client as `json=`. Two body
  encodings at once raises rather than guessing.

## 7. ADR-006 — SQLite through `sqlite3`, versioned migrations, no ORM

The donor declares `sqlalchemy==2.1.5` and `apscheduler==3.11.3` and imports neither. The real
persistence is 455 lines of raw `sqlite3` in `orchestration/jobstore.py` with three tables.

**Decision.** Keep raw `sqlite3`. WAL, `synchronous=NORMAL`, `busy_timeout=5000`, foreign keys
on. A `schema_migrations(version, applied_at)` table and forward-only migration functions.
No ORM: the queries are five statements and an ORM adds a dependency and a mapping layer that
would have to be debugged at 2 a.m. for no benefit.

## 8. ADR-007 — Two renderers behind one interface

```
Renderer (Protocol)
  capabilities() -> RendererCapabilities
  render(scene_spec | motion_plan, out_dir) -> RenderArtifact
```

1. **`RemotionRenderer` (primary).** Validated `SceneSpec` JSON → Remotion composition →
   MP4. Deterministic, frame-exact, already proven at 1080×1920.
2. **`BangMotionRenderer` (secondary).** Motion-skill HTML/CSS/GSAP → frame export → FFmpeg.
   Isolated: separate process, `--disable-web-security` **off**, no network at render time,
   filesystem restricted to the job's staging directory, wall-clock and frame-count caps.

**Bang Motion is not a Remotion component generator.** It emits a self-contained HTML document
with a `window.OPENER` contract; we drive it frame by frame. Treating it as a source of React
components would mean executing model-generated HTML inside the dashboard — explicitly forbidden
by brief §5.

**Verified facts about the dependency** (cloned at `c1aa65e`, v1.19.0, MIT, © 2026 Bang Tutorial):

- Contract exposed by every starter: `window.OPENER = { W, H, DURATION, tl, ready, seek(t),
  seekFrame(t), clipsReady(), play() }`.
- Frame export is `scripts/export-frames.mjs`: set timeline time, await two `requestAnimationFrame`
  ticks, `page.screenshot()`. Not screen recording, so no dropped frames.
- Starters are 1920×1080; the 9:16 recipe is documented in `references/explainer.md`
  (`#stage` 1080×1920, title 88–168 px, `.safe` wrapper at scale .78, phrases split per word).
- Starters load GSAP, Google Fonts and optionally three.js **from CDNs**. For a local-first,
  reproducible renderer this is unacceptable: a CDN hiccup changes the output, and an offline
  operator gets a blank stage. We vendor GSAP and the needed font files into the motion package
  and rewrite the `<script src>` on ingest.
- GSAP is free for commercial use as of 3.13 (Webflow relicensed it in 2025). The starters pin
  3.12.5 from a CDN; we vendor 3.12.5 or later and record the version in the skill manifest.

**Frame capture without a new dependency.** Remotion already ships
`node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe`
(verified: `Google Chrome for Testing 157.0.8080.0`). We drive it over CDP from a small Node
script instead of adding Puppeteer. One browser binary on the machine, already pinned by the
renderer we depend on.

## 9. ADR-008 — The 3D studio is a projection, never a source of truth

The donor's office is 2D pixel-art SVG (498 LOC across five components) — a deliberate earlier
decision recorded in its own spec. This brief requires a real 3D studio, so it is new work.

**Decision.** React Three Fiber scene, one character per agent, one workstation per stage. The
scene reads `StudioSnapshot` from the persisted event log and renders it. It cannot write state,
cannot start work, and cannot mark anything complete. Character states are derived:

```
event.status -> animation state
  working     -> working (typing / operating / reviewing per workstation)
  waiting     -> idle
  blocked     -> blocked (visible notification)
  failed      -> failed
  completed   -> completed (one-shot reaction, then idle)
```

If there is no event for an agent, the character idles. **No idle character may display a
working animation**, and no character may animate work when its persisted status is not
`working` — that is the "never fake productive activity" rule from brief §8, made mechanical.

**Performance.** Explicit quality tiers (`high | medium | low | off`), persisted per operator.
`off` renders the 2D fallback and the workflow stays fully usable. DPR capped at 1.5 on
`medium`, 1.0 on `low`; shadows off below `high`; frameloop set to `demand` when the tab is
hidden. A render job in progress must not be starved: the studio pauses itself when a
`RENDERING` event is active and the machine reports GPU memory pressure.

## 10. ADR-009 — The scene contract gains camera and motion

The donor's `SceneSpec` has no camera field; camera lives inside per-template `data`, so
"purposeful camera movement" (brief §5) is not expressible in the contract and cannot be
validated.

**Decision.** `SceneSpec` gains:

```python
camera: CameraSpec      # shot: wide|medium|close, move: static|push|pull|pan|tilt|orbit,
                        # target: str (element id), ease: str, amplitude: float
motion: MotionSpec      # beats: list[Beat], energy: float, continuity: str
```

Both are required, both validated. A scene with `move != "static"` must name a `target` that
exists in the scene's elements, or validation fails. This makes "unmotivated camera movement"
a validation error rather than a taste argument.

## 11. ADR-010 — Vision QA requires a declared vision capability

Brief §11 forbids claiming a text-only model inspected frames. Enforced structurally: the
`QualityAgent`'s visual pass requires `capabilities ⊇ {vision}`. If no bound provider declares
`vision`, the job's visual QA is recorded as `skipped_no_vision_provider` — an explicit,
visible, non-passing state. It is never recorded as passed.

## 12. Runtime shape

```
start-studio.bat
  |-- uvicorn apps.api.main:app        :8018   (API + SSE + worker thread)
  |-- next start apps/dashboard        :3018   (proxies /api/* -> 8018)
  `-- (on demand) node packages/video  (Remotion render, subprocess per job)
```

One worker thread in the API process for Phase 1–3. A separate worker process is a Phase 4
option, not a Phase 1 requirement; the lease design already supports it (two `JobStore`
instances, token-owned leases, verified in the donor's test suite).

## 13. Dependency graph (build order)

```
contracts ──┬──> providers ──> agents ──┐
            ├──> netguard ─────────────┤
            ├──> observability ─────────┤
            └──> orchestration <────────┘
                     |
        ┌────────────┼─────────────┐
        v            v             v
      media       motion       publishing
        |            |
        v            v
   packages/video  bang-motion (vendored, sandboxed)
        |
        v
     apps/api ──> apps/dashboard
```

Nothing in the right column may be started before the left column has passing tests. This is
the actual build order for Phase 1: contracts → netguard → providers → orchestration →
observability → api → dashboard.
