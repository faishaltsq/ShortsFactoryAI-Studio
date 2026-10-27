# Completion Plan — ShortsFactoryAI Studio, 2026-10-27

Baseline observed this morning (not claimed, run): `check.ps1` 11 gates PASS — ruff, pytest,
dash-typecheck, dash-test, schemas (14 current), secrets (0 findings), video-typecheck,
video-adapter, video-beats, still-smoke (7/7), e2e (10 passed). mypy SKIPPED: undeclared and
uninstalled. `pwsh` does not exist on this host; the suite runs under Windows PowerShell 5.1
(`powershell -File scripts/check.ps1`).

Scope source: `docs/IMPLEMENTATION_ROADMAP.md` (its own "Not proven / Not started" sections),
`PRODUCT_REQUIREMENTS.md`, `docs/HANDOFF.md`. Every gap below was confirmed against code, not
against the roadmap text alone.

## Verified gaps (what is actually missing)

| # | Gap | Evidence |
| --- | --- | --- |
| G1 | ~~Python type gate never ran~~ **DONE 2026-10-28**: mypy in dev deps, `[tool.mypy]` strict over `packages/core`, 49 files clean; enforced by `tests/test_gate_scripts.py` | roadmap cross-cutting table |
| G2 | ~~Thumbnail stage orphaned~~ **DONE 2026-10-28**: wired in `JobService.publish` under one lease, `tests/test_publish_wiring.py` 2 passed | `apps/api/jobs.py` publish; roadmap flipped |
| G3 | ~~Usage dashboard page absent~~ **DONE 2026-10-28**: `apps/dashboard/src/app/usage/` page + tests; `price_configured=false` renders "belum dikonfigurasi" | `apps/dashboard/src/app/usage/page.tsx` |
| G4 | ~~Topic discovery missing~~ **DONE 2026-10-28**: `orchestration/discovery.py` stage + `POST /api/topics/discover` + `topic_discoveries` table + avoid list; `tests/test_discovery.py` 9 passed | `apps/api/main.py`, `packages/core/orchestration/discovery.py` |
| G5 | ~~Per-agent bindings unimplemented~~ **DONE 2026-10-28**: `studio.json` `bindings[]` loaded in `apps/api/state.py` (`_load_configured_bindings`), honored by `_primary_for`/`_fallback_for`; `tests/test_bindings.py` 7 passed | `apps/api/state.py`, `packages/core/orchestration/pipeline.py` |
| G6 | Thumbnail **upload** absent: transport has `insert` (video) only — **HELD, operator-gated (M7)** | `packages/core/publish/transport.py`, roadmap Phase 4 |
| G7 | Real YouTube transport/OAuth flow absent (no listener, no browser launch, no `videos.insert`) — **HELD, operator-gated (M7)**: plumbing proven against loopback stubs; touching a real Google account needs the operator to ask (AGENTS.md §7) | `publish/oauth.py` docstring; roadmap "blocked on operator credentials" |
| G8 | Vision `passed` branch stub-only — **HELD, operator-gated (M7)**: needs an operator-declared vision-capable provider; code path complete and stub-tested | roadmap 2.6 "Not proven"; `agents/vision.py` rule 1 |
| G9 | ~~Per-scene cache unimplemented~~ **DONE 2026-10-28**: `SceneCache` in `render.py`, probe-validated hits, real-ffmpeg proofs in `tests/test_render_cache.py` (5 passed) | roadmap 2.3 flipped |
| G10 | **CLOSED as scoped 2026-10-28**: declared `camera` consumed by all seven templates via `DeclaredCameraScope`, reach proven per template (`still-templates`, PSNR 14.5–19.3 dB); beats drive every template with a character rig (IllustratedStory, MotionComic). Rig-less text/prop templates rightly take no beats. | roadmap 2.2/2.3 |
| G11 | ~~Queue priority / production calendar~~ **DONE 2026-10-28**: `priority` column + `claim_next` ordering + `scheduled_for`/`/api/jobs/upcoming` + calendar page; proven in `tests/test_scheduler.py` | roadmap Phase 4 |

