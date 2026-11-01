import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import type {SceneProps} from '../components/NarrativeFrame';
import {InformativeFrame} from '../components/InformativeFrame';
import {Environment} from '../art/Environment';
import {alpha, paletteFor, shade} from '../art/palette';
import {MetricShiftData, validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';

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
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as MetricShiftData;
  const palette = paletteFor(theme, data.environment);
  const decimals = data.decimals ?? 0;
  const top = 620;
  const rowH = Math.min(240, (H - top - 560) / Math.max(1, data.metrics.length));
  const max = data.maxValue ?? Math.max(...data.metrics.map((m) => m.value), 1);
  const barMaxW = 720;
  const barX = 190;
  const format = (value: number): string =>
    value.toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals});

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
            stroke={alpha(palette.accent, t === 0 ? 0.4 : 0.14)}
            strokeWidth={2}
          />
        ))}
      </svg>
      {data.metrics.map((metric, i) => {
        const start = 6 + i * STAGGER;
        const grow = interpolate(frame, [start, start + GROW_FRAMES], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        // Ease-out: a bar that lands hard reads as a cut, a bar that settles reads as a trend.
        const eased = 1 - Math.pow(1 - grow, 3);
        const value = metric.value * eased;
        const width = Math.max(4, (metric.value / max) * barMaxW * eased);
        const y = top + i * rowH;
        return (
          <div key={`metric-${i}`} style={{position: 'absolute', left: barX, top: y, width: barMaxW}}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: 14,
                fontFamily: theme.fontBody,
                fontSize: 32,
                color: theme.primary,
              }}
            >
              <span>{metric.label}</span>
              <span style={{fontFamily: theme.fontHeading, fontSize: 46, color: palette.accent}}>
                {format(value)}
                {metric.unit ? <span style={{fontSize: 28, color: theme.secondary}}> {metric.unit}</span> : null}
              </span>
            </div>
            <div
              style={{
                height: 58,
                borderRadius: 12,
                background: alpha(shade(palette.ink, 0.05), 0.55),
                overflow: 'hidden',
                border: `2px solid ${alpha(palette.accent, 0.18)}`,
              }}
            >
              <div
                style={{
                  width,
                  height: '100%',
                  borderRadius: 10,
                  background: `linear-gradient(90deg, ${shade(palette.accent, 0.25)}, ${palette.accent})`,
                }}
              />
            </div>
          </div>
        );
      })}
    </InformativeFrame>
  );
};
