import type {BoneId, ExpressionId, GestureId, HandPose, MotionPreset, PaintRole, PoseId} from './ids';

export interface Point {
  x: number;
  y: number;
}

export interface BoneLimit {
  min: number;
  max: number;
}

export interface BoneSpec {
  id: BoneId;
  parent: BoneId | null;
  /** Rest pivot in character viewBox space. Rotation happens around this point. */
  pivot: Point;
  /** Degrees, applied around `pivot` after the parent's transform. */
  limits?: BoneLimit;
}

export interface RigSpec {
  bones: BoneSpec[];
}

/**
 * A drawable shape. Paths are authored in character viewBox space; the rig
 * transform for `bone` is applied at render time, so one path can be reused by
 * any pose without the author re-drawing it.
 */
interface ShapeStyle {
  /** `none` is an explicit transparent fill, needed for open contour paths. */
  fill?: PaintRole | 'none';
  stroke?: PaintRole;
  strokeWidth?: number;
  opacity?: number;
}

export type ShapeSpec =
  | (ShapeStyle & {kind: 'path'; d: string})
  | (ShapeStyle & {kind: 'ellipse'; cx: number; cy: number; rx: number; ry: number})
  | (ShapeStyle & {kind: 'rect'; x: number; y: number; width: number; height: number; rx?: number});

export interface LayerSpec {
  id: string;
  bone: BoneId;
  /** Higher paints later. Independent of hierarchy so the near arm can cover the torso. */
  z: number;
  shapes: ShapeSpec[];
  /** Far-side limbs get a shade overlay instead of rim light. */
  far?: boolean;
  opacity?: number;
}

export interface CharacterPalette {
  /** Paint roles resolved at render time. `accent` follows the scene theme. */
  skin: string;
  skinShade: string;
  hair: string;
  hairShade: string;
  jacket: string;
  jacketShade: string;
  jacketLight: string;
  shirt: string;
  shirtShade: string;
  trousers: string;
  trousersShade: string;
  shoe: string;
  shoeSole: string;
  ink: string;
  accent: string;
}

export interface CharacterProvenance {
  author: string;
  source: string;
  createdAt: string;
}

export interface CharacterLicense {
  id: string;
  attribution?: string;
}

export interface CharacterFaceSpec {
  /** Feature anchor in character space: the centre of the eye line. */
  anchor: Point;
  /** Face width/height in character units; features scale from these. */
  width: number;
  height: number;
  /** Head turn in degrees; shifts features toward the facing side for a 3/4 read. */
  turn?: number;
}

export interface CharacterHandSpec {
  /** Hand length/width in character units, drawn from the hand bone's pivot. */
  length: number;
  width: number;
  /** Draw order for each hand. The far hand must sit behind the torso. */
  zNear: number;
  zFar: number;
}

/** Paint roles resolved to concrete colours for one scene. */
export interface CharacterPaint {
  skin: string;
  skinShade: string;
  hair: string;
  hairShade: string;
  jacket: string;
  jacketShade: string;
  jacketLight: string;
  shirt: string;
  shirtShade: string;
  trousers: string;
  trousersShade: string;
  shoe: string;
  shoeSole: string;
  ink: string;
  accent: string;
}

export interface CharacterManifest {
  id: string;
  version: string;
  displayName: string;
  artStyle: 'editorial-vector';
  /**
   * Character space. `minX`/`minY` are optional so a rig can extend the canvas on
   * one side for arm gestures without moving a single art coordinate.
   */
  viewBox: {minX?: number; minY?: number; width: number; height: number};
  /** Character-space y of the sole line. Placement uses this as the anchor. */
  groundY: number;
  poses: PoseId[];
  expressions: ExpressionId[];
  gestures: GestureId[];
  layers: LayerSpec[];
  rig: RigSpec;
  /** Optional parametric face drawn over the head art. */
  face?: CharacterFaceSpec;
  /** Optional parametric hands drawn at the hand bones. */
  hands?: CharacterHandSpec;
  palette: CharacterPalette;
  provenance: CharacterProvenance;
  license: CharacterLicense;
}

/** Per-bone angle offsets in degrees. Omitted bones keep their rest angle. */
export type BoneAngles = Partial<Record<BoneId, number>>;

export interface PoseTarget {
  /** Angles relative to rest, so one pose works on a rig with different proportions. */
  angles: BoneAngles;
  /** Hips translation in character units, for weight shift and sit. */
  hipsOffset?: Point;
  /** Whole-body lean applied at the root. */
  lean?: number;
  /** Hand shapes this pose implies unless a gesture overrides them. */
  hands?: {near?: HandPose; far?: HandPose};
  /**
   * Gaze offset in character units. In 2D, "looking up" is carried by the pupils and
   * lids, not by rotating the head: an in-plane rotation reads as a tilt, never a pitch.
   */
  gaze?: Point;
  /**
   * True when the pose already defines a meaningful arm action (reach, walk). A
   * gesture then contributes only head/chest accents, so a storyboard that pairs
   * `reach` with `openPalm` cannot fold the arm back down.
   */
  armsLocked?: boolean;
  /** Foot contact, used by the walk cycle to plant the sole. */
  contact?: 'near' | 'far' | 'both';
  /**
   * Ankle targets in character space. When present the resolver solves thigh/shin/
   * foot angles analytically, so a pose that lowers the hips still plants its feet.
   * Without this every bent-leg pose floats above the ground line.
   */
  feet?: {near?: FootTarget; far?: FootTarget};
}

export interface FootTarget {
  x: number;
  y: number;
  /** Sole pitch in degrees. Positive points the toe down (toe-off). */
  pitch?: number;
}

export interface ExpressionTarget {
  browAngle: number;
  browLift: number;
  eyeOpen: number;
  /** Pupil offset in character units. */
  gaze: Point;
  mouthWidth: number;
  mouthOpen: number;
  mouthCurve: number;
  /** 0..1; raises the lower lid for a squint. */
  cheek: number;
  blush: number;
}

export interface GestureArmTarget {
  upper?: number;
  fore?: number;
  /** Hand shape this gesture asks for; the wrist angle is derived from it. */
  hand?: HandPose;
  /** Extra wrist angle on top of the shape's default. */
  wrist?: number;
}

export interface GestureTarget {
  /** Absolute arm targets. Near/far are the character's own arms. */
  near?: GestureArmTarget;
  far?: GestureArmTarget;
  head?: number;
  chest?: number;
  /** Frames before the accent peaks. */
  attack: number;
  /** Frames the accent is held. */
  hold: number;
  /** Frames the accent releases. */
  release: number;
  /** 0..1 scale of the whole accent. */
  intensity?: number;
}

export interface MotionCue {
  preset: MotionPreset;
  durationInFrames?: number;
  /** 0..1. Presets treat 0.5 as their authored default. */
  intensity?: number;
  delayInFrames?: number;
  fromPose?: PoseId;
  fromExpression?: ExpressionId;
}

export interface ResolvedPose {
  angles: BoneAngles;
  hips: Point;
  lean: number;
  hands: {near: HandPose; far: HandPose};
  gaze?: Point;
}

export interface ResolvedExpression extends ExpressionTarget {}

/** Output of the motion layer: everything the renderer needs for one frame. */
export interface CharacterFrame {
  angles: BoneAngles;
  hips: Point;
  lean: number;
  expression: ExpressionTarget;
  hands: {near: HandPose; far: HandPose};
  /** 0..1, applied to the whole figure (entrance/exit). */
  opacity: number;
  /** Character-space lift in units, e.g. a hop or a sit-down drop. */
  lift: number;
}
