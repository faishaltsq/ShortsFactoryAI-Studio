# Video Design System — Editorial Light Identity

**Target Viewport:** 1080×1920 vertical video (YouTube Shorts, mobile viewing distance)  
**Direction:** Warm editorial light mode ("Claude-like") — soft cream, warm parchment, sand, muted terracotta/amber, warm espresso text, restrained contrast, subtle depth, premium minimalism.

---

## 1. Semantic Color Token System

All values defined in `packages/video/src/themes/tokens.ts`.  
The identity uses **one cohesive brand shell**: background, surface slabs, text hierarchy, line dividers, and shadow depth are invariant. Only the accent family and chart sequence shift by topic.

### 1.1 Brand Shell Tokens

| Token | Value | Semantics & Usage | Contrast Ratio (on `#FAF7F2`) |
| :--- | :--- | :--- | :--- |
| `background` | `#FAF7F2` | Warm parchment cream. Stage canvas default. | 1.00:1 (Canvas base) |
| `surface` | `#F3EFEA` | Warm linen / muted sand. Sub-panels and slabs. | 1.07:1 |
| `elevatedSurface` | `#FFFFFF` | Crisp warm card white. Floating overlays and cards. | 1.08:1 |
| `textPrimary` | `#241C15` | Deep warm espresso roast. Headlines, titles, primary body. | **15.70:1** (Passes AAA >= 7.0:1) |
| `textSecondary` | `#5C5248` | Warm charcoal stone. Subheadings, body commentary, subtitles. | **7.13:1** (Passes AAA >= 7.0:1) |
| `textMuted` | `#8C8175` | Warm taupe gray. Footnotes, metadata, chart ticks. | **3.57:1** (Passes AA >= 3.0:1) |
| `line` | `#E6DFD5` | Subtle warm rule line and card border. | 1.25:1 |
| `highlight` | `rgba(217,119,87,0.14)` | Subtle warm peach/terracotta keyword wash. | Non-text indicator |

### 1.2 Brand Accents & Topic Overrides

| Token Set | `accent` | `accentDeep` | `accentSoft` | `highlight` | Primary Domain |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Default (Editorial)** | `#D97757` | `#B85838` | `#FBECE4` | `rgba(217,119,87,0.14)` | General narrative, hook moments |
| **Energy** | `#D46B38` | `#A84A1C` | `#FBECE4` | `rgba(212,107,56,0.14)` | Power, economics, resources, heat |
| **Science** | `#4B7268` | `#34534B` | `#EBF2EE` | `rgba(75,114,104,0.14)` | Biology, computing, research, logic |
| **Infrastructure** | `#486581` | `#2E4861` | `#E8EEF5` | `rgba(72,101,129,0.14)` | Logistics, civic systems, hardware |

### 1.3 Chart Colors (Ordered Harmonic Sequence)

Accessible, distinct hues tested on `#FAF7F2` parchment:
1. `#D97757` (Claude Terracotta)
2. `#4B7268` (Eucalyptus Sage)
3. `#D29C44` (Warm Amber Ochre)
4. `#486581` (Slate Blue Steel)
5. `#935F7E` (Muted Mulberry)
6. `#758063` (Moss Olive)

### 1.4 Status & Shadow Tokens

- `status.success`: `#3A7D5C` (Restrained forest pine)
- `status.warning`: `#C27D23` (Warm ochre gold)
- `status.error`: `#BD3E33` (Editorial brick crimson)
- `shadow.sm`: `0 2px 8px rgba(36, 28, 21, 0.04)`
- `shadow.md`: `0 8px 24px rgba(36, 28, 21, 0.06)`
- `shadow.lg`: `0 20px 48px rgba(36, 28, 21, 0.08)`
- `shadow.float`: `0 28px 64px rgba(36, 28, 21, 0.12), 0 4px 12px rgba(36, 28, 21, 0.04)`

---

