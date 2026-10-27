# HANDOFF — continuing this build in another agent (OMP)

Written 2026-10-25. Read this top to bottom before touching code, then follow the prompt in §6.

## 1. Where the work lives

```
C:\Users\cubeb\orca\projects\ShortsFactoryAI-Studio
```

Fresh git repo, branch `master`, no remote. Baseline at handoff: **205 Python tests green, ruff
clean**. The donor tree (`OneDrive/Documents/coding/projects/ShortsFactoryAI`, 735 tests) is a
reference only — see §5.

## 2. What is actually finished (verified, not claimed)

| Module | What it does | Tests |
| --- | --- | --- |
| `packages/core/contracts/` | `SceneSpec` with required `camera`+`motion`, all artifact models, job state allow-list | 34 |
| `packages/core/security/netguard.py` | CIDR deny list, resolve-then-pin (closes DNS rebinding), no redirects | 17 |
| `packages/core/security/secretstore.py` | env references + DPAPI sealing, origin binding | 15 |
| `packages/core/security/redact.py` | whole-match + assignment redaction, one line, bounded | 8 |
| `packages/core/providers/` | 5 transports, frozen `ResolvedCall`, capability check **before** any call, usage + pre-call budget | 28 |
| `packages/core/orchestration/` | SQLite WAL jobstore, atomic artifacts, token-owned leases, stage runner (reuse, marker-last, lease-guard, no unverified success) | 44 |
| `packages/core/observability/events.py` | append-only event log, monotonic cursor, server-side staleness | 16 |
| `packages/core/agents/` | 8 agents, typed contracts, one bounded JSON repair | via pipeline |
| `packages/core/orchestration/pipeline.py` | 5 agent stages → `STORYBOARD_READY`, real usage attribution | 7 |
| `apps/api/` | jobs CRUD/run/cancel, approve/reject gate, Range video, providers, SSE, usage | 25 |

**End-to-end proof that was actually run** (not inferred): a mock job walks
`IDEA_DISCOVERY → STORYBOARD_READY`, produces 5 contract-valid artifacts, records 5 usage rows
with the right agent/provider/model, and a second run reports `reused: [True×5]` with **zero new
usage rows and zero new events**. A live-mode job with no provider ends `FAILED`, not mock.

## 3. What is half-finished — start here

`apps/dashboard/` has infrastructure and no pages:

```
written:  package.json, tsconfig, next.config.ts, vitest.config.ts, playwright.config.ts,
          src/app/globals.css (design tokens), src/app/layout.tsx, src/app/api/[...path]/route.ts,
          src/lib/api.ts, src/lib/useStudio.ts, src/components/Sidebar.tsx,
          src/components/states.tsx, src/three/{zones.ts,StudioScene.tsx,StudioFallback.tsx}
missing:  src/app/page.tsx          (Studio — 3D scene + inspector)
          src/app/jobs/page.tsx     (queue + detail with <video> and Range playback)
          src/app/providers/page.tsx (CRUD, test connection, model fetch, capabilities)
          and the remaining routes listed in Sidebar.tsx
```

`npm install` is already done (`node_modules` present). **`npm run typecheck` has never been
run** — expect real errors in the three components, fix them rather than deleting the code.

## 4. The next task, in order

> **Status 2026-10-25 — steps 1–5 done; Phase 2 not started.**
>
> `typecheck`'s only initial error was TS2353 for the `eslint` key that Next 16 removed from
> `next.config.ts`. Pages added: `src/app/page.tsx` (studio), `src/app/jobs/page.tsx` (list +
> detail), `src/app/providers/page.tsx`. Vitest: 16 tests. One Playwright spec covers
> create → `STORYBOARD_READY`, cancel of a running job, and projection parity (rendered
> `data-state` against the persisted snapshot). Three consecutive full gate runs were green:
> pytest 215, ruff 0, typecheck 0, Vitest 16, Playwright 1 passed.
>
> **Phase 2 (same day, later).** `packages/video` is ported: 49 files under `src/` (47 donor +
> `product-adapter.ts` and `storyboard-props.ts`), 10 scripts, 2 fixtures. The donor's
> `public/jobs/*.wav` were deliberately excluded; only `public/sample/narration-test.mp3` came
> across. The package is standalone — React 18.3.1 / Remotion 4.0.537, installed with
> `--include=dev` — and after a fresh install `npx remotion browser ensure` must run before the
> first render (Chrome headless shell 157.0.8080.0, 295 MB on disk here).
>
> `src/product-adapter.ts` maps our persisted `storyboard.json` onto the donor contract: text
> roles, transition kinds, theme, subtitles, and assetRefs limited to content-addressed rasters
> (non-content-addressed refs such as `character:maya` are dropped rather than turned into image
> requests). `src/storyboard-props.ts` resolves props inside `calculateMetadata`, because Remotion
> merges `--props` last and it overrides `defaultProps` — adapting only in `RemotionRoot` fixed the
> Studio preview but not a real render.
>
> `packages/core/media/render.py` is the single subprocess boundary: one `remotion render` call
> with an absolute `--props`, an explicit free port, `--concurrency=1`, `--pixel-format=yuv420p`
> and `--color-space=bt709` (both are needed: without the color space Remotion emits no
> `-color_range` and libx264 tags the output `yuvj420p`). ffprobe validates the file before
> `render.json` is written.
>
> Real proof: one API job with `render_video: true` produced a 1080×1920 h264 900-frame MP4 in
> ~70 s; `render.json` validates as `RenderArtifact`; the job ends `BLOCKED` at `TECHNICAL_QC` on
> `audio_streams` + `audio_codec` only, because narration/TTS (Phase 2.4) does not exist. `pix_fmt`
> passes.
>
> The new `STORYBOARD_READY → RENDERING` edge is an explicit, documented shortcut; its removal
> condition is recorded in `docs/STATE_MACHINE.md`. Still missing before the Phase 2 exit gate:
> TTS/subtitles (2.4), the asset stage, editorial QC, creative checks, and the second renderer.

