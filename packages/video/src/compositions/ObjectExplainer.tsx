import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {SceneProps} from '../components/NarrativeFrame';
import type {LayoutMode, CausalStateSpec} from '../types';
import {InformativeFrame} from '../components/InformativeFrame';
import {ObjectStage} from '../art/Stage';
import {paletteFor} from '../art/palette';
import {ExplainerData, validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';

/**
 * `ObjectExplainer` — the engine's primary template.
 *
 * The storyboard names things (a GPU, a rack, a satellite), where they stand, and what links them.
 * This component renders exactly that: nothing on screen exists unless `data.objects` named it, and
 * nothing moves unless `at`, `highlight` or `flows` said when. There is no fallback illustration and
 * no presenter, because either would be content the narration did not ask for.
 */
/**
 * Turns declared beats into object highlights.
 *
 * A beat is the one place a storyboard says *when* something deserves the eye — "at frame 48, look
 * at the rack". Without this the field would be recorded and ignored, which is exactly the kind of
 * contract that reads as motion in a document and does nothing on screen. The subject may be
 * `object:<index>` or an object's own label/kind; anything else is left to the camera.
 */
const highlightsFromBeats = (
  scene: SceneProps['scene'],
  objects: readonly {kind: string; label?: string; highlight?: [number, number]}[],
): ([number, number] | undefined)[] => {
  const windows: ([number, number] | undefined)[] = objects.map((object) => object.highlight);
  const beats = scene.motion?.beats ?? [];
  for (const beat of beats) {
    if (beat.kind !== 'action' && beat.kind !== 'reveal' && beat.kind !== 'emphasis') continue;
    const selector = /^object:(\d+)$/.exec(beat.subject);
    const index = selector
      ? Number(selector[1])
      : objects.findIndex(
          (object) => object.kind === beat.subject || object.label?.toLowerCase() === beat.subject.toLowerCase(),
        );
    if (index < 0 || index >= objects.length) continue;
    // A declared highlight wins: the storyboard author already said when this object is the subject.
    if (windows[index]) continue;
    windows[index] = [beat.atFrame, Math.min(scene.durationInFrames - 1, beat.atFrame + 14)];
  }
  return windows;
};

export const ObjectExplainerScene: React.FC<SceneProps> = ({scene, theme: inputTheme, watermark}) => {
  const theme = resolveTheme(inputTheme);
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as ExplainerData;
  const palette = paletteFor(theme, data.environment);
  const withBeats = React.useMemo(() => {
    const windows = highlightsFromBeats(scene, data.objects);
    return {
      ...data,
      objects: data.objects.map((object, index) => ({...object, highlight: windows[index]})),
    };
  }, [scene, data]);
  const lastArrival = Math.max(0, ...data.objects.map((o) => o.at ?? 0));
  const title = data.title ?? scene.text.find((t) => t.style.role === 'title')?.text;
  // The title steps back once the object it names is on stage: two things competing for the eye is
  // how a graphic ends up saying nothing.
  const titleOpacity = frame > lastArrival + 24 ? 0.55 : 1;
  const layoutMode =
    scene.layoutMode ??
    (scene as unknown as {layout_mode?: LayoutMode}).layout_mode ??
    (data.layoutMode as LayoutMode | undefined);
  const causalState =
    scene.causalState ??
    (scene as unknown as {causal_state?: CausalStateSpec}).causal_state ??
    data.causalState;

  return (
    <InformativeFrame scene={scene} theme={theme} watermark={watermark} title={title} caption={data.caption} titleOpacity={titleOpacity}>
      <ObjectStage
        data={withBeats}
        environment={data.environment}
        palette={palette}
        frame={frame}
        labelColor={theme.secondary}
        layoutMode={layoutMode}
        causalState={causalState}
      />
    </InformativeFrame>
  );
};
