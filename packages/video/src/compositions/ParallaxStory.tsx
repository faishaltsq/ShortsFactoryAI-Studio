import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {Prop} from '../art/Prop';
import {paletteFor} from '../art/palette';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {ParallaxData, localImage, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';

export const ParallaxStoryScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as ParallaxData;
  const progress = interpolate(frame, [0, scene.durationInFrames - 1], [-1, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <NarrativeFrame {...props} title={data.title}>
    <div style={{position: 'relative', flex: 1, minHeight: 0, overflow: 'hidden', borderRadius: SPACE.radius, background: theme.backgroundAccent}}>
      {[...data.layers].sort((a, b) => a.depth - b.depth).map((layer, i) => <div key={i} style={{position: 'absolute', inset: -50, transform: `translateX(${progress * layer.depth * 46}px) scale(${1.05 + layer.depth * 0.06})`}}>
        {layer.assetRef ? <Img src={staticFile(localImage(layer.assetRef))} style={{width: '100%', height: '100%', objectFit: 'cover'}} /> : (
          // Prop renders a positioned div, so it must live in HTML, not inside <svg>.
          <div style={{position: 'absolute', inset: 0}}>
            {layer.shape === 'circle' ? <Prop prop={{kind: 'moon', x: 0.7, y: 0.26, scale: 1.1}} palette={paletteFor(theme, 'night')} frame={frame} index={i} fit="box" /> : null}
            {/* Dusk, not night: the ground palette responds to time of day, so the ridge
                stays a shade of the theme's own ground instead of vanishing into the card. */}
            {layer.shape === 'ridge' ? <Prop prop={{kind: 'mountain', x: 0.5, y: 0.78, scale: 3.2}} palette={paletteFor(theme, 'dusk')} frame={frame} index={i} fit="box" /> : null}
            {layer.shape === 'city' ? <Prop prop={{kind: 'tower', x: 0.5, y: 0.72, scale: 3.4}} palette={paletteFor(theme, 'night')} frame={frame} index={i} fit="box" /> : null}
          </div>
        )}
      </div>)}
      <div style={{position: 'absolute', bottom: SPACE.card, left: SPACE.card, right: SPACE.card, height: 8, background: theme.accent, opacity: 0.8}} />
    </div>
    {data.caption ? <div style={{fontSize: TYPE.body, lineHeight: 1.25, color: theme.secondary}}>{data.caption}</div> : null}
  </NarrativeFrame>;
};
