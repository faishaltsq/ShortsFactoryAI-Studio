# DATA_CONTRACTS — the boundary between agents, renderers, and the UI

Every artifact is a JSON file in `data/jobs/<job_id>/`, validated by a Pydantic model **and**
by a generated JSON Schema stored in `config/schemas/`. A schema file that does not match its
model fails the build.

## 0. Rules

1. **Additive only within a version.** New optional fields are fine; renames and removals bump
   `schema_version` and require a migration note in `docs/ADR/`.
2. **Every artifact carries `schema_version` and `created_at`.**
3. **Writes are atomic**: write `*.tmp` in the same directory, `fsync`, `os.replace`.
4. **A completion marker is written last.** Multi-file stages write data first, marker last.
5. **Hashes are content hashes** of the canonical JSON (sorted keys, no whitespace), so a
   resume can prove an artifact is unchanged.

## 1. Job

```jsonc
{
  "schema_version": 1,
  "id": "b55babc8f8ea414f",
  "title": "…",
  "state": "READY_FOR_APPROVAL",
  "provider_mode": "live",            // "live" | "mock" — mock can never be published
  "payload": {
    "topic": "…", "genre": "…", "language": "id",
    "target_duration_s": 45, "style": "…", "voice": "id-ID-ArdiNeural",
    "audience": "…", "intensity": "…", "music": "…", "characters": ["maya"],
    "renderer": "remotion"            // "remotion" | "bang-motion"
  },
  "attempts": 0,
  "created_at": "…", "updated_at": "…"
}
```

## 2. Research

```jsonc
{
  "schema_version": 1,
  "topic": "…",
  "candidates": [{ "title": "…", "angle": "…", "score": 0.0 }],
  "sources": [{
    "url": "https://…", "title": "…", "retrieved_at": "…",
    "sha256": "…",            // hash of the fetched body, so a claim can be re-checked
    "status": "verified" | "unverified" | "unreachable"
  }],
  "claims": [{ "text": "…", "source_index": 0, "verdict": "supported" | "contradicted" | "unknown" }],
  "content_kind": "factual" | "fictional"    // fictional => sources may be empty, and the
                                             // script is labelled fictional everywhere
}
```

## 3. Script

```jsonc
{
  "schema_version": 1,
  "hook": "…",
  "segments": [{ "id": "s1", "text": "…", "purpose": "hook|build|turn|payoff" }],
  "cta": "…",
  "estimated_duration_s": 45,
  "content_kind": "factual" | "fictional",
  "prompt_hash": "…"
}
```

## 4. Review (creative director)

```jsonc
{
  "schema_version": 1,
  "verdict": "accept" | "revise",
  "scores": { "hook": 1, "coherence": 1, "pacing": 1, "originality": 1, "payoff": 1 },
  "findings": [{ "severity": "blocker|major|minor", "segment_id": "s1", "issue": "…", "fix": "…" }],
  "attempt": 0
}
```

A `revise` verdict is a decision, not a failure: the review evidence is committed and the chain
stops. It is never reused as a completed review — the stage's `done_when` requires `accept`.

## 4.1 Revision ledger — `revisions.json`

```jsonc
{
  "schema_version": 1,
  "attempts": [{
    "attempt": 1,
    "before_script": { "…": "ScriptArtifact before the revision" },
    "review": { "…": "the ReviewArtifact that requested it" },
    "candidate_script": null,          // null while phase is "prepared"
    "phase": "prepared" | "generated" | "applied" | "unchanged",
    "invalidated_artifacts": []        // downstream names removed when the revision is applied
  }]
}
```

Four rules make the ledger the authority on a revision:

1. **Reserved before the call.** `prepared` records the attempt number and the exact input script
   before any paid request, so a crash cannot invent a first attempt and cannot repeat one.
2. **The decision is durable before invalidation.** `generated` carries the candidate script and
   the list of downstream artifacts to remove. A crash after that commit finishes the same
   decision on resume; it never asks the model again.
3. **The marker is written last.** `applied` promotes the new `script.json` and removes the
   recorded downstream artifacts in one lease-fenced commit, `revisions.json` last.
4. **`unchanged` is a block, not a retry.** When the candidate's authored content hash equals the
   before script's, the revision blocks and preserves the original script and every downstream
   output. The contract refuses `unchanged` with a changed hash or a non-empty invalidation list.

The ceiling is `MAX_REVISIONS = 2`, counted from the ledger, so it survives a restart. Reaching it
blocks with the findings attached rather than looping.

## 5. Storyboard — `SceneSpec`

This is the single most important contract: it is what the model writes and what the renderer
consumes. The model never emits JSX, CSS, or HTML.

