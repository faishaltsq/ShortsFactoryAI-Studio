/**
 * Typed storyboard contract shared by the Python agent pipeline and the
 * Remotion renderer. Every field here is produced by StoryboardAgent and
 * validated with JSON Schema on the Python side before render.
 */

/**
 * A measured word window, scene-local milliseconds.
 *
 * The narration is still measured (SAPI reports a boundary per word and the audio stage persists
 * them). The tongue that used to consume this is gone; the timing remains because subtitles and
 * scene pacing are built from the same clock.
 */
export interface SpeechWindow {
  /** Scene-local, inclusive. */
  startMs: number;
  /** Scene-local, exclusive. */
  endMs: number;
}

export const TEMPLATE_IDS = [
  'KineticTypography',
  'MotionComic',
  'EducationalExplainer',
  'HistoricalTimeline',
  'ParallaxStory',
  'InfographicMotion',
  'ObjectExplainer',
  'ProcessFlow',
  'MetricShift',
] as const;

export type TemplateId = (typeof TEMPLATE_IDS)[number];

export interface TextStyleSpec {
  role: 'title' | 'highlight' | 'body' | 'caption' | 'kicker';
  /** 0..1 vertical anchor inside the safe area. */
  y?: number;
  size?: number;
  color?: string;
  uppercase?: boolean;
  align?: 'left' | 'center' | 'right';
  maxCharsPerLine?: number;
}

export interface TextElementSpec {
  id: string;
  text: string;
  style: TextStyleSpec;
  /** Frame offset relative to scene start. */
  inFrame?: number;
  outFrame?: number;
}

export interface AnimationSpec {
  /** Preset name from themes/presets.ts. */
  preset: 'popIn' | 'slideUp' | 'wordByWord' | 'wipeIn' | 'countUp' | 'fadeIn';
  durationInFrames?: number;
  /** 0..1, direction/strength hint per preset. */
  intensity?: number;
}

export type TransitionType = 'none' | 'fade' | 'slideUp' | 'wipe' | 'zoom';

/**
 * The product's camera vocabulary (`CameraSpec` in `packages/core/contracts/scene.py`).
 *
 * It is deliberately NOT `CameraMove` from `scene-data.ts`: that one is the renderer's own
 * per-shot table (`pushIn`, `panLeft`, …) which lives inside `data.shots[]`. Both exist; which one
 * drives the frame is decided in one place, `src/camera.ts`.
 */
export const SHOT_SIZES = ['wide', 'medium', 'close'] as const;
export type ShotSize = (typeof SHOT_SIZES)[number];

export const CAMERA_MOVE_KINDS = ['static', 'push', 'pull', 'pan', 'tilt', 'orbit'] as const;
export type CameraMoveKind = (typeof CAMERA_MOVE_KINDS)[number];

export const CAMERA_EASINGS = [
  'linear',
  'power1.out',
  'power2.out',
  'power3.out',
  'power4.out',
  'power1.in',
  'power2.in',
  'power2.inOut',
  'sine.inOut',
] as const;
export type CameraEasing = (typeof CAMERA_EASINGS)[number];

/** `static` amplitude above this is a zoom, not a still — mirrors `CameraSpec._target_required`. */
export const STATIC_AMPLITUDE_LIMIT = 0.35;

export const BEAT_KINDS = ['enter', 'emphasis', 'exit', 'action', 'reveal'] as const;
export type BeatKind = (typeof BEAT_KINDS)[number];

export const CONTINUITIES = ['carry', 'cut', 'match'] as const;
export type Continuity = (typeof CONTINUITIES)[number];

/**
 * Framing and movement. Present only when the storyboard declared one: the adapter forwards a
 * declared camera verbatim and leaves an undeclared one absent, so "no camera" stays visible
 * instead of becoming a plausible default.
 */
export interface CameraSpec {
  shot: ShotSize;
  move: CameraMoveKind;
  /** Element id the move is about. Required (and validated) for every non-static move. */
  target?: string;
  /** 0..1 scale of the move. `push`/`pull` zoom by exactly this fraction. */
  amplitude: number;
  ease: CameraEasing;
}

/** One directing instruction: at `atFrame`, something happens to `subject`. */
export interface MotionBeat {
  atFrame: number;
  kind: BeatKind;
  subject: string;
}

export interface MotionSpec {
  /** 0..1. Scales the character accents the beats produce. */
  energy: number;
  continuity: Continuity;
  beats: MotionBeat[];
}

export type LayoutMode =
  | 'DefaultHero'
  | 'SplitComparison'
  | 'RadialNetwork'
  | 'LeftRailProcess'
  | 'FullBleedFocus';

export interface CausalStateSpec {
  initialState: string;
  causalAction: string;
  resultingState: string;
  transition: string;
}

export interface SceneSpec {
  sceneId: string;
  template: TemplateId;
  /** Narrative segment this scene carries (verbatim from script). */
  segment: string;
  assetRefs: string[];
  text: TextElementSpec[];
  animation: AnimationSpec;
  transition: {type: TransitionType; durationInFrames?: number};
  /**
   * Declared camera. Absent means the storyboard said nothing; a renderer that needs a framing
   * then falls back to its own per-shot table and must say so (see `src/camera.ts`).
   */
  camera?: CameraSpec;
  /** Declared motion. Absent means no beats; the scene still renders, it just does not act. */
  motion?: MotionSpec;
  /**
   * Measured word windows for this scene, scene-local milliseconds — the same clock as the scene's
   * subtitles and `motion.beats[].atFrame`. Written by `update_storyboard_from_audio` from
   * `audio.json`. Absent means no measurement exists (an old artifact, or the donor fixture), and
   * the character's mouth stays closed: a mouth that moves without measured speech is a sine wave
   * pretending to be lip sync.
   */
  speech?: SpeechWindow[];
  audio?: {src: string; volume?: number};
  /** Timing is recalculated from real narration duration before render. */
  startFrame: number;
  durationInFrames: number;
  /** Optional data payload used by data-driven templates. */
  data?: Record<string, unknown>;
  layoutMode?: LayoutMode;
  causalState?: CausalStateSpec;
}

export interface SubtitleCue {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
}

export interface WordTimestamp {
  word: string;
  startMs: number;
  endMs: number;
  start: number; // in seconds
  end: number;   // in seconds
}

export interface ThemeSpec {
  id: string;
  background: string;
  backgroundAccent: string;
  primary: string;
  secondary: string;
  accent: string;
  fontHeading: string;
  fontBody: string;
}

export interface StoryboardSpec {
  id: string;
  language: string;
  width: number;
  height: number;
  fps: number;
  theme: ThemeSpec;
  scenes: SceneSpec[];
  subtitles: SubtitleCue[];
  captions?: WordTimestamp[];
  narration?: {src: string; durationMs: number; volume?: number};
  backgroundMusic?: {src: string; volume?: number};
  watermark?: {text: string; opacity?: number};
}

export const isTemplateId = (value: string): value is TemplateId =>
  (TEMPLATE_IDS as readonly string[]).includes(value);
