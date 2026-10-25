# IMPLEMENTATION_ROADMAP — phases, tasks, exit gates

Rule: a phase is done when its exit gate passes with real evidence, not when its code exists.
Every task below names its verification. Nothing is marked done on the strength of generation.

---

## PHASE 1 — FOUNDATION

### 1.1 Repository and toolchain
- [ ] `pyproject.toml` (uv), `package.json` workspaces, `.gitignore`, `.editorconfig`, `ruff` config.
- [ ] `scripts/check.ps1` / `check.sh`: ruff + pytest + tsc + vitest + schema export diff.
- **Verify:** `uv run ruff check .` clean; `uv run pytest` green on an empty suite (exit 5 handled).

### 1.2 Contracts package
- [ ] `packages/core/contracts/`: Job, Research, Script, Review, SceneSpec (with `camera`/`motion`),
      MotionPlan, Assets, Audio, Render, QA, Approval, Metadata, Publication, Event.
- [ ] JSON Schema export to `config/schemas/*.json`, generated not hand-written.
- [ ] Validator rejects: non-static camera without target; duration out of range; missing licence.
- **Verify:** contract tests, 1 per rejection rule; schema export diff is empty in CI.

### 1.3 Netguard
- [ ] `packages/core/security/netguard.py`: CIDR deny list, resolve-then-pin, redirect refusal.
- **Verify:** tests for each denied range, DNS-rebinding simulation (host resolves to public then
  private — second resolution never happens because the IP is pinned), `allow_private_hosts` opt-in.

