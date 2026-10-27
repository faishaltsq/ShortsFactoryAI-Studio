import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneSpec, ThemeSpec} from '../types';
import {resolveTheme} from '../themes/brand';
import {AccentBar, Background, SafeArea, Watermark} from '../components/Chrome';
import {fadeIn, popIn, slideUp} from '../components/presets';

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
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durationInFrames = scene.durationInFrames;
  const title = scene.text.find((t) => t.style.role === 'title')?.text ?? scene.segment.slice(0, 60);
  // A kicker is optional on-screen text. Falling back to `sceneId` printed the
  // internal identifier ("sc1") into the video, so an absent kicker now renders nothing.
  const kicker = scene.text.find((t) => t.style.role === 'kicker')?.text ?? '';
  const bullets = bulletsOf(scene);
  const titleAnim = slideUp({frame, fps, durationInFrames: 22, intensity: 0.5});

  return (
    <div style={{position: 'absolute', inset: 0}}>
      <Background theme={theme} variant="split" />
      {watermark ? <Watermark text={watermark} theme={theme} /> : null}
      <SafeArea top={300} bottom={360}>
        {kicker ? (
          <div
            style={{
              fontFamily: theme.fontBody,
              fontSize: 36,
              letterSpacing: 6,
              textTransform: 'uppercase',
              color: theme.accent,
              marginBottom: 26,
              ...fadeIn({frame, fps, durationInFrames: 18}),
            }}
          >
            {kicker}
          </div>
        ) : null}
        <div
          style={{
            ...titleAnim,
            fontFamily: theme.fontHeading,
            fontSize: 82,
            lineHeight: 1.1,
            color: theme.primary,
            marginBottom: 54,
          }}
        >
          {title}
        </div>
        <div style={{marginBottom: 54}}>
          <AccentBar theme={theme} width={140} />
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 34}}>
          {bullets.map((b, i) => {
            const local = frame - 18 - i * 14;
            const anim = popIn({frame: Math.max(0, local), fps, durationInFrames: 24, intensity: 0.8});
            return (
              <div
                key={`${b}-${i}`}
                style={{
                  ...anim,
                  opacity: local < 0 ? 0 : anim.opacity,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 24,
                  fontFamily: theme.fontBody,
                  fontSize: 46,
                  lineHeight: 1.3,
                  color: theme.secondary,
                }}
              >
                <span
                  style={{
                    flex: '0 0 auto',
                    width: 54,
                    height: 54,
                    borderRadius: 27,
                    backgroundColor: theme.accent,
                    color: theme.background,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 800,
                    fontSize: 34,
                  }}
                >
                  {i + 1}
                </span>
                <span>{b.trim()}</span>
              </div>
            );
          })}
        </div>
      </SafeArea>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 210, height: 10, backgroundColor: 'rgba(255,255,255,0.14)'}}>
        <div
          style={{
            height: '100%',
            width: `${interpolate(frame, [0, durationInFrames], [0, 100], {extrapolateRight: 'clamp'})}%`,
            backgroundColor: theme.accent,
          }}
        />
      </div>
    </div>
  );
};
