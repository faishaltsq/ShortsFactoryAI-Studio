# P0 Integration Hardening & Real Full-Pipeline Verification Design

**Date**: 2026-11-02  
**Author**: Principal AI Video Systems Engineer & Security Lead  
**Status**: Approved  
**Scope**: End-to-end integration hardening, AST CodeGuard security boundary, execution isolation, renderer & TTS selection, VoiceStudio integration, benchmark honesty, and semantic visual QC.

---

## 1. Context & Objectives

The project implements an AI-directed motion graphics video production system using:
- **Research & Scripting**: Gemini 3.8 Flash (`ag/gemini-3.8-flash-high`) via 9router
- **Motion Generation**: StepFun (`om/step-5-preview`) for `MotionCoderAgent`
- **Animation Framework**: Remotion + official Remotion agent skills
- **Narration**: Locally installed VoiceStudio CUDA service for Indonesian TTS
- **Quality Assurance**: Automated Technical QC, Beginning/Middle/End (B/M/E) frame visual QC, and human approval

### Deficiencies Addressed
1. **Security Vulnerability**: `CodeGuard` relied on regex and string checks, which could be bypassed in generated TSX code.
2. **Subprocess Host Risk**: Host environment variables (including API keys and secrets) were exposed to render subprocesses without sandboxing or process-tree lifecycle management.
3. **Renderer Transparency**: Dashboard did not expose renderer choice (`custom-motion` vs. `legacy-template`) or fallback policy (`strict` vs. `allow_legacy`), leading to silent fallback.
4. **VoiceStudio Integration**: No UI selector for VoiceStudio; timing was heuristically estimated but not transparently tagged.
5. **Benchmark Integrity**: `scripts/run_causal_benchmarks.py` had hardcoded `existing_job_id` values that reused old renders rather than demonstrating fresh end-to-end execution.

---

## 2. Architecture & Components

```
[Create Job (UI / API)]
       │
       ▼
[JobStore & Orchestrator Pipeline]
       │
  ┌────┴───────────────────────────┐
  │ 1. ResearchAgent (Gemini 3.8) │
  │ 2. ScriptAgent (Gemini 3.8)   │
  │ 3. CreativeDirectorAgent      │
  │ 4. StoryboardAgent            │
  └────┬───────────────────────────┘
       │
       ├─► [renderer == "custom-motion"] ──► MotionCoderAgent (StepFun + Remotion Skills)
       │                                            │
       │                                            ▼
       │                                  [AST CodeGuard Validation]
       │                                            │
       │                                     (Pass / Fail)
       │
       ├─► [AssetStage & AudioStage] ───────► VoiceStudioAdapter (Local :3900)
       │                                            │
       │                                            ▼
       │                                     [WAV + Subtitles]
       │
       ▼
[Secure Remotion Render Stage]
  - Environment Scrubbed (no secrets)
  - Windows Job Object Isolation (kill process tree on exit)
  - Fallback Policy:
      * strict: fail immediately if custom render fails
      * allow_legacy: fallback with explicit provenance logging
       │
       ▼
[Technical & Visual QC]
  - FFprobe specs & loudness (-16 LUFS)
  - Beginning / Middle / End (B/M/E) frame dynamics & entity validation
       │
       ▼
[Ready for Approval Gate] (Human Approval Required)
```

---

## 3. Detailed Component Specifications

### 3.1 Security Boundary: AST CodeGuard & Execution Isolation
1. **AST Parser Engine (`packages/video/scripts/ast_guard.mjs` & `packages/core/media/codeguard.py`)**:
   - Uses `@babel/parser` to construct an Abstract Syntax Tree for generated `.tsx` code.
   - AST Visitors strictly enforce:
     - `ImportDeclaration` / `CallExpression(import|require)`: Whitelist allowed modules (`react`, `remotion`, `@remotion/*`, `./*`). Rejects all Node.js built-ins (`fs`, `child_process`, `os`, `net`, `http`, `crypto`, etc.).
     - `Identifier` check: Rejects sensitive identifiers (`eval`, `Function`, `process`, `global`, `globalThis`, `window`, `document`, `fetch`, `XMLHttpRequest`, `WebSocket`, `localStorage`, `sessionStorage`).
     - `MemberExpression` check: Rejects prototype pollution and reflection (`constructor`, `__proto__`, `prototype`).
   - If any violation or syntax error occurs, code is immediately quarantined and rejected.