### 1.4 Providers
- [ ] `Provider` protocol, `ResolvedCall` frozen dataclass, `Capability` enum.
- [ ] Transports: `openai_compat`, `anthropic`, `ollama`, `cli`, `mock`.
- [ ] Immutable resolution: two agents on one provider get two independent calls (regression test
      for the donor's shared-mutation bug).
- [ ] Capability validation before call; `CapabilityMismatch` names agent/provider/capability.
- [ ] Credential store: env reference + DPAPI; origin binding; `has_credential` only in responses.
- [ ] Usage log with pre-call budget check.
- **Verify:** transport tests against a local stub HTTP server (no real keys); credential never
  appears in any response, log line, or artifact (sentinel-string test); capability matrix test.

### 1.5 Orchestration
- [ ] `JobState` enum + explicit allow-list transitions; illegal transition raises.
- [ ] `JobStore` on `sqlite3`: WAL, busy_timeout, migrations table, atomic artifact writes.
- [ ] Token-owned leases with heartbeat; expired lease → `waiting`, never `working`.
- [ ] Idempotent stage execution; completion marker written last.
- [ ] Bounded retries; exhaustion → `BLOCKED`.
- [ ] Cooperative cancellation at stage boundaries.
- [ ] Crash recovery on startup: jobs in `RUNNING` with a dead lease are resumable, not stuck.
- **Verify:** state-machine table test (every legal and illegal pair); kill-and-resume test that
  asserts zero duplicate provider calls; two-`JobStore` lease theft test.

### 1.6 Observability
- [ ] `studio_events` table, monotonic cursor, ordered replay, snapshot consistency.
- [ ] Redaction: sentinel secret never appears in an event row.
- [ ] SSE stream with `Last-Event-ID` resume.
- **Verify:** replay-after-reconnect test (no gaps, no duplicates); redaction test; snapshot p95
  measured under a simulated event flood.

### 1.7 API
- [ ] FastAPI app: jobs CRUD, run, cancel, approve, reject, artifacts, video (Range), providers,
      studio snapshot, studio stream, usage.
- [ ] Same-origin dashboard proxy; no token in the browser for local use.
- **Verify:** route tests; 409 on illegal approval; Range request returns 206 with correct
  `Content-Range`.

### 1.8 Dashboard shell
- [ ] Next.js app, dark default, sidebar, the eleven required routes (some as "coming in phase N"
      placeholders that are honest about their state).
- [ ] Provider Manager page: add/edit/remove, test connection, fetch models, capability editor,
      per-agent binding, fallback.
- [ ] Job list + detail with live progress and artifacts.
- **Verify:** Vitest for state logic; Playwright: create a job, watch it complete in mock mode,
  inspect the artifact, cancel a running job.

### 1.9 Phase 1 exit gate
```bash
uv run ruff check .
uv run pytest -q                       # all green
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run test
npm --prefix apps/dashboard run test:e2e
```
Plus: a scripted demo (`scripts/demo_phase1.py`) that creates a job with the mock transport, runs
it, cancels another mid-flight, kills the process, restarts, resumes, and prints the final state —
all without any real credential.

---

## PHASE 2 — PRODUCTION ENGINE

### 2.1 Agents
- [ ] Research (with source retrieval + claim verification), TopicSelection, Script, CreativeDirector,
      Storyboard, Asset, Animation, Audio, Editor, Quality, Metadata.
- **Verify:** each agent has a contract test with a recorded fixture response and a negative test
  (malformed JSON → bounded repair → `BLOCKED`).

### 2.2 Video package (port + extend)
- [ ] Port the seven working compositions; add `camera`/`motion` consumption to each.
- [ ] Art kit (`Stage`, `Figure`, `Prop`, `Camera`, `Effects`, `palette`, `rng`) with `fit="box"` in
      panels (frame coordinates in a small container delete the element silently).
- [ ] Character engine: rig, poses, expressions, motion presets, mouth sync.
- **Verify:** `still-smoke` renders every template at 1080×1920; each still inspected visually (a
  green `tsc` and a passing luma check cannot see a missing character).

### 2.3 Renderers
- [ ] `RemotionRenderer` with explicit `--port` and absolute `--props`.
- [ ] `BangMotionRenderer`: CDP frame capture via the bundled `chrome-headless-shell`, FFmpeg encode,
      sandboxed.
- [ ] Renderer parity: same storyboard, both renderers, both pass `validate_probe`.
- **Verify:** byte-stability test (render twice, compare frame hashes); per-scene rerender test.

### 2.4 Audio
- [ ] TTS adapter with word boundaries; subtitle generation; music/SFX mixing with ducking;
      loudness normalisation to −16 LUFS.
- **Verify:** ffprobe duration match; `silencedetect` finds no unexpected gap; subtitle cues inside
  the safe area and within duration.

### 2.5 QA
- [ ] Technical checks (all of FR-7.1).
- [ ] Creative checks with measured values (static ratio, fade ratio, text density, shot variety).
- [ ] Visual QA via a `vision`-capable provider; `skipped_no_vision_provider` when absent.
- [ ] Bounded repair with recorded decisions.
- **Verify:** negative fixtures — a black video, a silent video, a frozen video, a text wall, a
  slideshow — each must be caught by the specific check that should catch it.

### 2.6 Phase 2 exit gate
A complete 9:16 MP4 produced end to end, played in the browser, validated by ffprobe, with one
character-driven scene showing meaningful action and synced narration, and both renderers
producing a valid file from the same storyboard.

---

## PHASE 3 — 3D STUDIO

- [ ] R3F scene: nine zones, eleven agent characters, clay materials, isometric camera.
- [ ] Character state machine driven by events; lease expiry → idle.
- [ ] Inspector drawer; workstation navigation; camera focus transitions.
- [ ] Quality tiers + auto-downgrade + 2D fallback + pause during render.
- **Verify:** Playwright asserts `data-state` per character equals the persisted event status;
  reconnect restores identical state; snapshot p95 < 250 ms during a live render; 2D fallback
  keeps every route reachable.

---

## PHASE 4 — AUTONOMOUS PRODUCTION

- [ ] Topic discovery scheduler (operator-enabled, default off).
- [ ] Persistent queue, production calendar.
- [ ] Approval workflow UI with video playback and QA findings.
- [ ] Metadata editing, thumbnail upload.
- [ ] YouTube OAuth (installed-app flow), private upload, scheduling, reconciliation.
- [ ] Usage and cost dashboard.
- **Verify:** topic → approved private upload across a process restart with no duplicate render and
  no duplicate upload; an `uncertain` publication record blocks retry until reconciled; a scheduled
  task cannot bypass approval.

---

## Cross-cutting gates (every phase)

| Gate | Command | Pass |
| --- | --- | --- |
| Lint | `uv run ruff check .` | 0 findings |
| Types (py) | `uv run mypy packages/core --strict` on new modules | 0 errors |
| Types (ts) | `npm --prefix apps/dashboard run typecheck` | 0 errors |
| Unit | `uv run pytest -q` | all pass |
| UI unit | `npm --prefix apps/dashboard run test` | all pass |
| E2E | `npm --prefix apps/dashboard run test:e2e` | all pass |
| Schema | `uv run python scripts/export_schemas.py --check` | no diff |
| Secrets | `uv run python scripts/scan_secrets.py` | 0 findings |
| Render | `npm --prefix packages/video run still-smoke` | exit 0, count matches |
| Media | `uv run python scripts/verify_video.py <job>` | all checks pass |

## Risk-driven ordering note

The riskiest items are scheduled early on purpose: netguard and credential origin binding (1.3,
1.4) because they are security-shaped and cheap now, expensive later; the lease and resume design
(1.5) because retrofitting durability into a working pipeline is a rewrite; and renderer parity
(2.3) because discovering on day 40 that the secondary renderer cannot hit 1080×1920 invalidates
the motion-skill plan.
