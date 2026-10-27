import React from 'react';
import {SCENE_RENDERERS} from './registry';
import type {SceneProps} from '../components/NarrativeFrame';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';
import {validateSceneData} from '../scene-data';

export const Thumbnail: React.FC<SceneProps & {headline: string}> = ({scene, theme: inputTheme, watermark, headline}) => {
  validateSceneData(scene);
  if (!headline.trim() || headline.length > 32) throw new Error('Invalid thumbnail headline');
  const theme = resolveTheme(inputTheme);
  const Component = SCENE_RENDERERS[scene.template];
  return <div style={{position: 'absolute', inset: 0, background: theme.background}}>
    <Component scene={scene} theme={theme} watermark={watermark} />
    <div style={{position: 'absolute', left: 72, right: 72, bottom: 344, padding: SPACE.section,
      background: theme.accent, color: theme.background, borderRadius: SPACE.radius,
      fontFamily: theme.fontHeading, fontSize: TYPE.number, textAlign: 'center', lineHeight: 1.1, overflowWrap: 'anywhere'}}>{headline}</div>
  </div>;
};
