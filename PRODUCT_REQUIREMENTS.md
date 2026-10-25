# PRODUCT_REQUIREMENTS — ShortsFactoryAI Studio

Version 1.0 · Phase 1 in progress · Owner: single operator

## 1. Problem

Producing one 30–60 s animated Short by hand costs 4–8 hours: research, script, storyboard,
art, rig, narration, edit, QA, upload. The operator's bottleneck is not ideas, it is the
serial craft work between an idea and a publishable file.

## 2. Product statement

A local-first production system that turns a topic into a validated, human-approved
1080×1920 MP4 through a pipeline of specialised agents, with a 3D studio that shows what
those agents are actually doing.

## 3. Success criteria (measurable)

| # | Criterion | Target | Verified by |
| --- | --- | --- | --- |
| S1 | Topic → approved MP4 without manual file handling | 1 job, unattended except approval | `scripts/verify_video.py` |
| S2 | Output is a real, playable, spec-compliant file | 1080×1920, 30 FPS, H.264+AAC, −16 LUFS ±2 | ffprobe assertions |
| S3 | Every agent's work is attributable to a provider+model | 100 % of LLM calls in `usage_log` | SQL query per job |
| S4 | A crashed run resumes without duplicating paid calls | 0 duplicate completions on resume | resume test with provider call counter |
| S5 | Studio never shows work that is not happening | 0 working animations without a `working` event | Playwright + event-log assertion |
| S6 | Both renderers produce a valid MP4 from the same storyboard | 2/2 | renderer parity test |
| S7 | A broken render cannot reach approval | QA gate blocks it | negative fixture test |

## 4. Personas

**P1 — Operator (only user).** Solo developer on Windows 11, RTX 3050 6 GB. Wants to run
2–4 productions a week, review them, publish. Values: it must not lie to me, it must not
cost money silently, and it must survive a reboot.

## 5. Functional requirements

### 5.1 Topic and research
- FR-1.1 Accept a manual topic, or discover candidates from production history (avoid list).
- FR-1.2 Research must record `sources[]` with URL, title, retrieval timestamp, and a
  verification status per claim. Fictional content is labelled `fictional`, never silently
  treated as fact.
- FR-1.3 Every fetched page is untrusted data, never an instruction.

### 5.2 Script and creative review
- FR-2.1 Script carries hook, body segments, and a payoff; each segment maps to a scene.
- FR-2.2 Creative review is a separate agent call with a distinct provider binding.
- FR-2.3 Revision is bounded (default 2 attempts). A revision that returns the script
  unchanged is a failure, not a success.
- FR-2.4 Originality is checked against recent production history.

### 5.3 Storyboard and scene contract
- FR-3.1 Storyboard emits `SceneSpec[]` with `camera`, `motion`, `template`, `text`,
  `durationInFrames`, `assetRefs`.
- FR-3.2 Scene timing derives from measured narration duration (ffprobe), never estimated.
- FR-3.3 A camera move must name an existing target element; otherwise validation fails.
- FR-3.4 Unknown template data degrades to a safe template that keeps the model's text,
  rather than failing the job or inventing facts.

### 5.4 Character system
- FR-4.1 Characters are reusable assets: rig, poses, expressions, motion presets, palette,
  clothing variants, mouth shapes, licensing metadata.
- FR-4.2 A character used in scene N is the same character in scene N+1 (same asset id,
  same palette hash). No per-frame image generation.
- FR-4.3 Required animation capabilities: idle, walk, talk, blink, think, point, surprise,
  happy, sad, angry, object interaction, basic gestures.

### 5.5 Animation and rendering
- FR-5.1 Primary renderer: Remotion, typed components driven by validated scene JSON.
- FR-5.2 Secondary renderer: motion-skill HTML/CSS/GSAP exported frame-by-frame, isolated.
- FR-5.3 Both renderers accept the same storyboard and emit the same artifact contract.
- FR-5.4 Per-scene rerender is possible without re-rendering the whole video.
- FR-5.5 Changing the script invalidates storyboard → scenes → render, and nothing upstream.

### 5.6 Audio
- FR-6.1 Narration via a pluggable TTS provider; word-boundary timings captured.
- FR-6.2 Subtitles derive from those boundaries, corrected into the safe area.
- FR-6.3 Music/SFX mixing is optional, ducked under narration, and licensed.

