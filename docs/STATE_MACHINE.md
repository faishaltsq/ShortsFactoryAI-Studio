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

## Terminal and side states

| State | Entered by | Exits |
| --- | --- | --- |
| `FAILED` | an unrecoverable error | never automatically; operator may retry a new job |
| `BLOCKED` | retry cap, QA gate, budget, capability mismatch, unchanged revision | operator action |
| `CANCELLED` | operator cancel, honoured at a stage boundary | never |
| `PAUSED` | operator pause (Phase 4) | resume |

## Invariants

1. `FAILED` is never reached by "we tried enough times". Retry exhaustion → `BLOCKED`, because
   that needs a decision, not a louder error.
2. `CANCELLED` is cooperative: a stage in flight completes or times out, then the job stops. It is
   never a lie about a stage that is still writing files.
3. `READY_FOR_APPROVAL` requires: render artifact valid, technical QC passed, editorial QC passed,
   visual QC not `failed` (a `skipped_no_vision_provider` is allowed and visible).
4. `APPROVED` never implies publishable. `publishable = (provider_mode == "live") and
   approval.checks.publishable`.
5. Any transition writes an `event` row in the same transaction as the state update. A state
   change without an event is a bug, and a test asserts the two counts move together.