```jsonc
{
  "schema_version": 1,
  "fps": 30, "width": 1080, "height": 1920,
  "theme": "dusk|dawn|night|paper|…",
  "scenes": [{
    "sceneId": "sc1",
    "template": "IllustratedStory",       // one of the registered templates
    "segment": "s1",
    "startFrame": 0,
    "durationInFrames": 300,              // >= 30, <= 3000
    "assetRefs": ["character:maya", "bg:desert"],
    "text": [{ "id": "t1", "text": "…", "role": "title|body|caption", "atFrame": 0 }],
    "camera": {
      "shot": "wide|medium|close",
      "move": "static|push|pull|pan|tilt|orbit",
      "target": "t1",                      // required when move != static
      "amplitude": 0.15,
      "ease": "power2.out"
    },
    "motion": {
      "energy": 0.6,
      "continuity": "carry|cut|match",     // carry = keep world, cut = new world
      "beats": [{ "atFrame": 0, "kind": "enter|emphasis|exit", "subject": "t1" }]
    },
    "transition": { "kind": "cut|wipe|push|match", "frames": 12 },
    "data": { }                            // template-specific, validated per template
  }],
  "subtitles": [{ "startMs": 0, "endMs": 1200, "text": "…" }]
}
```

**Validation that matters:** `camera.target` must resolve to an element id present in the
scene. A non-static move without a target is rejected — this is how "unmotivated camera
movement" becomes a schema error instead of a taste debate.

## 6. Motion plan (AnimationAgent)

```jsonc
{
  "schema_version": 1,
  "renderer": "remotion" | "bang-motion",
  "style_brief": { "palette": ["#…"], "fonts": ["…"], "signature_move": "…" },
  "scenes": [{
    "sceneId": "sc1",
    "beats": [{ "atFrame": 0, "durationFrames": 20, "kind": "…", "subject": "…" }],
    "camera_path": [{ "atFrame": 0, "shot": "wide", "zoom": 1.0, "pan": 0 }],
    "continuity_from": null | "sc0"
  }],
  "anti_patterns_checked": ["static_slideshow", "generic_fade", "text_wall"]
}
```

### 6.1 Creative motion brief (CreativeDirectorAgent, `creative-motion-brief.json`)

The film's identity, decided by the director after the visual plan and before the storyboard. Every
field below defaults to empty, and an empty field means **the director did not decide** — the motion
coder is told which fields are undecided rather than handed an invented default that would read
downstream as a decision.

```jsonc
{
  "schema_version": 1,
  "narrative_thesis": "what the film argues",
  "visual_thesis": "what it looks like, and the metaphor it is built on",
  "visual_metaphor": "the organising image the film returns to",
  "art_direction": {
    "palette": "editorialLight" | "spaceDark" | "warmLifestyle" | "circuitDark" | "oceanFloor",
    "primary_accent": "#0055FF", "secondary_accent": "#FF4400", "background": "#F8FAFC",
    "typography_style": "boldSans" | "technicalMono" | "editorialSerif"
  },
  "subject_environment": "the world this subject lives in, and why that world",
  "palette_rationale": "why these colours, in terms of the subject",
  "typography_direction": "how type behaves as a design element",
  "camera_language": "framing and movement across the film",
  "motion_language": "what motion means here: cause, direction, scale, transformation",
  "narrative_arc": "hook → build → payoff", "scene_progression": "how the film advances",
  "transition_strategy": "the rule joining one shot to the next",
  "scene_transitions": ["cut", "wipe", "slideUp", "zoom"],
  "primary_visual_motifs": ["…"], "reusable_motifs": ["an object or treatment that survives a cut"],
  "pacing_strategy": "…", "motion_complexity_budget": "low" | "medium" | "high",
  "visual_climax": "the shot where the film peaks", "ending_payoff": "what the viewer is left with"
}
```

`art_direction.palette` governs the storyboard's `theme`. The keyword heuristic in
`StoryboardAgent.sanitize_payload` is a fallback for a job with no brief, not an override.

### 6.2 Motion code (MotionCoderAgent, `motion-code.json`)

```jsonc
{
  "schema_version": 1,
  "entry_component": "RootComposition",
  "files": { "RootComposition.tsx": "…", "Scene01.tsx": "…" },
  "dependencies": ["react", "remotion"],
  "skill_hashes": ["remotion-captions:<sha256 of the portion actually sent>"],
  "validated_by_codeguard": true,
  "issues": [],
  // Written by the pipeline, never by the model.
  "narration_timing_sha256": "<digest of audio.json scene boundaries and word timestamps>",
  "timing_source": "measured" | "estimated"
}
```

`narration_timing_sha256` is what makes the second pass honest. The stage's reuse predicate compares
it against the digest recomputed from the current `audio.json`, so motion code timed against a
narration that has since changed is regenerated rather than reused. An empty value means the code was
written before any measurement existed — the case the field is there to make visible. See
`ARCHITECTURE.md` ADR-011.

