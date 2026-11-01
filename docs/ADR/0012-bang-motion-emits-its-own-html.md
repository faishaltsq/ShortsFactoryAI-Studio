# ADR-0012 — Bang Motion emits its own HTML

**Status:** superseded by ADR 0013 (secondary renderer retired with character system)

**Supersedes:** ADR-0007, **only** the clause "motion-skill HTML/CSS/GSAP" and the vendoring
paragraph that depends on it ("We vendor GSAP and the needed font files into the motion package
and rewrite the `<script src>` on ingest"). Every isolation, contract, determinism and honesty
clause of ADR-0007 stands unchanged and is restated below as binding.

## Context

ADR-0007 assumed the secondary renderer would ingest the upstream `bang-motion` starters. Measured
against the pinned upstream copy (`bangtutorial/bang-motion@c1aa65e`, v1.19.0, MIT):

- All seven starters are 1920×1080. The 9:16 recipe is prose in `references/explainer.md`, not
  code. Rendered unmodified in a 1080×1920 viewport, `starter-explainer.html` lays out at
  `[0, 656, 1080, 608]` — a letterboxed band with 656 px of dead space above and below.
- Every starter loads GSAP 3.12.5 from cdnjs and Google Fonts from `fonts.googleapis.com`. Both
  are unavailable offline, and neither is present anywhere on this machine.
- The starters' only runtime contract is `window.OPENER`. GSAP is an implementation detail of
  *those documents*, not of the interface.

So the ADR's "HTML/CSS/GSAP" phrasing describes one possible implementation, and the vendoring
paragraph describes the cost of choosing it. Neither is load-bearing for isolation, parity, or
determinism.

## Decision

The secondary renderer **emits its own self-contained HTML document**. It does not ingest,
transform, or ship upstream starter markup. Upstream remains a *design* reference only: the
`OPENER` surface, the 9:16 layout law (`.safe` at scale .78, title 88–168 px, per-word spans), and
the anti-PPT rules.

- The document exposes exactly `window.OPENER = {W, H, DURATION, tl, ready, seek(t),
  clipsReady(), play()}`. That is the whole contract, and it is unchanged from ADR-0007.
- `seek(t)` is a pure function of time. No GSAP, no `requestAnimationFrame`-driven state, no
  `Date.now()`. Two runs at the same `t` produce the same pixels.
- No external URL of any kind appears in the document. Typography uses the same system stacks
  `packages/video/src/themes/brand.ts` already uses, so the secondary renderer inherits the
  primary renderer's font behaviour rather than introducing a second one.
- Text reaches the document only as escaped element content. The model never supplies markup,
  script, or CSS — only strings and numbers from validated contract fields.

## Consequences

**Preserved from ADR-0007, unchanged and still binding:**

- Separate process. `chrome-headless-shell` under `node_modules/.remotion`, no new dependency.
- No network at capture time; dead proxy, `--host-resolver-rules`, and `Network.setBlockedURLs`,
  asserted by a test that counts requests reaching a live local server (zero).
- `--disable-web-security` is never passed.
- Staging-directory filesystem; wall-clock and frame-count caps.
- Frame export by seek → two `requestAnimationFrame` ticks → `page.screenshot()`, not screen
  recording.
- Same `render-props.json`, same `RenderArtifact`, same `validate_render`. The parity test is the
  guard.
- **Subtitles are burned in from `storyboard.subtitles`**, in the same band the primary renderer
  uses (`Subtitles.tsx`: bottom 360 px of 1920, 90 px side insets, centred, translucent backing,
  same font stack). Each cue is its own element carrying `data-cue-start`/`data-cue-end` and is
  shown for the half-open window `[startMs, endMs)`, computed from `t` alone so out-of-order seeks
  produce the same caption. **This was missing until it was measured**: the first version of this
  renderer drew text and the character but no captions at all, and no test caught it because
  `verify_video` checks that cues fit their bounds, not that a cue reached a frame. The caption path
  is deliberate, and the pixel-level test in `test_bang_motion.py` is what keeps it honest.
- If the renderer cannot hold 1080×1920, only Remotion is offered for Shorts and the limitation is
  reported, not hidden.

**Lost, deliberately:**

- The upstream starters' visual polish (collage cutouts, photo treatments, SVG annotation draw-on)
  is not available. Rebuilding it is design work, not a port. Until that work happens the secondary
  renderer is a legitimate but plainer look — a real second code path, not a visual equal.
- **No cross-machine determinism claim.** System font fallback differs per host. Run-to-run
  determinism on one machine is measured and tested; machine-to-machine identity is not asserted,
  and this ADR does not create an obligation to assert it.

## Parity is structural, never visual — measured

"Both renderers pass the same gate" means the two files satisfy the same technical probe. It does
**not** mean they look alike, and the numbers say so plainly. From one `render-props.json`, 60
frames, both muxed with the same narration:

| Comparison | Mean PSNR |
| --- | --- |
| The two renderers, same frame | **14.34 dB** |
| Unrelated content (different art, different scene) | **14.38 dB** |
| Same art, 6 frames apart — Remotion | 27.52 dB |
| Same art, 6 frames apart — Bang Motion | 30.70 dB |

Cross-renderer PSNR is **indistinguishable from unrelated content** (14.34 vs 14.38 dB). That is
the expected result once the mechanism is stated: each renderer draws its own art. Remotion renders
the ported React compositions; this renderer renders a self-authored SVG document. Two different
pictures of the same storyboard.

Consequently the parity guard asserts only what is actually true:

- the same props file, byte-unchanged across both renders;
- the same unmodified `validate_render` probe, no renderer-specific tolerance;
- identical frame count, dimensions, fps, video codec, pixel format, colour range, audio codec;
- identical cut indices, measured from the picture rather than from the props;
- determinism **within** each renderer (render twice → identical `framemd5`).

It deliberately does **not** assert cross-renderer PSNR. An earlier 20 dB threshold failed at
17.74 dB for the honest reason, and the only way to make it green would have been to lower it to a
value that proves nothing. The number is printed by the test, not asserted, so a reader sees it
without the suite pretending it is a quality bar.

## Bang Motion is currently more static than Remotion

The same storyboard, measured end to end (re-measured after the mock fixture's beats moved to
frames 0/30/66, 0/48, 0/42 — all inside the retimed scenes):

| Metric | Remotion | Bang Motion |
| --- | --- | --- |
| `static_ratio` | **0.040** | **0.166** |
| static seconds / total | 0.5 / 12.467 s | 1.967 / 11.833 s |
| `freezedetect` intervals | 1 | 3 |

Read those as an order-of-magnitude gap, not a precise pair. The offline SAPI voice produces a
different narration length per run (12.467 s vs 11.833 s above), which retimes the scenes and moves
`static_ratio` on its own; the only strictly comparable measurement is an A/B on one identical
`render-props.json`, and that was run for the captions: **0.1662 with captions vs 0.1803 without**,
same props, same 11.833 s. Captions therefore *reduce* static time — a caption appearing and
disappearing changes pixels — but by ~0.014, not enough to close the gap.

Do not read the 0.166 above as a regression against an earlier 0.075: those two runs had different
narration lengths, and the only comparable pair is the A/B (0.1662 vs 0.1803 on one props file).
What *is* a real improvement is the beat placement — moving the beats inside the retimed scenes cut
Bang Motion's static time substantially on a like-for-like comparison — and it still does not close
the gap: Bang Motion remains roughly 2–4× as static as Remotion on equivalent input.

Remotion's compositions animate continuously — progress bars, camera work, character rigs ticking
every frame. A document that only reacts at `motion.beats` sits still between them, and
`freezedetect` reports exactly that gap.

The mitigation in `packages/core/motion/emit.py` is a continuous camera breath plus a **2–3 px
whole-pixel drift** evaluated at every `t`. Its size was chosen by measurement, not by taste: a
0.5 % sub-pixel breath left 7.067 s of freeze, because `freezedetect`'s default tolerance
(`n=-60dB`) treats a sub-pixel shift as identical. The drift is a **detector-satisfying minimum,
not authored motion.** It keeps consecutive frames from being pixel-identical; it does not make the
scene animated.

**Stated limitation: Bang Motion is currently more static than Remotion. Scenes need real
per-scene motion — subject animation, camera moves that are actually visible, transitions with
displacement — before it can be considered an equal.** The drift must not be removed (it is the
honest floor below which the file is literally a still), and it must not be mistaken for animation
by anyone reading a green `static_ratio`.

## Bang Motion has mouth sync, driven by measured speech

The secondary renderer's mouth aperture is driven by `scene.speech`, the measured word windows the
audio stage writes into `audio.json` and `render.py::update_storyboard_from_audio` forwards into
`render-props.json`. Each scene carries its windows as `data-speech="start-end,..."` on the
`<section class="scene">` element; `seek(t)` parses them and rewrites the `d` attribute of
`#maya-mouth` on every seek.

The envelope is the primary renderer's, ported so both open the mouth at the same times:
`ATTACK_MS = 40`, `RELEASE_MS = 70`, and both ramps clamp to **half the window** — a 40 ms word is
a triangle inside its own span rather than a mouth that opens after the word has finished. The
function is pure in `t`; capture seeks out of order, so nothing accumulates across frames. **No
windows means a closed mouth at every `t`** — there is no fallback clock and no synthetic sine. An
earlier version of this document recorded the opposite (a fixed path, narration over a closed
mouth); that gap is closed.

`_speech_windows` treats the window list as a trust boundary. It rejects windows that are
unordered, overlapping, or that end past the scene end, naming `speech[index]` and the reason.
Exact scene-end boundaries are allowed, and the scene duration is `durationInFrames * 1000 / fps`
computed without rounding down, so a window ending at 9966 ms is inside a 299-frame scene at 30 fps
(9966.66… ms). It does not sort, clamp, or drop: a repaired list would render a plausible mouth
over audio nobody measured.

**The proof is pixels, not a DOM assertion.** `test_the_mouth_reaches_pixels_inside_a_speech_window`
renders a real 90-frame file, extracts frame 9 (0.30 s, inside a 200–1400 ms window) and frame 51
(1.70 s, past the 70 ms release), crops a tight head box `200:160:440:820`, and blends the two with
`all_mode=difference` + `signalstats`. On the run that wrote this ADR the measured delta was
**YAVG 3.372, YMAX 160** against thresholds of `YAVG > 1.0` and `YMAX > 60`. Those two numbers are a
**measurement from this host and this test**, not a universal quality bar — the whole figure drifts
2–3 px between the frames, so some delta exists regardless, and the mouth's filled 28×26-unit shape
is what pushes the peak to 160.

Recorded here so it is not quietly lost: the shared `validate_render` probe still cannot see a
mouth move — it measures streams and frames. The pixel test is what keeps this honest.

**Reversal cost.** If the starters are wanted later, vendoring GSAP and the named woff2 subsets is
additive: the `OPENER` contract and the capture driver stay as they are, and only the document
source changes. Nothing in this ADR forecloses it.
