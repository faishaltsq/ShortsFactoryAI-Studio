# P0 Integration Hardening & Real Full-Pipeline Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement AST-based code validation, Windows subprocess execution isolation, explicit renderer/fallback selection, VoiceStudio timing honesty, and execute a verified fresh full-pipeline video production with Gemini 3.8 and StepFun without silent fallbacks.

**Architecture:** Replace regex CodeGuard with a Node-based `@babel/parser` AST validator; scrub subprocess environments and bind Windows Job Objects in `media/render.py`; update `apps/api/schemas.py`, `pipeline.py`, and `CreatePage.tsx` with explicit `renderer`, `tts_provider`, and `fallback_policy` (`strict` vs `allow_legacy`); ensure `VoiceStudioAdapter` preserves native audio sample rates and records `alignment_mode: "estimated"`; update `run_causal_benchmarks.py` with explicit `--mode fresh` removing reused job IDs.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Remotion (Node.js / React / TypeScript), `@babel/parser`, Windows Job Objects (ctypes/win32), VoiceStudio local API.

**Spec:** `docs/superpowers/specs/2026-11-02-p0-integration-hardening-design.md`

## Global Constraints
- Domain code in `packages/core/**` must never import `fastapi`, `starlette`, `next`, or `uvicorn`.
- `packages/video/**` is touched only through the Remotion subprocess in `media/render.py`.
- No credentials or API keys may appear in outputs, logs, or subprocess environments.
- In `strict` fallback mode, failures in custom motion generation or rendering must halt the job immediately with `StageError`.
- If legacy fallback occurs in `allow_legacy` mode, `actual_renderer` must be recorded as `legacy-template` and `fallback_used: true` logged; never report custom motion success if legacy was rendered.

## Review Focus
1. AST parsing bypasses via computed member expressions (`obj['const' + 'ructor']`) or indirect `globalThis`.
2. Subprocess credential leakage via inherited `os.environ` into Remotion CLI child processes.
3. Silent fallback masking custom motion failures when `strict` policy was requested.
4. VoiceStudio subtitle drift or false claims of forced-alignment accuracy.
5. Benchmark runner reusing pre-existing MP4 outputs rather than generating fresh artifacts.

---

### Task 1: AST-Based CodeGuard Validation Engine

**Files:**
- Create: `packages/video/scripts/ast_guard.mjs`
- Modify: `packages/core/media/codeguard.py`
- Test: `tests/test_codeguard.py`

**Interfaces:**
- Consumes: TSX source code strings or files.
- Produces: `CodeGuardResult(valid: bool, issues: list[str], imported_modules: list[str])`.

