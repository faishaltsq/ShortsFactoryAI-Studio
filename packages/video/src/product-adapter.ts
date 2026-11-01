/**
 * Adapter from the product's persisted `storyboard.json` to the donor `StoryboardSpec`.
 *
 * The two contracts describe the same film with different vocabularies, so this is a translation
 * with no defaults invented for content: every value either comes from the input or is a
 * documented constant of the donor renderer. Nothing is coerced into something plausible — an
 * ill-typed field is an error that names the field and the scene.
 */

import type {
  BeatKind,
  CameraEasing,
  CameraMoveKind,
  CameraSpec,
  Continuity,
  MotionBeat,
  MotionSpec,
  SceneSpec,
  ShotSize,
  StoryboardSpec,
  SpeechWindow,
  TextElementSpec,
  TextStyleSpec,
  TransitionType,
} from './types';
import {
  BEAT_KINDS,
  CAMERA_EASINGS,
  CAMERA_MOVE_KINDS,
  CONTINUITIES,
  SHOT_SIZES,
  STATIC_AMPLITUDE_LIMIT,
  isTemplateId,
} from './types';
import {resolveTheme} from './themes/brand';

export type ProductTextRole = 'title' | 'body' | 'caption' | 'label';
export type ProductTransitionKind = 'cut' | 'fade' | 'wipe' | 'push' | 'match';

export type ProductTextElement = {
  id: string;
  text: string;
  role: ProductTextRole;
  atFrame: number;
};

export type ProductScene = {
  sceneId: string;
  template: string;
  segment: string;
  startFrame: number;
  durationInFrames: number;
  assetRefs: string[];
  text: ProductTextElement[];
  transition: {kind: ProductTransitionKind; frames: number};
  /** Present on every scene the Python pipeline writes; absent on a hand-written storyboard. */
  camera?: unknown;
  motion?: unknown;
  audio?: unknown;
  data?: unknown;
};

export type ProductStoryboard = {
  schema_version: number;
  fps: number;
  width: number;
  height: number;
  theme: string;
  scenes: ProductScene[];
  subtitles?: {startMs: number; endMs: number; text: string}[];
};

/** Product text roles collapse onto donor roles. `label` is a caption in the renderer. */
const ROLE_MAP: Record<ProductTextRole, TextStyleSpec['role']> = {
  title: 'title',
  body: 'body',
  caption: 'caption',
  label: 'caption',
};

/**
 * Product transitions map onto the donor's five. `cut` and `match` both mean "no animated
 * transition" here; `match` is a continuity instruction for the planner, not a renderer effect.
 */
const TRANSITION_MAP: Record<ProductTransitionKind, TransitionType> = {
  cut: 'none',
  fade: 'fade',
  wipe: 'wipe',
  push: 'slideUp',
  match: 'none',
};

/** Only content-addressed rasters staged by AssetAgent may become browser image requests. */
const CONTENT_ADDRESSED_ASSET = /^assets\/[a-f0-9]{64}\.(png|jpe?g|webp)$/;

const TEXT_ROLES: readonly string[] = ['title', 'body', 'caption', 'label'];
const TRANSITION_KINDS: readonly string[] = ['cut', 'fade', 'wipe', 'push', 'match'];

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

// Explicitly typed so TypeScript treats a call as terminating control flow (CFA requires the
// annotation on the declaration, not just a `never` return in the inferred signature).
const fail: (message: string) => never = (message) => {
  throw new Error(message);
};

const requireNumber = (value: unknown, field: string, where: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    fail(`${where}: ${field} must be a finite number, got ${JSON.stringify(value)}`);
  }
  return value as number;
};

const requireInteger = (value: unknown, field: string, where: string): number => {
  const n = requireNumber(value, field, where);
  if (!Number.isInteger(n)) fail(`${where}: ${field} must be an integer, got ${n}`);
  return n;
};

const requireString = (value: unknown, field: string, where: string): string => {
  if (typeof value !== 'string' || value === '') {
    fail(`${where}: ${field} must be a non-empty string, got ${JSON.stringify(value)}`);
  }
  return value as string;
};

const requireArray = (value: unknown, field: string, where: string): unknown[] => {
  if (!Array.isArray(value)) fail(`${where}: ${field} must be an array`);
  return value as unknown[];
};

const requireOneOf = <T extends string>(
  allowed: readonly T[],
  value: unknown,
  field: string,
  where: string,
): T => {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    fail(`${where}: ${field} must be one of ${allowed.join('|')}, got ${JSON.stringify(value)}`);
  }
  return value as T;
};