`skill_hashes` is code-written provenance (`<skill>:<sha256>`), not a model answer: the model's own
list is discarded, because a list echoed by the model is a claim about its context rather than a
record of it.

## 7. Assets

```jsonc
{
  "schema_version": 1,
  "characters": [{ "id": "maya", "rig_hash": "…", "palette_hash": "…", "poses": ["stand"], "expressions": ["neutral"] }],
  "backgrounds": [{ "id": "desert-dusk", "path": "…", "sha256": "…", "license": "…", "source": "…" }],
  "audio": [{ "id": "…", "kind": "music|sfx", "path": "…", "sha256": "…", "license": "…" }],
  "manifest_sha256": "…"
}
```

A licence field is mandatory for any non-generated asset. `"license": null` fails validation.

## 8. Audio

```jsonc
{
  "schema_version": 1,
  "narration": { "src": "narration.wav", "durationMs": 36600, "voice": "id-ID-ArdiNeural" },
  "scenes": [{ "sceneId": "sc1", "startMs": 0, "endMs": 4200 }],
  "subtitles": [{ "startMs": 0, "endMs": 1200, "text": "…" }],
  "mix": { "music": null, "music_gain_db": null, "ducking": false, "loudness_lufs": -16.01 }
}
```

`narration.src` is a real PCM WAV produced by the configured offline voice (Windows SAPI through
`scripts/sapi_tts.ps1`). `system-default` is an explicit selector; every other voice string must
exactly match an installed SAPI voice or synthesis fails.

### 8.1 Speech extent is measured, not inferred

SAPI's `SpeakProgress` offsets stop before the trailing silence the synthesizer appends (~750 ms),
so they cannot answer "how long is this scene". The samples can:
`measure_speech_extent` reads the 16-bit PCM, reduces every channel to its loudest absolute value,
and takes the first and last frame above `SILENCE_FLOOR_DB = -60.0`. Anything at or below that
floor across the whole file is an error, not an empty scene.

Each scene WAV is then trimmed to that extent plus a deliberate pad — `SCENE_LEAD_IN_MS = 120` and
`SCENE_TAIL_MS = 150` — computed in frames, so the trimmed file is a whole number of frames and its
duration is reproducible without re-probing.

### 8.2 Boundaries and cues derive from the trimmed frames

`scene_timings` accumulates the trimmed frame counts, so `scenes[].startMs`/`endMs` and
`narration.durationMs` all come from measured audio. Render props are rewritten to those timings
before rendering.

Subtitle cues are rebased onto the trimmed timeline and then **clamped to the measured speech
offset, not to the trim window**: the trailing pad exists for the listener's ear, not for a caption.
A cue that would linger over the pad is shortened; boundaries that collapse to nothing are dropped
rather than emitted as zero-length cues. Cues are grouped per scene and never across a boundary.

### 8.3 Loudness is closed-loop, not open-loop

Raw SAPI speech has a peak-to-loudness ratio near 20 dB, so a plain `loudnorm` pass cannot reach
−16 LUFS under a −1.5 dBTP ceiling — the true-peak ceiling binds and the result lands near −18.
`normalise_narration` therefore renders, measures, and corrects:

| constant | value | meaning |
| --- | --- | --- |
| `NARRATION_TARGET_LUFS` | `-16.0` | integrated loudness target |
| `NARRATION_LOUDNESS_TOLERANCE` | `0.5` LU | accepted error; the loop stops at half of it |
| `NARRATION_TRUE_PEAK_MAX_DBTP` | `-1.5` | ceiling that must never be bought for loudness |
| `max_passes` | `4` | hard bound; exhaustion is an error, not a best effort |

Each pass applies `NARRATION_COMPRESSOR` (a gentle 0.3 ms attack / 10 ms release compressor, so the
crest factor comes down before gain does) and `NARRATION_LIMITER` (brickwall at −2 dBFS, 0.5 dB
under the promise), measures the *output*, and corrects the gain by
`min(error, NARRATION_TRUE_PEAK_MAX_DBTP - 0.1 - peak)` — the correction is capped by the headroom
that is left, so loudness is never bought with true peak. After the loop the stage re-measures the
file it hands to the mux and fails if loudness is outside ±0.5 LU, if no true peak was reported, or
if the peak exceeds −1.5 dBTP.

`mix.loudness_lufs` is that measured value (`round(measured.integrated, 2)`), not the target. When no
licensed music asset exists, `mix.music` is `null`, `music_gain_db` is `null` and `ducking` is
`false`; the narration-only mix is normalised without inventing a music or silence track.

## 9. Render

```jsonc
{
  "schema_version": 1,
  "src": "output.mp4", "sha256": "…", "bytes": 2852953,
  "width": 1080, "height": 1920, "fps": 30, "frames": 1098, "duration_ms": 36600,
  "video_codec": "h264", "audio_codec": "aac", "pix_fmt": "yuv420p",
  "renderer": "remotion", "renderer_version": "4.0.537",
  "scene_hashes": { "sc1": "…" }
}
```

