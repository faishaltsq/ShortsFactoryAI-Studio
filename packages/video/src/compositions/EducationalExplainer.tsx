import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneSpec, ThemeSpec} from '../types';
import {resolveTheme} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {TYPE_SCALE} from '../themes/type';
import {Body, Headline, Kicker} from '../components/Typography';
import {cohesiveGroupReveal, lineDraw, softSlideFade} from '../components/motion';
import {AccentBar, Background, SafeArea, Watermark} from '../components/Chrome';
import {rand} from '../art/rng';
import {alpha} from '../art/palette';

const bulletsOf = (scene: SceneSpec): string[] => {
  const raw = scene.data?.bullets;
  if (Array.isArray(raw)) return raw.map(String);
  return scene.segment.split(/(?<=[.!?])\s+/).filter(Boolean).slice(0, 3);
};

/**
 * EducationalExplainer — kicker + headline + staggered evidence bullets,
 * progress rail at the bottom so the viewer always sees remaining time.
 */
export const EducationalExplainerScene: React.FC<{scene: SceneSpec; theme: ThemeSpec; watermark?: string}> = ({
  scene,
  theme: inputTheme,
  watermark,
}) => {
  const theme = resolveTheme(inputTheme);
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durationInFrames = scene.durationInFrames;
  const title = scene.text.find((t) => t.style.role === 'title')?.text ?? scene.segment.slice(0, 60);
  const kicker = scene.text.find((t) => t.style.role === 'kicker')?.text ?? '';
  const bullets = bulletsOf(scene);

  const headerReveal = cohesiveGroupReveal({frame, fps, durationInFrames: 22});
  const barMotion = lineDraw({frame, fps, durationInFrames: 20});

  return (
    <div style={{position: 'absolute', inset: 0, background: tokens.background}}>
      <Background theme={theme} variant="split" />
      <svg
        viewBox="0 0 1080 1920"
        preserveAspectRatio="xMidYMid slice"
        style={{position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none'}}
        aria-hidden="true"
      >
        <g fill={tokens.accent}>
          {Array.from({length: 32}, (_, i) => {
            const drift = frame * (0.8 + rand(i + 7) * 1.6);
            const x = rand(i + 21) * 1080 + Math.sin(frame / 40 + i) * 24;
            const y = 1920 - ((drift + rand(i + 55) * 1920) % 1920);
            return (
              <circle
                key={i}
                cx={x}
                cy={y}
                r={2 + rand(i + 91) * 3}
                opacity={0.12 + rand(i + 3) * 0.18}
              />
            );
          })}
        </g>
      </svg>
      {watermark ? <Watermark text={watermark} theme={theme} /> : null}
      <SafeArea top={300} bottom={360}>
        <div style={{...headerReveal, marginBottom: 54}}>
          {kicker ? (
            <Kicker tokens={tokens} style={{marginBottom: 26}}>
              {kicker}
            </Kicker>
          ) : null}
          <Headline tokens={tokens} style={{marginBottom: 28}}>
            {title}
          </Headline>
          <div style={barMotion}>
            <AccentBar theme={theme} width={140} />
          </div>
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 34}}>
          {bullets.map((b, i) => {
            const delay = 18 + i * 14;
            const local = Math.max(0, frame - delay);
            const anim = softSlideFade({frame: local, fps, durationInFrames: 20, distance: 24, direction: 'up'});
            const isVisible = frame >= delay;
            return (
              <div
                key={`${b}-${i}`}
                style={{
                  ...anim,
                  opacity: isVisible ? anim.opacity : 0,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 24,
                }}
              >
                <span
                  style={{
                    flex: '0 0 auto',
                    width: 54,
                    height: 54,
                    borderRadius: 27,
                    backgroundColor: tokens.accent,
                    color: tokens.surface,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                    fontSize: 32,
                    fontFamily: TYPE_SCALE.techLabel.fontFamily,
                  }}
                >
                  {i + 1}
                </span>
                <Body tokens={tokens} color={tokens.textSecondary} style={{flex: 1, lineHeight: 1.3}}>
                  {b.trim()}
                </Body>
              </div>
            );
          })}
        </div>
      </SafeArea>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 440,
          height: 10,
          backgroundColor: alpha(tokens.line, 0.6),
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${interpolate(frame, [0, durationInFrames], [0, 100], {extrapolateRight: 'clamp'})}%`,
            backgroundColor: tokens.accent,
          }}
        />
      </div>
    </div>
  );
};
