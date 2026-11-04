import type React from 'react';

/**
 * Typography role and scale system for ShortsFactoryAI video engine.
 * Target viewport: 1080x1920 vertical video (9:16 mobile viewing distance).
 *
 * Font hierarchy:
 * - Display (editorial serif): Fraunces — headlines, hooks, hero statements, emphasis
 * - Body (humanist sans): Manrope — captions, subtitles, explanations, UI text
 * - Technical (mechanical mono): IBM Plex Mono — numbers, metrics, chart labels
 *
 * Note: src/fonts.ts will load woff2 font files via @remotion/fonts and alias these family strings.
 *
 * ponytail: static pixel scale for 1080x1920; add container-query relative scaling when non-vertical formats land.
 */

export const FONT_FAMILIES = {
  display: 'Fraunces',
  body: 'Manrope',
  technical: 'IBM Plex Mono',
} as const;

export type FontRole = keyof typeof FONT_FAMILIES;

// src/fonts.ts wires these family strings to vendored woff2 files in packages/video/public/fonts
export const FONT_ROLES: Record<FontRole, string> = {
  display: `"${FONT_FAMILIES.display}", Georgia, serif`,
  body: `"${FONT_FAMILIES.body}", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`,
  technical: `"${FONT_FAMILIES.technical}", "SF Mono", Menlo, Consolas, monospace`,
} as const;

export type TypeScaleLevel =
  | 'displayXl'
  | 'displayLg'
  | 'heading'
  | 'subheading'
  | 'body'
  | 'bodySmall'
  | 'caption'
  | 'techLabel'
  | 'micro';

export interface TypeStyle {
  readonly fontSize: number;
  readonly fontWeight: number;
  readonly fontFamily: string;
  readonly role: FontRole;
  readonly letterSpacing: string;
  readonly lineHeight: number;
  readonly textTransform?: 'none' | 'uppercase' | 'lowercase' | 'capitalize';
}

/**
 * Editorial typographic scale tuned for 1080x1920 mobile viewport.
 * Titles adhere to ADR-0012 title band (88-168px).
 * Captions guarantee mobile readability (>= 34-40px on 1080w stage).
 */
export const TYPE_SCALE: Record<TypeScaleLevel, TypeStyle> = {
  displayXl: {
    fontSize: 116,
    fontWeight: 700,
    fontFamily: FONT_ROLES.display,
    role: 'display',
    letterSpacing: '-0.03em',
    lineHeight: 1.05,
  },
  displayLg: {
    fontSize: 88,
    fontWeight: 600,
    fontFamily: FONT_ROLES.display,
    role: 'display',
    letterSpacing: '-0.025em',
    lineHeight: 1.12,
  },
  heading: {
    fontSize: 64,
    fontWeight: 600,
    fontFamily: FONT_ROLES.display,
    role: 'display',
    letterSpacing: '-0.02em',
    lineHeight: 1.20,
  },
  subheading: {
    fontSize: 48,
    fontWeight: 500,
    fontFamily: FONT_ROLES.body,
    role: 'body',
    letterSpacing: '-0.01em',
    lineHeight: 1.28,
  },
  body: {
    fontSize: 40,
    fontWeight: 400,
    fontFamily: FONT_ROLES.body,
    role: 'body',
    letterSpacing: '0em',
    lineHeight: 1.38,
  },
  bodySmall: {
    fontSize: 34,
    fontWeight: 400,
    fontFamily: FONT_ROLES.body,
    role: 'body',
    letterSpacing: '0.005em',
    lineHeight: 1.40,
  },
  caption: {
    fontSize: 38,
    fontWeight: 600,
    fontFamily: FONT_ROLES.body,
    role: 'body',
    letterSpacing: '0.01em',
    lineHeight: 1.30,
  },
  techLabel: {
    fontSize: 32,
    fontWeight: 500,
    fontFamily: FONT_ROLES.technical,
    role: 'technical',
    letterSpacing: '0.04em',
    lineHeight: 1.30,
  },
  micro: {
    fontSize: 24,
    fontWeight: 700,
    fontFamily: FONT_ROLES.body,
    role: 'body',
    letterSpacing: '0.12em',
    lineHeight: 1.20,
    textTransform: 'uppercase',
  },
} as const;

/**
 * Mobile Safe Area definitions for 1080x1920 vertical video (9:16).
 * Aligns with ADR-0012 9:16 layout rules (.safe scale 0.78).
 * Accounts for YouTube Shorts persistent chrome:
 * - Top: Status bar, back arrow, search/sound pill
 * - Bottom: Channel handle, subscribe button, audio marquee
 * - Right: Action rail (like, comment, share buttons)
 */
export const SAFE_AREA = {
  stageWidth: 1080,
  stageHeight: 1920,
  top: 220,
  bottom: 420,
  left: 72,
  right: 120,
  safeWidth: 888,
  safeHeight: 1280,
  scaleFactor: 0.78, // ADR-0012 safe scale
} as const;

export const PREVIEW_SCALES = {
  full: 1.0,
  adrSafe: SAFE_AREA.scaleFactor,
  half: 0.5,
  quarter: 0.25,
} as const;

/**
 * Scales a type style object for smaller previews or ADR-0012 .safe container.
 */
export const scaleTypeStyle = (
  style: TypeStyle,
  scaleFactor = 1.0
): React.CSSProperties => ({
  fontSize: Math.round(style.fontSize * scaleFactor),
  fontWeight: style.fontWeight,
  fontFamily: style.fontFamily,
  letterSpacing: style.letterSpacing,
  lineHeight: style.lineHeight,
  ...(style.textTransform ? { textTransform: style.textTransform } : {}),
});
