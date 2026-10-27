import React from 'react';
import type {SceneSpec, ThemeSpec} from '../types';
import {resolveTheme, TYPE, SPACE} from '../themes/brand';
import {Background, SafeArea, Watermark} from './Chrome';
import {validateSceneData} from '../scene-data';

export type SceneProps = {scene: SceneSpec; theme: ThemeSpec; watermark?: string};
export const NarrativeFrame: React.FC<SceneProps & {title?: string; children: React.ReactNode}> = ({scene, theme: inputTheme, watermark, title, children}) => {
  validateSceneData(scene);
  const theme = resolveTheme(inputTheme);
  return <div style={{position: 'absolute', inset: 0, background: theme.background}}>
    <Background theme={theme} variant="split" />
    {watermark ? <Watermark text={watermark} theme={theme} /> : null}
    <SafeArea>
      <div style={{height: '100%', display: 'flex', flexDirection: 'column', gap: SPACE.section, overflow: 'hidden', color: theme.primary, fontFamily: theme.fontBody}}>
        {title ? <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.heading, lineHeight: 1.1, flexShrink: 0, overflowWrap: 'anywhere'}}>{title}</div> : null}
        {children}
      </div>
    </SafeArea>
  </div>;
};
