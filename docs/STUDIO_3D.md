# STUDIO_3D — the interactive virtual studio

## 1. What it is

A read-only projection of the persisted event log. It renders what happened. It never causes
anything to happen. Clicking a workstation navigates to a module; clicking a character opens an
inspector. Neither starts, stops, or advances work.

## 2. Layout

Isometric room, 16 × 12 units, ten zones:

| Zone | Agent(s) | Workstation prop | Working animation |
| --- | --- | --- | --- |
| Director office | `DirectorAgent` | desk, storyboard wall | pacing, pointing at wall |
| Research desk | `ResearchAgent` | terminal, paper stacks | typing, flipping pages |
| Writing room | `ScriptAgent` | typewriter, lamp | typing |
| Review corner | `CreativeDirectorAgent` | armchair, tablet | reading, nodding |
| Storyboard desk | `StoryboardAgent` | drafting table | drawing |
| Animation bay | `AnimationAgent`, `AssetAgent` | dual monitor, lightbox | operating, dragging |
| Audio booth | `AudioAgent` | mic, headphones, waveform | speaking, adjusting |
| Edit suite | `EditorAgent` | timeline monitor | scrubbing |
| QC room | `QualityAgent` | wall of previews | watching, annotating |
| Publishing dock | `MetadataAgent`, `PublisherAgent` | parcel chute, screen | packing, sending |

The studio page combines the room with a selectable production-stage strip and a crew list.
Selecting a stage focuses its zone and filters the crew list; **Semua ruang** restores the whole
team. By default the strip summarises agent activity across jobs. **Pantau produksi** selects a
single persisted job and scopes the room, crew, inspector, and strip to its events. Neither mode
infers a pipeline percentage from historical stage completions.

Registered workstation occupants remain inspectable when a snapshot has no entries. These
unassigned visual occupants carry no job, model, progress, or event and never animate work.
An empty production history explains how to create a brief and start its job from **Produksi**.
The inspector explains the agent's production role, shows recorded model/task/progress/events,
and links to the existing agent settings and, only when present, its job.


## 3. Visual language

- Stylised isometric, clay-like: `MeshStandardMaterial` with `roughness 0.85`, `metalness 0.0`,
  soft `MeshSoftShadow`-style contact shadows.
- Palette: warm neutral walls (`#e8e0d4`), wood (`#b08454`), deep teal accents (`#2f6f6a`),
  amber light (`#f4bc68`). Same token set as the 2D UI, so the studio does not look like a
  different product.
- Lighting: one key `directionalLight` (warm, 35° elevation), one `ambientLight` at 0.45, one
  hemisphere for bounce. No HDR environment map (bundle size, and it fights the clay look).
- Restrained motion: idle breathing at 0.6 Hz, no bouncing, no floating UI, no particles.

Design dials: **ENERGY 2 / RHYTHM 2 / MOTION 2**.

- Dark surfaces keep the creative workbench subordinate to the warm clay room.
- Teal marks selection; amber draws attention to recorded problems rather than decorating every zone.
- The room leads the composition; the stage strip provides navigation, not a second metrics dashboard.
- System UI typography stays readable on Windows and requires no font download.
- Compact stage spacing supports scanning; larger room and crew spacing supports selection.
- Character anatomy and workstation motifs identify the production crew, not fictional human team members.
- Camera transitions explain a change of focus; work motion still requires a live persisted working state.

- Low-poly: hard cap of 30 k triangles for the whole scene.

## 4. Character state machine

```
                 event(status)
   ┌───────────────┬──────────────┬─────────────┬──────────────┐
   v               v              v             v              v
 idle  <──────  working  ────> reviewing ──> completed ──> idle (after 2 s)
   |               |              |
   └──────────> blocked / failed  ──> idle (when a new event arrives)
```

Rules:

- A character animates `working` **only** while the latest event for that agent has
  `status == "working"` and its lease is not expired.
- Lease expiry is computed server-side. The client never decides staleness from a timer, so a
  closed laptop lid cannot leave a character typing forever.
- `completed` is a one-shot 2 s reaction, then `idle`. It never loops.
- `blocked` and `failed` are sticky until a new event for that agent arrives, and they raise a
  visible badge in the sidebar, not just an in-world icon.

## 5. Interaction

| Input | Result |
| --- | --- |
| Hover character | name + role tooltip, subtle rim light |
| Click character | inspector: production role, recorded model/task/status/progress, last five job events, agent settings, and a link to the associated job |
| Hover workstation | zone highlight |
| Click workstation | navigate to the module for that stage |
| Drag | orbit within ±35° azimuth, ±20° polar; no free-fly |
| Scroll | dolly 0.7×–1.6× |
| `F` | focus the selected zone, 400 ms eased camera move |

Camera transitions use a single tweened `Vector3` target with `easeInOutCubic`, 400 ms. No
springs, no overshoot.

## 6. Performance

| Tier | DPR | Shadows | Post | Target |
| --- | --- | --- | --- | --- |
| `high` | ≤ 1.5 | soft | none | 60 fps desktop GPU |
| `medium` | ≤ 1.25 | contact only | none | 60 fps integrated |
| `low` | 1.0 | off | none | 30 fps |
| `off` | — | — | — | 2D fallback, full workflow available |

Additional rules:

