import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneProps} from './NarrativeFrame';
import {resolveTheme} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {Caption, Label, Title} from './Typography';
import {cohesiveGroupReveal} from './motion';
import {Watermark} from './Chrome';
import {alpha, isLight} from '../art/palette';
import {pinnedOverlayStyle} from './CameraPinning';
/**
 * The frame every informative composition shares: a full-bleed stage, a title band, an optional
 * caption band, and the watermark.
 *
 * The old templates put their content inside a card with a header. That is the right shape for a
 * slide, and the wrong shape for motion graphics: a card shrinks the picture and forces the visual
 * to live *under* the words. Here the illustration owns the frame and the type sits on top of it,
 * which is what lets the visual explain the narration instead of captioning it.
 *
 * The type is an annotation on the picture, not part of it: when the declared camera moves the
 * stage, the title and caption stay where the storyboard placed them (``pinnedOverlayStyle``
 * applies the camera's inverse), so a motivated pan cannot push the title out of the frame —
 * the failure visual QC caught on the first live vision run.
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
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const headerReveal = cohesiveGroupReveal({frame, fps, durationInFrames: 18});
  const pinned = pinnedOverlayStyle();
  const light = isLight(tokens.background);
  const dataCS = (scene.data as Record<string, unknown> | undefined)?.causalState ?? (scene.data as Record<string, unknown> | undefined)?.causal_state;
  const cs = (scene.causalState ?? (scene as unknown as {causal_state?: Record<string, string>}).causal_state ?? dataCS) as Record<string, string> | undefined;
  const causalAction = cs?.causalAction ?? cs?.causal_action;
  const scrimExtent = causalAction && caption ? '32%' : caption || causalAction ? '28%' : '24%';
  const hasHeader = Boolean(title || causalAction || caption);

  return (
    <div style={{position: 'absolute', inset: 0, background: tokens.background, overflow: 'hidden'}}>
      {children}
      {/* A legibility scrim sits under the top title only */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `linear-gradient(180deg, ${alpha(tokens.background, light ? 0.94 : 0.82)} 0%, ${alpha(tokens.background, 0)} ${scrimExtent})`,
          pointerEvents: 'none',
          ...pinned,
        }}
      />
      {hasHeader ? (
        <div
          style={{
            position: 'absolute',
            left: 80,
            right: 80,
            top: watermark ? 300 : 230,
            opacity: headerReveal.opacity * titleOpacity,
            ...pinned,
            transform: `${pinned.transform ?? ''} ${headerReveal.transform}`.trim(),
          }}
        >
          {title ? (
            <Title
              tokens={tokens}
              style={{
                textShadow: light ? 'none' : `0 4px 28px ${alpha(tokens.background, 0.85)}`,
              }}
            >
              {title}
            </Title>
          ) : null}
          {causalAction ? (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                marginTop: title ? 10 : 0,
                padding: '6px 14px',
                borderRadius: 9999,
                background: alpha(tokens.accent, light ? 0.12 : 0.2),
                border: `1px solid ${alpha(tokens.accent, 0.35)}`,
                maxWidth: '100%',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  background: tokens.accent,
                  display: 'inline-block',
                }}
              />
              <Label
                tokens={tokens}
                color={tokens.accent}
                style={{
                  fontSize: 20,
                  fontWeight: 600,
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {causalAction}
              </Label>
            </div>
          ) : null}
          {caption ? (
            <Caption
              tokens={tokens}
              align="left"
              color={tokens.textSecondary}
              style={{
                marginTop: 10,
                display: 'block',
                lineHeight: 1.35,
              }}
            >
              {caption}
            </Caption>
          ) : null}
        </div>
      ) : null}
      {watermark ? <Watermark text={watermark} theme={theme} /> : null}
      <span style={{display: 'none'}}>{scene.sceneId}</span>
    </div>
  );
};
