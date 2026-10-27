import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneSpec, ThemeSpec} from '../types';
import {resolveTheme} from '../themes/brand';
import {AccentBar, Background, SafeArea, Watermark} from '../components/Chrome';
import {popIn, slideUp} from '../components/presets';

/**
 * KineticTypography — one narrative segment rendered as a burst of oversized
 * words that land in rhythm, with an accent word emphasized per line.
 */
export const KineticTypographyScene: React.FC<{scene: SceneSpec; theme: ThemeSpec; watermark?: string}> = ({
  scene,
  theme: inputTheme,
  watermark,
}) => {
  const theme = resolveTheme(inputTheme);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durationInFrames = scene.durationInFrames;
  const title = scene.text.find((element) => element.style.role === 'title')?.text ?? scene.segment;
  const words = title.split(/\s+/);
  // This line is on screen. `sceneId` is an internal identifier ("sc1"), so it must
  // never be the fallback: it was rendering into the published video as a caption.
  const caption =
    scene.text.find((element) => element.style.role === 'caption')?.text ??
    (typeof scene.data?.caption === 'string' ? scene.data.caption : '');
  const highlightIndex = scene.data?.highlightIndex;
  const hi = typeof highlightIndex === 'number' ? highlightIndex : -1;

  const entrance = slideUp({frame, fps, durationInFrames: 20, intensity: 0.6});

  return (
    <div style={{position: 'absolute', inset: 0}}>
      <Background theme={theme} variant="radial" />
      {watermark ? <Watermark text={watermark} theme={theme} /> : null}
      <SafeArea top={340} bottom={420}>
        <div style={{...entrance, marginBottom: 42}}>
          <AccentBar theme={theme} />
        </div>
        <div
          style={{
            fontFamily: theme.fontHeading,
            fontSize: 96,
            lineHeight: 1.08,
            color: theme.primary,
            textTransform: 'uppercase',
            letterSpacing: -1,
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0 22px',
          }}
        >
          {words.map((w, i) => {
            const delay = i * 3;
            const local = frame - delay;
            const style = popIn({frame: Math.max(0, local), fps, durationInFrames: 24, intensity: 0.9});
            const accent = i === hi || w.startsWith('#');
            return (
              <span
                key={`${w}-${i}`}
                style={{
                  ...style,
                  opacity: local < 0 ? 0 : style.opacity,
                  color: accent ? theme.accent : theme.primary,
                  textShadow: accent ? `0 0 46px ${theme.accent}66` : '0 6px 24px rgba(0,0,0,0.6)',
                  display: 'inline-block',
                }}
              >
                {w.replace('#', '')}
              </span>
            );
          })}
        </div>
        {caption ? (
          <div
            style={{
              marginTop: 56,
              fontFamily: theme.fontBody,
              fontSize: 40,
              color: theme.secondary,
              opacity: interpolate(frame, [durationInFrames * 0.4, durationInFrames * 0.6], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
            }}
          >
            {caption}
          </div>
        ) : null}
      </SafeArea>
    </div>
  );
};
