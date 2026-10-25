# ADR-0007 — Two renderers behind one interface

**Status:** accepted

## Decision
`Renderer` protocol with `capabilities()` and `render(spec, out_dir) -> RenderArtifact`.

1. **Remotion** — validated `SceneSpec` → composition → MP4. Primary, deterministic.
2. **Bang Motion** — motion-skill HTML/CSS/GSAP → CDP frame capture → FFmpeg. Secondary, isolated.

## Why the secondary renderer is not "Bang Motion generates Remotion components"
Bang Motion emits a self-contained HTML document exposing `window.OPENER`. It has no knowledge of
React. Treating it as a component source would require executing model-generated HTML inside the
dashboard — forbidden by the brief and by R-13.

## Isolation
Separate process, `chrome-headless-shell` (already vendored under `node_modules/.remotion`, so no
new dependency), no network at capture time, staging-directory filesystem, wall-clock and frame
caps.

## Consequences
Two code paths to keep in parity; the parity test is the guard. If Bang Motion cannot hold 1080×1920
(R-07), only Remotion is offered for Shorts and the limitation is reported, not hidden.
