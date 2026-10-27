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
- [x] Crash recovery on startup. `create_app(None)` runs `_recover_interrupted`: every job in a
      running stage whose lease has expired **and** that this process does not already hold is
      re-Started through `JobService.start`, so the runner reuses completed stages from artifacts
      and repeats none of the paid work. Proven by `scripts/demo_phase1.py` step 5, which expires a
      lease directly, resumes through the real hook, and asserts the job was picked up. Two gates
      keep it safe: a live lease is never stolen (the worker may be mid-render), and a job this
      process is already running is never double-Started.
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
      **Recorded blocker, not a skipped test.** Three route files exist out of the eleven the sidebar
      advertises — `/` (`Studio`), `/jobs` (`Produksi`), `/providers` (`Provider`) — and the other
      eight have no `page.tsx`: `/create`, `/storyboard`, `/assets`, `/agents`, `/skills`,
      `/calendar`, `/settings`, plus no page for any route a zone might gain later. Two of the three
      are zone targets (`/`, `/jobs`); `/providers` is reached from the sidebar only, because no
      production zone owns model configuration. Seven distinct `href`s are declared across the ten
      zones, and five of them point at no page: `/agents`, `/assets`, `/calendar`, `/create`,
      `/storyboard`. Zones now render a disabled span (`data-zone-link-disabled`) for those instead
      of a dead anchor.
      `apps/dashboard/e2e/fallback-routes.spec.ts` navigates the zone-linked routes that render and
      asserts that exact five-name placeholder set, so creating a page — or adding a zone `href`
      without a page — fails the suite instead of passing silently.
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

**Implemented and run.** The demo asserts, rather than narrates: five artifacts exist after the run,
the job made exactly five provider calls (one per stage), a cancelled job ends at `CANCELLED` and not
`FAILED`, the artifact set is byte-identical across the simulated restart, and the resume makes
**zero** additional provider calls because every stage is reused from its validated artifact. It
exits non-zero on any violation and removes its temporary data directory unless `--keep` is passed.

---

## PHASE 2 — PRODUCTION ENGINE

### 2.1 Agents
- [ ] Research (with source retrieval + claim verification), TopicSelection, Script, CreativeDirector,
      Storyboard, Asset, Animation, Audio, Editor, Quality, Metadata.
- **Verify:** each agent has a contract test with a recorded fixture response and a negative test
  (malformed JSON → bounded repair → `BLOCKED`).

### 2.2 Video package (port + extend)
- [x] Port the seven working compositions. `still-smoke` renders 7/7 at 1080×1920 and asserts the
      count and distinct template ids before printing "7/7 real Remotion stills verified".
- [x] Consume `camera` in every template. `Short.tsx` wraps every template in
      `DeclaredCameraScope`, which applies `declaredCameraAt` — the same transform
      `IllustratedStory` applies inline — so a declared push/pan/tilt/pull/orbit moves the frame in
      all seven. Standalone per-template compositions in `Root.tsx` get the same wrapper and re-base
      the scene to `startFrame: 0`, mirroring what a cut does inside a `Sequence`.
- [x] **Reach proven per template, not assumed:** `still-templates`
      (`scripts/verify-template-stills.mjs`, wired into `check.ps1`/`check.sh` and skipped with
      `-Quick`) renders each template twice through real Remotion — a `static` baseline and a
      `push` at frame 30 — and asserts baseline 1080×1920 non-blank plus PSNR < 20 dB baseline vs
      push. First run exposed the silent gap: five templates rendered push and baseline
      byte-identical because the props scene kept its global `startFrame`, so the standalone scope
      clamped the camera to identity. The re-base in `Root.tsx`/the script fixed it; measured reach
      is 14.5–19.3 dB across all seven.
      Verified by `still-smoke` 7/7 at 1080×1920 after the wiring.
      `motion` (beats) remains `IllustratedStory`-only: beats drive the character rig, and only
      that template has a rig. Text/prop templates have no subject for a beat to act on, and
      inventing one would be decoration, not direction.
      `CharacterReel` reads a `camera` field of its own, not the product one.
