import type {ExpressionId} from './ids';
import {clamp, lerp} from './math';
import type {ExpressionTarget} from './types';

/**
 * Expression library. Each entry is a parameter set, not a drawing, so the same
 * face art can interpolate continuously between emotions.
 *
 * Units are relative to the face spec: browLift and gaze are in character units,
 * mouthWidth/mouthOpen are multipliers of the neutral mouth, and mouthCurve is a
 * signed bend (positive = smile).
 */
export const EXPRESSIONS: Record<ExpressionId, ExpressionTarget> = {
  neutral: {
    browAngle: 0,
    browLift: 0,
    eyeOpen: 1,
    gaze: {x: 0, y: 0},
    mouthWidth: 1,
    mouthOpen: 0,
    mouthCurve: 0.18,
    cheek: 0,
    blush: 0,
  },
  // One brow up, eyes slightly wide, mouth part-open: attention without alarm.
  curious: {
    browAngle: -7,
    browLift: 4.5,
    eyeOpen: 1.12,
    gaze: {x: 2.5, y: -2},
    mouthWidth: 0.86,
    mouthOpen: 0.3,
    mouthCurve: 0.06,
    cheek: 0,
    blush: 0.08,
  },
  // Squint + smile: the eyes must participate or the smile reads as a decal.
  happy: {
    browAngle: -3,
    browLift: 2.5,
    eyeOpen: 0.74,
    gaze: {x: 0, y: 0},
    mouthWidth: 1.42,
    mouthOpen: 0.4,
    mouthCurve: 0.9,
    cheek: 0.9,
    blush: 0.3,
  },
  surprised: {
    browAngle: -4,
    browLift: 9,
    eyeOpen: 1.38,
    gaze: {x: 0, y: -1.5},
    mouthWidth: 0.7,
    mouthOpen: 1,
    mouthCurve: -0.1,
    cheek: 0,
    blush: 0.05,
  },
  // Inner brows up and pinched: concern is a brow shape, not a frown mouth.
  concerned: {
    browAngle: 11,
    browLift: 3,
    eyeOpen: 1.02,
    gaze: {x: -1.5, y: 2},
    mouthWidth: 0.9,
    mouthOpen: 0.12,
    mouthCurve: -0.34,
    cheek: 0,
    blush: 0,
  },
  determined: {
    browAngle: -13,
    browLift: -3,
    eyeOpen: 0.9,
    gaze: {x: 1.5, y: 0},
    mouthWidth: 0.94,
    mouthOpen: 0,
    mouthCurve: -0.16,
    cheek: 0.2,
    blush: 0,
  },
  // Gaze off-axis plus a flat mouth: the classic thinking read.
  thinking: {
    browAngle: 6,
    browLift: 1.5,
    eyeOpen: 0.94,
    gaze: {x: 4.5, y: -3.5},
    mouthWidth: 0.8,
    mouthOpen: 0,
    mouthCurve: -0.08,
    cheek: 0.1,
    blush: 0,
  },
  sad: {
    browAngle: 14,
    browLift: 2,
    eyeOpen: 0.82,
    gaze: {x: -1, y: 3.5},
    mouthWidth: 0.84,
    mouthOpen: 0.06,
    mouthCurve: -0.6,
    cheek: 0,
    blush: 0.06,
  },
};

/** Per-parameter clamps so blending two extremes can never invert an eyelid. */
const BOUNDS: Record<keyof Omit<ExpressionTarget, 'gaze'>, [number, number]> = {
  browAngle: [-20, 20],
  browLift: [-8, 12],
  eyeOpen: [0.1, 1.5],
  mouthWidth: [0.5, 1.6],
  mouthOpen: [0, 1],
  mouthCurve: [-1, 1],
  cheek: [0, 1],
  blush: [0, 1],
};

export const resolveExpression = (id: ExpressionId): ExpressionTarget => {
  const source = EXPRESSIONS[id];
  return {...source, gaze: {...source.gaze}};
};

export const blendExpression = (from: ExpressionTarget, to: ExpressionTarget, t: number): ExpressionTarget => {
  const k = clamp(t);
  const out = {} as ExpressionTarget;
  for (const key of Object.keys(BOUNDS) as (keyof typeof BOUNDS)[]) {
    const [low, high] = BOUNDS[key];
    out[key] = clamp(lerp(from[key], to[key], k), low, high);
  }
  out.gaze = {x: lerp(from.gaze.x, to.gaze.x, k), y: lerp(from.gaze.y, to.gaze.y, k)};
  return out;
};

/** Speaking opens the mouth on syllable-ish beats without changing the emotion. */
export const withSpeech = (base: ExpressionTarget, amount: number): ExpressionTarget => ({
  ...base,
  mouthOpen: clamp(base.mouthOpen + amount * 0.55),
  mouthWidth: clamp(base.mouthWidth - amount * 0.06, 0.5, 1.6),
});
