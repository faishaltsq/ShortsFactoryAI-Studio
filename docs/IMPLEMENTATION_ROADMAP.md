# IMPLEMENTATION_ROADMAP — phases, tasks, exit gates

Rule: a phase is done when its exit gate passes with real evidence, not when its code exists.
Every task below names its verification. Nothing is marked done on the strength of generation.

---

## PHASE 1 — FOUNDATION

### 1.1 Repository and toolchain
- [x] `pyproject.toml` (uv), `package.json` workspaces, `.gitignore`, `.editorconfig`, `ruff` config.
- [x] `scripts/check.ps1` / `check.sh`: ruff + pytest + tsc + vitest + schema export diff.
- **Verify:** `uv run ruff check .` clean; `uv run pytest` green on an empty suite (exit 5 handled).

### 1.2 Contracts package
- [x] `packages/core/contracts/`: Job, Research, Script, Review, SceneSpec (with `camera`/`motion`),
      MotionPlan, Assets, Audio, Render, QA, Approval, Metadata, Publication, Event.
- [x] JSON Schema export to `config/schemas/*.json`, generated not hand-written.
- [x] Validator rejects: non-static camera without target; duration out of range; missing licence.
- **Verify:** contract tests, 1 per rejection rule; schema export diff is empty in CI.

### 1.3 Netguard
- [x] `packages/core/security/netguard.py`: CIDR deny list, resolve-then-pin, redirect refusal.
- **Verify:** tests for each denied range, DNS-rebinding simulation (host resolves to public then
  private — second resolution never happens because the IP is pinned), `allow_private_hosts` opt-in.

