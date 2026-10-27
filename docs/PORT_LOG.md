# PORT_LOG — what came from the donor tree, and at which commit

Donor: `C:\Users\cubeb\OneDrive\Documents\coding\projects\ShortsFactoryAI`
Reference commit at audit: `cb85f1b` (branch `merge/pixel-studio-ui`, 51 uncommitted files).

A module is ported only when (a) it is re-argued against this brief, (b) its donor tests come with
it, and (c) it passes here. "The donor does it this way" is not a justification.

| Module | Donor path | Status | Notes |
| --- | --- | --- | --- |
| Job state allow-list | `packages/core/orchestration/states.py` | to port (P1.5) | Keep the shape; add `PAUSED` and the event-in-same-transaction rule. |
| Job store | `packages/core/orchestration/jobstore.py` (455 L) | to port (P1.5) | Keep `sqlite3`. Add migrations table. |
| Leases | `packages/core/orchestration/leases.py` | to port (P1.5) | Token ownership is correct and hard-won; keep. |
| Netguard CIDR list | `packages/core/research/retrieval.py:35-45` | port (P1.3) | Extracted into `security/netguard.py` and applied to providers, which the donor never did. |
| Provider protocol | `packages/core/providers/base.py` | rewrite (P1.4) | `ResolvedCall` frozen; no mutation. |
| OpenAI-compatible transport | `packages/core/providers/openai_compat.py` | port + fix (P1.4) | Keep the honest error text; add netguard and origin binding. |
| Mock provider | `packages/core/providers/mock.py` | port (P1.4) | Deterministic, seeded. |
| TTS adapter | `packages/core/providers/tts.py` | port (P2.4) | Word boundaries are the basis of subtitle timing. |
| Media probe/validation | `packages/core/media/render.py:20-41` | port + extend (P2.3) | `validate_probe` is good; keep the checks verbatim. |
| Render boundary | `packages/core/media/render.py` | new (P2.3) | Single subprocess into `packages/video`: absolute `--props`, explicit free port, `--concurrency=1`, then ffprobe. `render.json` is written only after the probe passes. |
| Render stage | `packages/core/orchestration/pipeline.py::_render_stages` | new (P2.3) | `RENDERING` -> `TECHNICAL_QC`, appended only when `job.payload["render_video"] is True`. `qa_blocked` maps to `BLOCKED`, not `FAILED`. |
| Remotion compositions (7) | `packages/video/src/compositions/` | ported (P2.2) | 7/7 wired into `SCENE_RENDERERS`. `still-smoke` renders all seven at 1080×1920 and asserts seven distinct templates; it is the npm alias `npm --prefix packages/video run still-smoke -- <abs-output-dir>` (the `--` and an absolute dir are required). `camera`/`motion` are consumed through the adapter, not yet by each composition. |
| Art kit | `packages/video/src/art/` | ported unchanged (P2.2) | `fit="box"` kept; the frame-coordinate trap is documented and still absent from the donor source. |
| Character engine | `packages/video/src/character/` | ported unchanged (P2.2) | One character `maya`: 7 poses, 8 expressions, 7 gestures, 7 motion presets. |
| Product adapter | `packages/video/src/product-adapter.ts` | new (P2.2) | Not donor work: maps our `storyboard.json` onto the donor contract (roles, transitions, theme, subtitles, content-addressed assetRefs only). |
| Props resolver | `packages/video/src/storyboard-props.ts` | new (P2.2) | Not donor work: adapts inside `calculateMetadata`, because `--props` overrides `defaultProps`. |
| `animation` scene field | `packages/video/src/types.ts` | carried, unused | Declared in the donor contract and emitted by the adapter, but read by no composition. Do not port it forward as if it did something. |
| Storyboard normalisation | `packages/core/storyboard_normalize.py` (850 L) | port (P2.1) | The degradation strategy (keep the text, drop the invented facts) is right. |
| Event store / projection | `packages/core/observability/` | port (P1.6) | Monotonic cursor + replay is correct. |
| Publishing service | `packages/core/publishing/` | port (P4) | The pre-flight vs uncertain classification must come with it; it was a real bug. |
| Pixel office (2D) | `apps/dashboard/src/components/pixel/` | do not port | Replaced by the 3D studio; the 2D fallback is new work with the same state contract. |
| Bang Motion document source | `bangtutorial/bang-motion@c1aa65e` (v1.19.0, MIT © 2026 Bang Tutorial) | **self-authored (P2.3)** | ADR-0012. The design law (9:16 stage, `.safe` at .78, per-word spans), the `window.OPENER` interface and the seek→2×rAF→screenshot frame technique are reused **as knowledge**. **Zero upstream executable lines are copied**: no starter HTML, no `export-frames.mjs`, no Puppeteer. `packages/core/motion/emit.py` writes the document and `packages/video/scripts/bang-render.mjs` drives CDP with Node's built-in `WebSocket`. GSAP and the CDN fonts are deliberately not vendored. |
| SQLAlchemy / APScheduler deps | `pyproject.toml` | do not port | Declared, never imported. |

## `packages/video` — installed and verified

The package is installed (`--include=dev`) and its own gates pass, run from `packages/video`:

| Gate | Result |
| --- | --- |
| `npx tsc --noEmit` | clean, exit 0 |
| `npm run still-smoke -- <abs-dir>` | 7/7 templates, each 1080×1920 |
| `npm run test:adapter` | 44 checks, 0 failures |
| `npm run test:render-props` | 21 checks, 0 failures |

**Why adaptation lives in `calculateMetadata`.** Remotion merges composition props as
`{...defaultProps, ...editorProps, ...inputProps}`, so a `--props` payload always wins over the
`defaultProps` a `RemotionRoot` computed. Adapting the product storyboard in `RemotionRoot` alone
therefore fixed the Studio preview but not a real render — the render passed the raw product
storyboard straight into `Short`. `storyboard-props.ts` adapts inside `calculateMetadata`, whose
returned props replace the merged set, and `test:render-props` is the regression test for exactly
that merge order.

## Known donor defects not carried forward

| Defect | Where | Fixed by |
| --- | --- | --- |
| Per-agent override mutates shared provider | `providers/router.py:202-209` | ADR-0003 |
| `base_url` editable with no SSRF check | `studio.py` validator | ADR-0005 |
| No `camera` in `SceneSpec` | `schemas.py:164` | ADR-0009 |
| Two declared, unused dependencies | `pyproject.toml` | ADR-0006 |
| Approval CLI-only in some branches | checkout-dependent | Phase 4 API routes |
