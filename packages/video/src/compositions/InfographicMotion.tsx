import React from 'react';
import {useCurrentFrame} from 'remotion';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {InfographicData, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {Label, Metric} from '../components/Typography';
import {gentleCount} from '../components/motion';

export const InfographicMotionScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as InfographicData;
  const maximum = data.maxValue ?? Math.max(1, ...data.items.map((i) => i.value));

  return (
    <NarrativeFrame {...props} title={data.title}>
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-evenly',
          gap: SPACE.section,
          minHeight: 0,
          transform: 'translateY(-40px)',
        }}
      >
        {data.items.map((item, i) => {
          const step = Math.min(10, Math.floor((scene.durationInFrames - 2) / data.items.length));
          const start = i * step;
          const duration = Math.min(45, Math.max(1, scene.durationInFrames - 1 - start));
          const count = gentleCount({
            from: 0,
            to: item.value,
            frame: Math.max(0, frame - start),
            durationInFrames: duration,
            decimals: data.decimals ?? 0,
          });

          return (
            <div
              key={i}
              style={{
                padding: SPACE.card,
                background: tokens.surface,
                borderRadius: SPACE.radius,
                border: `1px solid ${tokens.line}`,
                boxShadow: tokens.shadow.sm,
              }}
            >
              <Label
                tokens={tokens}
                style={{
                  display: 'block',
                  color: tokens.textSecondary,
                  marginBottom: SPACE.small,
                }}
              >
                {item.label}
              </Label>
              <div style={{marginBottom: SPACE.card}}>
                <Metric tokens={tokens} size="xl" suffix={item.unit}>
                  {count.formatted}
                </Metric>
              </div>
              <div
                style={{
                  height: 20,
                  borderRadius: 10,
                  background: tokens.background,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: `${((item.value / maximum) * count.progress * 100).toFixed(2)}%`,
                    height: '100%',
                    background: tokens.accent,
                    borderRadius: 10,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </NarrativeFrame>
  );
};