`scene_hashes` is what makes per-scene rerender possible: a scene whose hash is unchanged is
copied from cache, not re-rendered.

`audio_codec` is nullable. A render produced before the TTS stage exists has no audio stream, so
the field is `null` — the contract records what ffprobe observed, not what a finished video would
carry. Do not write `"aac"` for a silent file: `TECHNICAL_QC` fails its `audio_streams` check and
the job is blocked, which is the honest outcome. `video_codec` stays required; a render with no
video stream is not a render.

## 10. QA — three artifacts, one question each

The gate is split so that no artifact has to state something it could not have measured. One file
that carried the technical verdict, the creative score, the visual status and the gate decision
would have to invent the visual status before any provider was consulted — which is exactly what
the pre-split `qc.json` did.

### 10.1 `technical-qc.json` — FR-7.1, measured

```jsonc
{
  "schema_version": 1, "kind": "technical-qc",
  "passed": false,
  "checks": { "resolution": true, "black_frames": false, "…": true },
  "observed": { "width": 1080, "frames": 405, "expected_frames": 405,
                "duration_ms": 13500, "expected_duration_ms": 13485,
                "integrated_lufs": -17.72, "true_peak_dbtp": -1.29,
                "subtitle_cues": 3, "subtitle_max_chars": 23 },
  "thresholds": { "black_frames": "blackdetect=d=0.4:pix_th=0.02:pic_th=0.98", "…": "…" },
  "failed": ["black_frames"],
  "detectors": { "blackdetect": { "ran": true, "count": 1, "detail": "black_start:1" } },
  "inputs_sha256": "…64 hex…"
}
```

Expected values come from `render-props.json` (dimensions, fps, frame count), `audio.json`
(narration duration) and `storyboard.json` (scene ids). **Never from `render.json`**: a render that
supplies its own expected frame count can never disagree with itself.

| check | measured with | threshold |
| --- | --- | --- |
| `resolution` | ffprobe width/height | `1080x1920` |
| `frame_rate` | `avg_frame_rate` | `30 ± 0.01` |
| `video_codec` | `codec_name` | `h264` |
| `pix_fmt` | `pix_fmt` | `yuv420p` |
| `color_range` | `color_range` | `tv`; an untagged stream fails here |
| `video_stream_count` / `audio_stream_count` | stream counts | exactly `1` each |
| `audio_codec` | `codec_name` | `aac` |
| `frame_count` | `nb_read_frames` | `== sum(render-props scene durationInFrames)` |
| `duration` | `format.duration` | within 120 ms of `audio.narration.durationMs` |
| `black_frames` | `blackdetect=d=0.4:pix_th=0.02:pic_th=0.98` | no interval |
| `unexpected_silence` | `silencedetect=n=-45dB:d=2.5` | no interval |
| `frozen_frames` | `freezedetect=n=-60dB:d=2.0` | no interval |
| `subtitle_bounds` | `audio.json` cues | ordered, non-overlapping, ≤ 42 chars, inside narration |
| `loudness` | `loudnorm=I=-16:TP=-1.5:LRA=11` | `-16 ± 2 LUFS` |
| `true_peak` | same pass | `≤ -1.0 dBTP` |
| `checksum` | `sha256(output.mp4)` | `== render.json.sha256` |
| `scene_hashes` | `render.json.scene_hashes` keys | `== storyboard scene ids` |

A detector that did not run is a **failure**, not a warning. `scripts/verify_video.py` prints it
as WARN, which is honest for a human reading a terminal; a pipeline stage that cannot measure must
not report success.

### 10.2 `qc.json` — FR-7.2 plus the visual pass

```jsonc
{
  "schema_version": 1, "kind": "qa",
  "technical": { "passed": true, "failed": [], "checks": { } },   // summary only
  "creative": {
    "passed": true,
    "metrics": { "static_ratio": 0.0, "fade_ratio": 0.0, "text_density_max": 4.884,
                 "shot_variety": 1.0, "repeated_world": 1.0, "character_rig_palette_pairs": 1,
                 "pacing_max_scene_share": 0.3556, "pacing_median_cue_ms": 4285,
                 "hook_score": 4.0, "coherence_score": 4.0, "mapped_segments": 3,
                 "repetition": 0.0, "history_compared": 0 },
    "thresholds": { "static_ratio": "<= 0.45", "…": "…" },
    "failed": []
  },
  "visual": {
    "status": "passed" | "failed" | "skipped_no_vision_provider",
    "provider": "vision-a" | null,
    "frames_extracted": 5, "frames_inspected": 0,
    "findings": [{ "atMs": 4200, "issue": "…", "severity": "major" }]
  },
  "repairs": [{ "attempt": 0, "target": "static_ratio", "reason": "0.91 > 0.45",
                "artifacts_invalidated": [], "action": "blocked" }]
}
```

