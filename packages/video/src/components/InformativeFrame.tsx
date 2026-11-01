import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import type {SceneProps} from './NarrativeFrame';
import {resolveTheme, TYPE} from '../themes/brand';
import {Watermark} from './Chrome';
import {alpha} from '../art/palette';

/**
 * The frame every informative composition shares: a full-bleed stage, a title band, an optional
 * caption band, and the watermark.
 *
 * The old templates put their content inside a card with a header. That is the right shape for a
 * slide, and the wrong shape for motion graphics: a card shrinks the picture and forces the visual
 * to live *under* the words. Here the illustration owns the frame and the type sits on top of it,
 * which is what lets the visual explain the narration instead of captioning it.
 */
export const InformativeFrame: React.FC<
  SceneProps & {
    title?: string;
    caption?: string;
    /** 0..1 how strongly the title band is drawn. Lets a title fade before the hero action. */
    titleOpacity?: number;
    children: React.ReactNode;
  }
> = ({scene, theme: inputTheme, watermark, title, caption, titleOpacity = 1, children}) => {
  const theme = resolveTheme(inputTheme);
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 14], [24, 0], {extrapolateRight: 'clamp'});
  const fade = interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: theme.background, overflow: 'hidden'}}>
      {children}
      {/* A legibility scrim sits under the type only, never over the illustration's subject. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `linear-gradient(180deg, ${alpha(theme.background, 0.78)} 0%, ${alpha(theme.background, 0)} 30%)`,
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `linear-gradient(0deg, ${alpha(theme.background, 0.7)} 0%, ${alpha(theme.background, 0)} 24%)`,
          pointerEvents: 'none',
        }}
      />
      {title ? (
        <div
          style={{
            position: 'absolute',
            left: 72,
            right: 72,
            top: 236,
            opacity: fade * titleOpacity,
            transform: `translateY(${rise}px)`,
            fontFamily: theme.fontHeading,
            fontSize: TYPE.heading,
            lineHeight: 1.08,
            color: theme.primary,
            textShadow: `0 4px 28px ${alpha(theme.background, 0.85)}`,
          }}
        >
          {title}
        </div>
      ) : null}
      {caption ? (
        <div
          style={{
            position: 'absolute',
            left: 72,
            right: 72,
            bottom: 300,
            opacity: fade,
            fontFamily: theme.fontBody,
            fontSize: TYPE.detail,
            lineHeight: 1.3,
            color: theme.secondary,
            textShadow: `0 3px 20px ${alpha(theme.background, 0.9)}`,
          }}
        >
          {caption}
        </div>
      ) : null}
      {watermark ? <Watermark text={watermark} theme={theme} /> : null}
      <span style={{display: 'none'}}>{scene.sceneId}</span>
    </div>
  );
};
