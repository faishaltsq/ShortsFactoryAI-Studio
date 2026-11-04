import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneSpec, ThemeSpec} from '../types';
import {resolveTheme} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {Body, Headline, Highlight, Kicker} from '../components/Typography';
import {lineDraw, staggeredWordReveal} from '../components/motion';
import {AccentBar, Background, SafeArea, Watermark} from '../components/Chrome';
import {alpha, isLight} from '../art/palette';

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
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durationInFrames = scene.durationInFrames;
  const title = scene.text.find((element) => element.style.role === 'title')?.text ?? scene.segment;
  const words = title.split(/\s+/);
  const kicker = scene.text.find((element) => element.style.role === 'kicker')?.text;
  // This line is on screen. `sceneId` is an internal identifier ("sc1"), so it must
  // never be the fallback: it was rendering into the published video as a caption.
  const caption =
    scene.text.find((element) => element.style.role === 'caption')?.text ??
    (typeof scene.data?.caption === 'string' ? scene.data.caption : '');
  const highlightIndex = scene.data?.highlightIndex;
  const hi = typeof highlightIndex === 'number' ? highlightIndex : -1;

  const barMotion = lineDraw({frame, fps, durationInFrames: 20});
  const light = isLight(tokens.background);

  return (
    <div style={{position: 'absolute', inset: 0, background: tokens.background}}>
      <Background theme={theme} variant="radial" />
      {watermark ? <Watermark text={watermark} theme={theme} /> : null}
      <SafeArea top={340} bottom={420}>
        {kicker ? (
          <div style={{marginBottom: 20}}>
            <Kicker tokens={tokens}>{kicker}</Kicker>
          </div>
        ) : null}
        <div style={{...barMotion, marginBottom: 42}}>
          <AccentBar theme={theme} />
        </div>
        <Headline
          as="div"
          tokens={tokens}
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0 22px',
          }}
        >
          {words.map((w, i) => {
            const wordMotion = staggeredWordReveal({frame, fps, wordIndex: i, staggerFrames: 3});
            const accent = i === hi || w.startsWith('#');
            const cleanWord = w.replace('#', '');
            if (accent) {
              return (
                <Highlight
                  key={`${w}-${i}`}
                  tokens={tokens}
                  variant="accent"
                  style={{
                    ...wordMotion,
                    textShadow: light
                      ? `0 0 46px ${alpha(tokens.accent, 0.25)}`
                      : `0 0 46px ${alpha(tokens.accent, 0.5)}`,
                  }}
                >
                  {cleanWord}
                </Highlight>
              );
            }
            return (
              <span
                key={`${w}-${i}`}
                style={{
                  ...wordMotion,
                  color: tokens.textPrimary,
                  textShadow: light ? 'none' : `0 4px 24px ${alpha(tokens.background, 0.85)}`,
                }}
              >
                {cleanWord}
              </span>
            );
          })}
        </Headline>
        {caption ? (
          <Body
            tokens={tokens}
            color={tokens.textSecondary}
            style={{
              marginTop: 56,
              opacity: interpolate(frame, [durationInFrames * 0.4, durationInFrames * 0.6], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
            }}
          >
            {caption}
          </Body>
        ) : null}
      </SafeArea>
    </div>
  );
};
