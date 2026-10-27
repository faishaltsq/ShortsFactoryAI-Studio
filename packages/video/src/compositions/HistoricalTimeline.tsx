import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {TimelineData, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';

export const HistoricalTimelineScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as TimelineData;
  const progress = interpolate(frame, [0, Math.max(1, scene.durationInFrames - 20)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <NarrativeFrame {...props} title={data.title}>
    <div style={{position: 'relative', display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly', gap: SPACE.card, flex: 1, minHeight: 0}}>
      <div style={{position: 'absolute', left: SPACE.card, top: SPACE.card, bottom: SPACE.card, width: 6, background: theme.secondary, opacity: 0.3}} />
      <div style={{position: 'absolute', left: SPACE.card, top: SPACE.card, height: `${progress * 90}%`, width: 6, background: theme.accent}} />
      {data.events.map((event, i) => {
        const local = interpolate(frame, [i * 12, i * 12 + 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        return <div key={i} style={{position: 'relative', display: 'flex', alignItems: 'flex-start', gap: SPACE.section, opacity: local, transform: `translateY(${(1 - local) * 22}px)`}}>
          <div style={{width: SPACE.card * 2, height: SPACE.card * 2, borderRadius: '50%', background: theme.accent, flexShrink: 0, border: `6px solid ${theme.background}`, zIndex: 1}} />
          <div style={{flex: 1, padding: SPACE.card, borderRadius: SPACE.radius, background: theme.backgroundAccent}}>
            <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.kicker, color: theme.accent, marginBottom: SPACE.small}}>{event.date}</div>
            <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.body, lineHeight: 1.15}}>{event.label}</div>
            {event.detail ? <div style={{fontSize: TYPE.detail, color: theme.secondary, marginTop: SPACE.small, lineHeight: 1.25}}>{event.detail}</div> : null}
          </div>
        </div>;
      })}
    </div>
  </NarrativeFrame>;
};
