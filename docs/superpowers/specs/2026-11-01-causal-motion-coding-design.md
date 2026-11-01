# Causal Visual Storytelling: StepFun Motion Coding, Remotion Skills, and VoiceStudio Integration

**Date:** 2026-11-01  
**Status:** Approved  
**Target Milestone:** Causal Visual Storytelling & AI-Directed Remotion Pipeline  

---

## 1. Executive Summary & Intent

ShortsFactoryAI Studio produces 1080x1920 vertical video shorts for educational and informative topics. While previous iterations introduced object diversity, scenes remained largely static collections of icons with rigid `top title -> central icon -> bottom subtitle` framing.

This specification upgrades the engine to **Causal Visual Storytelling**:
- Every scene demonstrates an observable physical or diagrammatic cause-and-effect process.
- Scenes are governed by validated 4-part state cycles: `initial_state`, `causal_action`, `resulting_state`, and `transition`.
- StepFun (`step-5-preview`) acts as `MotionDirector` / `MotionCoder`, authoring tailored Remotion compositions with official Remotion AI skills (`.agents/skills/remotion-*`).
- Untrusted AI-generated code runs in an isolated workspace with strict AST import and token validation (`CodeGuard`).
- VoiceStudio (`http://127.0.0.1:3900`) is integrated locally with CUDA acceleration for natural Indonesian narration and accurate timing alignment.
- Quality Control extracts and compares Beginning, Middle, and End (B/M/E) keyframes to catch and repair static scenes before human review.
- The 3D virtual office, all character systems, job leases, and existing safety rails remain completely preserved.

---

## 2. System Architecture & Component Mapping

```
                                      [Topic / Research]
                                               │
                                               ▼
                                      [ScriptAgent (Gemini)]
                                               │
                                               ▼
                           [CreativeDirectorAgent: Film-Level Brief]
                                 (creative-motion-brief.json)
                                               │
                                               ▼
                          [StoryboardAgent: Causal Scene States]
                                    (storyboard.json)
                                               │
                        ┌──────────────────────┴──────────────────────┐
                        ▼                                             ▼
             [AudioAgent: VoiceStudio]                    [MotionSkillLoader]
             (http://127.0.0.1:3900)                     (.agents/skills/remotion-*)
                        │                                             │
                        ▼                                             ▼
                 (narration.wav)                        [MotionCoder: StepFun]
                  (audio.json)                                        │
                        │                                             ▼
                        │                               [CodeGuard: AST Sandbox]
                        │                               (import/call whitelist)
                        │                                             │
                        └──────────────────────┬──────────────────────┘
                                               ▼
                                 [Remotion Rendering Engine]
                                 (custom-motion / fallback)
                                               │
                                               ▼
                                        (output.mp4)
                                               │
                                               ▼
                                  [QC: B/M/E Frame Delta & Gate]
                                  (technical-qc.json, qc.json)
                                               │
                                               ▼
                                     [Human Review Gate]
```

### Layering Constraints
- `packages/core/contracts`: Defines immutable Pydantic schemas. Never imports from outer layers.
- `packages/core/providers`: Hosts `OpenAICompatProvider` and `StepFun` configurations. Resolves credentials strictly at runtime.
- `packages/core/media`: Hosts `VoiceStudioAdapter`, `RemotionWorker`, `CodeGuard`, and `QC Evaluators`.
- `packages/core/agents`: Houses `CreativeDirectorAgent`, `StoryboardAgent`, `AnimationAgent`, `MotionCoderAgent`, and `SkillLoader`.
- `packages/video`: Houses shared Remotion primitives, types, and compositions.

---

## 3. Detailed Milestone Specifications

### Milestone 1 — Foundation & Provider Integration

#### 1.1 StepFun Provider Configuration
- Supported via `OpenAICompatProvider` pointing to local `9router` (`http://127.0.0.1:20128/v1`) using model `om/step-5-preview` or direct operator endpoint `https://api.stepfun.com/v1`.
- Bound in `config/studio.json` with credential reference `{"env": "NINEROUTER_KEY"}` or DPAPI sealed key.
- Capabilities declared: `chat`, `json_schema`, `vision`.
- Request timeouts set to 90s with max 2 retries and exponential backoff.

#### 1.2 Remotion Skills Integration (`MotionSkillLoader`)
- Reads installed skills from `.agents/skills/`:
  - `remotion-best-practices`
  - `remotion-markup`
  - `remotion-render`
  - `remotion-captions`
- Selects and extracts relevant rules (spring physics, layout bounds, typography timing, safe zones).
- Computes SHA-256 content hashes of loaded skills, recording them in provenance metadata.
- Applies token-budget trimming to keep skill context dense and relevant without bloating prompt limits.

---

### Milestone 2 — MotionDirector & Causal Scene Contracts

#### 2.1 Film-Level Creative Brief (`creative-motion-brief.json`)
Produced by `CreativeDirectorAgent` before individual scenes:
- `visual_thesis`: Overarching metaphor and explanatory progression.
- `art_direction`: Bright editorial palette, typography hierarchy, accent colors.
- `pacing_strategy`: Hook build -> dynamic process -> comparative payoff.
- `reusable_motifs`: Anchor symbols and continuity cues across scene transitions.