1. `npm --prefix apps/dashboard run typecheck` → fix everything it reports.
2. `src/app/page.tsx`: Studio overview. `useStudio()` → `StudioScene` when quality allows,
   `StudioFallback` when `quality === "off"`. Clicking a character opens an inspector drawer with
   name, role, status, task, model, progress, last 5 events, and a link to its job.
3. `src/app/jobs/page.tsx`: list + detail. Detail shows `<video src={videoUrl(id)} controls>` when
   `has_video`, the event log, artifacts, usage table, and approve/reject controls that surface
   server-side 409 gate failures verbatim.
4. `src/app/providers/page.tsx`: add/edit provider, "Uji koneksi" (`POST /api/providers/test`,
   which reports *reachability only* — say so in the UI), fetch models, capability checkboxes,
   private-host warning when `allow_private_hosts` is on.
5. `npm run test` (Vitest) for the state logic, then `npm run test:e2e` (Playwright) for: create a
   mock job → watch it reach `STORYBOARD_READY` → cancel a running job → assert no character shows
   `working` when the event log has none.
6. Only then Phase 2: port `packages/video` (Remotion, 11 compositions, art kit, character engine)
   and add the render stage. Do not start this before the dashboard gate passes.

## 5. Donor tree — how to use it, and how not to

| Use it for | Do not |
| --- | --- |
| Porting `packages/video/src/**` (Remotion compositions, art kit, character rig) | Copying `packages/core/**` wholesale |
| Reference implementations for ffprobe validation, subtitle timing, TTS word boundaries | Inheriting its provider router (it mutates shared providers) |
| Its 735 tests as a source of edge cases worth re-testing | Trusting its branch as a baseline — 51 files are uncommitted there |

Known donor defects deliberately **not** carried forward, each with an ADR: shared-provider
mutation (`0003`), no SSRF check on `base_url` (`0005`), no `camera` in `SceneSpec` (`0009`), two
declared-but-unimported dependencies (`0006`). Details in `docs/PORT_LOG.md`.

One donor test (`test_current_artifact_is_reused_without_quarantine`) is order-dependent and
flakes. It is logged as R-02; do not "fix" it in the new repo, which does not share its fixtures.

## 6. The prompt to give OMP

Run from anywhere; `--cwd` takes a **native** path (the POSIX `/c/Users/...` form is rejected by
native tools, and `--cwd` is passed to one):

```bash
omp --cwd "C:/Users/cubeb/orca/projects/ShortsFactoryAI-Studio" \
    --approval-mode=write --max-time=2h \
  "Continue the ShortsFactoryAI Studio build from docs/HANDOFF.md section 4, starting at step 1.
   Read AGENTS.md and docs/HANDOFF.md in the working directory first.
   Rules that are not negotiable: no credential in any output, no unverified success, no silent
   mock, and the layering in tests/test_architecture.py stays intact.
   Work step by step. After each step run the gate commands from AGENTS.md section 2 and report the
   real output. Do not claim a command passed if you did not run it. Do not touch git remotes, do
   not publish anything, do not install global tools.
   Step 1: run npm --prefix apps/dashboard run typecheck and report every error it emits."
```

Notes on the flags:

- `--cwd` sets the working directory without relying on the shell's `cd`, and OMP auto-discovers
  `AGENTS.md` there. That auto-discovery is exactly why the product's agent inventory was moved to
  `docs/AGENT_CONTRACTS.md`: otherwise the coding agent reads "ResearchAgent → research.json" as an
  instruction addressed to itself.
- `--approval-mode=write` lets it edit files and run non-destructive commands without a prompt per
  edit, while still asking before anything dangerous. Use `always-ask` if you want to watch.
- `--max-time=2h` bounds the session; a bounded agent reports honestly instead of drifting.
- Do **not** use `@file` syntax on the first prompt for files under `docs/` — OMP resolves `@` as a
  file attachment and a trailing sentence after it is parsed as part of the filename. Point at the
  files in prose instead, as above.

Expect step 1 to fail with real type errors in `StudioScene.tsx`, `StudioFallback.tsx` and
`states.tsx` (typecheck has never been run). That failure is the task, not a blocker.

## 7. Things that will bite the next agent

- `NODE_ENV=production` is exported in this shell → a bare `npm install` prunes every
  devDependency and `vitest`/`tsc` vanish. Always `npm install --include=dev --no-audit --no-fund`.
- Never pipe `node`/`python` into `tail`/`head` on this host; it dies with `stdin is not a tty`.
- Native tools need native paths: `C:/Users/...`, not `/c/Users/...`.
- A patch tool can write a literal `***` over code and still report success. After every patch:
  `grep -n '\*\*\*' <file>` and `python -c "import ast;ast.parse(open(p,encoding='utf-8').read())"`.
- The 3D scene must never be the only path to a function — every zone is also a sidebar link.
- `data/`, `config/studio.json`, `config/studio-history/` are operator runtime state. Never
  `git add -A`.

## 8. Definition of done for the current phase

A job created in the browser with the mock transport runs to `STORYBOARD_READY`, is visible in the
job list with live events, can be cancelled mid-run, and the studio shows exactly the agents that
the event log says are working — verified in Playwright, with `typecheck`, `vitest`, `pytest` and
`ruff` all green in the same run.