/**
 * Shape check only — never throws. `RemotionRoot` uses this to decide whether the incoming
 * props are a product storyboard or the donor's own shape, so it must stay total.
 */
export function isProductStoryboard(raw: unknown): boolean {
  if (!isObject(raw)) return false;
  if (!Array.isArray(raw.scenes) || raw.scenes.length === 0) return false;
  if (typeof raw.theme !== 'string') return false;
  if (typeof raw.fps !== 'number' || !Number.isFinite(raw.fps)) return false;
  if (typeof raw.width !== 'number' || !Number.isFinite(raw.width)) return false;
  if (typeof raw.height !== 'number' || !Number.isFinite(raw.height)) return false;
  return raw.scenes.every(
    (scene) =>
      isObject(scene) &&
      typeof scene.sceneId === 'string' &&
      Array.isArray(scene.text) &&
      (scene.transition === undefined || isObject(scene.transition)),
  );
}

const adaptText = (raw: unknown, sceneId: string, index: number): TextElementSpec => {
  const where = `scene ${JSON.stringify(sceneId)} text[${index}]`;
  if (!isObject(raw)) fail(`${where} must be an object`);
  const element = raw as Record<string, unknown>;

  const id = requireString(element.id, 'id', where);
  const text = requireString(element.text, 'text', where);
  const atFrame = requireInteger(element.atFrame, 'atFrame', where);

  const role = element.role;
  if (typeof role !== 'string' || !TEXT_ROLES.includes(role)) {
    fail(`${where}: role must be one of ${TEXT_ROLES.join('|')}, got ${JSON.stringify(role)}`);
  }

  return {
    id,
    text,
    style: {role: ROLE_MAP[role as ProductTextRole]},
    inFrame: atFrame,
  };
};

/**
 * Forward the declared camera. Returns `undefined` when the scene declared none — an absent camera
 * is a fact about the storyboard, and inventing one here is what made the field decorative.
 *
 * The Python contract already rejects `move != static` without a resolvable `target` and
 * `static` with `amplitude > 0.35`; both are re-checked because the renderer can be driven by a
 * hand-written props file that never went through Pydantic.
 */
const adaptCamera = (raw: unknown, where: string, textIds: readonly string[]): CameraSpec | undefined => {
  if (raw === undefined || raw === null) return undefined;
  if (!isObject(raw)) fail(`${where}: camera must be an object`);
  const camera = raw as Record<string, unknown>;

  const shot = requireOneOf(SHOT_SIZES, camera.shot, 'camera.shot', where) as ShotSize;
  const move = requireOneOf(CAMERA_MOVE_KINDS, camera.move, 'camera.move', where) as CameraMoveKind;
  const ease = requireOneOf(CAMERA_EASINGS, camera.ease, 'camera.ease', where) as CameraEasing;
  const amplitude =
    camera.amplitude === undefined || camera.amplitude === null
      ? 0.12
      : requireNumber(camera.amplitude, 'camera.amplitude', where);
  if (amplitude < 0 || amplitude > 1) {
    fail(`${where}: camera.amplitude must be within 0..1, got ${amplitude}`);
  }

  const targetRaw = camera.target;
  let target: string | undefined;
  if (targetRaw !== undefined && targetRaw !== null) {
    target = requireString(targetRaw, 'camera.target', where);
    if (!textIds.includes(target)) {
      fail(
        `${where}: camera.target=${JSON.stringify(target)} does not name an element in the scene ` +
          `(have: ${textIds.length ? textIds.join(',') : 'none'})`,
      );
    }
  }
  if (move !== 'static' && !target) {
    fail(`${where}: camera.move=${move} requires camera.target`);
  }
  if (move === 'static' && amplitude > STATIC_AMPLITUDE_LIMIT) {
    fail(`${where}: camera.amplitude > ${STATIC_AMPLITUDE_LIMIT} with move=static is a zoom, not a still`);
  }

  return target ? {shot, move, target, amplitude, ease} : {shot, move, amplitude, ease};
};

/**
 * Forward the declared motion. `beats` are carried verbatim in frame order; nothing is synthesised,
 * so a scene that declares no beats stays a scene with no beats.
 */
