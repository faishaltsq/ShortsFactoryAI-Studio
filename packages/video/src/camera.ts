/**
 * Declared camera (`SceneSpec.camera`) → a concrete stage transform.
 *
 * ## Precedence, stated once
 *
 * The renderer has two camera vocabularies and they must not both author the same frame:
 *
 * 1. `SceneSpec.camera` — the product's declaration (`shot`/`move`/`target`/`amplitude`/`ease`),
 *    validated in Python and re-checked by `product-adapter.ts`. **When present it owns the scene
 *    transform**: its `shot` sets the base framing scale and its `move` is the only movement.
 * 2. `data.shots[].camera` — the renderer's own per-shot table (`pushIn`, `panLeft`, …). It stays
 *    authoritative for scenes that declare no camera, which is what keeps every donor storyboard
 *    (and `fixtures/all-templates.json`) rendering exactly as before. When a declared camera
 *    exists, the per-shot *move* is suppressed; `data.shots[].framing` still selects the shot and
 *    its cut, because shot selection is not camera movement.
 *
 * `static` is not "no camera": it is a declaration that the frame must not move, so the returned
 * transform is frame-invariant — no sines, no progress term, no easing residue. QA's `static_ratio`
 * is measured on pixels with `freezedetect`, so an accidental drift here is a real regression.
 */

import type {CameraEasing, CameraSpec, SceneSpec, ShotSize, TextStyleSpec} from './types';

export interface CameraTransform {
  scale: number;
  /** Pixels, applied before the scale so the value is a real screen offset. */
  x: number;
  y: number;
  rotate: number;
  /** Normalised transform origin — the subject the move is about. */
  originX: number;
  originY: number;
}

/** Framing scale per declared shot size. Gentle: the stage anchors on the subject's ground line. */
export const SHOT_SCALE: Record<ShotSize, number> = {wide: 1, medium: 1.1, close: 1.24};

/** Canonical vertical band per text role, as a fraction of the 1080×1920 frame. */
const ROLE_BAND: Record<TextStyleSpec['role'], number> = {
  kicker: 0.155,
  title: 0.2,
  highlight: 0.29,
  body: 0.42,
  caption: 0.58,
};

/** `SafeArea` is 260px from the top and 320px from the bottom, so `style.y` maps into that band. */
const SAFE_TOP = 260 / 1920;
const SAFE_BOTTOM = 1 - 320 / 1920;

const clamp01 = (value: number): number =>
  Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;

/** The nine easings the scene contract allows. `powerN` is an exponent on the remaining distance. */
export const EASING_FUNCTIONS: Record<CameraEasing, (t: number) => number> = {
  linear: (t) => t,
  'power1.out': (t) => t,
  'power2.out': (t) => 1 - (1 - t) ** 2,
  'power3.out': (t) => 1 - (1 - t) ** 3,
  'power4.out': (t) => 1 - (1 - t) ** 4,
  'power1.in': (t) => t,
  'power2.in': (t) => t ** 2,
  'power2.inOut': (t) => (t < 0.5 ? 2 * t ** 2 : 1 - (-2 * t + 2) ** 2 / 2),
  'sine.inOut': (t) => (1 - Math.cos(Math.PI * t)) / 2,
};

export interface TextAnchor {
  x: number;
  y: number;
}

/**
 * Resolve a camera target to the position of the text element it names.
 *
 * Vertical placement comes from the element's declared `style.y` (inside the safe area) or, when
 * it declares none, from its role's canonical band. Horizontal placement comes from its declared
 * alignment; every current template lays text out against the safe area, so centre is the honest
 * default rather than a measured position the renderer cannot know statically.
 */
export const textAnchorOf = (scene: SceneSpec, target: string | undefined): TextAnchor => {
  const element = target ? scene.text.find((candidate) => candidate.id === target) : undefined;
  if (!element) return {x: 0.5, y: 0.5};
  const {y, align} = element.style;
  const band =
    typeof y === 'number'
      ? SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP) * clamp01(y)
      : ROLE_BAND[element.style.role];
  return {x: align === 'left' ? 0.35 : align === 'right' ? 0.65 : 0.5, y: band};
};

/**
 * The transform for one frame of a declared camera.
 *
 * `frame` is scene-local. Amplitude is the fraction of a frame the move travels: a `push` of 0.12
 * ends at 112 % scale, a `pan` of 0.12 slides 6 % of the frame width, and both are exactly zero at
 * `amplitude: 0`.
 */
export const declaredCameraAt = (
  camera: CameraSpec,
  frame: number,
  durationInFrames: number,
  anchor: TextAnchor,
  viewport: {width: number; height: number},
): CameraTransform => {
  const base = SHOT_SCALE[camera.shot];
  const origin = {originX: anchor.x, originY: anchor.y};
  const still: CameraTransform = {scale: base, x: 0, y: 0, rotate: 0, ...origin};
  if (camera.move === 'static') return still;

  const span = Math.max(1, durationInFrames - 1);
  const eased = EASING_FUNCTIONS[camera.ease](clamp01(frame / span));
  const amplitude = clamp01(camera.amplitude);
  // A subject left of centre is panned toward from the right, and vice versa; a centred subject
  // pans left, which is a direction, not a hidden default.
  const dirX = anchor.x < 0.5 ? 1 : -1;
  const dirY = anchor.y < 0.5 ? 1 : -1;

  switch (camera.move) {
    case 'push':
      return {scale: base * (1 + amplitude * eased), x: 0, y: 0, rotate: 0, ...origin};
    case 'pull':
      return {scale: base * (1 + amplitude * (1 - eased)), x: 0, y: 0, rotate: 0, ...origin};
    case 'pan':
      // The over-scale is exactly what a translation of `amplitude/2` of the frame needs to keep
      // the edge covered: 2 · (amplitude/2) = amplitude.
      return {
        scale: base * (1 + amplitude),
        x: dirX * amplitude * 0.5 * viewport.width * eased,
        y: 0,
        rotate: 0,
        ...origin,
      };
    case 'tilt':
      return {
        scale: base * (1 + amplitude),
        x: 0,
        y: dirY * amplitude * 0.5 * viewport.height * eased,
        rotate: 0,
        ...origin,
      };
    case 'orbit':
      return {
        scale: base * (1 + amplitude * 0.75),
        x: dirX * amplitude * 0.15 * viewport.width * eased,
        y: dirY * amplitude * 0.05 * viewport.height * eased,
        rotate: dirX * amplitude * 6 * eased,
        ...origin,
      };
    default:
      return still;
  }
};
