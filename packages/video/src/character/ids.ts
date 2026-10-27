/**
 * Canonical vocabulary for the character engine.
 *
 * This module deliberately imports nothing. `scene-data.ts` re-exports POSES from
 * here, so the art layer and the validator share one list without a cycle.
 */

export const POSES = ['stand', 'point', 'reach', 'walk', 'lookUp', 'shrug', 'sit'] as const;
export type PoseId = (typeof POSES)[number];

export const EXPRESSIONS = [
  'neutral',
  'curious',
  'happy',
  'surprised',
  'concerned',
  'determined',
  'thinking',
  'sad',
] as const;
export type ExpressionId = (typeof EXPRESSIONS)[number];

/** Transient accents layered over a sustained pose. `none` is a valid, explicit no-op. */
export const GESTURES = ['none', 'pointForward', 'openPalm', 'bothOpen', 'wave', 'think', 'shrug'] as const;
export type GestureId = (typeof GESTURES)[number];

export const MOTION_PRESETS = ['idle', 'talk', 'walk', 'gesture', 'react', 'enter', 'poseChange'] as const;
export type MotionPreset = (typeof MOTION_PRESETS)[number];

export const HAND_POSES = ['relaxed', 'open', 'point', 'fist'] as const;
export type HandPose = (typeof HAND_POSES)[number];

/**
 * The humanoid bone contract. Every character declares its own pivots and may
 * vary proportions, but the ids are fixed: the pose, motion and gesture libraries
 * address these bones by name, and a rig missing one cannot be animated by them.
 */
export const BONE_IDS = [
  'root',
  'hips',
  'spine',
  'chest',
  'neck',
  'head',
  'clavicleNear',
  'armUpperNear',
  'armForeNear',
  'handNear',
  'clavicleFar',
  'armUpperFar',
  'armForeFar',
  'handFar',
  'thighNear',
  'shinNear',
  'footNear',
  'thighFar',
  'shinFar',
  'footFar',
  'hairStrand',
  'hairTip',
] as const;
export type BoneId = (typeof BONE_IDS)[number];

/** Optional bones: a character may omit these, and motion checks before animating them. */
export const OPTIONAL_BONES: readonly BoneId[] = ['hairStrand', 'hairTip'];

/** Bones that must carry visible art. A flattened image cannot satisfy this. */
export const ARTICULATED_BONES: readonly BoneId[] = [
  'head',
  'spine',
  'armUpperNear',
  'armForeNear',
  'armUpperFar',
  'armForeFar',
  'thighNear',
  'shinNear',
  'footNear',
  'thighFar',
  'shinFar',
  'footFar',
];

export const PAINT_ROLES = [
  'skin',
  'skinShade',
  'hair',
  'hairShade',
  'jacket',
  'jacketShade',
  'jacketLight',
  'shirt',
  'shirtShade',
  'trousers',
  'trousersShade',
  'shoe',
  'shoeSole',
  'ink',
  'accent',
] as const;
export type PaintRole = (typeof PAINT_ROLES)[number];