`technical` is a summary on purpose: the observed values, thresholds and detector logs live in
`technical-qc.json`, and two copies of the same measurement can disagree.

| metric | computed from | threshold |
| --- | --- | --- |
| `static_ratio` | `freezedetect=d=0.5` freeze seconds / duration | `≤ 0.45` |
| `fade_ratio` | forwarded `transition.frames` where kind is `fade` / total frames | `≤ 0.35` |
| `text_density_max` | scene text chars / scene seconds; longest single element | `≤ 42 chars/s`, `≤ 120 chars` |
| `shot_variety` | distinct rendered `data.shots[]` (framing, camera) / all shots | `≥ 0.5` |
| `repeated_world` | distinct (template, setting, timeOfDay) / scenes | `≥ 0.5` |
| `pacing` | max scene share of narration; median cue length | `≤ 0.6`, `≥ 700 ms` |
| `hook`, `coherence` | `review.json` verdict and score | verdict `accept`, score `≥ 3` |
| `segment_mapping` | scene `segment` vs `script.json` segment ids | complete, both directions |
| `character_consistency` | rendered `data.actors[].character` vs `assets.json` | ≥ 1 id, all resolve to one rig/palette |
| `repetition` | Jaccard of a style/world/shot signature against ≤ 10 prior rendered jobs | `≤ 0.8` |
| `narration_visual_relevance` | per scene: the domain subjects its own narration names vs the objects it draws | complete, per scene |
| `cause_effect` | a declared `causal_state`: all four parts stated, and `resulting_state ≠ initial_state` | complete and changed |
| `transition_continuity` | a scene declaring `motion.continuity: "carry"` vs shared object kinds with the previous scene | ≥ 1 shared kind |
| `visual_payoff` | final scene draws something; if it declares a causal cycle, it records a resulting state | non-empty |

`narration_visual_relevance` is per scene while `concrete_subjects` is per film: the film-wide gate
is satisfied when *some* scene draws a required subject, which is why a ramen shot that draws a GPU
can pass it. Both read the same `DOMAIN_REQUIREMENTS` table, so a subject cannot be required by one
and optional in the other.

`cause_effect` is conditional on declaration, because `SceneSpec.causal_state` is optional in the
contract and a gate that required it would make the contract's own optionality a lie. What it does
enforce is that a storyboard which *claims* a transformation shows one.

`transition_continuity` is the measured form of "a subject that survives a cut stays recognisable":
a storyboard that says `carry` while drawing an entirely new set of objects is claiming continuity
it did not build. Scenes declaring `cut` or `match` are not required to share anything.

`shot_variety` reads `data.shots[]` and nothing else: `product-adapter.ts` forwards `data` and
drops `camera`/`motion`, so a score derived from `camera.move` would be a number no pixel can
contradict. `hook`/`coherence` are read from the accepted review, never re-scored here.

`visual.status` has no default. `passed` requires `frames_inspected ≥ 1` and equal to the number of
frames actually sent; `skipped_no_vision_provider` requires `frames_inspected == 0` and
`provider == null`. Both are enforced by `QaArtifact`, so a claim about frames nobody looked at
cannot be constructed.

`repairs` records decisions, never hidden retries. `action` is one of `blocked`, `rerendered`,
`re-authored`; this build emits only `blocked`, and `artifacts_invalidated: []` is the truthful
statement that nothing was rewritten. Automatic repair is **zero** because every failure this gate
can detect is deterministic — re-running a black or frozen render cannot converge.

### 10.3 `readiness.json` — the DirectorAgent gate

```jsonc
{
  "schema_version": 1, "kind": "readiness",
  "ready": true,
  "checks": { "technical": true, "creative": true, "visual": true, "checksum": true },
  "blockers": [],
  "technical_passed": true, "creative_passed": true,
  "visual_status": "skipped_no_vision_provider",
  "inputs_sha256": "…64 hex…"
}
```

`ready: true` is refused by the contract while any blocker remains, any check is false,
`technical_passed`/`creative_passed` is false, or `visual_status` is `failed`. A skip is not a
blocker — it is visible and non-passing.

`inputs_sha256` binds the verdict to the bytes and timings it judged:

```
content_hash({ "render_sha256": <render.json.sha256>,
               "narration_ms": <audio.narration.durationMs, 3 dp>,
               "storyboard": <StoryboardArtifact.content_hash()> })
```

`created_at` is excluded because `Artifact.canonical_json` already excludes it — a field stamped
with the current whole second made the hash depend on the clock (40 identical calls produced 3
distinct hashes, so a verdict computed at 12:00:00 failed to verify at 12:00:01). The approval gate
recomputes this hash from disk before an operator can approve, so a re-render invalidates a stale
pass.

