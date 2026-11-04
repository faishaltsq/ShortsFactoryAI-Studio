# ADR 0014 — One warm editorial design system, light by default

Status: accepted (implemented in this change)

## Context

The renderer had no design system. Each of the nine templates invented its own colors, sizes and
entrances; the fixtures calibrated against a dark `midnight` theme with Inter/system fonts; the
default theme (`editorialLight`) was a teal-on-mint accent no brief ever asked for; contract palette
ids (`circuitDark`, `oceanFloor`, `dusk`) silently fell back to a theme nobody picked; and the
Python `StoryboardArtifact` default (`dusk`) resolved to `editorialLight` — a third identity. The
output looked like a generic dashboard, not a publication.

## Decision

**Warm editorial, light-first. One token set, three font roles, restrained motion.**

1. **Light is the global default.** `editorialLight` (parchment `#FAF7F2`, espresso ink `#241C15`,
   terracotta `#D97757`) is the base for all content. Dark themes remain available as justified
   exceptions (space/night/mood) and share the same warm shell; they are no longer the calibration
   default.

2. **Semantic tokens are the single source of color.** `src/themes/tokens.ts` defines `ThemeTokens`
   (background/surface/elevatedSurface/textPrimary/textSecondary/textMuted/accent/accentDeep/
   accentSoft/line/highlight/chartColors/status/shadow) plus `DEFAULT_TOKENS` and topic variants
   (energy, science, infrastructure). `resolveTheme()` always attaches `tokens`; a dark theme can
   never render with light tokens. Legacy `ThemeSpec` color fields remain for compatibility.

3. **Three font roles.** Fraunces (display serif), Manrope (body/captions), IBM Plex Mono
   (numbers/technical labels), declared in `src/themes/type.ts` as `FONT_ROLES` + `TYPE_SCALE`
   (9 levels, 1080x1920-calibrated) + `SAFE_AREA` (top 220, bottom 420, left 72, right 120).
   `src/components/Typography.tsx` exposes Display/Headline/Title/Subheading/Body/Caption/Kicker/
   Metric/Label/Highlight/StackedLayout as pure React consumers of the tokens.

4. **Fonts are vendored, not fetched.** `packages/video/public/fonts/*.woff2` (11 Latin subsets)
   load through `@remotion/fonts` in `src/fonts.ts`, imported once by `Root.tsx`. Rendering is
   offline-deterministic; no runtime network fetch.

5. **Motion is editorial.** `src/components/motion.ts` replaces the old pop/slide presets:
   maskedReveal, staggeredWordReveal, softSlideFade, scaleEmphasis, lineDraw, gentleCount,
   cohesiveGroupReveal — springs with damping >= 22 (no bounce), eased with `smoothOut`.

6. **YouTube chrome is a hard layout constraint.** No informative element above y=230 or below
   y=1500. `SafeArea` defaults to bottom 420; the stills QC gate (`verify-template-stills.mjs`)
   asserts the frame-edge band matches the theme background luma (theme-relative, so it holds for
   light and dark).

## Consequences

- All nine templates, the caption/chrome components, and the art layer (palette, Stage,
  Environment, Prop, objects) consume tokens; hardcoded hex/rgba in render paths is gone except
  for intrinsically-colored object identity colors, harmonized toward the warm palette.
- `THEMES` covers every contract palette id; `resolveTheme` fallback is now deliberate, not silent.
- Benchmarks: `verify-template-stills.mjs` + `still-smoke.mjs` pass 9/9 against
  `fixtures/all-templates.json` (theme switched to `editorialLight`).
- `themes/__checks__/tokens.test.mjs` asserts WCAG AA contrast on all text pairs, scale monotonicity,
  font-role wiring and safe-area geometry; run with `node src/themes/__checks__/tokens.test.mjs`.
