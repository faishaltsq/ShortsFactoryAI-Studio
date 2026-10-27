# JOB STATE MACHINE

Transitions are an explicit allow-list. Anything not listed raises `IllegalTransition`; there is
no "any → any" escape hatch, and no stage may write a state it does not own.

```
                        ┌──────────────────┐
                        │  IDEA_DISCOVERY  │  ResearchAgent
                        └────────┬─────────┘
                                 │
                        ┌────────v─────────┐
                        │  TOPIC_SELECTED  │  TopicSelectionAgent
                        └────────┬─────────┘
                                 │
                        ┌────────v─────────┐
                        │ RESEARCH_COMPLETE│  ResearchAgent
                        └────────┬─────────┘
                                 │
                        ┌────────v─────────┐
                        │ SCRIPT_GENERATED │  ScriptAgent
                        └────────┬─────────┘
                                 │
                        ┌────────v─────────┐
                        │ CREATIVE_REVIEW  │  CreativeDirectorAgent
                        └────────┬─────────┘
                        accept   │   revise (bounded, max 2)
                    ┌────────────┴────────────┐
                    │                         │
           ┌────────v─────────┐      back to SCRIPT_GENERATED
           │ STORYBOARD_READY │  StoryboardAgent
           └────────┬─────────┘
                    │
           ┌────────v─────────┐
           │  ASSETS_READY    │  AssetAgent
           └────────┬─────────┘
                    │
           ┌────────v─────────┐
           │   AUDIO_READY    │  AudioAgent
           └────────┬─────────┘
                    │
           ┌────────v─────────┐
           │    RENDERING     │  RenderAgent (Animation + Editor)
           └────────┬─────────┘
                    │
           ┌────────v─────────┐
           │  TECHNICAL_QC    │  RenderAgent
           └────────┬─────────┘
                    │
           ┌────────v─────────┐
           │  EDITORIAL_QC    │  QualityAgent
           └────────┬─────────┘
                    │
           ┌────────v─────────┐
           │ READY_FOR_       │  (operator gate)
           │ APPROVAL         │
           └────────┬─────────┘
              ┌─────┴──────┐
        approve│            │reject (+reason)
              v            v
        ┌──────────┐  ┌──────────┐
        │ APPROVED │  │ REJECTED │
        └────┬─────┘  └──────────┘
             │
      ┌──────v────────┐
      │ PRIVATE_UPLOAD│  PublisherAgent
      └──────┬────────┘
             │
      ┌──────v────────┐
      │  SCHEDULED    │  (optional)
      └──────┬────────┘
             │ explicit --confirm --by
      ┌──────v────────┐
      │   PUBLISHED   │
      └───────────────┘
```

## Required media path

`render_video: true` appends six deterministic stages. The direct
`STORYBOARD_READY → RENDERING` shortcut is not allowed: every rendered job walks
`STORYBOARD_READY → ASSETS_READY → AUDIO_READY → RENDERING → TECHNICAL_QC → EDITORIAL_QC →
READY_FOR_APPROVAL`.

| # | Stage | Agent | Produces | Question it answers |
| --- | --- | --- | --- | --- |
| 1 | `ASSETS_READY` | `AssetAgent` | `assets.json` | Which rig, palette and artwork bytes are in play, by hash? |
| 2 | `AUDIO_READY` | `AudioAgent` | `audio.json`, `narration.wav` | How long is the narration, measured, and where are the words? |
| 3 | `RENDERING` | stage name `RenderAgent`, events attributed to `EditorAgent` | `output.mp4`, `render.json` | Does a file exist that ffprobe can describe? |
| 4 | `TECHNICAL_QC` | `QualityAgent` | `technical-qc.json` | Is every FR-7.1 property true of *this* file? |
| 5 | `EDITORIAL_QC` | `QualityAgent` | `qc.json`, `qa-contact-sheet.jpg` | Is it any good, and did a vision provider look at it? |
| 6 | `READY_FOR_APPROVAL` | `DirectorAgent` | `readiness.json` | Do the bindings still hold, and may an operator decide? |

`QualityAgent` owns both QC stages because both answer questions about the same file, but they are
separate stages with separate artifacts. Splitting them is what stops `qc.json` from having to
invent a visual status before any vision provider has been consulted.

`DirectorAgent` owns `READY_FOR_APPROVAL` and does not merely observe it. `TECHNICAL_QC →
READY_FOR_APPROVAL` is not in the allow-list, so an editorial stage declaring `READY_FOR_APPROVAL`
could never validate; and a stage left at `EDITORIAL_QC` never advances the job there at all,
because `run_stages` transitions only to `stage.state`. The DirectorAgent stage recomputes the
input hash from `render.json`, `audio.json` and `storyboard.json` and refuses to certify when
`technical-qc.json` recorded a different hash — the stage that scored the job does not get to
certify its own score.

The default `id-ID-ArdiNeural` voice remains an explicit request and fails when that exact voice is
not installed. A mock job uses the installed Windows default only when its payload explicitly sets
`voice: system-default`; the offline adapter never substitutes another voice.

## Repair is zero, and why

`qc.json.repairs` is append-only and records decisions, not attempts. This build emits exactly one
shape:

```jsonc
{ "attempt": 0, "target": "static_ratio", "reason": "0.91 > 0.45",
  "artifacts_invalidated": [], "action": "blocked" }
```

`artifacts_invalidated: []` is the truthful statement that nothing was rewritten. Automatic repair
is zero because every failure these gates can detect is deterministic: re-rendering a black,
frozen, silent or 720p file produces the same file, and re-authoring the script cannot change what
the renderer already drew. `TECHNICAL_QC → RENDERING` exists in the allow-list and is deliberately
unused by the pipeline; a test asserts the chain does not take it. Repair becomes mandatory only
when a model-authored artifact is provably the cause — that is, when `creative` fails while
`technical` passes — and even then the decision must be recorded with the artifacts it invalidated.


