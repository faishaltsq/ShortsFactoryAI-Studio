import React from 'react';
import {Composition, getInputProps} from 'remotion';
import {TEMPLATE_IDS} from './types';
import type {StoryboardSpec} from './types';
import {resolveTheme} from './themes/brand';
import {Short} from './compositions/Short';
import {Thumbnail} from './compositions/Thumbnail';
import {SCENE_RENDERERS} from './compositions/registry';
import {DeclaredCameraScope} from './components/DeclaredCameraScope';
import {SAMPLE_STORYBOARD} from './sample/storyboard';
import {
  calculateSceneMetadata,
  calculateShortMetadata,
  resolveStoryboard,
  totalFramesOf,
} from './storyboard-props';
import fixture from '../fixtures/all-templates.json';

export {calculateSceneMetadata};

export const RemotionRoot: React.FC = () => {
  const input = getInputProps() as {storyboard?: unknown} | null;
  // A malformed storyboard throws here rather than being passed through: a bad shape must fail at
  // the boundary, not inside a composition mid-render.
  const storyboard: StoryboardSpec = resolveStoryboard(input?.storyboard ?? SAMPLE_STORYBOARD);
  const defaults = fixture as unknown as StoryboardSpec;
  return <>
    <Composition id="Short" component={Short} defaultProps={{storyboard}} calculateMetadata={calculateShortMetadata}
      durationInFrames={totalFramesOf(storyboard)} fps={storyboard.fps} width={storyboard.width} height={storyboard.height} />
    <Composition id="Thumbnail" component={Thumbnail}
      defaultProps={{scene: storyboard.scenes[0], theme: resolveTheme(storyboard.theme), headline: 'DEMO', watermark: storyboard.watermark?.text}}
      calculateMetadata={({props}) => ({durationInFrames: props.scene.durationInFrames})} durationInFrames={storyboard.scenes[0].durationInFrames}
      fps={30} width={1080} height={1920} />
    {TEMPLATE_IDS.map(id => {
      const scene = storyboard.scenes.find(s => s.template === id) ?? defaults.scenes.find(s => s.template === id)!;
      // The declared camera must reach every template in every composition context (a per-template
      // `remotion still` as well as the full `Short` timeline). `Short.renderScene` wraps its own
      // dispatch, so wrapping again there would double-apply the transform; these standalone
      // compositions have no wrapper of their own. The composition runs on its own timeline, so
      // the scene enters it re-based to frame 0 — the same re-basing a cut performs when `Short`
      // mounts the scene inside a `<Sequence from={startFrame}>`.
      const local = {...scene, startFrame: 0};
      const TemplateWithCamera: React.FC<{
        scene: typeof local;
        theme: StoryboardSpec['theme'];
        watermark?: string;
      }> = ({scene: propsScene, theme: propsTheme, watermark: propsWatermark}) => (
        // A CLI `--props` scene or the fixture default both pass through the declared camera:
        // the wrapper is the composition's single camera authority, exactly as in `Short`.
        <DeclaredCameraScope scene={propsScene}>
          {React.createElement(SCENE_RENDERERS[id], {
            scene: propsScene,
            theme: propsTheme,
            watermark: propsWatermark,
          })}
        </DeclaredCameraScope>
      );
      return <Composition key={id} id={id} component={TemplateWithCamera}
        defaultProps={{scene: local, theme: resolveTheme(storyboard.theme), watermark: storyboard.watermark?.text}}
        calculateMetadata={calculateSceneMetadata} durationInFrames={scene.durationInFrames}
        fps={30} width={1080} height={1920} />;
    })}
  </>;
};