Non-gaps kept honest (documented deviations, no work planned): GPU-pressure half of ADR-008
(unobservable from the browser; banner says so), zone count ten vs "nine" in the original doc.

## Milestones (dependency-ordered)

### M0 — Make the Python type gate real (G1) — first, because every later milestone should be type-clean as it lands
1. `pyproject.toml`: add `mypy` to the `dev` group; add `[tool.mypy]` (`strict = true`,
   `python_version = "3.12"`, `packages = ["packages/core"]`, disallow untyped defs; pytest/tests
   excluded).
2. `uv sync`, then run `uv run mypy packages/core --strict`; fix real findings module by module
   (`media/qc.py` and `media/tts.py` hold most of the `Any` surface). Budget for real work: the
   roadmap already predicts `Any`-heavy boundaries.
3. `scripts/check.ps1` + `check.sh`: replace the SKIP line with a real `mypy` gate.
4. Update the roadmap's cross-cutting table and the module table (they get type-cleaned, the
   table records scope).

Tests: the gate itself is the check (`scripts/test_gate_scripts.py` pattern: planted defect
exits 1). Docs: roadmap table row flips from NOT RUNNABLE to PASS-criterion.

### M1 — Wire the thumbnail into approval → upload (G2)
1. In `JobService.publish`, run two stages under the same lease: `build_thumbnail_stage` then
   `build_publish_stage`. Rationale: `thumbnail.py`'s own docstring names this wiring point
   ("between READY_FOR_APPROVAL and PRIVATE_UPLOAD"), and publishing is what reads the digest.
