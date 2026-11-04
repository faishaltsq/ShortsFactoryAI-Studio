import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneProps} from '../components/NarrativeFrame';
import {InformativeFrame} from '../components/InformativeFrame';
import {Environment} from '../art/Environment';
import {alpha, paletteFor, shade} from '../art/palette';
import {MetricShiftData, validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {Body, Metric} from '../components/Typography';
import {gentleCount, softSlideFade} from '../components/motion';

const W = 1080;
const H = 1920;
/** Frames a bar takes to reach its value. Shared, so several bars on one scene stay in sync. */
const GROW_FRAMES = 40;
/** Gap between one bar starting and the next. */
const STAGGER = 10;

/**
 * `MetricShift` — a quantity that changes.
 *
 * Every bar carries its own number, counted to the value the storyboard declared, so the motion and
 * the figure agree at every frame. A bar that grows over a label that already reads the final number
 * is a lie the eye catches; this template never draws that.
 */
export const MetricShiftScene: React.FC<SceneProps> = ({scene, theme: inputTheme, watermark}) => {
  const theme = resolveTheme(inputTheme);
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  validateSceneData(scene);
  const data = scene.data as unknown as MetricShiftData;
  const palette = paletteFor(theme, data.environment);
  const decimals = data.decimals ?? 0;
  const top = 620;
  const rowH = Math.min(240, (H - top - 560) / Math.max(1, data.metrics.length));
  const max = data.maxValue ?? Math.max(...data.metrics.map((m) => m.value), 1);
  const barMaxW = 720;
  const barX = 190;

  return (
    <InformativeFrame scene={scene} theme={theme} watermark={watermark} title={data.title} caption={data.caption}>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        <Environment kind={data.environment} palette={palette} frame={frame} />
      </svg>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        {/* the scale the bars are read against */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <line
            key={t}
            x1={barX + barMaxW * t}
            y1={top - 40}
            x2={barX + barMaxW * t}
            y2={top + rowH * data.metrics.length}
            stroke={t === 0 ? alpha(tokens.line, 0.9) : alpha(tokens.line, 0.45)}
            strokeWidth={2}
          />
        ))}
      </svg>
      {data.metrics.map((metric, i) => {
        const start = 6 + i * STAGGER;
        const countLocal = Math.max(0, frame - start);
        const {formatted, progress} = gentleCount({
          from: 0,
          to: metric.value,
          frame: countLocal,
          durationInFrames: GROW_FRAMES,
          decimals,
        });
        const width = Math.max(4, (metric.value / max) * barMaxW * progress);
        const barColor = tokens.chartColors[i % tokens.chartColors.length];
        const y = top + i * rowH;
        const rowSlide = softSlideFade({
          frame: countLocal,
          fps,
          durationInFrames: 18,
          direction: 'up',
          distance: 14,
        });

        return (
          <div
            key={`metric-${i}`}
            style={{
              position: 'absolute',
              left: barX,
              top: y,
              width: barMaxW,
              opacity: rowSlide.opacity,
              transform: rowSlide.transform,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: 14,
              }}
            >
              <Body
                tokens={tokens}
                small
                style={{
                  fontWeight: 600,
                  color: tokens.textPrimary,
                  fontSize: 34,
                }}
              >
                {metric.label}
              </Body>
              <Metric
                tokens={tokens}
                size="lg"
                color={tokens.textPrimary}
                suffix={metric.unit}
              >
                {formatted}
              </Metric>
            </div>
            <div
              style={{
                height: 58,
                borderRadius: 14,
                background: alpha(tokens.surface, 0.9),
                overflow: 'hidden',
                border: `1.5px solid ${tokens.line}`,
                boxShadow: tokens.shadow.sm,
              }}
            >
              <div
                style={{
                  width,
                  height: '100%',
                  borderRadius: 12,
                  background: `linear-gradient(90deg, ${shade(barColor, 0.15)}, ${barColor})`,
                  boxShadow: `0 2px 10px ${alpha(barColor, 0.25)}`,
                }}
              />
            </div>
          </div>
        );
      })}
    </InformativeFrame>
  );
};