#### 2.2 Causal Scene States (`storyboard.json`)
Every scene must declare:
- `initial_state`: Visual baseline at scene entry (e.g., satellite transmitting uncorrected pulse).
- `causal_action`: Visible transformation occurring at `atFrame` (e.g., gravitational time dilation accelerates frequency, drift increases).
- `resulting_state`: Observable outcome before cut (e.g., 11 km positional offset highlighted with warning banner).
- `transition`: Visual continuity connecting to the next beat.

#### 2.3 Adaptive Layout Engine
Replaces the static `x=0.5, y=0.46, size=0.62` layout lock:
- Dynamic layouts: `SplitComparison`, `LeftRailProcess`, `RadialNetwork`, `LayerStack`, `FullBleedFocus`.
- Safe margin validation: Top 210px–360px reserved for title; bottom 420px reserved for TikTok captions and UI controls.
- Automatic collision avoidance between labels, leader lines, and subtitles.

---

### Milestone 3 — Custom Remotion Coding & Safe Execution Sandbox

#### 3.1 Workspace Isolation
- Generated TSX modules written strictly to `data/jobs/<job-id>/code/`.
- Isolated from repository source code.
- Ephemeral render workspace mounted to Remotion CLI via clean `--props` and entry point.

#### 3.2 `CodeGuard` Static AST Sandbox
Before compiling or executing generated TypeScript/JSX:
1. Parse AST using Python/TypeScript AST visitor.
2. Verify imports against strict allowlist:
   - Allowed: `react`, `remotion`, `packages/video/src/*`.
   - Forbidden: `fs`, `path`, `child_process`, `os`, `net`, `http`, `process`, `eval`, `Function`, `window.fetch`, `localStorage`.
3. Reject external URLs, non-relative file reads, or shell invocation strings.
4. If validation fails, log diagnostic reason and fall back automatically to `legacy-template` declarative renderer.

#### 3.3 Dual Rendering Strategy
- `custom-motion`: Compiles and executes validated generated TSX compositions.
- `legacy-template`: Deterministic fallback maintaining existing reliable video export.

---

### Milestone 4 — VoiceStudio Local Integration

#### 4.1 Connection & Discovery
- Endpoint: `http://127.0.0.1:3900`
- Device: NVIDIA GeForce RTX 3050 6GB Laptop GPU (`cuda`).
- Active discovery via `GET /health` and `GET /v1/models`.
- Primary engine: `omnivoice` / `tts-1` with fallback to `kittentts`.

#### 4.2 Synthesis & Audio Alignment
- Endpoint: `POST /v1/audio/speech`
- Language: Indonesian (`id` / `id-ID`).
- Returns raw WAV audio; sample rate preserved (24 kHz or 48 kHz, avoiding downsampling).
- Accurate word timestamps extracted and mapped to Remotion `TiktokCaptions`.
- Scene durations adjusted dynamically to match spoken audio lengths (+/- 120ms tolerance).

---

### Milestone 5 — Automated Quality Control & Visual Iteration

#### 5.1 Beginning / Middle / End (B/M/E) Keyframe Analysis
- In addition to contact sheets, extract three representative stills per scene:
  - Beginning: `startFrame + 6` (after entrance settles)
  - Middle: `startFrame + (duration // 2)` (during peak causal action)
  - End: `startFrame + duration - 6` (at final resulting state)
- Compute structural similarity / pixel delta between B, M, and E frames.
- Flag scenes where `delta(Beginning, Middle) < threshold` or `delta(Middle, End) < threshold` as frozen or static.

#### 5.2 Bounded Revision Loop
- Up to 2 automated repair attempts per failing scene.
- Revision prompt injects exact frame timestamps and missing visual actions.
- Unaffected scenes are preserved via render cache.

---

### Milestone 6 — Autonomous 3-Domain Benchmark Proofs

1. **Benchmark A (Tech Explainer)**: How an API gateway routes requests between AI models (incoming request -> gateway evaluation -> primary model saturation -> fallback redirect -> success response).
2. **Benchmark B (Science Explainer)**: GPS satellite relativity clock corrections (orbital velocity slowdown vs. gravitational speedup -> 38 µs delta -> 11 km drift -> active clock sync).
3. **Benchmark C (Everyday Informative)**: An observable process from everyday life (e.g., instant noodle flash-frying and dehydration science).
- Success criterion: Each video clearly communicates its core process visually even when audio and subtitles are muted.

---

## 4. Verification & Testing Strategy

- `uv run ruff check .`: 0 findings.
- `uv run pytest tests/test_agent_contracts.py tests/test_qc_evaluate.py tests/test_pipeline.py`: 100% green.
- `npm --prefix packages/video run typecheck`: clean.
- `scripts/check.ps1 -Quick`: all passing.
- Real MP4 generation for all 3 benchmark topics with B/M/E frame evidence.

---

## 5. Security & Non-Negotiables Check
- Zero credentials in output files or logs.
- Generated code strictly quarantined in job workspaces and guarded by `CodeGuard`.
- 3D agent virtual office untouched and running.
- No deletions or regressions of character/office systems.