## 2. Typography Role & Scale System

All definitions in `packages/video/src/themes/type.ts`. Loaded via `@remotion/fonts` and aliased in `src/fonts.ts`.

### 2.1 Font Roles & Rationale

| Role | Font Family | Fallback Stack | Design Rationale |
| :--- | :--- | :--- | :--- |
| **Display** | **Fraunces** | `Georgia, serif` | Wonky, warm variable serif with soft curvature and sharp serifs. Replaces cold tech sans with an authoritative editorial, literary voice (reminiscent of Atlantic/NYT Magazine or Claude editorial). |
| **Body** | **Manrope** | `-apple-system, "Segoe UI", sans-serif` | Clean geometric humanist sans with high x-height and open apertures. Maximizes instant legibility on 5.5"–6.7" smartphone screens at rapid video pacing. |
| **Technical** | **IBM Plex Mono** | `"SF Mono", Consolas, monospace` | Engineered monospaced typeface with tabular figures. Grounds metrics, data shifts, timestamps, and percentages with precision without feeling retro. |

### 2.2 Type Scale (1080×1920 Stage)

Conforms to ADR-0012 title band rules (88–168px for hero titles) and mobile reading distance minimums (>= 34–40px for captions on 1080w viewport).

| Scale Level | Family Role | Font Size | Weight | Line Height | Tracking | Purpose / Usage |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `displayXl` | Display (`Fraunces`) | 116px | 700 (Bold) | 1.05 | `-0.03em` | Single-word impact, hero hooks, climax words |
| `displayLg` | Display (`Fraunces`) | 88px | 600 (Semi) | 1.12 | `-0.025em` | Major scene headlines, segment titles |
| `heading` | Display (`Fraunces`) | 64px | 600 (Semi) | 1.20 | `-0.02em` | Section headers, card titles, concept titles |
| `subheading` | Body (`Manrope`) | 48px | 500 (Med) | 1.28 | `-0.01em` | Core takeaways, thesis statements |
| `body` | Body (`Manrope`) | 40px | 400 (Reg) | 1.38 | `0.00em` | Explanatory narrative, multi-line exposition |
| `bodySmall` | Body (`Manrope`) | 34px | 400 (Reg) | 1.40 | `+0.005em` | Supporting details, footnotes, card notes |
| `caption` | Body (`Manrope`) | 38px | 600 (Semi) | 1.30 | `+0.01em` | Burned-in subtitles, lower-third speech cues |
| `techLabel` | Technical (`IBM Plex Mono`) | 32px | 500 (Med) | 1.30 | `+0.04em` | Axis markers, metadata tags, units, stats |
| `micro` | Body (`Manrope`) | 24px | 700 (Bold) | 1.20 | `+0.12em` | Uppercase kickers, badge tags, supertitles |

### 2.3 Mobile Safe Area Constants (9:16)

```ts
export const SAFE_AREA = {
  stageWidth: 1080,
  stageHeight: 1920,
  top: 220,       // Clears YouTube Shorts search & audio bar
  bottom: 420,    // Clears channel title, subscribe button, audio disc
  left: 72,       // Left margin
  right: 120,     // Clears right action rail (Like, Comment, Share)
  safeWidth: 888,
  safeHeight: 1280,
  scaleFactor: 0.78, // ADR-0012 .safe container scale
} as const;
```

---

## 3. Motion Language Rules

Implemented in `packages/video/src/components/motion.ts`.

### 3.1 Core Principles
1. **Zero Cartoon Bounce:** Damping is critically calibrated (`damping >= 22`). Spring motion settles with dignified precision rather than wobbling or ringing.
2. **Zero Glitch or Loud Pop:** No high-frequency RGB splits, jitter, or 0.4 -> 1.4 -> 1.0 zoom pops. Replaced with masked curtain reveals and gentle 14px directional glides.
3. **Decoupled Reading Speed:** Elements enter with deliberate staggering (`staggerFrames = 3`), allowing the viewer's eye to track word-by-word without motion blur.
4. **Cohesive Block Movement:** When an entire section transitions, child elements move together via `cohesiveGroupReveal` rather than independently flying in from random angles.