2. Idempotence: thumbnail reuses `thumb.png` when its sha256 already matches `metadata.json`
   (mirror the runner's `artifact_reused` pattern, no re-render on retry).
3. Mock-mode jobs: thumbnail still renders (it is a local render, not a publication), but the
   publish stage keeps refusing mock jobs — no behavior change there.

Tests: `tests/test_publish_stage.py` — approved job runs publish → `thumb.png` exists,
`metadata.thumbnail` set; second run reports reuse and does not re-render (mtime or render-counter
assertion). E2E stays out (minutes-long fixture stays gated behind `STUDIO_VIDEO_PROOF`).

### M2 — Usage & cost page (G3)
1. `apps/dashboard/src/app/usage/page.tsx`: per-day, per-agent, per-model tables from
   `/api/usage/summary`; `price_configured=false` renders "belum dikonfigurasi", never a bare 0.
2. Sidebar entry; `fallback-routes.spec.ts` gets the route; vitest for the
   price-unconfigured rendering rule; the page follows the existing states.tsx
   empty/loading/error pattern.

### M3 — Topic discovery (G4)
1. `packages/core/orchestration/discovery.py`: `propose_topics(history, avoid, limit)` — pure:
   reads recent job titles + an avoid list, returns scored candidates (deterministic in mock
   mode, model-backed with the topic prompt when a live provider is bound).
2. A `DirectorAgent`-attributed discovery stage + `POST /api/topics/discover` returning
   candidates for operator selection ( proposals are metadata; **no job is auto-created** —
   a scheduler that spends money unattended stays off, per product premise).
3. Avoid list: persisted in the DB (`topic_discoveries` table, additive migration), seeded from
   the last N job titles.
4. Scheduler unchanged: it still only claims existing jobs. FR-1.1's "discover from production
   history" is satisfied by the stage + route; auto-scheduling stays an operator switch that
   already exists (`SHORTS_SCHEDULER_ENABLED`).

Tests: pure-function tests for avoid/scoring; API test: discover → candidates recorded, no job
rows created; live-path test with the stub server recording the provider call.

### M4 — Per-agent provider bindings (G5)
1. `studio.json` gains `bindings: [{agent, primary?, fallback?[]}]`, loaded in
   `AppState._load_configured_providers` (same skip-malformed rule), stored as
   `state.bindings: dict[str, dict]` so the pipeline's existing `getattr(state, "bindings")`
   branch becomes real instead of dead.
2. `_fallback_for` reads the same entry; unknown agent names are rejected at load (they would
   otherwise bind silently to nothing).
3. API: expose in `GET /api/providers`, accept in `PUT`; capability mismatch still fails at
   resolve time (existing net already raises `CapabilityMismatch` before any call).
4. Dashboard: binding selects on the providers page (primary + fallback dropdowns per agent).

Tests: binding honored (recording provider sees the bound id), fallback order tried in order,
malformed binding skipped with events noting it, unknown agent rejected. API round-trip test.

### M5 — Queue priority + production calendar (G11)
1. `jobs` table: additive `priority INTEGER DEFAULT 5` column (migration in `_migrate`;
   additive-only per DATA_CONTRACTS rule 0).
2. `claim_next` orders by `priority, created_at`; `POST /api/jobs` accepts priority.
3. Calendar: `scheduled_for` timestamp honored the way `SCHEDULED` already implies — the
   scheduler skips jobs whose `scheduled_for` is in the future; `/api/jobs?upcoming=1` + a
   dashboard section lists them.
4. No auto-publish: `scheduled_for` schedules *production*, never `PUBLISHED`; the
   `--confirm --by` explicit step stays the only path (STATE_MACHINE, FR-8.4).

Tests: priority ordering, future `scheduled_for` never claimed, approval-gate bypass test
already exists and must keep passing unchanged.

### M6 — Renderer depth (G10) — largest, scheduled last of the offline work
1. G9 per-scene cache: **done 2026-10-28** (`SceneCache`, `tests/test_render_cache.py`). Remaining: G10.
1. G10 camera/motion on the other templates: extend `src/camera.ts` +
   `src/motion-beats.ts` coverage to all seven templates (they are already wired per-scene; the
   gap is template renderers not reading the fields). Parity + beats suites extend to cover one
   scene per template.

Tests: `test_renderer_parity.py` gains per-template cases.

### M7 — Operator-gated: real upload path (G6, G7, G8) — not started without an explicit operator decision
- G6 thumbnail upload: one transport method (`insert_thumbnail`) + receipt, stub-tested first
  exactly like `insert` was. Can land offline against the stub only.
- G7 real YouTube: loopback OAuth listener, browser launch, `videos.insert` transport. This
  touches a real Google account and AGENTS.md §7 forbids it without the operator asking. The
  plumbing (`oauth.py`, `PinnedHTTP` form/stream/ResumeInfo) is already proven against loopback
  stubs; the remaining work is concretely scoped but **held**.
- G8 real vision pass: needs an operator-declared vision-capable provider (9router at
  `localhost:20128` is the PRD's default answer, Ollama the second). Config + one recorded
  intake run; the code path (`agents/vision.py`) is complete and tested against a stub.

## Commit boundaries
One commit per numbered step (small, by name, `git add <file>`; runtime state stays untracked).
Phase-gate discipline: three consecutive green `check.ps1` runs before any phase is declared
passed; a flake is quarantined with a written cause in `TEST_STRATEGY.md`.

## Risks
- M0 can uncover a large finding count in `qc.py` (1126 lines, `--strict`). Mitigation: module
  allowlist grows only by cleaning, never by `# type: ignore` sweeps; a per-module ignore needs a
  written reason in the roadmap.
- M1 touches the approval-adjacent path; the stale-approval tests
  (`test_a_stale_approval_blocks_after_a_re_render`) must pass unchanged.
- M4 changes provider resolution order; the "live job with no provider fails, never mocks"
  test is the guard and must not be weakened.
- M6 renders are minutes-long; parity suites must stay gated the way `still-smoke` is, or the
  gate budget triples.