### 10.4 `qa-contact-sheet.jpg` — one image, no padding cell

One 1080-wide JPEG holding the keyframes: each scene's midpoint plus one still 0.5 s after each
cut, capped at 6 distinct frames. The grid is sized to the count so no empty cell exists —
1x1, 2x1, 3x1, 2x2, 3x2 for 5, 3x2 for 6. Only 5-in-3x2 leaves a cell, and that cell is filled with
a neutral grey and labelled `no frame 6`. Black is never used: a black tile is indistinguishable
from a black frame, and the vision prompt is instructed to report an unreadable tile as a finding.

## 11. Approval

```jsonc
{
  "schema_version": 1,
  "decision": "approved" | "rejected",
  "operator": "…", "reason": null | "…",
  "checks": { "render_valid": true, "qc_passed": true, "publishable": true },
  "decided_at": "…",
  "render_sha256": "…64 hex…"        // the render this decision was made about
}
```

`publishable` is false for any job whose `provider_mode == "mock"`.

**`render_sha256` is the binding between the decision and the bytes.** The approve route writes it
from the same digest `_approval_checks` already recomputed from `output.mp4`, so it cannot be
copied from a stale `render.json` — the gate refuses first if the two disagree.

The field is optional in the contract, for one reason: an `approval.json` written before the field
existed must still parse. It is **not** optional at the transition — an artifact with
`render_sha256: null` cannot prove what it approved, and `JobStore.transition` refuses it. Contract
tolerance and transition strictness are deliberately different here.

**The transition requires the artifact, not just the edge.** `JobStore.transition(job_id,
JobState.APPROVED)` refuses unless `approval.json` exists for that job and satisfies a minimal
shape check the store performs without knowing policy:

| Condition | Refusal |
| --- | --- |
| file absent | `APPROVED requires approval.json, which does not exist for this job` |
| unreadable / not JSON | `approval.json cannot be read: <ErrorType>` |
| `decision != "approved"` | `approval.json decision is '<value>', not 'approved'` |
| empty `operator` | `approval.json records no operator` |
| `checks.publishable` not `true` | `approval.json does not record checks.publishable == true` |
| no `render_sha256` | `approval.json records no render_sha256, so it cannot prove which render it approved` |
| `render.json` missing | `approval.json names a render_sha256 but render.json is missing or unreadable` |
| digest mismatch | `stale approval: approval.json was decided against render_sha256 <recorded>, but render.json.sha256 is <current>` |

The store does **not** decide whether the gate should have passed — that is `_approval_checks` in
`apps/api/jobs.py`, which reads artifacts and recomputes hashes. It only refuses to record the
outcome without the gate's evidence. Enforced by
`tests/test_jobstore.py::test_approved_without_an_approval_artifact_is_refused`,
`::test_a_rejected_approval_artifact_cannot_authorise_approved`,
`::test_an_approval_for_a_different_render_cannot_authorise_approved`,
`::test_an_approval_recording_no_render_hash_is_refused`,
`::test_a_matching_approval_artifact_permits_approved`,
`::test_the_gate_route_is_the_only_door_after_a_block`,
`tests/test_api_approval_gate.py::test_resuming_to_the_gate_state_does_not_authorise_approval`,
`::test_the_approve_route_records_the_render_it_approved`, and
`::test_a_stale_approval_blocks_after_a_re_render`.

## 12. Metadata

**HTTP surface.** `GET /api/jobs/{job_id}/metadata` returns the artifact, `404` when absent.
`POST /api/jobs/{job_id}/metadata` merges a partial edit into it.

| Field | Rule |
| --- | --- |
| `title` | 1–100 chars when present; an empty string is a `422`, not a clear |
| `description` | ≤ 5000 chars |
| `tags` | ≤ 50 entries |
| `category_id` | ≤ 10 chars |
| `made_for_kids` | boolean |
| anything else | `422` — `extra="forbid"`, so a typo cannot be silently ignored |

Every field is optional; omitted fields keep their current value. The edit is refused with `409`
unless the job is at or past `READY_FOR_APPROVAL` (`READY_FOR_APPROVAL`, `APPROVED`,
`PRIVATE_UPLOAD`, `SCHEDULED`, `BLOCKED`), because before that state `MetadataAgent` has not
written its draft and the edit would be silently overwritten, and after a terminal state there is
nothing left to publish. A merged payload that fails `MetadataArtifact` validation is a `422`.


```jsonc
{
  "schema_version": 1,
  "title": "…", "description": "…", "tags": ["…"],
  "category_id": "22", "made_for_kids": false, "synthetic_media": true,
  "thumbnail": { "concept": "…", "path": "thumb.png", "sha256": "…" }
}
```

## 13. Publication

