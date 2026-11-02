import React from 'react';
import type {SceneSpec, ThemeSpec} from '../types';
import {resolveTheme, TYPE, SPACE} from '../themes/brand';
import {Background, SafeArea} from './Chrome';
import {validateSceneData} from '../scene-data';
import {pinnedOverlayStyle} from './CameraPinning';

export type SceneProps = {scene: SceneSpec; theme: ThemeSpec; watermark?: string};
export const NarrativeFrame: React.FC<SceneProps & {title?: string; children: React.ReactNode}> = ({scene, theme: inputTheme, watermark, title, children}) => {
  validateSceneData(scene);
  const theme = resolveTheme(inputTheme);
  // The type is an annotation over the picture (see InformativeFrame): the safe-area column is
  // pinned against the declared camera so a pan cannot push the words out of the frame.
  const pinned = pinnedOverlayStyle();
  return <div style={{position: 'absolute', inset: 0, background: theme.background}}>
    <Background theme={theme} variant="split" />
    <div style={{position: 'absolute', inset: 0, ...pinned}}>
      <SafeArea>
        <div style={{height: '100%', display: 'flex', flexDirection: 'column', gap: SPACE.section, overflow: 'hidden', color: theme.primary, fontFamily: theme.fontBody}}>
          {title ? <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.heading, lineHeight: 1.1, flexShrink: 0, overflowWrap: 'anywhere'}}>{title}</div> : null}
          {children}
        </div>
      </SafeArea>
    </div>
  </div>;
};
