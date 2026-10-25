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
  "mix": { "music_gain_db": -18, "ducking": true, "loudness_lufs": -16 }
}
```

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

## 10. QA

```jsonc
{
  "schema_version": 1,
  "technical": { "passed": true, "checks": { "resolution": true, "…": true }, "loudness_lufs": -16.01 },
  "creative": { "passed": true, "scores": { }, "static_ratio": 0.12, "repetition": 0.0 },
  "visual": {
    "status": "passed" | "failed" | "skipped_no_vision_provider",
    "provider": "vision-a", "frames_inspected": 6,
    "findings": [{ "atMs": 4200, "issue": "…", "severity": "major" }]
  },
  "repairs": [{ "attempt": 1, "target": "sc2", "reason": "…", "artifacts_invalidated": ["storyboard.json"] }]
}
```

`visual.status` has no default. A job cannot reach `READY_FOR_APPROVAL` with a missing status;
`skipped_no_vision_provider` is visible to the operator and is not a pass.

## 11. Approval

```jsonc
{
  "schema_version": 1,
  "decision": "approved" | "rejected",
  "operator": "…", "reason": null | "…",
  "checks": { "render_valid": true, "qc_passed": true, "publishable": true },
  "decided_at": "…"
}
```

`publishable` is false for any job whose `provider_mode == "mock"`.

## 12. Metadata

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
  "receipts": [{ "at": "…", "step": "upload|readback|thumbnail|schedule", "ok": true, "detail": "…" }]
}
```

`phase: "uncertain"` blocks every retry until an operator reconciles: a blind retry after a
timeout that may have succeeded creates a duplicate upload. A failure that provably happened
before the request left (`no token`, `expired token`) is recorded as `initiating`, not
`uncertain` — otherwise the job becomes permanently un-uploadable after the operator fixes
their OAuth.

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
