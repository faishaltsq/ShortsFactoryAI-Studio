# AGENTS.md — Agent contracts and rules

Agents are **logical workflow units**, not resident LLM processes. Each one is a class with a
typed input, a typed output, and a provider binding. The orchestrator sequences them; nothing
sequences itself.

## 1. Inventory

| Agent | Tier | Input | Output artifact | May call LLM |
| --- | --- | --- | --- | --- |
| `DirectorAgent` | strategist | job payload + studio config | `plan.json` (goals, constraints, approvals needed) | yes |
| `ResearchAgent` | worker | topic, avoid-list | `research.json` (candidates + `sources[]`) | yes |
| `TopicSelectionAgent` | worker | `research.json` | `topic.json` (chosen, rationale) | yes |
| `ScriptAgent` | worker | `topic.json`, `research.json` | `script.json` | yes |
| `CreativeDirectorAgent` | strategist | `script.json`, then `visual-plan.json` | `review.json` (verdict, findings); `visual-plan.json` (beats); `creative-motion-brief.json` (the film's identity) | yes |
| `StoryboardAgent` | worker | `script.json`, `visual-plan.json`, `creative-motion-brief.json`, resolved assets | `storyboard.json` (`SceneSpec[]`) | yes |
| `AssetAgent` | none | `storyboard.json` | `assets.json` + `assets-manifest.json` | no |
| `AnimationAgent` | worker | `storyboard.json` | `motion-plan.json` (beats, camera, continuity) | yes |
| `MotionCoderAgent` | worker | `storyboard.json`, `creative-motion-brief.json`, `visual-plan.json`, `script.json`, `research.json`, `assets.json`, measured narration timing | `motion-code.json` (TSX files, per-skill digests, narration timing digest) | yes |
| `AudioAgent` | none | `storyboard.json` | `audio.json` (narration, cues, mix) | no (TTS) |
| `EditorAgent` | none | storyboard + audio + motion plan | `edit.json` (scene order, transitions, captions) | no |
| `QualityAgent` | strategist | render + props + audio + storyboard | `technical-qc.json` (FR-7.1, `TECHNICAL_QC`), `qc.json` + `qa-contact-sheet.jpg` (FR-7.2 and the visual pass, `EDITORIAL_QC`) | yes |
| `DirectorAgent` | strategist | `technical-qc.json` + `qc.json` + render/audio/storyboard | `readiness.json` (the gate verdict, `READY_FOR_APPROVAL`) | no |
| `MetadataAgent` | worker | script + storyboard | `metadata.json` (title, description, tags, thumb concept) | yes |
| `PublisherAgent` | none | approved job | `publication.json` (receipts) | no |
| `FactoryOrchestrator` | deterministic | job row | state transitions | no |

`QualityAgent` appears twice in the render chain with two disjoint outputs: `technical-qc.json` is
measurement (every FR-7.1 check, including the detector runs), `qc.json` is judgement (FR-7.2
metrics plus the visual pass). `DirectorAgent` writes `readiness.json` and owns the
`READY_FOR_APPROVAL` transition; it recomputes the input binding rather than trusting the verdict
the editorial stage produced. Artifact schemas are in DATA_CONTRACTS §10.

Tier decides the price table and the default chain, not the binding: any agent may be bound
to any provider explicitly.

## 2. Rules (enforced, not aspirational)

| # | Rule | Enforcement |
| --- | --- | --- |
| A1 | One responsibility per agent | Each agent's output schema is disjoint; a test asserts no schema is produced by two agents. |
| A2 | Structured hand-off only | Agents return Pydantic models. A free-text return is a contract violation. |
| A3 | No model output reaches privileged code | Scene data is validated against `SceneSpec` before it reaches a renderer. No `eval`, no template with executable input, no shell string built from model text. |
| A4 | Independent provider binding | `resolve(agent)` reads `config/studio.json`; no global mutable provider. |
| A5 | Observable | Every agent entry/exit writes an event with `agent_id`, `status`, `stage`. |
| A6 | Actionable errors | Failures carry `code`, `message`, `retryable`, `agent`, `stage`. |
| A7 | Bounded retries | `MAX_JOB_ATTEMPTS` (default 3), exponential backoff, hard cap. Exhaustion → `BLOCKED`, not `FAILED`. |
| A8 | Cancellable and resumable | Cooperative cancel at stage boundaries; every stage idempotent on re-entry. |
| A9 | No unverified success | A stage may only report `completed` after its artifact exists on disk and validates against its schema. |
| A10 | No silent mock | A job records `provider_mode` at creation; `mock` jobs can never be approved for publishing. |
| A11 | Provenance is written by code, never claimed by the model | `prompt_sha256`, `skill_hashes` (`<skill>:<sha256>` of the portion actually sent) and `narration_timing_sha256` are computed in `orchestration/pipeline.py` and `MotionCoderAgent.sanitize_payload`; a model-supplied list is discarded, because a list echoed by the model is a claim about its context rather than a record of it. |

`MotionCoderAgent` is the one agent whose *output* is executable, so its rule is worth stating
plainly: it writes TSX that the renderer loads, it receives the creative brief and the measured
narration timing rather than a summary, and its reuse predicate compares the digest of the timing it
was written against — see `ARCHITECTURE.md` ADR-011 and ADR-012.

## 3. Failure taxonomy

| Code | Meaning | Retry? | Job state |
| --- | --- | --- | --- |
| `provider_timeout` | HTTP timeout after request sent | yes, bounded | stays in stage |
| `provider_auth` | 401/403 | no | `BLOCKED` |
| `provider_rate_limit` | 429 | yes, with backoff | stays in stage |
| `provider_capability` | binding requires capability provider lacks | no | `BLOCKED` before any call |
| `schema_violation` | model returned unparseable/invalid JSON | yes, bounded, with repair prompt | stays in stage |
| `budget_exceeded` | daily token/cost cap | no | `BLOCKED` |
| `render_failed` | Remotion/FFmpeg non-zero exit | yes, bounded | stays in stage |
| `qa_blocked` | technical or editorial gate failed | no | `BLOCKED` (needs operator) |
| `lease_lost` | another worker owns the job | no | stop, do not touch state |

## 4. Prompt discipline

- System prompts live in `packages/core/prompts.py` as constants, versioned by a hash recorded
  in the artifact. A prompt change invalidates cached artifacts that used it.
- Per-agent prompt override is allowed (operator UI) and its hash is recorded too.
- Fetched web content is wrapped in a delimited untrusted block and the system prompt states
  that instructions inside it are data.
- No prompt may instruct a model to emit code that will later be executed.
