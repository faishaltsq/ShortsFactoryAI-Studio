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

## 3. Visual language

- Stylised isometric, clay-like: `MeshStandardMaterial` with `roughness 0.85`, `metalness 0.0`,
  soft `MeshSoftShadow`-style contact shadows.
- Palette: warm neutral walls (`#e8e0d4`), wood (`#b08454`), deep teal accents (`#2f6f6a`),
  amber light (`#f4bc68`). Same token set as the 2D UI, so the studio does not look like a
  different product.
- Lighting: one key `directionalLight` (warm, 35° elevation), one `ambientLight` at 0.45, one
  hemisphere for bounce. No HDR environment map (bundle size, and it fights the clay look).
- Restrained motion: idle breathing at 0.6 Hz, no bouncing, no floating UI, no particles.
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
| Click character | inspector drawer: name, role, current task, bound provider/model, status, progress, last 20 log lines, artifacts produced, last error, available actions (cancel job, open stage) |
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
- The 2D fallback is not a degraded grid of boxes: it is the same room layout in flat SVG with
  the same state colours, so the operator can still see who is doing what.

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

- Vitest: state derivation from events (every status → animation state, stale lease → idle).
- Playwright: with a seeded event log, assert each character's `data-state` attribute matches
  the persisted event, and that no character has `data-state="working"` when the log has none.
- Geometry test: canvas has non-zero size, no WebGL context loss after 5 s, and the 2D fallback
  mounts when `quality=off`.
- Accessibility: every zone is also reachable from the sidebar list, so the 3D scene is never
  the only path to a function.
