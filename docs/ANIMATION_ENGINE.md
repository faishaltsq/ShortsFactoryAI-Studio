# ANIMATION_ENGINE — scene contract to pixels

## 1. Pipeline

```
SceneSpec[]  ──validate──>  MotionPlan  ──>  Renderer  ──>  RenderArtifact
     ^                          ^                |
     |                          |                +── RemotionRenderer  (primary)
  StoryboardAgent          AnimationAgent        +── BangMotionRenderer (secondary)
```

## 2. Why a motion plan exists

`SceneSpec` says *what* is in a scene. `MotionPlan` says *how it moves*: beats, camera path,
continuity. Splitting them means the storyboard can be approved before motion is designed, and
motion can be re-authored without re-running the storyboard agent.

## 3. Camera model

```
shot:   wide | medium | close        (framing, not zoom)
move:   static | push | pull | pan | tilt | orbit
target: element id the move is about (required unless static)
ease:   power1..4 .in/.out/.inOut
```

Rules that make movement purposeful:

1. `move != static` requires a `target` that exists. No target, no move.
2. At most one `push` or `pull` per video; a push is reserved for a reveal.
3. `orbit` requires a 3D-ish scene (`IllustratedStory`, `ParallaxStory`); it is rejected for
   flat templates.
4. A scene's `continuity: "carry"` inherits the previous camera position, so the world does not
   jump between scenes.
5. Breathing (a 0.5 % scale oscillation) is a baseline layer, never the only motion. A scene
   whose only motion is breathing fails creative QA.

## 4. Anti-PPT rules (mechanical checks)

Creative QA computes these from the storyboard, not from vibes:

| Check | Rule | Failure |
| --- | --- | --- |
| Static ratio | scenes with `move == static` AND no beats / total scenes | > 0.5 fails |
| Fade ratio | `transition.kind == "fade"` / transitions | > 0.3 fails |
| Text density | characters of on-screen text per second | > 18 fails |
| Shot variety | distinct `shot` values per video | < 2 fails |
| Repeated world | identical `theme` + `background` across consecutive scenes | > 3 in a row fails |
| Beat coverage | scenes with ≥ 2 beats / scenes | < 0.6 fails |

These are recorded in `qc.json` with their measured values, so the operator can see *why* a
video was rejected rather than trusting a score.

## 5. Remotion renderer

- Compositions registered in `packages/video/src/compositions/registry.ts`, one per template.
- Props are the validated `SceneSpec[]` — never raw model text.
- `--port` is always explicit (the preview server defaults to 3000, which collides with the
  dashboard; on Windows a bind can "succeed" on a port another process already answers, and
  Remotion then serves a bundle Chrome cannot reach).
- `--props` is always an absolute path (a relative path fails silently as an empty render).
- Frame count in the output must equal `sum(durationInFrames)`; a mismatch fails the render.
- Version pinned in `package.json`; the version is recorded in `RenderArtifact`.

## 6. Bang Motion renderer

- Skill HTML is ingested into `data/motion-skills/bang-motion@<version>/`, CDN references
  rewritten to vendored local files (GSAP, fonts, three.js).
- Rendering: a Node script drives `chrome-headless-shell` over CDP (already present under
  `node_modules/.remotion/`, so no Puppeteer dependency), seeking `window.OPENER` per frame,
  awaiting two `requestAnimationFrame` ticks, capturing. FFmpeg then encodes the PNG sequence.
- Isolation: separate process, no network at capture time, working directory is the job's
  staging dir, wall-clock cap, frame-count cap, and the HTML is served from a `file://` URL or
  a loopback server bound to 127.0.0.1 with a random port — never loaded into the dashboard.
- The 9:16 recipe from the skill is applied at ingest: stage 1080×1920, `.safe` wrapper at
  scale .78, per-word spans so long phrases can wrap.

## 7. Per-scene rerender

`RenderArtifact.scene_hashes` maps scene id → hash of its validated spec. A rerender compares
hashes and re-renders only changed scenes, then concatenates. Concatenation uses FFmpeg
`concat` demuxer with identical encoder settings, then remuxes audio; the result is re-probed
and must pass the same `validate_probe` as a full render.

## 8. Determinism

- Random values come from a seeded PRNG keyed by `(job_id, scene_id, element_id)`. Two renders
  of the same spec produce byte-identical frames.
- Fonts are bundled, not fetched.
- Date/time is never rendered unless it is in the spec.
- A render test asserts: render twice, compare SHA-256 of the frame sequence (allowing encoder
  nondeterminism only at the container level, not the frames).