```jsonc
{
  "schema_version": 1,
  "phase": "initiating" | "uncertain" | "confirmed" | "scheduled",
  "video_id": null | "…",
  "privacy": "private",
  "publish_at": null | "2027-01-01T18:00:00+07:00",
  "receipts": [{ "at": "…", "step": "upload|readback|thumbnail|schedule|insert_sent|reconcile", "ok": true, "detail": "…" }],
  "idempotency_key": "…32 hex…",             // required
  "attempt": 1                                // how many inserts were started
}
```

`idempotency_key` is **derived, never minted**: `sha256(job_id + "\0" + render.json.sha256)`
truncated to 32 hex chars. Re-running the stage cannot produce a different key, so "the same video"
is a property of the data rather than of a variable that survived in memory. A re-render changes
`render.json.sha256` and therefore the key — which is correct, because it is a different video.

`phase: "uncertain"` blocks every retry until an operator reconciles: a blind retry after a
timeout that may have succeeded creates a duplicate upload. A failure that provably happened
before the request left (`no token`, `expired token`) is recorded as `initiating`, not
`uncertain` — otherwise the job becomes permanently un-uploadable after the operator fixes
their OAuth.

**Contract enforcement** (`PublicationArtifact` validators, `packages/core/contracts/artifacts.py`):

| Phase | Requirement |
| --- | --- |
| `uncertain` | must carry an `insert_sent` receipt with `at` (when the request left) and `sent` (what was sent). An uncertain record that cannot say what it did is not actionable. |
| `confirmed` | must carry `video_id`. Without an id the assertion is unverifiable. |

**The stage** (`packages/core/publish/stage.py`) applies three rules in order, and each is a
separate lock:

1. An existing record for a **different** key is refused as `publication_key_mismatch` — a
   confirmation binds to bytes, and a re-render is a different video, not a retry.
2. An existing **`confirmed`** record for the same key is never re-inserted; the stage reports
   reuse. Enforced twice: the runner's `Stage.done_when` treats a non-`confirmed` artifact as not
   done, and the stage itself re-checks before calling the transport.
3. An existing **`uncertain`** record refuses to proceed with a non-retryable
   `publication_uncertain` naming reconciliation. `BLOCKED -> PRIVATE_UPLOAD` is not in the
   allow-list, so the job cannot even re-enter the stage while blocked.

The pre-flight/uncertain split is delegated to the transport, which is the only code that knows
whether bytes went out: `TransportRefused` is retryable and writes nothing; `TransportUncertain`
writes the `uncertain` record and is never retryable. `publication_uncertain` and
`publication_key_mismatch` both map to `BLOCKED`, never `FAILED`, because `FAILED` invites a retry
and a retry is the duplicate.

**Reconciliation** (`packages/core/publish/reconcile.py`) resolves `uncertain` by *reading*:

```python
reconcile_uncertain(store, job_id, transport) -> PublicationArtifact
```

It loads `publication.json`, requires `phase == "uncertain"`, calls `list_private()`, and matches
on the idempotency key. It **never inserts**, in either branch.

* **found exactly one** → `phase: "confirmed"`, adopting the remote `video_id`, with a
  `reconciled_found` receipt recording what it matched on and that no insert was performed.
* **found none** → `phase: "initiating"`, with a `reconciled_not_found` receipt recording the key
  and how many private videos were seen. The record is reset so the operator can deliberately
  publish again; nothing is retried automatically.
* **more than one** → raises `ValueError` and leaves the record `uncertain`. Confirming a stranger's
  video is worse than staying blocked, so an ambiguous match is never resolved by picking one.
* **`confirmed` or `initiating`** → raises `ValueError`. A healthy record is not "fixed" by
  reconciling it; silently rewriting one would erase the evidence that the upload happened.

**Why the not-found branch clears rather than refuses.** "No match" is *positive* evidence from a
successful read, not an absence of evidence — the request almost certainly never landed, and the
alternative (keeping the record `uncertain` forever) makes the job permanently un-publishable on a
false positive, which is the failure this section already warns about. The residual risk is an
incomplete or eventually-consistent remote listing, so the receipt records how many private videos
were seen and the operator is expected to confirm the listing looked complete. Clearing is not a
retry: it changes a record, and the next insert is a separate, deliberate call.

**How the key survives the round trip.** A remote API may expose no custom-metadata field, so the
key travels inside the payload the transport actually sends: `key_marker(key)` embeds
`#sf-key:<key>` in the description, and `key_from_description` reads it back. Matching order is the
explicit `idempotency_key` field first, then the description marker, then title + privacy as a last
resort. `tests/test_publish_stage.py::test_reconcile_matches_on_the_description_marker_when_there_is_no_key_field`
proves the marker path; `::test_the_stub_records_the_idempotency_key_it_was_given` proves the stub
sends both.

