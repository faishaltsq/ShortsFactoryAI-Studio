import {resolveExpression, withSpeech} from './expressions';
import {speechAt, type SpeechWindow} from '../speech';
import {gestureFrame} from './gestures';
import type {ExpressionId, GestureId, HandPose, MotionPreset, PoseId} from './ids';
import {blinkAt, clamp, dampedSettle, easeInOutCubic, hash01, lerp, mixAngle, smoothstep} from './math';
import {POSES, resolvePose} from './poses';
import type {BoneAngles, CharacterFrame, ExpressionTarget, MotionCue, Point} from './types';
import type {PivotLookup} from './poses';

/** Authored default. 0.6 maps to gain 1.0 so the model can ask for subtle or broad. */
export const DEFAULT_INTENSITY = 0.6;

const gainOf = (intensity: number | undefined): number =>
  clamp(intensity ?? DEFAULT_INTENSITY, 0, 1) / DEFAULT_INTENSITY;

export interface MotionInput {
  pose: PoseId;
  expression: ExpressionId;
  gesture: GestureId;
  motion?: MotionCue;
  /** Stable per-actor seed so two characters never breathe or blink in lockstep. */
  seed: number;
  /** Measured word windows for the scene. Absent or empty means the mouth stays closed. */
  speech?: readonly SpeechWindow[];
  /**
   * Scene-local frame the speech windows are measured against. Defaults to the frame this call
   * was made with, which is right when the rig is already on the scene clock.
   */
  speechFrame?: number;
}

interface Delta {
  angles: BoneAngles;
  hips: Point;
  lift: number;
}

const ZERO: Delta = {angles: {}, hips: {x: 0, y: 0}, lift: 0};

const add = (a: Delta, b: Delta): Delta => {
  const angles: BoneAngles = {...a.angles};
  for (const [bone, value] of Object.entries(b.angles) as [keyof BoneAngles, number][]) {
    angles[bone] = (angles[bone] ?? 0) + value;
  }
  return {
    angles,
    hips: {x: a.hips.x + b.hips.x, y: a.hips.y + b.hips.y},
    lift: a.lift + b.lift,
  };
};

/**
 * Sustained idle: breath at 3.6 s, weight shift at 7.5 s, micro head drift at 5.1 s.
 * The periods are mutually prime-ish so the loop never visibly repeats inside a
 * 45 s short. Amplitudes are small: idle should be felt, not watched.
 */
const idleDelta = (frame: number, fps: number, seed: number): Delta => {
  const breath = Math.sin((frame / (3.6 * fps)) * Math.PI * 2 + seed);
  const shift = Math.sin((frame / (7.5 * fps)) * Math.PI * 2 + seed * 0.7);
  const drift = Math.sin((frame / (5.1 * fps)) * Math.PI * 2 + seed * 1.3);
  return {
    angles: {
      chest: breath * 1.5,
      spine: breath * 0.7 + shift * 0.6,
      neck: -breath * 0.5,
      head: drift * 1.3 - shift * 0.5,
      clavicleNear: breath * 0.8,
      clavicleFar: breath * 0.8,
      armUpperNear: drift * 0.9,
      armUpperFar: -drift * 0.7,
      armForeNear: -breath * 0.8,
      armForeFar: breath * 0.6,
      hairStrand: drift * 1.1,
      hairTip: drift * 1.6,
    },
    hips: {x: shift * 2.2, y: breath * 0.5},
    lift: 0,
  };
};

/** Speaking beats: short head accents and a small near-hand lift on stressed words. */
const talkDelta = (frame: number, fps: number, seed: number): Delta => {
  const beat = Math.sin((frame / (0.62 * fps)) * Math.PI * 2 + seed);
  const accent = Math.sin((frame / (1.9 * fps)) * Math.PI * 2 + seed * 2.1);
  return {
    angles: {
      head: accent * 3.2 + beat * 0.9,
      neck: accent * 1.1,
      chest: accent * 1.4,
      armUpperNear: -accent * 3.4 - 1.5,
      armForeNear: -Math.max(0, accent) * 5.5,
      handNear: -Math.max(0, accent) * 6,
      hairStrand: accent * 1.4,
      hairTip: accent * 2,
    },
    hips: {x: beat * 0.8, y: accent * 0.5},
    lift: 0,
  };
};

