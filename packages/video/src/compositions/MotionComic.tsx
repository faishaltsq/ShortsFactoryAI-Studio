import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {Figure} from '../art/Figure';
import {paletteFor} from '../art/palette';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {ComicData, localImage, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';

export const MotionComicScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as ComicData;
  return <NarrativeFrame {...props} title={data.title}>
    <div style={{display: 'flex', flexDirection: 'column', flex: 1, gap: SPACE.card, minHeight: 0}}>
      {data.panels.map((panel, i) => {
        const progress = interpolate(frame, [i * 10, i * 10 + 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        return <div key={i} style={{position: 'relative', flex: 1, minHeight: 0, display: 'flex', gap: SPACE.card, alignItems: 'center', overflow: 'hidden', padding: SPACE.card, border: `4px solid ${theme.primary}`, borderRadius: SPACE.radius, background: theme.backgroundAccent, opacity: progress, transform: `translateX(${(1 - progress) * (i % 2 ? 48 : -48)}px)`}}>
          {panel.assetRef ? (
            <Img src={staticFile(localImage(panel.assetRef))} style={{width: '34%', height: '100%', objectFit: 'cover', borderRadius: SPACE.radius}} />
          ) : (
            <div style={{width: '34%', height: '100%', position: 'relative', flexShrink: 0}}>
              <Figure
                actor={{pose: i === 0 ? 'point' : i === 1 ? 'shrug' : 'stand', x: 0.5, ground: 0.96, scale: 0.55, facing: 'right', tone: 'accent', silhouette: false}}
                palette={paletteFor(theme, 'night')}
                frame={frame}
                index={i}
                fit="box"
              />
            </div>
          )}
          <div style={{flex: 1, minWidth: 0}}>
            {panel.speaker ? <div style={{fontSize: TYPE.kicker, fontWeight: 800, color: theme.accent, marginBottom: SPACE.small}}>{panel.speaker}</div> : null}
            <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.body, lineHeight: 1.18, overflowWrap: 'anywhere'}}>{panel.caption}</div>
          </div>
        </div>;
      })}
    </div>
  </NarrativeFrame>;
};