- [ ] **Step 1: Write the failing adversarial test in `tests/test_codeguard.py`**
Add tests asserting that AST-based CodeGuard rejects computed member accesses, dynamic imports, illegal identifiers, and disallowed modules while allowing valid React/Remotion TSX.

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_codeguard.py -k test_ast_guard -v`
Expected: FAIL

- [ ] **Step 3: Implement `packages/video/scripts/ast_guard.mjs`**
Write a Node script utilizing `@babel/parser` (`packages/video/node_modules/@babel/parser`) to inspect TSX AST nodes for:
- Static imports and dynamic `import()` / `require()` calls (whitelist: `react`, `remotion`, `@remotion/*`, safe relative `./*`).
- Banned identifiers: `eval`, `Function`, `process`, `child_process`, `fs`, `os`, `net`, `http`, `https`, `global`, `globalThis`, `window`, `document`, `fetch`, `XMLHttpRequest`, `WebSocket`, `localStorage`, `sessionStorage`.
- Banned property access: `constructor`, `__proto__`, `prototype`.

- [ ] **Step 4: Update `packages/core/media/codeguard.py` to invoke AST validator**
In `CodeGuard.validate_source` and `validate_file`, invoke `ast_guard.mjs` via `subprocess.run(["node", ...])` when Node is available, merging results with static pattern checks.

- [ ] **Step 5: Run tests to verify they pass**
Run: `uv run pytest tests/test_codeguard.py -v`
Expected: PASS with 0 failures

- [ ] **Step 6: Commit**
```bash
git add packages/video/scripts/ast_guard.mjs packages/core/media/codeguard.py tests/test_codeguard.py
git commit -m "feat(security): implement AST-based CodeGuard validation for custom TSX"
```

---

### Task 2: Subprocess Execution Isolation & Windows Job Object

**Files:**
- Modify: `packages/core/media/render.py`
- Test: `tests/test_media_render.py`

**Interfaces:**
- Consumes: TSX code directory, props, output path.
- Produces: `render_custom_motion(...) -> dict[str, Any]` running inside a scrubbed environment with process-tree containment.

- [ ] **Step 1: Write failing tests for execution environment scrubbing and process containment**
In `tests/test_media_render.py`, write tests asserting:
- `render_custom_motion` does not pass `NINEROUTER_KEY` or custom env secrets to Remotion subprocess.
- Process tree lifecycle management terminates cleanly on timeout.

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_media_render.py -k test_isolation -v`
Expected: FAIL

- [ ] **Step 3: Implement environment scrubbing & Windows Job Object in `render.py`**
In `packages/core/media/render.py`:
- Build minimal clean `env`: copy only `SYSTEMROOT`, `PATH`, `TEMP`, `TMP`, `NODE_PATH`, `LOCALAPPDATA`. Explicitly delete sensitive keys.
- On Windows (`sys.platform == 'win32'`), use `ctypes.windll.kernel32` to create a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (limit flag `0x2000`) and assign the subprocess handle to the Job Object.
- Set memory limit constraints and enforce execution timeout.

- [ ] **Step 4: Run tests to verify they pass**
Run: `uv run pytest tests/test_media_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add packages/core/media/render.py tests/test_media_render.py
git commit -m "feat(media): enforce scrubbed environment and Windows Job Object for Remotion render"
```

---

### Task 3: API Schemas, Pipeline Orchestration & Fallback Policy

**Files:**
- Modify: `apps/api/schemas.py`
- Modify: `packages/core/orchestration/pipeline.py`
- Modify: `packages/core/media/render.py`
- Test: `tests/test_renderer_dispatch.py`

**Interfaces:**
- Consumes: `CreateJobBody(renderer, tts_provider, fallback_policy, ...)`.
- Produces: Correct pipeline stage construction and honest render metadata recording.

- [ ] **Step 1: Write failing tests for renderer selection and strict fallback**
In `tests/test_renderer_dispatch.py`, test:
- `renderer="custom-motion"` with `fallback_policy="strict"` raises `StageError` when code validation or render fails.
- `renderer="custom-motion"` with `fallback_policy="allow_legacy"` records `renderer: "legacy-template"`, `fallback_used: true`, and emits progress warning.
- `CreateJobBody` validates `renderer` in `["remotion", "custom-motion", "legacy-template"]` and `fallback_policy` in `["strict", "allow_legacy"]`.

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_renderer_dispatch.py -v`
Expected: FAIL

- [ ] **Step 3: Update `apps/api/schemas.py`**
Add `renderer`, `tts_provider`, `fallback_policy`, and `motion_provider` fields to `CreateJobBody`.

- [ ] **Step 4: Update `pipeline.py` and `render.py`**
- Pass `fallback_policy` from payload into render stage.
- In `render.py`: if `active_strategy == "custom-motion"` and custom rendering fails:
  - If `fallback_policy == "strict"`: raise `StageError("render_failed", str(exc))` immediately.
  - If `fallback_policy == "allow_legacy"`: fall back to legacy, set `actual_renderer = "legacy-template"`, record `fallback_used = True` in `render.json`.

- [ ] **Step 5: Run tests to verify they pass**
Run: `uv run pytest tests/test_renderer_dispatch.py -v`
Expected: PASS

- [ ] **Step 6: Commit**
```bash
git add apps/api/schemas.py packages/core/orchestration/pipeline.py packages/core/media/render.py tests/test_renderer_dispatch.py
git commit -m "feat(orchestration): support custom-motion renderer selection and strict fallback policy"
```

---

### Task 4: VoiceStudio Adapter Hardening & Timing Transparency

**Files:**
- Modify: `packages/core/media/voicestudio.py`
- Modify: `packages/core/media/tts.py`
- Test: `tests/test_voicestudio.py`

**Interfaces:**
- Consumes: Narration text, voice profile, language code.
- Produces: WAV audio with native sample rate, `word_timestamps`, and explicit `alignment_mode`.

- [ ] **Step 1: Write failing tests for sample rate preservation and alignment mode tagging**
In `tests/test_voicestudio.py`, test:
- Preserves native sample rate (e.g., 24000 Hz or 48000 Hz from WAV header).
- Marks `alignment_mode: "estimated"` when word timestamps are duration-derived.
- Marks `alignment_mode: "aligned"` when forced-alignment header `x-word-timestamps` is present.

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_voicestudio.py -k test_alignment_mode -v`
Expected: FAIL

- [ ] **Step 3: Update `packages/core/media/voicestudio.py` and `tts.py`**
- In `VoiceStudioResult`: add field `alignment_mode: str` ("aligned" or "estimated").
- In `VoiceStudioAdapter.synthesize`: set `alignment_mode = "aligned"` if header was valid, else `"estimated"`.
- In `VoiceStudioProvider.synthesize`: return metadata dict with `alignment_mode` and `sample_rate`.

- [ ] **Step 4: Run tests to verify they pass**
Run: `uv run pytest tests/test_voicestudio.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add packages/core/media/voicestudio.py packages/core/media/tts.py tests/test_voicestudio.py
git commit -m "feat(media): preserve native VoiceStudio sample rate and tag subtitle alignment mode"
```

---

### Task 5: Dashboard Create Video UI Controls

**Files:**
- Modify: `apps/dashboard/src/app/create/page.tsx`
- Test: `apps/dashboard/tests/create.test.tsx` (or dashboard vitest suite)

**Interfaces:**
- Consumes: Operator selection from UI form.
- Produces: API payload to `POST /api/jobs` containing `renderer`, `tts_provider`, and `fallback_policy`.

- [ ] **Step 1: Write failing test in dashboard vitest suite**
Verify form includes controls for Renderer (`custom-motion` / `remotion`), TTS Provider (`voicestudio` / `edge-tts`), and Fallback Policy (`strict` / `allow_legacy`).

- [ ] **Step 2: Run vitest to verify failure**
Run: `npm --prefix apps/dashboard run test`
Expected: FAIL

- [ ] **Step 3: Update `apps/dashboard/src/app/create/page.tsx`**
- Add state variables: `renderer` ("custom-motion" | "remotion"), `ttsProvider` ("edge-tts" | "voicestudio" | "sapi"), `fallbackPolicy` ("strict" | "allow_legacy").
- Add UI select inputs with clear Indonesian labels.
- Pass fields to `api.createJob`.

- [ ] **Step 4: Run typecheck and tests to verify they pass**
Run: `npm --prefix apps/dashboard run typecheck`
Run: `npm --prefix apps/dashboard run test`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add apps/dashboard/src/app/create/page.tsx
git commit -m "feat(dashboard): expose custom-motion renderer, TTS provider, and fallback policy in job creation"
```

---

### Task 6: StepFun MotionCoder & Remotion Skills Integration

**Files:**
- Modify: `config/studio.json`
- Modify: `packages/core/agents/concrete.py`
- Test: `tests/test_motion_coder.py`

**Interfaces:**
- Consumes: `Storyboard`, `CreativeMotionBrief`, Remotion skills.
- Produces: `MotionCodeArtifact` with `validated_by_codeguard` and `skill_hashes`.

- [ ] **Step 1: Write failing tests for MotionCoderAgent skill hash verification**
Test that `MotionCoderAgent` injects available Remotion skill text, calculates SHA-256 skill hashes, and validates output files via AST CodeGuard.

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_motion_coder.py -v`
Expected: FAIL

- [ ] **Step 3: Update `config/studio.json` and `packages/core/agents/concrete.py`**
- In `config/studio.json`: add binding for `MotionCoderAgent` with primary `stepfun` (model `om/step-5-preview`).
- In `MotionCoderAgent.sanitize_payload`: invoke AST CodeGuard on all generated TSX files. If issues exist, mark `validated_by_codeguard: false` and list issues.

- [ ] **Step 4: Run tests to verify they pass**
Run: `uv run pytest tests/test_motion_coder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add config/studio.json packages/core/agents/concrete.py tests/test_motion_coder.py
git commit -m "feat(agents): bind MotionCoderAgent to StepFun and enforce AST CodeGuard verification"
```

---

### Task 7: Benchmark Integrity & Runner Modes

**Files:**
- Modify: `scripts/run_causal_benchmarks.py`
- Test: `tests/test_gate_scripts.py`

**Interfaces:**
- Consumes: CLI args `--mode {fresh,resume,verify-existing}`, `--benchmark {all,a,b,c}`.
- Produces: Execution without hardcoded job reuse in fresh mode; writes comprehensive verification report.

- [ ] **Step 1: Write tests for benchmark CLI argument parsing and modes**
Test that `--mode fresh` ignores `existing_job_id` and configures `renderer="custom-motion"`, `fallback_policy="strict"`, `tts_provider="voicestudio"`.

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_gate_scripts.py -k test_benchmark_modes -v`
Expected: FAIL

- [ ] **Step 3: Update `scripts/run_causal_benchmarks.py`**
- Add `--mode` choices: `fresh`, `resume`, `verify-existing`. Default: `fresh`.
- In `fresh` mode: never reuse `existing_job_id`. Set `renderer: "custom-motion"`, `fallback_policy: "strict"`, `provider_mode: "live"`.
- Log audit metrics: Git SHA, provider model, code hash, audio hash, video hash, duration, QC results.

- [ ] **Step 4: Run tests to verify they pass**
Run: `uv run pytest tests/test_gate_scripts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add scripts/run_causal_benchmarks.py tests/test_gate_scripts.py
git commit -m "feat(benchmarks): introduce explicit fresh/resume/verify-existing benchmark runner modes"
```

---

### Task 8: Real Full-Pipeline Production Execution & Verification

**Files:**
- Output Artifacts: `data/jobs/{job_id}/*` (including `motion-code.json`, `code/RootComposition.tsx`, `audio.json`, `tts_metadata.json`, `output.mp4`, `qc.json`)
- Report: `docs/BENCHMARK_REPORT.md`

**Interfaces:**
- Consumes: Live Gemini 3.8 + StepFun + VoiceStudio + Remotion.
- Produces: Verified fresh MP4 short with custom motion graphics, Indonesian narration, and QC evaluation.

- [ ] **Step 1: Execute Benchmark A in `--mode fresh`**
Run: `python scripts/run_causal_benchmarks.py --benchmark a --mode fresh`
- Verify pipeline executes:
  - Research & Script via Gemini 3.8 Flash
  - MotionCoderAgent via StepFun (`om/step-5-preview`) with Remotion skills
  - AST CodeGuard passes
  - Remotion renders custom composition inside scrubbed sandbox
  - VoiceStudio synthesizes Indonesian narration
  - Technical QC and Visual QC evaluate B/M/E frames
  - Pipeline halts at `READY_FOR_APPROVAL`

- [ ] **Step 2: Inspect output video and artifact provenance**
- Confirm `actual_renderer == "custom-motion"`
- Confirm `fallback_used == false`
- Confirm `output.mp4` exists, is non-zero, and plays custom motion animation
- Confirm contact sheet and B/M/E QC scores

- [ ] **Step 3: Update `docs/BENCHMARK_REPORT.md` with verifiable deliverables**
Document Job ID, Git SHA, provider IDs, actual renderer, hashes, and QC scores.

- [ ] **Step 4: Commit**
```bash
git add docs/BENCHMARK_REPORT.md
git commit -m "docs(benchmarks): record real full-pipeline verification deliverables for Benchmark A"
```