- `frameloop="demand"` when the document is hidden or the tab is not visible.
- Auto-downgrade: if median frame time over 3 s exceeds 33 ms, drop one tier and persist the
  choice for that session only.
- The studio pauses rendering (frameloop stops) while a `RENDERING` event is active and free
  GPU memory is below 1 GB, because the render job has priority. It shows a "render in
  progress — studio paused" banner rather than silently freezing.
- The 2D fallback is an illustrated production floor: responsive zones contain selectable crew
  portraits and role-specific workstation drawings, with the same agent state mapping and module links.
  Native buttons provide keyboard/touch selection; the floor scrolls inside the room on narrow screens.
- Every zone's module link now resolves to a real page, and for the job-scoped zones
  (`/storyboard`, `/assets`, `/jobs`) it carries the currently selected `job_id`, so the studio
  opens exactly the job the operator was watching. A zone with no route renders an honest
  disabled span rather than a dead anchor, and `fallback-routes.spec.ts` walks each one.
- Renderer errors and WebGL context loss switch to that 2D floor with an explanation and a
  **Coba 3D lagi** action. Recovery is session-only and does not overwrite the operator's saved quality.

**What is actually implemented, and what is not.** The pause is real and it is narrower than the
rule above: `renderingActive(agents)` pauses and shows a "render sedang berjalan — studio dijeda"
banner whenever an agent's `stage` is `RENDERING` and its resolved state is `working`
(`apps/dashboard/src/three/sceneState.ts`); a stale lease resolves to `waiting` and does **not**
pause, and no other stage pauses anything. The GPU-memory half of ADR-008 is **not implemented:
free GPU memory is not observable from the browser** here, so the banner's `title` says so and
claims no measurement. Auto-downgrade is one `useFrame` sampler in `StudioScene` that accumulates
frame deltas and evaluates the median of each 3 s window; a median above 33 ms drops exactly one
tier (`nextTierOnFrameTime`), `low` is the floor, and 33 ms or below changes nothing. The
downgrade is **session-only**: it never writes `shorts-studio-quality`, so the operator's stored
tier — and the dropdown, which still shows that tier — is untouched; the effective tier is
observable as `data-effective-quality` on `[data-studio-scene]` while `data-quality` keeps
reporting the operator's choice.

## 7. Testing

- Vitest: state derivation from events (every status → animation state, stale lease → waiting),
  unassigned crew inspection, workflow selection/reset, and real orthographic projection scale.
- Playwright: with a seeded event log, assert each character's `data-state` attribute matches
  the persisted event, and that no character has `data-state="working"` when the log has none.
- Scoped subscription regressions cover delayed responses/errors after a job change, reordered
  snapshots, reconnect/unmount cleanup, query encoding, and render safety from other jobs.
- Monitor regressions cover late details, absent/deleted selections, and independent list/detail
  error recovery without silently changing the operator's selection.
- Geometry test: canvas has non-zero size, no WebGL context loss after 5 s, and the 2D fallback
  mounts when `quality=off`.
- Accessibility: every zone is also reachable from the sidebar list, so the 3D scene is never
  the only path to a function.

## 8. Orthographic framing

The camera uses an explicit world-unit frustum fitted to the canvas aspect ratio. Zoom is a
dimensionless 0.7–1.6 multiplier, not the inverse room extent applied to R3F's default
pixel-sized frustum. The latter shrank the whole room to only a few pixels even though the
canvas, meshes, and DOM state mirror all existed. Projection checks therefore measure floor
coverage and character height in screen pixels, not merely camera metadata.

OrbitControls polar angles are measured from the Y axis; the isometric floor elevation is
converted to that convention. Resetting focus restores the room centre, isometric pose, and
base zoom. Agent labels live in one React-owned DOM overlay, projected from the camera, so
switching quality does not create per-character portal roots.
On narrow canvases, the overview keeps labels hidden so they cannot cover the crew. Selecting
a production zone reveals only that zone's labels; the full crew list remains available below.


## 9. Per-job production monitoring

The read-only monitor reuses the existing job list/detail endpoints. It shows persisted state,
whether the worker is running, explicit mock/live mode, actual video availability, recent state
transitions, and artifact names. Secondary records are inside a native disclosure so the room
remains the main work surface. `last_error` is labelled historical; its presence alone does not
mean a currently advancing job failed.

The selected id is the `job_id` query parameter. **Buka detail produksi** preserves it on the
production page; **Pantau di studio** returns to the same scope. Selecting **Semua job** removes
only that parameter. Browser history changes update the scope. A missing/deleted id stays
selected with an explanation and retry, rather than silently switching the operator to another job.

`useStudio({ jobId, pollMs })` binds each read/connection lifecycle to one selection generation.
Changing scope masks the previous projection immediately, even before effects run. Late
responses, errors, stream callbacks, and reconnect timers from the previous generation cannot
replace it. A slower same-scope read cannot rewind either snapshot.

The SSE stream and resume cursor remain global. A selected view reads a scoped snapshot plus
an unfiltered snapshot together: only scoped agents reach the room/inspector, while the
unfiltered projection preserves the render pause when a different job is rendering. A stale
working lease does not pause the studio. All-job mode uses just its single unfiltered read.

No selection, polling, retry, disclosure, or navigation action creates, runs, cancels, approves,
or publishes a job.

