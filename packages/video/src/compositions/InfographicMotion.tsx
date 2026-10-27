import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {InfographicData, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';

export const InfographicMotionScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as InfographicData;
  const maximum = data.maxValue ?? Math.max(1, ...data.items.map(i => i.value));
  return <NarrativeFrame {...props} title={data.title}>
    <div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly', gap: SPACE.section, minHeight: 0}}>
      {data.items.map((item, i) => {
        const start = i * Math.min(10, Math.floor((scene.durationInFrames - 2) / data.items.length));
        const end = Math.min(scene.durationInFrames - 1, start + 45);
        const progress = frame >= end ? 1 : interpolate(frame, [start, end], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        const value = frame >= end ? item.value : item.value * progress;
        return <div key={i} style={{padding: SPACE.card, background: theme.backgroundAccent, borderRadius: SPACE.radius}}>
          <div style={{fontSize: TYPE.body, color: theme.secondary, marginBottom: SPACE.small}}>{item.label}</div>
          <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.number, color: theme.primary, fontVariantNumeric: 'tabular-nums', marginBottom: SPACE.card}}>
            {value.toFixed(data.decimals ?? 0)} <span style={{fontSize: TYPE.kicker, color: theme.accent}}>{item.unit}</span>
          </div>
          <div style={{height: 22, borderRadius: SPACE.radius, background: theme.background, overflow: 'hidden'}}>
            <div style={{width: `${item.value / maximum * progress * 100}%`, height: '100%', background: theme.accent}} />
          </div>
        </div>;
      })}
    </div>
  </NarrativeFrame>;
};