/**
 * Walk cycle. Contact → passing → contact, one stride per 24 frames at 30 fps.
 *
 * Knees bend only while the leg is travelling forward (swing), never while it
 * carries weight, which is the single detail that stops a sine-wave walk from
 * looking like a marionette. Hips drop twice per stride and sway once.
 */
const walkDelta = (frame: number, fps: number, seed: number, intensity: number): Delta => {
  const strideFrames = 24 * (30 / fps);
  const p = (frame / strideFrames) * Math.PI * 2 + seed * 0.4;
  const swing = Math.sin(p);
  const nearSwing = Math.max(0, -swing);
  const farSwing = Math.max(0, swing);
  const bob = Math.abs(Math.sin(p)) * 3.4;
  return {
    angles: {
      thighNear: swing * 20,
      thighFar: -swing * 20,
      shinNear: nearSwing * 30 + 4,
      shinFar: farSwing * 30 + 4,
      footNear: -swing * 8,
      footFar: swing * 8,
      // Arms counter-swing against the legs at roughly 70 % of the leg amplitude.
      armUpperNear: -swing * 9,
      armUpperFar: swing * 9,
      armForeNear: -6 - Math.max(0, -swing) * 10,
      armForeFar: -6 - Math.max(0, swing) * 10,
      // The torso counter-rotates against the hips; the head stays level.
      spine: -swing * 2.4,
      chest: -swing * 1.6,
      hips: swing * 3.2,
      neck: swing * 1.2,
      head: -swing * 1.4,
      hairStrand: -swing * 2.2,
      hairTip: -swing * 3.4,
    },
    hips: {x: swing * 2.6 * intensity, y: -bob * intensity},
    lift: 0,
  };
};

/** Reaction: one damped jolt, then stillness. Weight drops into the heels. */
const reactDelta = (frame: number, fps: number, seed: number, duration: number): Delta => {
  const settle = dampedSettle(clamp(frame / Math.max(1, duration * 0.55)), 6.2, 1.15);
  const direction = hash01(seed + 7) > 0.5 ? 1 : -1;
  return {
    angles: {
      chest: -settle * 3.4,
      spine: -settle * 1.6,
      head: settle * 4.2 * direction,
      neck: settle * 1.8,
      armUpperNear: settle * 5,
      armUpperFar: -settle * 4,
      armForeNear: -settle * 7,
      armForeFar: -settle * 5,
      hairStrand: -settle * 3,
      hairTip: -settle * 5,
    },
    hips: {x: settle * 2 * direction, y: settle * 1.8},
    lift: 0,
  };
};

/** Entrance: rises and settles with one small overshoot, then holds. */
const enterDelta = (frame: number, fps: number, seed: number): Delta => {
  const t = clamp(frame / (0.45 * fps));
  const settle = dampedSettle(t, 5, 0.85);
  return {
    angles: {head: -settle * 1.6, chest: settle * 1.2},
    hips: {x: 0, y: 0},
    lift: (1 - settle) * 10,
  };
};

/** Gesture preset: the body leans a fraction toward the gesture, nothing more. */
const gestureDelta = (frame: number, fps: number, seed: number, duration: number): Delta => {
  const t = smoothstep(clamp(frame / Math.max(1, duration * 0.3)));
  return {
    angles: {chest: -t * 1.4, head: -t * 1.1, spine: -t * 0.7},
    hips: {x: -t * 1.2, y: 0},
    lift: 0,
  };
};

const presetDelta = (
  preset: MotionPreset,
  frame: number,
  fps: number,
  seed: number,
  duration: number,
  intensity: number,
): Delta => {
  switch (preset) {
    case 'idle':
      return idleDelta(frame, fps, seed);
    case 'talk':
      return add(idleDelta(frame, fps, seed), talkDelta(frame, fps, seed));
    case 'walk':
      return add(idleDelta(frame, fps, seed), walkDelta(frame, fps, seed, intensity));
    case 'react':
      return add(idleDelta(frame, fps, seed), reactDelta(frame, fps, seed, duration));
    case 'enter':
      return add(idleDelta(frame, fps, seed), enterDelta(frame, fps, seed));
    case 'gesture':
      return add(idleDelta(frame, fps, seed), gestureDelta(frame, fps, seed, duration));
    case 'poseChange':
      return idleDelta(frame, fps, seed);
    default:
      return ZERO;
  }
};