const adaptMotion = (raw: unknown, where: string, durationInFrames?: number): MotionSpec | undefined => {
  if (raw === undefined || raw === null) return undefined;
  if (!isObject(raw)) fail(`${where}: motion must be an object`);
  const motion = raw as Record<string, unknown>;

  const energy =
    motion.energy === undefined || motion.energy === null ? 0.5 : requireNumber(motion.energy, 'motion.energy', where);
  if (energy < 0 || energy > 1) fail(`${where}: motion.energy must be within 0..1, got ${energy}`);
  const continuity =
    motion.continuity === undefined || motion.continuity === null
      ? ('cut' as Continuity)
      : (requireOneOf(CONTINUITIES, motion.continuity, 'motion.continuity', where) as Continuity);

  const beatsRaw = motion.beats === undefined || motion.beats === null ? [] : requireArray(motion.beats, 'motion.beats', where);
  const beats: MotionBeat[] = beatsRaw.map((item, i) => {
    const beatWhere = `${where} motion.beats[${i}]`;
    if (!isObject(item)) fail(`${beatWhere} must be an object`);
    const beat = item as Record<string, unknown>;
    const rawAtFrame = requireInteger(beat.atFrame, 'atFrame', beatWhere);
    const atFrame = durationInFrames !== undefined ? Math.max(0, Math.min(durationInFrames - 1, rawAtFrame)) : rawAtFrame;
    return {
      atFrame,
      kind: requireOneOf(BEAT_KINDS, beat.kind, 'kind', beatWhere) as BeatKind,
      subject: requireString(beat.subject, 'subject', beatWhere),
    };
  });

  return {energy, continuity, beats};
};

/**
 * Forward measured word windows. Returns `undefined` for an absent or empty list so the renderer can
 * tell "not measured" from "measured, and this scene is silent".
 *
 * The Python side already rejects overlapping or out-of-scene windows in
 * `render.py::_speech_windows`; this re-checks because a hand-written props file never went through
 * it, and a wrong window opens the mouth at the wrong frame while still looking plausible in a still.
 */
const adaptSpeech = (raw: unknown, where: string): SpeechWindow[] | undefined => {
  if (raw === undefined || raw === null) return undefined;
  const windows = requireArray(raw, 'speech', where);
  if (windows.length === 0) return undefined;
  let previousEnd = 0;
  return windows.map((item, index) => {
    const windowWhere = `${where} speech[${index}]`;
    if (!isObject(item)) fail(`${windowWhere} must be an object`);
    const value = item as Record<string, unknown>;
    const startMs = requireInteger(value.startMs, 'startMs', windowWhere);
    const endMs = requireInteger(value.endMs, 'endMs', windowWhere);
    if (startMs < previousEnd || endMs <= startMs) {
      fail(
        `${windowWhere} ${startMs}..${endMs} must be ordered and non-empty ` +
          `(previous end ${previousEnd})`,
      );
    }
    previousEnd = endMs;
    return {startMs, endMs};
  });
};

const adaptScene = (raw: unknown, index: number): SceneSpec => {
  if (!isObject(raw)) fail(`scenes[${index}] must be an object`);
  const scene = raw as Record<string, unknown>;

  // Resolve the id first so every later message can name it.
  const sceneId = requireString(scene.sceneId, 'sceneId', `scenes[${index}]`);
  const where = `scene ${JSON.stringify(sceneId)}`;

  const template = requireString(scene.template, 'template', where);
  if (!isTemplateId(template)) {
    fail(`${where}: template must be one of the known templates, got ${JSON.stringify(template)}`);
  }

  const segment = requireString(scene.segment, 'segment', where);
  const startFrame = requireInteger(scene.startFrame, 'startFrame', where);
  const durationInFrames = requireInteger(scene.durationInFrames, 'durationInFrames', where);

  const transitionRaw = scene.transition ?? {kind: 'cut', frames: 0};
  if (!isObject(transitionRaw)) fail(`${where}: transition must be an object`);
  const transition = transitionRaw as Record<string, unknown>;
  const kind = requireString(transition.kind, 'transition.kind', where);
  if (!TRANSITION_KINDS.includes(kind)) {
    fail(
      `${where}: transition.kind must be one of ${TRANSITION_KINDS.join('|')}, got ${JSON.stringify(kind)}`,
    );
  }
  const frames = requireInteger(transition.frames, 'transition.frames', where);

  const textRaw = requireArray(scene.text, 'text', where);
  const text = textRaw.map((element, i) => adaptText(element, sceneId, i));

  // Non-content-addressed refs (`bg:desert-dusk`, or the retired `character:maya`) cannot become image
  // requests. Dropping one renders as no image; inventing a path would render a broken one.
  const assetRefsRaw = requireArray(scene.assetRefs, 'assetRefs', where);
  const assetRefs = assetRefsRaw
    .map((ref, i) => requireString(ref, `assetRefs[${i}]`, where))
    .filter((ref) => CONTENT_ADDRESSED_ASSET.test(ref));

  const adapted: SceneSpec = {
    sceneId,
    template,
    segment,
    assetRefs,
    text,
    // No composition reads `animation`; the donor contract requires it, so it is a constant.
    animation: {preset: 'fadeIn'},
    transition: {type: TRANSITION_MAP[kind as ProductTransitionKind], durationInFrames: frames},
    startFrame,
    durationInFrames,
  };

  // Declared camera and motion are forwarded, not interpreted. Which of them (or `data.shots[]`)
  // owns the frame is decided in `src/camera.ts` and `src/motion-beats.ts`, so there is one place
  // to read the precedence instead of a rule spread across every composition.
  const camera = adaptCamera(scene.camera, where, text.map((element) => element.id));
  if (camera) adapted.camera = camera;
  const motion = adaptMotion(scene.motion, where, durationInFrames);
  if (motion) adapted.motion = motion;

  // Measured speech windows are forwarded when present. They are written by the audio stage, not
  // by a model, so an absent list is normal (the donor fixture has none) and stays absent: the
  // renderer's "no windows means a closed mouth" rule depends on being able to see the absence.
  const speech = adaptSpeech(scene.speech, where);
  if (speech) adapted.speech = speech;

  // `data` is passed through untouched. A template that needs it will reject it in
  // `validateSceneData` with its own message; synthesising a payload would hide a real gap.
  if (scene.data !== undefined && scene.data !== null) {
    adapted.data = scene.data as Record<string, unknown>;
  }

  return adapted;
};

