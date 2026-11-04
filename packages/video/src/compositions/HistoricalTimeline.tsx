import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {TimelineData, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {Body, Kicker} from '../components/Typography';
import {softSlideFade} from '../components/motion';

export const HistoricalTimelineScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  validateSceneData(scene);
  const data = scene.data as unknown as TimelineData;
  const progress = interpolate(
    frame,
    [0, Math.max(1, scene.durationInFrames - 20)],
    [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
  );

  return (
    <NarrativeFrame {...props} title={data.title}>
      <div
        style={{
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-evenly',
          gap: SPACE.card,
          flex: 1,
          minHeight: 0,
          maxHeight: 1040,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: SPACE.card,
            top: SPACE.card,
            bottom: SPACE.card,
            width: 6,
            background: tokens.line,
            opacity: 0.7,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: SPACE.card,
            top: SPACE.card,
            height: `${progress * 90}%`,
            width: 6,
            background: tokens.accent,
          }}
        />
        {data.events.map((event, i) => {
          const delay = i * 12;
          const local = Math.max(0, frame - delay);
          const anim = softSlideFade({
            frame: local,
            fps,
            durationInFrames: 18,
            distance: 24,
            direction: 'up',
          });
          const isVisible = frame >= delay;

          return (
            <div
              key={i}
              style={{
                position: 'relative',
                display: 'flex',
                alignItems: 'flex-start',
                gap: SPACE.section,
                opacity: isVisible ? anim.opacity : 0,
                transform: anim.transform,
              }}
            >
              <div
                style={{
                  width: SPACE.card * 2,
                  height: SPACE.card * 2,
                  borderRadius: '50%',
                  background: tokens.accent,
                  flexShrink: 0,
                  border: `6px solid ${tokens.background}`,
                  boxShadow: tokens.shadow.sm,
                  zIndex: 1,
                }}
              />
              <div
                style={{
                  flex: 1,
                  padding: SPACE.card,
                  borderRadius: SPACE.radius,
                  background: tokens.surface,
                  border: `1px solid ${tokens.line}`,
                  boxShadow: tokens.shadow.sm,
                }}
              >
                <Kicker tokens={tokens} style={{marginBottom: SPACE.small}}>
                  {event.date}
                </Kicker>
                <Body tokens={tokens} style={{fontWeight: 700, lineHeight: 1.2}}>
                  {event.label}
                </Body>
                {event.detail ? (
                  <Body tokens={tokens} small color={tokens.textSecondary} style={{marginTop: SPACE.small, lineHeight: 1.3}}>
                    {event.detail}
                  </Body>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </NarrativeFrame>
  );
};
