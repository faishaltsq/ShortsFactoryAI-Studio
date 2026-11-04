import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneProps} from '../components/NarrativeFrame';
import {InformativeFrame} from '../components/InformativeFrame';
import {Environment} from '../art/Environment';
import {alpha, paletteFor, tint} from '../art/palette';
import {ProcessFlowData, validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {Body, Label} from '../components/Typography';
import {EDITORIAL_EASING, lineDraw, maskedReveal, softSlideFade} from '../components/motion';

const W = 1080;
const H = 1920;
/** Frames one link takes to travel. Every other timing in the template is derived from it. */
const LINK_FRAMES = 26;

/**
 * `ProcessFlow` — how a thing works, one stage at a time.
 *
 * The motion is the explanation: a packet leaves stage *n* and arrives at stage *n+1*, and the stage
 * it lands on lights up. A viewer who reads nothing still learns the order. This is the template for
 * "how a training run works", "how a request reaches a data centre", "how a chip is fabricated".
 */
export const ProcessFlowScene: React.FC<SceneProps> = ({scene, theme: inputTheme, watermark}) => {
  const theme = resolveTheme(inputTheme);
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  validateSceneData(scene);
  const data = scene.data as unknown as ProcessFlowData;
  const palette = paletteFor(theme, data.environment);
  const steps = data.steps;
  const count = steps.length;

  // Nodes sit in a right-hand column; the rail runs down the left so the chain reads top-to-bottom
  // even on a 9:16 frame where a horizontal chain would be illegibly narrow.
  const top = 560;
  const gap = Math.min(300, (H - top - 520) / Math.max(1, count - 1));
  const nodeX = 530;
  const nodeW = 560;
  const nodeH = 168;
  const railX = 176;

  const stepAt = (i: number): number => i * LINK_FRAMES;

  return (
    <InformativeFrame scene={scene} theme={theme} watermark={watermark} title={data.title} caption={data.caption}>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        <Environment kind={data.environment} palette={palette} frame={frame} />
      </svg>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        {/* the rail */}
        <line
          x1={railX}
          y1={top}
          x2={railX}
          y2={top + gap * (count - 1)}
          stroke={alpha(tokens.accent, 0.25)}
          strokeWidth={6}
          strokeLinecap="round"
        />
        {steps.slice(0, -1).map((_, i) => {
          const linkStart = stepAt(i);
          const local = Math.max(0, frame - linkStart);
          const rawTravel = Math.min(1, local / LINK_FRAMES);
          const travelled = interpolate(rawTravel, [0, 1], [0, 1], {
            easing: EDITORIAL_EASING.smoothOut,
          });
          const y1 = top + gap * i;
          const y2 = top + gap * (i + 1);
          // The lit segment grows with the packet, so the rail records how far the process has got.
          return (
            <g key={`link-${i}`}>
              <line
                x1={railX}
                y1={y1}
                x2={railX}
                y2={y1 + (y2 - y1) * travelled}
                stroke={tokens.accent}
                strokeWidth={6}
                strokeLinecap="round"
                opacity={0.9}
              />
              {local > 0 && travelled < 1 ? (
                <circle cx={railX} cy={y1 + (y2 - y1) * travelled} r={13} fill={tint(tokens.accent, 0.45)} />
              ) : null}
            </g>
          );
        })}
      </svg>
      {steps.map((step, i) => {
        const start = stepAt(i);
        const stepLocal = Math.max(0, frame - start);
        const cardReveal = maskedReveal({
          frame: stepLocal,
          fps,
          durationInFrames: 18,
          direction: 'left',
        });
        const slide = softSlideFade({
          frame: stepLocal,
          fps,
          durationInFrames: 18,
          direction: 'left',
          distance: 20,
        });
        const isRevealed = stepLocal >= 18;
        const y = top + gap * i;
        // A stage is "now" for one link's worth of frames after it lands; afterwards it is history
        // and drops back so the current stage is always the brightest thing in the column.
        const current = frame >= start && frame < start + LINK_FRAMES;
        const done = frame >= start + LINK_FRAMES;
        const border = current ? tokens.accent : done ? alpha(tokens.accent, 0.45) : tokens.line;
        const stepColor = tokens.chartColors[i % tokens.chartColors.length];
        return (
          <React.Fragment key={`step-${i}`}>
            <div
              style={{
                position: 'absolute',
                left: railX,
                top: y - 1.5,
                width: nodeX - nodeW / 2 - railX,
                height: 3,
                background: alpha(tokens.accent, current ? 0.9 : 0.35),
                ...lineDraw({
                  frame: stepLocal,
                  fps,
                  durationInFrames: 14,
                  orientation: 'horizontal',
                }),
              }}
            />
            <div
              style={{
                position: 'absolute',
                left: nodeX - nodeW / 2,
                top: y - nodeH / 2,
                width: nodeW,
                height: nodeH,
                opacity: cardReveal.opacity,
                clipPath: isRevealed ? undefined : cardReveal.clipPath,
                transform: slide.transform,
                borderRadius: 20,
                background: tokens.elevatedSurface,
                border: `2px solid ${border}`,
                padding: '22px 26px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                gap: 8,
                boxShadow: current
                  ? `0 0 36px ${alpha(tokens.accent, 0.3)}, ${tokens.shadow.md}`
                  : tokens.shadow.md,
              }}
            >
              <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
                <div
                  style={{
                    width: 42,
                    height: 42,
                    borderRadius: 21,
                    background: current ? tokens.accent : alpha(stepColor, 0.16),
                    border: `1.5px solid ${current ? tokens.accent : alpha(stepColor, 0.35)}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                  }}
                >
                  <Label
                    tokens={tokens}
                    color={current ? '#FFFFFF' : stepColor}
                    style={{fontSize: 22, fontWeight: 700, lineHeight: 1}}
                  >
                    {i + 1}
                  </Label>
                </div>
                <Body
                  tokens={tokens}
                  small
                  style={{
                    fontWeight: 600,
                    color: tokens.textPrimary,
                    lineHeight: 1.2,
                  }}
                >
                  {step.label}
                </Body>
              </div>
              {step.detail ? (
                <Body
                  tokens={tokens}
                  small
                  style={{
                    fontSize: 34,
                    color: tokens.textSecondary,
                    lineHeight: 1.3,
                    marginLeft: 56,
                  }}
                >
                  {step.detail}
                </Body>
              ) : null}
            </div>
          </React.Fragment>
        );
      })}
      {/* Progress readout: the chain's own clock, so the last frame is visibly "finished". */}
      <div
        style={{
          position: 'absolute',
          left: 72,
          right: 72,
          bottom: 440,
          height: 8,
          borderRadius: 4,
          background: alpha(tokens.line, 0.75),
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${interpolate(frame, [0, stepAt(count - 1) + LINK_FRAMES], [0, 100], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
              easing: EDITORIAL_EASING.smoothOut,
            })}%`,
            background: tokens.accent,
            borderRadius: 4,
          }}
        />
      </div>
    </InformativeFrame>
  );
};
