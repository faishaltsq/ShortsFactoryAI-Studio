import type {GestureId, HandPose} from './ids';
import {clamp, easeInBack, easeInOutCubic, phase} from './math';
import type {BoneAngles, GestureArmTarget, GestureTarget} from './types';

/**
 * Gesture library: transient accents that take over the arms.
 *
 * Angles are ABSOLUTE rest-relative degrees, not deltas. A gesture blends from the
 * pose's arm angles toward its own target and back out, so `point` pose +
 * `pointForward` gesture does not add two raises together and overshoot the
 * shoulder. Everything else (head, chest) stays additive.
 *
 * Envelope: attack with an ease-in-back curve (which is where anticipation comes
 * from — the limb winds slightly past its start), a sustained hold, then a release.
 */
export const GESTURES: Record<GestureId, GestureTarget> = {
  none: {attack: 1, hold: 0, release: 1},

  // Index extended toward the facing side.
  //
  // In a three-quarter turn toward screen-right, the FAR arm is the one on the side the
  // character faces. Pointing with the near arm would drag the forearm across the chest
  // in the same colour as the jacket, which reads as a stripe rather than a gesture.
  // The far arm rotates negative (toward screen-right) and clears the body entirely.
  pointForward: {
    far: {upper: -64, fore: -18, hand: 'point', wrist: 4},
    near: {upper: 4, fore: -14, hand: 'relaxed'},
    head: -3,
    chest: -2,
    attack: 6,
    hold: 12,
    release: 8,
  },

  // Palm up at chest height, elbow tucked: an offering / explaining beat.
  openPalm: {
    near: {upper: -6, fore: -74, hand: 'open', wrist: -6},
    far: {upper: 10, fore: -16, hand: 'relaxed'},
    head: -1,
    attack: 7,
    hold: 14,
    release: 8,
  },

  bothOpen: {
    near: {upper: -22, fore: -62, hand: 'open', wrist: -4},
    far: {upper: 2, fore: -70, hand: 'open', wrist: 4},
    chest: 2,
    attack: 8,
    hold: 16,
    release: 9,
  },

  // Upper arm raised, forearm vertical, hand beside the head. Only the wrist and
  // forearm oscillate: a whole-arm wave reads as a windscreen wiper.
  wave: {
    near: {upper: 122, fore: 26, hand: 'open'},
    far: {upper: 8, fore: -14, hand: 'relaxed'},
    head: -2,
    attack: 8,
    hold: 20,
    release: 9,
  },

  // Fist under the chin, elbow low, head tilted away. The tilt is the gesture.
  think: {
    near: {upper: 16, fore: -112, hand: 'fist', wrist: -10},
    far: {upper: 12, fore: -20, hand: 'relaxed'},
    head: 5,
    chest: -1,
    attack: 9,
    hold: 18,
    release: 8,
  },

  // Palms turned up at waist height while the clavicles lift.
  shrug: {
    near: {upper: -14, fore: -128, hand: 'open', wrist: 20},
    far: {upper: 18, fore: -150, hand: 'open', wrist: -20},
    head: 2,
    chest: 3,
    attack: 7,
    hold: 14,
    release: 8,
  },
};

/**
 * Envelope: attack, sustain for the body of the scene, release at the end.
 *
 * `hold` is a minimum hold, not the whole accent: a 10 s scene must not drop the
 * arm after one second. The accent sustains from `attack` until
 * `duration - release`, which is what a storyboard means by "he points while
 * explaining". A scene shorter than the envelope degrades to a triangle that fits.
 */
export const gestureEnvelope = (
  frame: number,
  gesture: GestureTarget,
  durationInFrames: number,
  intensity = 1,
): {weight: number; wave: number} => {
  if (gesture.attack <= 0 && gesture.hold <= 0 && gesture.release <= 0) return {weight: 0, wave: 0};
  const total = gesture.attack + gesture.hold + gesture.release;
  const span = Math.max(1, durationInFrames);
  const attackEnd = Math.min(gesture.attack, span * 0.4);
  const releaseFrames = Math.min(gesture.release, span * 0.3);
  const holdEnd = Math.max(attackEnd + Math.min(gesture.hold, span), span - releaseFrames);
  const weight =
    frame < attackEnd
      ? easeInBack(clamp(frame / Math.max(1e-6, attackEnd))) * 0.94 + 0.06
      : frame < holdEnd
        ? 1
        : 1 - easeInOutCubic(clamp((frame - holdEnd) / Math.max(1e-6, span - holdEnd)));
  const scaled = clamp(weight) * clamp(intensity);
  // Oscillation is tied to the scene clock so a wave keeps waving while it holds.
  return {weight: scaled, wave: phase(frame, Math.max(total, span))};
};

export interface GestureFrame {
  weight: number;
  /** Absolute arm targets, only present for arms this gesture drives. */
  near?: {upper: number; fore: number; hand: number; pose: HandPose};
  far?: {upper: number; fore: number; hand: number; pose: HandPose};
  /** Additive accents. */
  angles: BoneAngles;
  hands: {near?: HandPose; far?: HandPose};
}

const armTarget = (
  spec: GestureArmTarget | undefined,
  waveOscillation: number,
): GestureFrame['near'] => {
  if (!spec) return undefined;
  const pose: HandPose = spec.hand ?? 'relaxed';
  // Wrist deviation is a few degrees, not a joint: the hand must read as a
  // continuation of the forearm. The shape itself is drawn by Hand.tsx.
  const shapeAngle = pose === 'open' ? 0 : pose === 'point' ? -2 : pose === 'fist' ? -8 : 0;
  return {
    upper: spec.upper ?? 0,
    fore: spec.fore ?? 0,
    hand: shapeAngle + (spec.wrist ?? 0) + waveOscillation,
    pose,
  };
};

/** Resolve one gesture to arm targets plus additive head/chest accents. */
export const gestureFrame = (
  id: GestureId,
  frame: number,
  durationInFrames: number,
  intensity = 1,
): GestureFrame => {
  const gesture = GESTURES[id];
  if (id === 'none') return {weight: 0, angles: {}, hands: {}};
  const {weight, wave} = gestureEnvelope(frame, gesture, durationInFrames, intensity);
  if (weight <= 0) return {weight: 0, angles: {}, hands: {}};

  // A wave oscillates the wrist and forearm together, tapering with the envelope.
  const oscillation = id === 'wave' ? Math.sin(wave * Math.PI * 2 * 2.4) * 20 * weight : 0;
  const near = armTarget(gesture.near, oscillation);
  const far = armTarget(gesture.far, 0);
  if (near) near.fore += oscillation * 0.25;

  const angles: BoneAngles = {};
  if (gesture.head) angles.head = gesture.head * weight;
  if (gesture.chest) angles.chest = gesture.chest * weight;

  return {
    weight,
    near,
    far,
    angles,
    hands: {
      near: gesture.near?.hand && weight > 0.4 ? gesture.near.hand : undefined,
      far: gesture.far?.hand && weight > 0.4 ? gesture.far.hand : undefined,
    },
  };
};

/** Peak frame of a gesture, used by the reel and tests. */
export const gesturePeakFrame = (id: GestureId): number => GESTURES[id].attack + 1;