### 1.4 Providers
- [x] `Provider` protocol, `ResolvedCall` frozen dataclass, `Capability` enum.
- [x] Transports: `openai_compat`, `anthropic`, `ollama`, `cli`, `mock`.
- [x] Immutable resolution: two agents on one provider get two independent calls (regression test
      for the donor's shared-mutation bug).
- [x] Capability validation before call; `CapabilityMismatch` names agent/provider/capability.
- [x] Credential store: env reference + DPAPI; origin binding; `has_credential` only in responses.
- [x] Usage log with pre-call budget check.
- Uncertain text requests require explicit duplicate-risk confirmation. The journal records the
  operator's authorization and consumes it when one worker atomically claims the next attempt;
  the original uncertain attempt remains in the journal. Reservation enforcement and crash
  recovery across the full provider boundary still require the proofs in the completion plan.
  Completed text responses replay before the pre-call budget check, so an exhausted budget cannot
  block recovery of work already paid for; new calls remain subject to the budget.
  `tests/test_request_journal.py::test_completed_call_replays_when_budget_is_exhausted` covers both.
- **Verify:** transport tests against a local stub HTTP server (no real keys); credential never
  appears in any response, log line, or artifact (sentinel-string test); capability matrix test.

### 1.5 Orchestration
- [x] `JobState` enum + explicit allow-list transitions; illegal transition raises.
- [x] `JobStore` on `sqlite3`: WAL, busy_timeout, migrations table, atomic artifact writes.
- [x] Token-owned leases with heartbeat; expired lease → `waiting`, never `working`.
- [x] Idempotent stage execution; completion marker written last.
- [x] Bounded retries; exhaustion → `BLOCKED`.
- [x] Cooperative cancellation at stage boundaries.
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
- [x] `studio_events` table, monotonic cursor, ordered replay, snapshot consistency.
- [x] Redaction: sentinel secret never appears in an event row.
- [x] SSE stream with `Last-Event-ID` resume.
- **Verify:** replay-after-reconnect test (no gaps, no duplicates); redaction test; snapshot p95
  measured under a simulated event flood.

### 1.7 API
- [x] FastAPI app: jobs CRUD, run, cancel, approve, reject, artifacts, video (Range), providers,
      studio snapshot, studio stream, usage.
- [x] Same-origin dashboard proxy; no token in the browser for local use.
- **Verify:** route tests; 409 on illegal approval; Range request returns 206 with correct
  `Content-Range`.
### 1.8 Dashboard shell
- [x] Next.js app, dark default, sidebar, the eleven required routes — all linked and rendered.
      The sidebar links to `/`, `/jobs`, `/create`, `/storyboard`, `/assets`, `/providers`,
      `/usage`, `/agents`, `/skills`, `/calendar`, and `/settings`. Studio production zones link
      to `/storyboard`, `/assets`, `/agents`, or `/jobs` where their operator controls exist, and
      carry the current `job_id` so a zone's module opens on the job the operator is watching.
      `apps/dashboard/e2e/fallback-routes.spec.ts` walks every zone link in the 2D fallback and
      asserts the page it names renders.
      After creating a job, `/create` links directly to its selected detail in `/jobs`, where the
      operator can start it; creation alone does not start production.
      `/create` offers an explicit local video render using the Windows system-default voice.
      Without that choice, the job stops at storyboard; mock output remains unpublishable.
      `/agents` lists all fourteen workflow agents. LLM agents show and edit provider/model
      bindings; deterministic agents are labelled as local code and expose no fake model control.
      A binding is the whole configuration of a call, not just its provider: `model`,
      `temperature`, `max_tokens` and `system_prompt_override` are persisted, restored on restart,
      and reach the call itself — `build_call` applies the first three and the agent sends the
      fourth, so `prompt_sha256` hashes the prompt that was actually sent. The save response is
      the binding verbatim, so a client can PUT it straight back; an explicit `null` clears an
      override. An unknown or duplicated provider candidate is a 422 before anything is written.
      `capability_gaps` diagnoses the agent's own selected provider, not a union over every
      enabled one, so the banner is honest in exactly the case it exists for.
      `/storyboard` and `/assets` are read-only artifact workspaces: they select a persisted job
      (deep-link `?job_id=`, history-safe) and render the actual `storyboard.json` /
      `render-props.json`, `assets.json` and `audio.json` contents. They never invent a frame
      preview or an asset file; an artifact that has not been produced says so.
      `/skills` presents the built-in capability catalog from `GET /api/catalog` (seven template
      ids, the secondary renderer's motion vocabulary, and the installed character manifest). It
      is explicitly not a MotionSkillRegistry: no plugin versions, install paths, or validation
      badges are claimed, because none is read at runtime.
      `/settings` edits the durable budget and render-admission policy through `GET`/`PUT
      /api/settings`. The render thresholds it saves are enforced: the render stage reads the
      saved policy before a renderer process exists.
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

### 2.0 Informative-engine migration (ADR 0013)
- [x] Character engine retired from the exported video: `packages/video/src/character/**`,
      `art/Figure.tsx`, `motion-beats.ts`, `speech.ts`, `CharacterSheet`, `CharacterReel` and the
      `IllustratedStory` composition are deleted, along with `config/characters.json` and the
      `bang-motion` renderer (`packages/core/motion/`, `scripts/bang-render.mjs`).
- [x] Object library shipping fifteen animated objects (`packages/video/src/art/objects.tsx`) over
      seven backdrops, with `OBJECT_KINDS` as the single cross-language vocabulary
      (`tests/test_architecture.py` proves the TypeScript library and the Python contract agree).
- [x] Three informative templates replace the presenter: `ObjectExplainer` (objects + callouts +
      flows, beats drive highlights), `ProcessFlow` (an ordered chain whose motion *is* the
      explanation) and `MetricShift` (bars grow as their numbers count).
- [x] Evidence: `evidence/topic-ai.mp4` and `evidence/topic-space.mp4`, both real 1080×1920 /
      30 FPS / 180-frame renders with different objects, backdrops, themes and templates;
      `packages/video/scripts/verify-template-stills.mjs` proves all nine templates mount, answer a
      declared `push` camera, and only `ObjectExplainer` reacts to beats.
- [x] The 3D agent office is untouched and now protected by an architecture test that fails if
      `apps/dashboard/src/three/**` ever imports the video engine.


### 2.1 Agents
- [x] Research (with source retrieval + claim verification), TopicSelection, Script, CreativeDirector,
      Storyboard, Asset, Animation, Audio, Editor, Quality, Metadata.
      **Contract behaviour is proven per agent, not per pipeline.**
      `tests/test_agent_contracts.py` drives each of the eight LLM agents with a scripted fake
      provider and asserts four things for every one: a recorded fixture payload validates into
      its artifact with exactly one provider call; malformed prose gets **exactly one** repair and
      then raises `ModelOutputError("schema_violation")` (the stage maps that to a non-retryable
      `StageError` and the job to `BLOCKED`); a valid second answer is accepted, so the repair is a
      real chance rather than a formality; and a `ProviderError` is **not** re-spent as a repair —
      the original error code survives. The repair bound is mutation-proven: replacing the single
      repair with a retry loop fails the test. `test_every_llm_agent_has_a_fixture` fails when an
      agent is added without a fixture, so "each agent" stays true as the set grows.
      The deterministic agents (Asset, Audio, Editor, Publisher, Director, FactoryOrchestrator)
      make no model call and are covered by their own stage tests.
- **Verify:** each agent has a contract test with a recorded fixture response and a negative test
  (malformed JSON → bounded repair → `BLOCKED`). **Done** — see above; the negative test is
  parametrized over all eight LLM agents.

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
- [x] Art kit (`Stage`, `Figure`, `Prop`, `Camera`, `Effects`, `palette`, `rng`) with `fit="box"` in
      panels. All components in `packages/video/src/art/`; `Figure` and `Prop` accept
      `fit: 'frame' | 'box'` and scale accordingly.
- [x] Character engine: rig, poses, expressions, motion presets, mouth sync.
      `packages/video/src/character/`: `rig.ts`, `poses.ts`, `expressions.ts`, `motion.ts`,
      `gestures.ts`; `CharacterFigure` and `Face` render; `speech.ts` envelope drives mouth sync.
- **Verify:** `still-smoke` renders every template at 1080×1920; each still inspected visually (a
  green `tsc` and a passing luma check cannot see a missing character).

### 2.3 Renderers
- [x] `RemotionRenderer` with explicit `--port` and absolute `--props` (Remotion 4.0.537).
- [x] `BangMotionRenderer`: CDP frame capture via the bundled `chrome-headless-shell`, FFmpeg encode,
      sandboxed. Design law and the seek→2×rAF→screenshot technique reused from Bang Motion 1.19.0
      (`c1aa65e`, MIT) as knowledge only — no upstream executable lines.
- [x] Renderer parity: same storyboard, both renderers, both pass `validate_probe`
      (`tests/test_renderer_parity.py::test_both_renderers_pass_the_same_gate_from_the_same_props`).
      **All seven templates** now walk the same rig in one multi-scene storyboard
      (`::test_every_template_renders_through_both_renderers`): shared gate unmodified, muxed
      narration, seven declared scene boundaries located from the picture itself (per-frame
      `tblend` delta: boundaries dominate the strongest in-scene animation frame in each renderer —
      Remotion >= 4.09 vs 2.11, Bang Motion >= 2.09 vs 0.74), plus the character beat measured
      visible in both.
- [x] Per-scene rerender. `render.json.scene_hashes` is consumed by a per-scene render cache
      (`packages/core/media/render.py`, `SceneCache`): cache keys hash the *timed* scene dict plus
      renderer/version/theme/geometry plus the global pixel inputs (whole-timeline frame count for
      the progress bar, watermark text). A hit must ffprobe validating geometry and frame count —
      a truncated or half-written part is a miss and re-renders, never spliced. Hits concat with
      zero renderer invocations; misses render frame-windowed per scene. Bang Motion bypasses
      the cache (one full render). FR-5.4 met.
- **Verify:** byte-stability test (render twice, compare frame hashes) — done within each renderer
  (`test_each_renderer_is_deterministic_within_itself`, 60/60 identical framemd5 twice); cross-renderer
  identity is not expected and is not claimed. Per-scene rerender — proven with real ffmpeg in
  `tests/test_render_cache.py`: unchanged storyboard => zero renderer invocations and a real probed
  full-timeline output; one changed scene => exactly that scene's frame window re-renders and the
  other part file is reused verbatim; truncated part => detected by probe, that scene re-renders;
  concat of two real parts merges into a real probeable timeline; keys separate watermark/total-length.

### 2.4 Audio
- [x] Local Windows SAPI TTS adapter with word boundaries; deterministic subtitle grouping;
      narration-only −16 LUFS normalisation; optional licensed-music ducking argv; AAC mux.
- **Verify:** ffprobe duration match; `silencedetect` finds no unexpected gap; subtitle cues inside
  the safe area and within duration. The real-media proof records any remaining detector gate.
- [ ] Music/SFX asset acquisition remains out of scope until real licensed paths exist; no asset is
      fabricated to satisfy the mixer.

### 2.5 QA
- **V3-E semantic inspection:** the current path uses individual checksum-bound MP4 frames,
  eight explicit semantic criteria per scene, journaled vision requests and current-context
  revalidation. Readiness is fail-closed; UNVERIFIED requires explicit per-render operator/reason
  review permission and FAIL cannot be waived. This is separate from the historical contact-sheet
  proof below. Science remains UNVERIFIED without retrieved source/quote evidence; no live V3
  benchmark or production model-quality claim is implied. See `SEMANTIC_VISUAL_QA.md`.
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
that `currentTime` advances). With `STUDIO_VIDEO_PROOF=1` the spec provisions its own fixture —
`scripts/render_proof_job.py --render`, which itself refuses any terminal state other than
`READY_FOR_APPROVAL` (a blocked job with a partial video is exit 2, not success) and goes through
`PinnedHTTP` like every other caller — and a requested proof with no fixture afterwards is a
failure, not a skip. The E2E suite runs inside `scripts/dashboard_e2e.py`, which owns a
`TemporaryDirectory` test root instead of deleting a fixed repository path. Both renderers pass the same `validate_probe` from the same props, and
each is deterministic within itself (60/60 identical framemd5 twice). A seven-scene storyboard —
one scene per template — renders through both renderers and passes the identical gate
(`test_every_template_renders_through_both_renderers`), with every declared scene boundary proven
to be a picture change in each from the frames themselves.

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
- Per-scene render cache is implemented and proven (`tests/test_render_cache.py`); renders reuse
  unchanged scenes with zero renderer invocations.
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
- [x] Read-only per-job monitor with URL scope and production-page round-trip navigation.
      The room, inspector, and workflow use the selected job's persisted events; all-job mode
      remains explicit. Generation and ordering guards reject stale reads and callbacks.
      The global projection still pauses 3D for another job's live render. Covered by
      `useStudio.test.ts`, `StudioProductionMonitor.test.tsx`, and browser smoke scenarios
      using a completed storyboard job beside a never-started job.
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

- [x] Topic discovery scheduler (operator-enabled, default off). **The loop exists; topic
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
- [x] Persistent queue, production calendar. `jobs` is a persistent store with claim-next
      (`priority, created_at` ordering), an additive `scheduled_for` column honored by the
      scheduler, and `/api/jobs?upcoming=1` + `/api/jobs/upcoming` for the calendar page. The
      scheduler loop itself stays off by default and is an operator action (see above). Proven in
      `tests/test_scheduler.py` (priority ordering, a future `scheduled_for` is never claimed, an
      approval-waiting job is never claimed).
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
- [x] Thumbnail **upload**: `ThumbnailTransport` protocol in `transport.py` with
      `set_thumbnail(video_id, thumbnail_path) -> ThumbnailResult`. `YouTubeTransport` implements
      it via `POST thumbnails/set?videoId=...`; `StubTransport` records the call. The publish
      stage uploads the thumbnail **after** a successful video insert when the transport supports
      it and `metadata.json.thumbnail.path` names a file that exists on disk. Best-effort: a
      failure emits `thumbnail_failed` but does not roll back or fail the publish — the video is
      safely on the channel with an auto-generated thumbnail. Proven by three tests:
      `test_publish_uploads_thumbnail_when_present` (stub records the call with the correct
      video_id), `test_publish_skips_thumbnail_upload_when_not_rendered` (zero thumbnail calls),
      `test_publish_succeeds_even_when_thumbnail_upload_fails` (`TransportRefused` → video still
      confirmed, `thumbnail_failed` event emitted). mypy strict clean.
- [x] Publish / reconcile, **proven offline against the stub transport**:
      `PublicationArtifact` gained `idempotency_key` + `attempt`; `packages/core/publish/` derives
      the key from `render.json.sha256`, refuses to re-insert a confirmed record, records
      `uncertain` on a timeout-after-send (non-retryable), and reconciles by *reading*
      (`reconcile_uncertain`, zero inserts in every branch). Routes:
      `POST /api/jobs/{id}/publish` and `POST /api/jobs/{id}/publish/reconcile`.
      `tests/test_publish_stage.py::test_a_process_restart_after_uncertain_uploads_exactly_once`
      proves exactly one insert across a first run ending uncertain, a fresh service object over
      the same database, and a post-reconcile re-run.
- [x] **YouTube OAuth (installed-app flow) and credentials configured**: `scripts/setup_youtube.py`
      drives an RFC 8252 loopback authorization flow with PKCE S256 (`build_authorize_url`,
      `exchange_code`, `seal_client_credentials`, `seal_tokens`). Client credentials and token bundles
      are sealed with Windows DPAPI at `data/secrets/oauth-youtube-client.bin` and
      `data/secrets/oauth-youtube.bin`. `apps/api/main.py`'s `_transport("youtube")` unseals credentials
      and instantiates `YouTubeTransport`. Operator authenticated successfully; channel access
      verified against `pochitalk` (`UC-oFcju00rkFpoqNKuAtFpA`).
      Tests: `tests/test_http_base.py` (16), `tests/test_oauth.py` (15), `tests/test_api_publish.py` (20).
- [x] Usage and cost **accounting**: `GET /api/usage/summary` aggregates per day, per agent and per
      model, and `PUT /api/providers` now accepts `price_in_per_mtok`/`price_out_per_mtok` so
      `est_cost_usd` can be a real number. `price_configured` distinguishes an unpriced zero from a
      free run.
- [x] Usage and cost **dashboard**: `/usage` renders the three summary tables (per day, per agent,
      per provider+model) from `GET /api/usage/summary`. `CostCell` reports "belum dikonfigurasi"
      when `price_configured` is false, so an unpriced zero is never presented as a free run.
      Covered by `apps/dashboard/src/app/usage/page.test.tsx`.
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
| Types (py) | `uv run mypy packages/core --strict` | exit 0, 53 files strict-clean |
| Types (ts) | `npm --prefix apps/dashboard run typecheck` | 0 errors |
| Unit | `uv run pytest -q` | all pass |
| UI unit | `npm --prefix apps/dashboard run test` | all pass |
| E2E | `npm --prefix apps/dashboard run test:e2e` | all pass |
| Schema | `uv run python scripts/export_schemas.py --check` | exit 0, 15 schemas current |
| Secrets | `uv run python scripts/scan_secrets.py` | exit 0, 0 findings |
| Render | `npm --prefix packages/video run still-smoke` | exit 0, count matches |
| Media | `uv run python scripts/verify_video.py <job>` | all checks pass |

**The Types (py) gate runs.** mypy 1.18.2 is in the `dev` dependency group, `[tool.mypy]` sets
`strict = true` / `python_version = "3.12"` / `packages = ["packages.core"]`, and
`scripts/check.ps1` + `check.sh` invoke it like every other gate. `uv run mypy packages/core
--strict` exits 0 over all 56 core source files (2026-11-03, after the creative-pipeline V2 work
below added `providers/presets.py` and three new core flows). Rules for keeping it green: no
blanket `# type: ignore`, no per-module `ignore_errors`; a single ignore with a written reason in
this file is the only tolerated escape hatch, and the planted defect test
(`tests/test_gate_scripts.py`) proves the gate still fails when it should.

One recurring trap, worth naming because it cost four rounds here: narrowing through a ternary on
an `Any` — `x = value if isinstance(value, dict) else {}` — is inferred as
`Any | dict[Any, Any] | None`, and every later `x.get(...)` fails. Annotate the target
(`x: dict[str, Any] = value if isinstance(value, dict) else {}`).

## Creative pipeline V2 (2026-11-03)

Four changes, each with its own ADR. They are recorded here because they change the shape of a
phase-2 run, not just its output quality.

| Change | ADR | Where |
| --- | --- | --- |
| Motion code is a second pass on its own state (`MOTION_READY`), timed against the measured narration, with a digest guard on reuse | ADR-011 | `packages/core/contracts/state.py`, `orchestration/pipeline.py`, `contracts/artifacts.py` |
| `creative-motion-brief.json` is a directing decision on its own stage, not a derivation from the visual plan | ADR-012 | `packages/core/agents/concrete.py`, `contracts/artifacts.py`, `orchestration/pipeline.py` |
| `full-stepfun-v2` is a selectable whole-studio preset with cross-family fallback off | ADR-013 | `packages/core/providers/presets.py`, `apps/api/{config,state,main,schemas}.py` |
| Creative QC gained four checks beyond frame differences: per-scene narration relevance, declared cause and effect, transition continuity, visual payoff | — | `packages/core/media/qc.py` |

`MotionCoderAgent` was rewritten around the visual-first principle (illustrate the noun, animate the
verb, show the consequence). It now receives the brief, the shot plan with measured timing, the
assets and the narration instead of a titles-and-frame-counts summary, and its Remotion skill
reference is selected per shot against a configurable token budget with per-skill digests recorded
in the artifact. `docs/MOTION_SKILLS.md` §3.1 has the selection table.

New suites: `tests/test_presets.py`, `tests/test_two_pass_timing.py`.

### What was deliberately not built

- **Section-level retrieval inside a Remotion skill.** Every `SKILL.md` here is 1–13 KB, so the whole
  file fits the budget; splitting it would add a parser without changing what the model reads.
- **A hard `cause_effect` requirement.** `SceneSpec.causal_state` is optional in the contract, and a
  gate that required it would make the contract's own optionality a lie. The check fires on a
  *declared* cycle instead. The mock reference storyboard now declares one (and a truthful
  `continuity: "carry"` between the scenes that share an object kind), so the check is exercised
  end to end and not only by its unit tests.
- **Deliberate stillness as a permitted shot.** The `bme_dynamics` gate fails any scene whose
  beginning/middle/end keyframes do not differ, so "allow stillness when pacing calls for it" cannot
  be honoured without first changing that gate. The prompt asks for restrained, subject-driven
  motion instead, and says an ambient layer added to satisfy the metric is a defect.

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