### 3.2 Motion Presets

- `maskedReveal`: Clip-path curtain wipe (`inset(0 0 H% 0)`) with `EDITORIAL_EASING.smoothOut`.
- `staggeredWordReveal`: Word-level upward settle (`translateY: 14px -> 0px`) + opacity ramp with high damping.
- `softSlideFade`: Restrained directional displacement (24px) for cards and paragraphs.
- `scaleEmphasis`: Subtle 0.97 -> 1.00 focus breath; zero overshoot.
- `lineDraw`: Horizontal/vertical `scaleX` expansion from left origin for accent lines and underlines.
- `gentleCount`: Paced numeric interpolation for statistics without abrupt snapping.
- `cohesiveGroupReveal`: Group fade + 12px upward settle for title blocks.

---

## 4. How Compositions Consume Tokens

### Custom-motion bootstrap

`render_custom_motion()` seeds the existing token, typography, motion, brand and font modules
into the job workspace. It imports `./fonts` once in the final root entry, including entries
that call `registerRoot` themselves. The existing `loadFont` calls hold Remotion until the
vendored faces load. An explicit `--public-dir` points at that workspace's assets.
`remotion.config.ts` resolves installed dependencies from the video package even when the
entry lives outside it; no global install or dependency symlink is required.

This supplies the design system, but does not force every generated drawing to use its tokens
or prove visual quality. `tests/test_custom_motion_design.py` verifies bootstrap idempotency
and renders a real three-frame fixture that fails if Fraunces, Manrope or IBM Plex Mono is
not loaded. It also probes the encoded dimensions, frame count and pixel format.

### 4.1 Strict Token Consumption Rules
- **No hardcoded hex or RGB strings in compositions.**
- Import `DEFAULT_TOKENS` or pass `tokens: ThemeTokens` into components.
- Use semantic roles: `tokens.textPrimary` for primary copy, `tokens.textSecondary` for commentary, `tokens.accent` for visual focus.
- Wrap titles and captions with `<Display>`, `<Headline>`, `<Title>`, `<Subheading>`, `<Body>`, `<Caption>`, `<Kicker>`, `<Metric>`, `<Label>`, `<Highlight>`, or `<StackedLayout>`.

### 4.2 Example Composition Usage

```tsx
import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {DEFAULT_TOKENS, resolveTokens} from '../themes/tokens';
import {Display, Subheading, Kicker, Highlight, StackedLayout} from '../components/Typography';
import {staggeredWordReveal, softSlideFade} from '../components/motion';

export const EditorialScene: React.FC<{topic?: string}> = ({topic}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const tokens = resolveTokens(topic);

  const words = "The Future of Nuclear Energy".split(" ");
  const subtitleMotion = softSlideFade({frame, fps, durationInFrames: 24, distance: 20});

  return (
    <div style={{position: 'absolute', inset: 0, backgroundColor: tokens.background}}>
      <div style={{position: 'absolute', top: 260, left: 80, right: 130}}>
        <StackedLayout gap={18}>
          <Kicker tokens={tokens}>Clean Transition</Kicker>
          
          <Display tokens={tokens}>
            {words.map((w, i) => (
              <span key={i} style={staggeredWordReveal({frame, fps, wordIndex: i})}>
                {w === 'Nuclear' ? <Highlight tokens={tokens}>{w}</Highlight> : w}{' '}
              </span>
            ))}
          </Display>

          <div style={subtitleMotion}>
            <Subheading tokens={tokens}>
              Why modern reactors produce 90% less waste than early designs.
            </Subheading>
          </div>
        </StackedLayout>
      </div>
    </div>
  );
};
```
