import React from 'react';
import {Composition, getInputProps} from 'remotion';
import {TEMPLATE_IDS} from './types';
import type {StoryboardSpec} from './types';
import {resolveTheme} from './themes/brand';
import {Short} from './compositions/Short';
import {Thumbnail} from './compositions/Thumbnail';
import {SCENE_RENDERERS} from './compositions/registry';
import {CharacterSheet} from './compositions/CharacterSheet';
import {CharacterReel, REEL_DURATION} from './compositions/CharacterReel';
import {SAMPLE_STORYBOARD} from './sample/storyboard';
import {
  calculateSceneMetadata,
  calculateShortMetadata,
  resolveStoryboard,
} from './storyboard-props';
import fixture from '../fixtures/all-templates.json';

export {calculateSceneMetadata};

const totalFramesOf = (sb: StoryboardSpec): number => Math.max(...sb.scenes.map(s => s.startFrame + s.durationInFrames));

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
    <Composition id="CharacterSheet" component={CharacterSheet} defaultProps={{theme: resolveTheme(storyboard.theme)}}
      durationInFrames={300} fps={30} width={1080} height={1920} />
    <Composition id="CharacterReel" component={CharacterReel} defaultProps={{theme: resolveTheme(storyboard.theme)}}
      durationInFrames={REEL_DURATION} fps={30} width={1080} height={1920} />
    <Composition id="CharacterReelBefore" component={CharacterReel} defaultProps={{theme: resolveTheme(storyboard.theme), compare: true}}
      durationInFrames={REEL_DURATION} fps={30} width={1080} height={1920} />
    {TEMPLATE_IDS.map(id => {
      const scene = storyboard.scenes.find(s => s.template === id) ?? defaults.scenes.find(s => s.template === id)!;
      return <Composition key={id} id={id} component={SCENE_RENDERERS[id]}
        defaultProps={{scene, theme: resolveTheme(storyboard.theme), watermark: storyboard.watermark?.text}}
        calculateMetadata={calculateSceneMetadata} durationInFrames={scene.durationInFrames}
        fps={30} width={1080} height={1920} />;
    })}
  </>;
};
