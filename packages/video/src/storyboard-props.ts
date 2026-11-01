/**
 * Storyboard prop resolution shared by the compositions' metadata functions.
 *
 * Remotion merges a composition's props as `{...defaultProps, ...editorProps, ...inputProps}`
 * (see `ResolveCompositionConfig` in the installed package), so `--props` always wins over the
 * `defaultProps` a `RemotionRoot` computed. Adapting in `RemotionRoot` alone therefore only fixed
 * the Studio preview: a render passed the raw product storyboard straight into `Short`.
 *
 * Adapting in `calculateMetadata` fixes it, because the `props` a metadata function returns
 * replace the merged props. This module holds that logic with no React or Remotion import so it
 * can be asserted directly by a plain node test.
 */

import type {CalculateMetadataFunction} from 'remotion';
import type {SceneSpec, StoryboardSpec, ThemeSpec} from './types';
import {isTemplateId} from './types';
import {adaptProductStoryboard, isProductStoryboard} from './product-adapter';

/**
 * Shape guard for the donor's own `StoryboardSpec`. Total: never throws.
 *
 * Deliberately checks the fields a composition actually dereferences — including `style.role`,
 * which is the difference between an adapted element and a raw product one.
 */
export function isDonorStoryboard(raw: unknown): raw is StoryboardSpec {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return false;
  const storyboard = raw as Record<string, unknown>;
  if (typeof storyboard.id !== 'string' || typeof storyboard.language !== 'string') return false;
  if (
    typeof storyboard.width !== 'number' ||
    typeof storyboard.height !== 'number' ||
    typeof storyboard.fps !== 'number'
  ) {
    return false;
  }
  if (!storyboard.theme || typeof storyboard.theme !== 'object' || Array.isArray(storyboard.theme)) {
    return false;
  }
  if (!Array.isArray(storyboard.scenes) || storyboard.scenes.length === 0) return false;
  return storyboard.scenes.every((candidate) => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return false;
    const scene = candidate as Record<string, unknown>;
    if (typeof scene.sceneId !== 'string') return false;
    if (typeof scene.template !== 'string' || !isTemplateId(scene.template)) return false;
    if (typeof scene.durationInFrames !== 'number') return false;
    if (!Array.isArray(scene.text)) return false;
    return scene.text.every((element) => {
      if (!element || typeof element !== 'object' || Array.isArray(element)) return false;
      const style = (element as Record<string, unknown>).style;
      return (
        !!style &&
        typeof style === 'object' &&
        !Array.isArray(style) &&
        typeof (style as Record<string, unknown>).role === 'string'
      );
    });
  });
}

/**
 * Resolve one storyboard prop to the donor contract.
 *
 * Product shape → adapted. Donor shape → passed through. Anything else throws: a permissive cast
 * here is what let a raw storyboard reach a composition and fail at `localImage` instead of at the
 * boundary.
 */
export function resolveStoryboard(raw: unknown): StoryboardSpec {
  if (isProductStoryboard(raw)) return adaptProductStoryboard(raw);
  if (isDonorStoryboard(raw)) return raw;
  throw new Error(
    'storyboard props are neither a product storyboard nor a donor StoryboardSpec: ' +
      `got ${JSON.stringify(Object.keys((raw ?? {}) as object))}`,
  );
}

/**
 * Pick the scene a per-template composition should render.
 *
 * The composition id is the template id, so a storyboard carried in the props wins: that is the
 * only way a direct render of a template composition with `{storyboard: <product>}` gets the adapted
 * scene instead of the default one. Without a storyboard prop the scene already came from the
 * adapted `defaultProps`.
 */
export function resolveSceneProps<T extends {scene: SceneSpec}>(
  props: T,
  compositionId: string,
): SceneSpec {
  // `in` narrowing rather than a cast: the storyboard prop is optional and arrives from
  // Remotion's input props, so its presence must be checked, not asserted.
  if (!("storyboard" in props)) return props.scene;
  const carried: unknown = props.storyboard;
  if (carried === undefined || carried === null) return props.scene;
  const storyboard = resolveStoryboard(carried);
  return storyboard.scenes.find((scene) => scene.template === compositionId) ?? props.scene;
}

export const totalFramesOf = (sb: StoryboardSpec): number => {
  const sceneEnd =
    sb.scenes.length > 0
      ? Math.max(...sb.scenes.map((scene) => scene.startFrame + scene.durationInFrames))
      : 0;
  const narrationEnd = sb.narration?.durationMs
    ? Math.ceil((sb.narration.durationMs / 1000) * sb.fps)
    : 0;
  const lastCaptionEnd =
    sb.captions && sb.captions.length > 0
      ? Math.ceil(Math.max(...sb.captions.map((c) => c.end)) * sb.fps)
      : 0;
  return Math.max(30, sceneEnd, narrationEnd, lastCaptionEnd);
};

/**
 * `Short` metadata. Adapts here because the props a metadata function returns replace the merged
 * `{...defaultProps, ...inputProps}`, which is what makes the adaptation survive a render.
 */
export const calculateShortMetadata: CalculateMetadataFunction<{storyboard: StoryboardSpec}> = ({
  props,
}) => {
  const storyboard = resolveStoryboard(props.storyboard);
  return {
    props: {storyboard},
    durationInFrames: totalFramesOf(storyboard),
    fps: storyboard.fps,
    width: storyboard.width,
    height: storyboard.height,
  };
};

/** Per-template metadata. The composition id is the template id. */
export const calculateSceneMetadata: CalculateMetadataFunction<{
  scene: SceneSpec;
  theme: ThemeSpec;
  watermark?: string;
}> = ({props, compositionId}) => {
  const scene = resolveSceneProps(props, compositionId);
  return {props: {...props, scene}, durationInFrames: scene.durationInFrames};
};