/**
 * Pose transition curve: a short wind-up in the opposite direction, a fast middle,
 * and a settle. The negative segment is anticipation; it is what makes a character
 * look like it decided to move rather than being teleported.
 */
const poseChangeBlend = (t: number): number => {
  const p = clamp(t);
  const anticipation = -0.09 * Math.sin(Math.PI * clamp(p / 0.32)) * (1 - p);
  const travel = easeInOutCubic(clamp((p - 0.1) / 0.9));
  return travel + anticipation;
};

const BONE_KEYS: readonly (keyof BoneAngles)[] = [
  'hips', 'spine', 'chest', 'neck', 'head',
  'clavicleNear', 'armUpperNear', 'armForeNear', 'handNear',
  'clavicleFar', 'armUpperFar', 'armForeFar', 'handFar',
  'thighNear', 'shinNear', 'footNear', 'thighFar', 'shinFar', 'footFar',
  'hairStrand', 'hairTip',
];

const mixAngles = (from: BoneAngles, to: BoneAngles, t: number): BoneAngles => {
  const out: BoneAngles = {};
  for (const bone of BONE_KEYS) {
    const a = from[bone] ?? 0;
    const b = to[bone] ?? 0;
    if (a === 0 && b === 0) continue;
    out[bone] = lerp(a, b, t);
  }
  return out;
};

/** Follow-through bones lag behind the body by a frame count, then overshoot slightly. */
const LAG_FRAMES = 2;

export interface CharacterFrameInput {
  input: MotionInput;
  frame: number;
  fps: number;
  durationInFrames: number;
  /** Character pivots, needed to solve leg IK for poses with foot targets. */
  pivot?: PivotLookup;
}

/**
 * Resolve every animation channel for one frame.
 *
 * Determinism: the entire function is a pure function of (input, frame, fps,
 * duration). Follow-through re-samples the same preset at `frame - lag`, so it is
 * still frame-derived and never accumulates state.
 */