- [ ] Art kit (`Stage`, `Figure`, `Prop`, `Camera`, `Effects`, `palette`, `rng`) with `fit="box"` in
      panels (frame coordinates in a small container delete the element silently).
- [ ] Character engine: rig, poses, expressions, motion presets, mouth sync.
- **Verify:** `still-smoke` renders every template at 1080×1920; each still inspected visually (a
  green `tsc` and a passing luma check cannot see a missing character).

### 2.3 Renderers
- [x] `RemotionRenderer` with explicit `--port` and absolute `--props` (Remotion 4.0.537).
- [x] `BangMotionRenderer`: CDP frame capture via the bundled `chrome-headless-shell`, FFmpeg encode,
      sandboxed. Design law and the seek→2×rAF→screenshot technique reused from Bang Motion 1.19.0
      (`c1aa65e`, MIT) as knowledge only — no upstream executable lines.
- [x] Renderer parity: same storyboard, both renderers, both pass `validate_probe`
      (`tests/test_renderer_parity.py::test_both_renderers_pass_the_same_gate_from_the_same_props`).
- [ ] Per-scene rerender. `render.json.scene_hashes` is written and `TECHNICAL_QC` compares its
      keyset to the storyboard scene ids, but **nothing reuses a cached scene**: there is no consumer
      that skips rendering, and `_scene_hashes` says so in its own docstring ("there is no per-scene
      cache yet, and none is claimed"). FR-5.4 is therefore unmet.
- **Verify:** byte-stability test (render twice, compare frame hashes) — done within each renderer
  (`test_each_renderer_is_deterministic_within_itself`, 60/60 identical framemd5 twice); cross-renderer
  identity is not expected and is not claimed. Per-scene rerender test — **not written**, because the
  cache it would test does not exist.

### 2.4 Audio
- [x] Local Windows SAPI TTS adapter with word boundaries; deterministic subtitle grouping;
      narration-only −16 LUFS normalisation; optional licensed-music ducking argv; AAC mux.
- **Verify:** ffprobe duration match; `silencedetect` finds no unexpected gap; subtitle cues inside
  the safe area and within duration. The real-media proof records any remaining detector gate.
- [ ] Music/SFX asset acquisition remains out of scope until real licensed paths exist; no asset is
      fabricated to satisfy the mixer.

### 2.5 QA
- [x] Technical checks (all of FR-7.1), written to `technical-qc.json` even when the gate blocks.
      Expected values come from `render-props.json` and `audio.json`, never from `render.json`.
- [x] Creative checks with measured values: static ratio, fade ratio, text density, shot variety,
      repeated world, pacing, segment mapping, character consistency, cross-job repetition.
- [x] Visual QA via a `vision`-capable provider; `skipped_no_vision_provider` when absent.
      Contact sheet is one bounded JPEG with no padding cell; the answer must account for every
      frame sent. **Proven end to end with a real model**, not only stubs: a local router provider
      (`nine-router` → `gpt-5.6-luna`, vision-capable) configured in `config/studio.json` with a
      credential *reference* (`{"env": "NINEROUTER_KEY"}`) produced `visual.status=passed` with
      5/5 frames inspected on a live render. The first live run came back `BLOCKED` with a real
      finding — scene text quoting a seed that matched nothing in the narration — which traced to
      the mock provider deriving a fresh prompt-hash seed per call instead of reusing the script's
      (`packages/core/providers/mock.py::MockProvider._seed_for`). Fixed in the provider, then the
      run passed honestly. Two guards around that config path exist because of what it enables:
      `AppState` loads provider declarations only from the file the settings name, and
      `tests/conftest.py::_isolate_operator_config` points that setting at a per-test temp path so
      an operator's real provider cannot leak into a suite — the 'live mode with no provider must
      fail' test is the one that caught the leak.
- [x] Recorded decisions in `qc.json.repairs`, with `artifacts_invalidated: []` and
      `action: "blocked"`. Automatic repair is zero: every detectable failure is deterministic, so
      re-rendering cannot converge. Bounded *automatic* repair stays open by design.
- [x] Readiness gate owned by `DirectorAgent` at `READY_FOR_APPROVAL`, recomputing the input hash.
- **Verify:** negative fixtures — a black video, a silent video, a frozen video, a text wall, a
  slideshow, one theme, a fade wall, one shot, a text-heavy scene — each caught by the specific
  check named in TEST_STRATEGY §5. Proven against real ffmpeg output, not hand-built dicts.
- **Remaining:** the vision provider used is a local router; no cloud provider (OpenAI /
  Anthropic) has been exercised. `MotionSpec` beats reach frames only in `IllustratedStory`;
  other templates render declared `camera` via `DeclaredCameraScope` but have no character rig to
  perform beats on.

### 2.6 Phase 2 exit gate
A complete 9:16 MP4 produced end to end, played in the browser, validated by ffprobe, with one
character-driven scene showing meaningful action and synced narration, and both renderers
producing a valid file from the same storyboard.

**Proven.** A real 1080×1920 H.264/AAC MP4 walks the six-stage chain to `READY_FOR_APPROVAL`
(`verify_video.py` exit 0, 13/13 checks), with narration and subtitle cues derived from measured
SAPI speech and the whole file played in Chromium by the gated Playwright spec
(`apps/dashboard/e2e/video-proof.spec.ts`, which asserts `readyState ≥ 1`, `videoWidth/Height`, and
that `currentTime` advances). Both renderers pass the same `validate_probe` from the same props, and
each is deterministic within itself (60/60 identical framemd5 twice).

**Not proven, and not claimed.**

- The visual `passed` branch has only stub coverage. No vision-capable endpoint is configured, so
  every real job records `skipped_no_vision_provider` and no model has inspected a real sheet.
- "Meaningful action within a scene" rests on stills a human inspects, not on a measured pose delta.
  `test_matched_stills_at_a_character_beat` produces the before/after frames and asserts only that
  they exist and are non-trivial; it does not compute a delta. Treat the claim as a visual review,
  not a gate.
- The Python type gate was long unrunnable (mypy undeclared); it now runs in the cross-cutting
  gates and passes strict over `packages/core` (see the gate table). Any new module must keep it
  green — that is part of "done" from here on.
- Per-scene cache is unimplemented; every render is a full re-render.
- Only `IllustratedStory` consumes the declared motion fields. The other six templates honour the
  authored `camera` (declared push/pan/tilt/pull reach the frame, proven per template by
  `still-templates` at 14.5–19.3 dB) but have no character rig to perform beats on.

Bang Motion **does** now burn subtitles (`_caption_markup` emits one `data-cue-start`/`data-cue-end`
element per cue, shown for the half-open window `[startMs, endMs)`), and it **does** animate the
mouth from `scene.speech` via `data-speech` and a 40 ms/70 ms half-window-clamped envelope. Both are
proven at the pixel level, not by DOM assertions: `test_captions_reach_pixels_inside_their_window`
and `test_the_mouth_reaches_pixels_inside_a_speech_window`. The earlier version of this section
claimed Bang Motion had neither; that was true when written and is no longer.

---

## PHASE 3 — 3D STUDIO

- [x] R3F scene: **ten** zones, **fourteen** agent characters (`AGENT_IDS`), clay materials,
      orthographic isometric camera. The "nine zones, eleven characters" in the original line was
      never true of the code: `zones.ts` declares ten zones and the projection emits one character
      per `AGENT_IDS` entry. Camera is `atan(1/√2)` elevation, 45° azimuth, frustum half-height
      12.5, dolly 0.7×–1.6×.
- [x] Character state machine driven by events; lease expiry → not-working. `resolveCharacterState`
      is pure in `(status, updated_at, nowMs)`: `completed` holds 2 s then rests as `idle`,
      `blocked`/`failed` never decay, `working` never decays client-side. Staleness is the server's:
      `live_agents` derives from persisted lease rows (`unexpired_jobs`), a renewed heartbeat keeps a
      long render alive, and `owns()` honours `expires_at`. A worker that stops heartbeating reads
      `waiting`, not `working`.
- [x] Inspector drawer; workstation navigation; camera focus transitions. Native `<dialog>` with
      focus return to the opener; ten zone anchors (real `<a>` where the route exists, honest
      disabled span where it does not); 400 ms eased camera tween exposed as `data-camera-target`.
- [x] Quality tiers + auto-downgrade + 2D fallback + pause during render. Tiers `high|medium|low|off`
      persist per browser; a `TierSampler` drops one tier on a 3 s median over 33 ms without
      writing the operator's preference and reports the result as `data-effective-quality`; an
      active `RENDERING` event pauses the scene and shows a banner. **GPU-memory pressure from
      ADR-008 is not implemented** — the browser cannot read it, and the banner says so rather than
      pretending.
- **Verify:** Playwright asserts `data-state` per character equals the persisted event status — on
      both the 2D list and the 3D mirror (`data-scene-mirror`, a clipped test seam, because a canvas
      exposes no DOM). Reconnect restores state and does not duplicate events. Snapshot p95 measured
      by `tests/test_studio_perf.py`: 32.9 ms pre-fix, 1.62 ms post-fix at 1200 events — the 250 ms
      budget was already met, so the N+1 removal is a regression guard, not the reason it passes.
      2D fallback reachability is proven only for the routes that exist; the rest are recorded
      placeholders, and `fallback-routes.spec.ts` fails if a route is added without a page.

**Two deviations from the docs, both deliberate and recorded:** the zone count is ten, not nine,
and GPU-pressure detection is absent. `docs/STUDIO_3D.md` carries the same numbers.

---

## PHASE 4 — AUTONOMOUS PRODUCTION

- [ ] Topic discovery scheduler (operator-enabled, default off). **The loop exists; topic
      discovery does not.** `packages/core/orchestration/scheduler.py` provides `claim_next`
      (selection only) and `SchedulerLoop` (one tick at a time, no cron, no dependency). Config:
      `SHORTS_SCHEDULER_ENABLED` (default unset = off) and `SHORTS_SCHEDULER_INTERVAL_S` (default
      `60`, minimum `1`; an invalid value raises rather than silently meaning "off"). It is
      **off by default, no cron, one tick at a time**, and `create_app` does not start it —
      `AppState.build_scheduler` creates it and `start()` is an operator action. The loop re-reads
      the job's state after the claim and refuses if it is no longer schedulable, because the state
      can change between `claim_next` and the hand-off.
      `tests/test_scheduler.py::test_an_approval_waiting_job_is_never_claimed` and
      `::test_the_loop_rechecks_the_state_before_handing_off` cover the gate refusal;
      `::test_the_loop_is_off_by_default` covers the switch. **Topic discovery is now
      implemented as an operator-invoked endpoint, not a scheduler step:**
      `POST /api/topics/discover` runs a `DirectorAgent`-attributed stage
      (`packages/core/orchestration/discovery.py`) that scores recent job titles into
      candidates (deterministic mock path; the provider path when a live provider resolves),
      records the run in the additive `topic_discoveries` table (migration 2) with an avoid
      list seeded from recent titles and prior proposals, and persists events under the
      discovery id. **No job is auto-created** — proposals are metadata; the scheduler still
      only claims existing jobs (`tests/test_discovery.py` proves discover leaves job rows
      untouched).
- [ ] Persistent queue, production calendar. **Not started.** `jobs` is a persistent store with no
      queue semantics: no claim-next, no priority, no worker loop.
- [x] Metadata stage: `MetadataAgent` is in `build_stages` and writes `metadata.json`.
      `GET`/`POST /api/jobs/{job_id}/metadata` edit it. Proven by
      `tests/test_publish_stage.py::test_the_metadata_stage_writes_metadata_json` and
      `tests/test_api_publish.py::test_metadata_edit_at_the_gate_writes_the_artifact`.
- [x] Thumbnail **render**: `COMPOSITION_ID` is parameterised, `build_thumbnail_stage` renders
      `thumb.png` through the `Thumbnail` composition and records its sha256 in
      `MetadataArtifact.thumbnail`.
- [x] Thumbnail **wired between approval and upload**: `JobService.publish` runs
      `build_thumbnail_stage` then the publish stage under one lease; a second publish run
      reports reuse instead of re-rendering. Proven by
      `tests/test_publish_stage.py` and `tests/test_publish_wiring.py`.
- [ ] Thumbnail **upload**: absent. Needs a transport operation and a real endpoint. (M7, held
      pending operator decision.)
- [x] Publish / reconcile, **proven offline against the stub transport**:
      `PublicationArtifact` gained `idempotency_key` + `attempt`; `packages/core/publish/` derives
      the key from `render.json.sha256`, refuses to re-insert a confirmed record, records
      `uncertain` on a timeout-after-send (non-retryable), and reconciles by *reading*
      (`reconcile_uncertain`, zero inserts in every branch). Routes:
      `POST /api/jobs/{id}/publish` and `POST /api/jobs/{id}/publish/reconcile`.
      `tests/test_publish_stage.py::test_a_process_restart_after_uncertain_uploads_exactly_once`
      proves exactly one insert across a first run ending uncertain, a fresh service object over
      the same database, and a post-reconcile re-run.
- [ ] **YouTube OAuth (installed-app flow) and real upload: plumbing exists, stub-tested, blocked
      on operator credentials.** The transport capabilities a real flow needs now exist and are
      proven against a loopback stub: form bodies (`data=`, `application/x-www-form-urlencoded`),
      streamed upload bodies (`UploadBody`, chunked, declared length checked against the file), and
      an opt-in `allow_resume_308` that returns `ResumeInfo` instead of raising — while every other
      3xx still raises (`docs/ARCHITECTURE.md` §ADR-005). `packages/core/publish/oauth.py` provides
      `build_authorize_url`, `pkce_challenge`, `exchange_code`, `refresh`, `seal_tokens` and
      `load_tokens`; the token bundle is DPAPI-sealed and never appears in a `repr`, a returned
      dict, or an error detail. **There is still no listener, no browser launch, no real endpoint,
      and no YouTube client.** No `videos.insert` has ever run. This cannot be proven offline and
      must not be attempted without the operator's Google account.
      Tests: `tests/test_http_base.py` (16), `tests/test_oauth.py` (14).
- [x] Usage and cost **accounting**: `GET /api/usage/summary` aggregates per day, per agent and per
      model, and `PUT /api/providers` now accepts `price_in_per_mtok`/`price_out_per_mtok` so
      `est_cost_usd` can be a real number. `price_configured` distinguishes an unpriced zero from a
      free run.
- [ ] Usage and cost **dashboard**: no page. The API shape exists; the UI does not.
- **Verify:** topic → approved private upload across a process restart with no duplicate render and
  no duplicate upload; an `uncertain` publication record blocks retry until reconciled; a scheduled
  task cannot bypass approval.

  **Status of each half of that sentence:**

  | Half | Status | Evidence |
  | --- | --- | --- |
  | no duplicate **render** across a restart | **proven offline** | `tests/test_runner.py::test_resume_after_a_crash_does_not_repeat_paid_work` (provider counter == 1) and `tests/test_runner_reuse.py` |
  | no duplicate **upload** across a restart | **proven offline** | `tests/test_publish_stage.py::test_a_process_restart_after_uncertain_uploads_exactly_once` — exactly one insert across a first run ending `uncertain`, a fresh service over the same database, and a post-reconcile re-run |
  | an `uncertain` record blocks retry until reconciled | **proven offline** | `::test_an_uncertain_publication_blocks_and_does_not_insert`, `::test_reconcile_confirms_without_a_second_insert` (zero inserts in every reconcile branch) |
  | a scheduled task cannot bypass approval | **proven structurally and by test** | `READY_FOR_APPROVAL` is the only inbound edge to `APPROVED`; `JobStore.transition` additionally requires `approval.json` with a matching `render_sha256` (`STATE_MACHINE.md` invariant 6); `tests/test_scheduler.py::test_an_approval_waiting_job_is_never_claimed` and `::test_the_loop_rechecks_the_state_before_handing_off` |
  | topic → **real private upload** | **NOT proven, NOT claimed** | There is no YouTube client, no OAuth flow, and no network client. `PinnedHTTP` has no form-body or streaming support and rejects 3xx. **Blocked on operator credentials.** |

  The offline half of Phase 4 is complete. The upload half is blocked, not deferred by choice.

---

## Cross-cutting gates (every phase)

| Gate | Command | Pass |
| --- | --- | --- |
| Lint | `uv run ruff check .` | 0 findings |
| Types (py) | `uv run mypy packages/core --strict` | exit 0, 48 files strict-clean |
| Types (ts) | `npm --prefix apps/dashboard run typecheck` | 0 errors |
| Unit | `uv run pytest -q` | all pass |
| UI unit | `npm --prefix apps/dashboard run test` | all pass |
| E2E | `npm --prefix apps/dashboard run test:e2e` | all pass |
| Schema | `uv run python scripts/export_schemas.py --check` | exit 0, 14 schemas current |
| Secrets | `uv run python scripts/scan_secrets.py` | exit 0, 0 findings |
| Render | `npm --prefix packages/video run still-smoke` | exit 0, count matches |
| Media | `uv run python scripts/verify_video.py <job>` | all checks pass |

**The Types (py) gate runs.** mypy 1.18.2 is in the `dev` dependency group, `[tool.mypy]` sets
`strict = true` / `python_version = "3.12"` / `packages = ["packages.core"]`, and
`scripts/check.ps1` + `check.sh` invoke it like every other gate. `uv run mypy packages/core
--strict` exits 0 over all 48 core source files (2026-10-27, after a 93-finding burn-down across
`media/`, `motion/`, `agents/`, `orchestration/`, `providers/`, `publish/`, `security/`). Rules
for keeping it green: no blanket `# type: ignore`, no per-module `ignore_errors`; a single
ignore with a written reason in this file is the only tolerated escape hatch, and the planted
defect test (`tests/test_gate_scripts.py`) proves the gate still fails when it should.

The eight-media-module scope table below is superseded: the gate now covers the whole
`packages/core` tree, which is the honest version of "new modules only".

| Module | Lines |
| --- | --- |
| `packages/core/media/tts.py` | 886 |
| `packages/core/media/render.py` | 756 |
| `packages/core/media/qc.py` | 1126 |
| `packages/core/media/__init__.py` | 9 |
| `packages/core/motion/emit.py` | 665 |
| `packages/core/motion/__init__.py` | 9 |
| `packages/core/agents/vision.py` | 340 |
| `packages/core/orchestration/editorial.py` | 640 |
| **total** | **4431** |

Expect real findings. These modules use `Any` at the media and provider boundaries, `dict[str, Any]`
for artifact payloads, and `state: Any` for the pipeline handle — patterns `--strict` rejects. The
work is not a formality and should not be scheduled as one.

## Risk-driven ordering note

The riskiest items are scheduled early on purpose: netguard and credential origin binding (1.3,
1.4) because they are security-shaped and cheap now, expensive later; the lease and resume design
(1.5) because retrofitting durability into a working pipeline is a rewrite; and renderer parity
(2.3) because discovering on day 40 that the secondary renderer cannot hit 1080×1920 invalidates
the motion-skill plan.
