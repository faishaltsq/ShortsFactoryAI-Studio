import React, {useEffect, useState} from 'react';
import {AbsoluteFill, cancelRender, continueRender, delayRender} from 'remotion';
import {DEFAULT_TOKENS} from './themes/tokens';
import {resolveTheme} from './themes/brand';
import {Display, Body, Label} from './components/Typography';

/** Render fixture: fails instead of silently drawing system fallback fonts. */
export const RootComposition: React.FC = () => {
  const [handle] = useState(() => delayRender('Verify vendored font faces'));
  useEffect(() => {
    document.fonts.ready.then(() => {
      for (const family of ['Fraunces', 'Manrope', 'IBM Plex Mono']) {
        const loaded = Array.from(document.fonts).some(
          (face) => face.family.replaceAll('"', '') === family && face.status === 'loaded',
        );
        if (!loaded) {
          cancelRender(new Error(`Font not loaded: ${family}`));
          return;
        }
      }
      continueRender(handle);
    }).catch(cancelRender);
  }, [handle]);
  const tokens = DEFAULT_TOKENS;
  const theme = resolveTheme({id: 'editorialLight'});
  return <AbsoluteFill style={{backgroundColor: theme.background, padding: 100, justifyContent: 'center', gap: 40}}>
    <Display tokens={tokens}>Editorial font proof</Display>
    <Body tokens={tokens}>Fraunces + Manrope</Body>
    <Label tokens={tokens}>IBM Plex Mono / 1080 x 1920</Label>
  </AbsoluteFill>;
};
export default RootComposition;