2. **Execution Environment Isolation (`packages/core/media/render.py`)**:
   - Scrubbed environment: Creates a clean `env` dict containing only `PATH`, `SYSTEMROOT`, `TEMP`, `TMP`, and `NODE_PATH`. Strips all API keys (`NINEROUTER_KEY`, secret tokens, `.env`).
   - Windows Job Object: Uses Win32 Job Object API with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` to ensure all child and grandchild processes of Remotion are cleanly killed on completion, error, or timeout.
   - Dedicated staging directory for custom composition rendering.

### 3.2 Renderer & Fallback Transparency
1. **API Schema (`apps/api/schemas.py`)**:
   - Adds `renderer: Literal["remotion", "custom-motion", "legacy-template"] = "remotion"`
   - Adds `tts_provider: Literal["edge-tts", "voicestudio", "sapi"] = "edge-tts"`
   - Adds `fallback_policy: Literal["strict", "allow_legacy"] = "allow_legacy"`
   - Adds `motion_provider: str | None = None`

2. **Dashboard UI (`apps/dashboard/src/app/create/page.tsx`)**:
   - Adds form controls for:
     - Renderer: `Custom Motion (StepFun AI)` or `Template Dinamis (Remotion)`
     - TTS Provider: `VoiceStudio (Lokal GPU)`, `Edge-TTS (Cloud Neural)`, `SAPI (Windows)`
     - Fallback Policy: `Strict (Berhenti jika gagal)`, `Allow Legacy (Gunakan template)`
   - Voice preview and dynamic voice dropdown adapt to the selected TTS provider.

3. **Fallback Policy Enforcement**:
   - In `strict` mode: Any failure in `MotionCoderAgent`, AST CodeGuard, or Remotion custom render halts the job with `StageError("render_failed", ...)`.
   - In `allow_legacy` mode: If custom rendering fails, falls back to legacy template, records `renderer: "legacy-template"`, `fallback_used: true`, `fallback_reason: ...`, and emits audit events.

### 3.3 StepFun MotionCoder & Remotion Skills Integration
1. **Agent Provider Binding (`config/studio.json`)**:
   - Bind `MotionCoderAgent` to `stepfun` with model `om/step-5-preview`.
   - Injects verified Remotion skills from `.agents/skills/remotion-*` into the system prompt.
   - `motion-code.json` records `skill_hashes` and `validated_by_codeguard`.

2. **Code Generation Output**:
   - Produces `RootComposition.tsx` and scene files (`Scene01.tsx`, `Scene02.tsx`, etc.).
   - Validated by AST CodeGuard before being written to `jobs/{job_id}/code/`.

### 3.4 VoiceStudio Integration & Timing Honesty
1. **VoiceStudio Local Adapter (`packages/core/media/voicestudio.py`)**:
   - Connects to local VoiceStudio service on port 3900.
   - If service is not running, attempts auto-start via local installation (`C:\Users\cubeb\AppData\Roaming\VoiceStudio\runtime\project\backend\main.py`).
   - Supports Indonesian synthesis (`language: "id"`) with native sample rate preservation.
   - Explicitly records `alignment_mode: "estimated"` if forced-alignment timestamps are derived, preventing misleading claims of word-accurate sync.

### 3.5 Benchmark Runner Integrity (`scripts/run_causal_benchmarks.py`)
1. **Explicit Execution Modes**:
   - `--mode fresh`: Generates brand new job IDs. Executes live with StepFun custom motion + VoiceStudio TTS + strict fallback.
   - `--mode resume`: Resumes an existing incomplete job ID.
   - `--mode verify-existing`: Read-only inspection of previous benchmark outputs.
2. **Provenance Recording**:
   - Produces comprehensive benchmark report logging: Job ID, Git SHA, provider model, actual renderer, code hash, audio hash, video hash, duration, render time, and QC results.

---

## 4. Verification Plan

1. **Unit & Adversarial Tests**:
   - Test AST CodeGuard with adversarial payloads: dynamic imports, obfuscated member expressions, sensitive globals, prototype pollution.
   - Test `render_custom_motion` environment scrubbing and Job Object binding.
   - Test fallback policy (`strict` vs. `allow_legacy`).
   - Test VoiceStudio timing metadata transparency.
2. **E2E Benchmark Run**:
   - Run Benchmark A ("Bagaimana API gateway mengalihkan traffic AI ketika model utama overload?") in `--mode fresh` with `custom-motion` and `strict` fallback policy.
   - Verify all generated artifacts exist on disk and validate against contracts.
   - Confirm output MP4 renders custom generated motion graphics.
