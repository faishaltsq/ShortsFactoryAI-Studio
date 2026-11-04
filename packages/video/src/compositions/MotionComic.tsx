import React from 'react';
import {Img, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {alpha} from '../art/palette';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {ComicData, localImage, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {FONT_ROLES} from '../themes/type';
import {Body, Display, Kicker} from '../components/Typography';
import {softSlideFade} from '../components/motion';

/**
 * `MotionComic` — a three-panel strip of statements.
 *
 * Panels carry a caption and, optionally, a staged image. They no longer carry a figure: the
 * presenter was the only thing this template added over `KineticTypography`, and a comic about a
 * data centre does not need someone standing in it. A panel with no image draws its own punch
 * block from the theme, so the strip keeps its rhythm without inventing content.
 */
export const MotionComicScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  validateSceneData(scene);
  const data = scene.data as unknown as ComicData;

  return (
    <NarrativeFrame {...props} title={data.title}>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          flex: 1,
          gap: 16,
          minHeight: 0,
          maxHeight: 1020,
        }}
      >
        {data.panels.map((panel, i) => {
          const delay = i * 10;
          const local = Math.max(0, frame - delay);
          const anim = softSlideFade({
            frame: local,
            fps,
            durationInFrames: 18,
            distance: 24,
            direction: i % 2 ? 'right' : 'left',
          });
          const isVisible = frame >= delay;

          return (
            <div
              key={i}
              style={{
                position: 'relative',
                flex: 1,
                minHeight: 0,
                display: 'flex',
                gap: 18,
                alignItems: 'center',
                overflow: 'hidden',
                padding: '16px 20px',
                border: `2px solid ${tokens.line}`,
                borderRadius: SPACE.radius,
                background: tokens.surface,
                boxShadow: tokens.shadow.sm,
                opacity: isVisible ? anim.opacity : 0,
                transform: anim.transform,
              }}
            >
              {panel.assetRef ? (
                <Img
                  src={staticFile(localImage(panel.assetRef))}
                  style={{width: '34%', height: '100%', objectFit: 'cover', borderRadius: SPACE.radius}}
                />
              ) : (
                <div
                  style={{
                    width: '34%',
                    height: '100%',
                    flexShrink: 0,
                    borderRadius: SPACE.radius,
                    background: `linear-gradient(135deg, ${alpha(tokens.accent, 0.18)} 0%, ${alpha(
                      tokens.surface,
                      0.5,
                    )} 100%)`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Display
                    tokens={tokens}
                    oversized
                    color={alpha(tokens.accentDeep, 0.45)}
                    style={{fontFamily: FONT_ROLES.technical}}
                  >
                    {i + 1}
                  </Display>
                </div>
              )}
              <div style={{flex: 1, minWidth: 0}}>
                {panel.speaker ? (
                  <Kicker tokens={tokens} style={{marginBottom: SPACE.small}}>
                    {panel.speaker}
                  </Kicker>
                ) : null}
                <Body tokens={tokens} style={{overflowWrap: 'anywhere', lineHeight: 1.25}}>
                  {panel.caption}
                </Body>
              </div>
            </div>
          );
        })}
      </div>
    </NarrativeFrame>
  );
};