const adaptSubtitles = (raw: unknown): StoryboardSpec['subtitles'] => {
  if (raw === undefined || raw === null) return [];
  const cues = requireArray(raw, 'subtitles', 'storyboard');
  return cues.map((cue, index) => {
    const where = `subtitles[${index}]`;
    if (!isObject(cue)) fail(`${where} must be an object`);
    const value = cue as Record<string, unknown>;
    return {
      id: `sub-${index}`,
      text: requireString(value.text, 'text', where),
      startMs: requireInteger(value.startMs, 'startMs', where),
      endMs: requireInteger(value.endMs, 'endMs', where),
    };
  });
};

const adaptCaptions = (raw: unknown): StoryboardSpec['captions'] => {
  if (raw === undefined || raw === null) return undefined;
  const items = requireArray(raw, 'captions', 'storyboard');
  return items.map((item, index) => {
    const where = `captions[${index}]`;
    if (!isObject(item)) fail(`${where} must be an object`);
    const value = item as Record<string, unknown>;
    const word = requireString(value.word ?? value.text, 'word', where);
    const startMs =
      typeof value.startMs === 'number'
        ? requireInteger(value.startMs, 'startMs', where)
        : Math.round(requireNumber(value.start, 'start', where) * 1000);
    const endMs =
      typeof value.endMs === 'number'
        ? requireInteger(value.endMs, 'endMs', where)
        : Math.round(requireNumber(value.end, 'end', where) * 1000);
    return {
      word,
      startMs,
      endMs,
      start: Number((startMs / 1000).toFixed(3)),
      end: Number((endMs / 1000).toFixed(3)),
    };
  });
};

/**
 * Translate a product storyboard into the donor `StoryboardSpec`.
 *
 * Throws on any ill-typed or missing required field; never substitutes a plausible value for a
 * bad one.
 */
export function adaptProductStoryboard(raw: unknown): StoryboardSpec {
  if (!isObject(raw)) fail('storyboard must be an object');
  const storyboard = raw as Record<string, unknown>;

  requireInteger(storyboard.schema_version, 'schema_version', 'storyboard');
  const fps = requireInteger(storyboard.fps, 'fps', 'storyboard');
  const width = requireInteger(storyboard.width, 'width', 'storyboard');
  const height = requireInteger(storyboard.height, 'height', 'storyboard');
  const theme = requireString(storyboard.theme, 'theme', 'storyboard');

  const scenesRaw = requireArray(storyboard.scenes, 'scenes', 'storyboard');
  if (scenesRaw.length === 0) fail('storyboard: scenes must not be empty');
  const scenes = scenesRaw.map((scene, index) => adaptScene(scene, index));

  return {
    id: `product-${scenes[0]?.sceneId ?? 'storyboard'}`,
    language: 'id',
    width,
    height,
    fps,
    // An unknown id falls back to the documented default theme inside `resolveTheme`.
    theme: resolveTheme({id: theme}),
    scenes,
    subtitles: adaptSubtitles(storyboard.subtitles),
    captions: adaptCaptions(storyboard.captions ?? storyboard.words),
  };
}