export const characterFrameAt = ({input, frame, fps, durationInFrames, pivot}: CharacterFrameInput): CharacterFrame => {
  const motion = input.motion;
  const preset: MotionPreset = motion?.preset ?? 'idle';
  const duration = clamp(motion?.durationInFrames ?? durationInFrames, 1, 100000);
  const local = clamp(frame - (motion?.delayInFrames ?? 0), 0, duration);
  const gain = gainOf(motion?.intensity);

  const base = resolvePose(input.pose, pivot);
  let angles: BoneAngles = {...base.angles};
  let hips: Point = {...base.hips};
  let lean = base.lean;
  let hands: {near: HandPose; far: HandPose} = {...base.hands};
  let expression: ExpressionTarget = resolveExpression(input.expression);

  // --- pose transition ---------------------------------------------------------
  if (preset === 'poseChange' && motion?.fromPose) {
    const from = resolvePose(motion.fromPose, pivot);
    const blend = poseChangeBlend(clamp(local / Math.max(1, duration * 0.6)));
    angles = mixAngles(from.angles, base.angles, blend);
    hips = {
      x: lerp(from.hips.x, base.hips.x, blend),
      y: lerp(from.hips.y, base.hips.y, blend),
    };
    lean = lerp(from.lean, base.lean, blend);
    hands = blend < 0.5 ? from.hands : base.hands;
    if (motion.fromExpression) {
      const fromExpression = resolveExpression(motion.fromExpression);
      expression = {
        ...expression,
        ...Object.fromEntries(
          (Object.keys(expression) as (keyof ExpressionTarget)[])
            .filter((key) => key !== 'gaze')
            .map((key) => [key, lerp(fromExpression[key] as number, expression[key] as number, blend)]),
        ),
        gaze: {
          x: lerp(fromExpression.gaze.x, expression.gaze.x, blend),
          y: lerp(fromExpression.gaze.y, expression.gaze.y, blend),
        },
      } as ExpressionTarget;
    }
  }

  // --- sustained motion + follow-through ---------------------------------------
  const now = presetDelta(preset, local, fps, input.seed, duration, gain);
  const lagged = presetDelta(preset, Math.max(0, local - LAG_FRAMES), fps, input.seed, duration, gain);
  const delayed = presetDelta(preset, Math.max(0, local - LAG_FRAMES * 2), fps, input.seed, duration, gain);

  for (const [bone, value] of Object.entries(now.angles) as [keyof BoneAngles, number][]) {
    angles[bone] = (angles[bone] ?? 0) + value * gain;
  }
  // Head, neck and hair are driven by the lagged sample: the body leads, the head follows.
  for (const bone of ['head', 'neck'] as const) {
    const own = angles[bone] ?? 0;
    const body = now.angles[bone] ?? 0;
    const behind = lagged.angles[bone] ?? 0;
    angles[bone] = own + (behind - body) * gain;
  }
  for (const bone of ['hairStrand', 'hairTip'] as const) {
    const own = angles[bone] ?? 0;
    const body = now.angles[bone] ?? 0;
    const behind = delayed.angles[bone] ?? 0;
    angles[bone] = own + (behind - body) * gain * 1.5;
  }

  hips = {
    x: hips.x + now.hips.x * gain,
    y: hips.y + now.hips.y * gain,
  };
  const lift = now.lift * gain;

  // --- gesture accent ----------------------------------------------------------
  // Arms blend toward absolute targets by gesture weight; head/chest stay additive.
  const gesture = gestureFrame(input.gesture, local, duration, gain);
  for (const [bone, value] of Object.entries(gesture.angles) as [keyof BoneAngles, number][]) {
    angles[bone] = (angles[bone] ?? 0) + value;
  }
  const poseSpec = POSES[input.pose];
  for (const side of ['Near', 'Far'] as const) {
    const target = side === 'Near' ? gesture.near : gesture.far;
    // A locked pose keeps its own arms; the gesture still contributes its head and
    // chest accents above, which is what a director would actually ask for.
    if (!target || poseSpec.armsLocked) continue;
    const upperBone = `armUpper${side}` as const;
    const foreBone = `armFore${side}` as const;
    const handBone = `hand${side}` as const;
    // Mixing absolute angles must go through the shortest arc, or a 170° gesture
    // spins the arm the long way around.
    angles[upperBone] = mixAngle(angles[upperBone] ?? 0, target.upper, gesture.weight);
    angles[foreBone] = mixAngle(angles[foreBone] ?? 0, target.fore, gesture.weight);
    angles[handBone] = mixAngle(angles[handBone] ?? 0, target.hand, gesture.weight);
    if (side === 'Near') hands = {...hands, near: target.pose};
    else hands = {...hands, far: target.pose};
  }

  // --- face --------------------------------------------------------------------
  // A pose's gaze wins over the expression's, unless the expression is a strong
  // off-axis look (thinking), which a pose should not override.
  if (base.gaze) {
    expression = {...expression, gaze: {x: expression.gaze.x + base.gaze.x, y: expression.gaze.y + base.gaze.y}};
  }
  // Speech aperture comes from the measured word windows, never from a clock. `speechAt` returns 0
  // for an empty window list, so a storyboard without boundaries renders a closed mouth — the
  // previous implementation ran `sin(local / 3.1)` here, which moved the mouth but not with the
  // voice and is indistinguishable from lip sync only if nobody listens.
  //
  // The window index is the frame's scene-local time; `input.speechFrame` is the clock it is
  // measured against, because `motion.beats[]` re-bases the rig onto the scene clock while the
  // windows are already scene-local.
  const aperture = speechAt(input.speech ?? [], input.speechFrame ?? frame, fps);
  if (aperture.weight > 0) {
    expression = withSpeech(expression, aperture.weight);
  }
  const blink = blinkAt(local, fps, input.seed);
  expression = {...expression, eyeOpen: expression.eyeOpen * (1 - blink * 0.92)};

  return {
    angles,
    hips,
    lean,
    expression,
    hands,
    opacity: preset === 'enter' ? clamp(local / Math.max(1, fps * 0.35)) : 1,
    lift,
  };
};