**The service entry** (`apps/api/jobs.py::JobService.publish`, no route yet) refuses in order: the
job must be `APPROVED`; `provider_mode` must be `live` (a mock job refuses with
`publishable is false`); and `_approval_checks` is recomputed so an approval that is no longer
publishable is refused. Only then does it run the stage under a lease. The route it will get is
`POST /api/jobs/{job_id}/publish`, a thin wrapper that resolves the transport from operator config.

`tests/test_publish_stage.py::test_a_process_restart_after_uncertain_uploads_exactly_once` proves
the Phase 4 gate's restart half offline: exactly one insert across a first run that ends
`uncertain`, a fresh service object over the same database, and a post-reconcile re-run.

Proven by `tests/test_publish_stage.py` (20 tests), including
`::test_reconcile_confirms_without_a_second_insert` which asserts the stub's insert count is 0
across the whole reconcile sequence.

### 13.1 Usage summary

**Render admission** (`packages/core/orchestration/resources.py`) guards the one global render
slot with the operator's saved policy, before a renderer process exists:

* `min_free_ram_mib` and `min_free_vram_mib` come from `studio.json` `render`, saved through
  `PUT /api/settings`. The cap is fixed at one concurrent render and is not configurable.
* RAM is read through Windows `GlobalMemoryStatusEx`; VRAM through `nvidia-smi`. A value that
  cannot be measured is `None`, never `0`.
* An unmeasured GPU refuses unless the operator opted in with `allow_unmeasured_gpu`. That opt-in
  never raises the cap above 1.
* A refusal returns `waiting_resources` with the measured reason, blocks the job, and writes no
  render artifact and no success checkpoint. It is the operator-visible "this will start when the
  machine can take it", not a silent queue.

**Resuming a job at a render or QC state** reuses only stages whose artifacts exist and whose
contract validates. If historical upstream evidence is missing, unreadable, or no longer valid,
the run stops with `resume_evidence_missing` naming the stage and artifact before any paid call —
resuming never regenerates earlier work and never fakes success.

`GET /api/usage/summary` aggregates `usage_log` three ways plus a flag:

```jsonc
{
  "days":     [{ "day": "2026-01-01", "tokens": 160, "calls": 3, "cost_usd": 0.0 }],
  "by_agent": [{ "day": "…", "agent": "ScriptAgent", "tokens": 150, "calls": 2, "cost_usd": 0.0 }],
  "by_model": [{ "day": "…", "provider": "stub", "model": "model-a", "tokens": 150, "calls": 2, "cost_usd": 0.0 }],
  "price_configured": false
}
```

`tokens` is `prompt_tokens + completion_tokens`. `cost_usd` is the sum of `est_cost_usd`, which is
**0.0 for every call unless the operator configured prices**. `estimate_cost` returns 0.0 when both
prices are `None` rather than inventing one, so `price_configured` (true once any row has a
non-zero cost) is what distinguishes "this run was free" from "nobody set a price". A dashboard must
read that flag before presenting the number as money.

Prices are set per provider: `PUT /api/providers` accepts `price_in_per_mtok` and
`price_out_per_mtok`, which reach `ProviderSpec` and then `RecordingProvider`. Before that field
existed, every recorded cost was structurally 0.0.

## 14. Event

```jsonc
{
  "event_id": 1234, "job_id": "…", "agent_id": "ScriptAgent",
  "event_type": "stage_started|stage_completed|artifact_reused|progress|failed|blocked",
  "status": "working|waiting|reviewing|blocked|failed|completed",
  "description": "…",                       // redacted, bounded
  "progress": 0.42,                          // only from real counters
  "model": "eg/deepseek-v4.1-flash",
  "stage": "SCRIPT_GENERATED",
  "created_at": "…"
}
```

`progress` is never synthetic. 100 % is reserved for a validated artifact. Cached work emits
`artifact_reused` with `status: "completed"` and no working phase.

## 15. Topic discovery record (SQLite, not a job artifact)

`POST /api/topics/discover` persists one row in the additive `topic_discoveries` table
(migration 2 in `packages/core/contracts/store.py`), keyed by a `disc-…` id. The payload is
metadata, never a job:

```jsonc
{
  "schema_version": 1,
  "discovery_id": "disc-…",
  "provider": "eg/deepseek-v4.1-flash",   // resolved provider id
  "provider_mode": "mock|live",
  "avoid": ["…"],                          // recent titles + prior proposals, bounded
  "history_titles": ["…"],
  "candidates": [ { "title": "…", "angle": "…", "why": "…", "score": 0.33, "source": "history" } ]
}
```

Discovery emits the same event rows as a stage job (`job_id` = the discovery id, agent
`DirectorAgent`), but creates no job, no artifact files, and never enters the approval gate:
proposals become jobs only through the operator's explicit create call.