## Terminal and side states

| State | Entered by | Exits |
| --- | --- | --- |
| `FAILED` | an unrecoverable error | never automatically; operator may retry a new job |
| `BLOCKED` | retry cap, QA gate, budget, capability mismatch, unchanged revision | operator action, into any pre-approval stage, or `CANCELLED` |
| `CANCELLED` | operator cancel, honoured at a stage boundary | never |
| `PAUSED` | operator pause from a running stage | resume into the stage it left |

`BLOCKED` cannot return to `APPROVED`, and `BLOCKED → READY_FOR_APPROVAL` — which is legal, so an
operator who fixes a provider does not need a brand-new job — does not itself authorise approval.
The store additionally requires the gate's `approval.json`, so reaching the gate state and passing
the gate are different things. See invariant 6.

`PAUSED` is now reachable, from any pre-gate stage where a pause is meaningful
(`IDEA_DISCOVERY` through `EDITORIAL_QC`). It is deliberately **not** reachable from
`READY_FOR_APPROVAL` or `APPROVED` — pausing a job the operator is deciding would hide it from the
queue with no owner — and not from any terminal state. A paused job resumes into the stage it left.

`PAUSED` is also deliberately **not schedulable** (`packages/core/orchestration/scheduler.py`): a
paused job is paused on purpose, and auto-resuming it would make the pause meaningless.

`tests/test_contracts_state.py::test_paused_is_reachable_only_from_a_running_stage` asserts the
inbound set, and `tests/test_scheduler.py::test_paused_is_not_schedulable` asserts the exclusion.

## Invariants

1. `FAILED` is never reached by "we tried enough times". Retry exhaustion → `BLOCKED`, because
   that needs a decision, not a louder error.
2. `CANCELLED` is cooperative: a stage in flight completes or times out, then the job stops. It is
   never a lie about a stage that is still writing files.
3. `READY_FOR_APPROVAL` requires all of: `technical-qc.json` validates and `passed` is true;
   `qc.json` validates, `technical.passed` and `creative.passed` are true, and
   `visual.status != "failed"`; `sha256(output.mp4)` recomputed from disk equals
   `render.json.sha256`; and `readiness.json` is `ready` with an `inputs_sha256` that the gate
   recomputes to the same value. A `skipped_no_vision_provider` is allowed and visible; a missing
   artifact is not. The approval gate recomputes every one of these rather than reading a flag.
4. `APPROVED` never implies publishable. `publishable = (provider_mode == "live") and
   approval.checks.publishable`.
5. Any transition writes an `event` row in the same transaction as the state update. A state
   change without an event is a bug, and a test asserts the two counts move together.
6. **`APPROVED` requires both a legal edge and the gate's recorded evidence.** Two independent
   mechanisms, because neither alone is sufficient:

   **(a) The allow-list limits the edge.** `READY_FOR_APPROVAL` is the only state that lists
   `APPROVED` as an exit. `BLOCKED` does not, so a resume path, a scheduler, or a maintenance
   script cannot approve a job by moving it there; the transition raises `IllegalTransition` and
   writes no event. `PRIVATE_UPLOAD`'s only inbound edge is `APPROVED`, so no path reaches an
   upload-capable state without passing through the gate state.

   **(b) The store requires the artifact.** A legal edge is not evidence: `BLOCKED →
   READY_FOR_APPROVAL` is deliberately kept legal (an operator who fixes a provider should not
   need a brand-new job), and that edge does **not** run `_approval_checks`. So
   `JobStore.transition(job_id, APPROVED)` additionally requires an `approval.json` for the job
   with `decision == "approved"`, a non-empty `operator`, `checks.publishable is True`, and a
   `render_sha256` equal to the current `render.json.sha256`. Without it the transition raises
   `ApprovalEvidenceMissing` (a subclass of `IllegalTransition`) and writes no event. A stale
   approval — one whose recorded digest no longer matches `render.json` — is refused for the same
   reason: it is evidence about bytes that no longer exist.

   The store does not decide *whether* the gate should pass; that is `_approval_checks` in
   `apps/api/jobs.py`, which reads artifacts and recomputes hashes. The store only refuses to
   record the outcome without the gate's evidence. `ApprovalArtifact.render_sha256` and the full
   refusal table are in `DATA_CONTRACTS.md` §11.

   Enforced by `tests/test_contracts_state.py::test_the_only_state_that_can_reach_approved_is_ready_for_approval`
   (computed from the allow-list, not hardcoded, so a future edit cannot silently reopen it),
   `::test_approved_cannot_be_reentered_without_a_fresh_gate`,
   `tests/test_jobstore.py::test_no_transition_to_approved_from_blocked`,
   `::test_an_approved_job_cannot_reenter_approved_after_blocking`,
   `::test_approved_without_an_approval_artifact_is_refused`,
   `::test_a_rejected_approval_artifact_cannot_authorise_approved`,
   `::test_an_approval_for_a_different_render_cannot_authorise_approved`,
   `::test_an_approval_recording_no_render_hash_is_refused`,
   `::test_a_matching_approval_artifact_permits_approved`,
   `::test_the_gate_route_is_the_only_door_after_a_block`,
   `tests/test_api_approval_gate.py::test_a_blocked_job_cannot_be_resumed_into_approved`,
   `::test_resuming_to_the_gate_state_does_not_authorise_approval`,
   `::test_the_approve_route_records_the_render_it_approved`, and
   `::test_a_stale_approval_blocks_after_a_re_render`.
