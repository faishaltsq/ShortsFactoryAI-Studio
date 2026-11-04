import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {Prop} from '../art/Prop';
import {alpha, paletteFor} from '../art/palette';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {ParallaxData, localImage, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {Body} from '../components/Typography';

export const ParallaxStoryScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as ParallaxData;
  const progress = interpolate(
    frame,
    [0, scene.durationInFrames - 1],
    [-1, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
  );

  return (
    <NarrativeFrame {...props} title={data.title}>
      <div
        style={{
          position: 'relative',
          flex: 1,
          minHeight: 0,
          overflow: 'hidden',
          borderRadius: SPACE.radius,
          background: tokens.surface,
          border: `1px solid ${tokens.line}`,
          boxShadow: tokens.shadow.md,
        }}
      >
        {[...data.layers]
          .sort((a, b) => a.depth - b.depth)
          .map((layer, i) => (
            <div
              key={i}
              style={{
                position: 'absolute',
                inset: -50,
                transform: `translateX(${progress * layer.depth * 46}px) scale(${1.05 + layer.depth * 0.06})`,
              }}
            >
              {layer.assetRef ? (
                <Img
                  src={staticFile(localImage(layer.assetRef))}
                  style={{width: '100%', height: '100%', objectFit: 'cover'}}
                />
              ) : (
                // Prop renders a positioned div, so it must live in HTML, not inside <svg>.
                <div style={{position: 'absolute', inset: 0}}>
                  {layer.shape === 'circle' ? <Prop shape="circle" palette={paletteFor(theme, 'space')} /> : null}
                  {/* Dusk, not night: the ground palette responds to time of day, so the ridge
                      stays a shade of the theme's own ground instead of vanishing into the card. */}
                  {layer.shape === 'ridge' ? <Prop shape="ridge" palette={paletteFor(theme, 'abstract')} /> : null}
                  {layer.shape === 'city' ? <Prop shape="city" palette={paletteFor(theme, 'city')} /> : null}
                </div>
              )}
            </div>
          ))}
        <div
          style={{
            position: 'absolute',
            bottom: SPACE.card,
            left: SPACE.card,
            right: SPACE.card,
            height: 8,
            background: tokens.accent,
            opacity: 0.8,
            borderRadius: 4,
          }}
        />
        {data.caption ? (
          <div
            style={{
              position: 'absolute',
              bottom: SPACE.card + 18,
              left: SPACE.card,
              right: SPACE.card,
              padding: '12px 18px',
              borderRadius: SPACE.radius / 2,
              background: alpha(tokens.surface, 0.88),
            }}
          >
            <Body tokens={tokens} color={tokens.textSecondary} style={{lineHeight: 1.3}}>
              {data.caption}
            </Body>
          </div>
        ) : null}
      </div>
    </NarrativeFrame>
  );
};