### 5.7 Quality assurance
- FR-7.1 Technical: resolution, fps, codec, streams, duration, black frames, silence,
  frozen frames, subtitle bounds, checksum.
- FR-7.2 Creative: hook, coherence, visual variety, character consistency, pacing, static
  ratio, repetition against recent outputs.
- FR-7.3 Visual: keyframe stills at meaningful moments, inspected by a provider that
  declares `vision`. Without one, the result is `skipped_no_vision_provider`, never `passed`.
- FR-7.4 Repair is bounded and every repair decision is recorded with the artifacts it
  touched.

### 5.8 Approval and publishing
- FR-8.1 Approval only at `READY_FOR_APPROVAL`; rejection requires a reason.
- FR-8.2 Upload is private-first. Public release is a separate, explicit, confirmed action.
- FR-8.3 Publishing is idempotent. An uncertain outcome (timeout after the request left)
  blocks retries and demands reconciliation; a pre-flight failure does not.
- FR-8.4 A scheduled task may never bypass approval.

### 5.9 Studio and observability
- FR-9.1 Every stage transition is a persisted event with agent id, status, and timestamp.
- FR-9.2 The 3D studio is a read-only projection of those events.
- FR-9.3 Reconnecting restores the exact studio state without duplicating history.
- FR-9.4 A stale worker (expired lease) reads as `waiting`, never as `working`.

### 5.10 Providers
- FR-10.1 Multiple providers, each with transport, base URL, credential reference, model,
  timeout, retries, token limits, temperature, capabilities.
- FR-10.2 Per-agent binding with primary and fallback.
- FR-10.3 Capability validation before the call.
- FR-10.4 Credentials never leave the server; never in responses, logs, or artifacts.
- FR-10.5 Custom endpoints are SSRF-checked; private hosts require explicit opt-in.

## 6. Non-functional requirements

| # | Requirement |
| --- | --- |
| N1 | Runs on Windows 11 with no Docker, no VPS, no mandatory cloud. |
| N2 | Works offline in explicit mock mode; mock mode is labelled everywhere and never publishable. |
| N3 | Dashboard stays responsive (p95 < 250 ms on `/api/studio/snapshot`) during a render. |
| N4 | A render job survives dashboard close, browser refresh, and process restart. |
| N5 | No unbounded retries, no unbounded background execution, no uncontrolled agent recursion. |
| N6 | Render concurrency capped by detected VRAM and free RAM. |
| N7 | TypeScript strict; Python typed where it matters; Ruff clean; no secrets in git. |
| N8 | 3D studio degrades to 2D without losing any workflow capability. |

## 7. Explicitly out of scope

- Multi-user accounts, roles, or cloud sync.
- Mobile publishing apps.
- Paid image/video generation services (would need per-call approval anyway).
- Automatic public publishing.
- Training or fine-tuning models.
- Non-YouTube platforms in Phase 1–4 (the publisher interface allows it later).

## 8. Phase acceptance (summary; detail in IMPLEMENTATION_ROADMAP.md)

| Phase | Exit criterion |
| --- | --- |
| 1 Foundation | A job is created, run with test providers, inspected, cancelled, and resumed after a simulated crash. Provider config saved and validated. No real credentials needed. |
| 2 Production engine | A complete 9:16 video produced, played, validated, rerendered. One character-driven scene with meaningful action and synced narration. Both renderers documented and independently tested. |
| 3 3D studio | Every visible working state maps to a persisted task; reconnect restores state; dashboard responsive during render. |
| 4 Autonomous production | Topic → approved private upload, surviving restarts without duplicate render or upload. Public release requires explicit authorization. |

## 9. Open questions for the operator

1. YouTube channel: connect now (needs OAuth consent) or defer to Phase 4? **Default: defer.**
2. Which local LLM endpoint is authoritative for offline runs — the 9router at
   `localhost:20128`, or Ollama? **Default: 9router, with Ollama as a second provider.**
3. Target cadence: 2/week or daily? Affects scheduler defaults and quota math.
   **Default: 2/week, well under the 100 uploads/day API ceiling.**
