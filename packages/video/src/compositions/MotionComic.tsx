import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {alpha, paletteFor} from '../art/palette';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {ComicData, localImage, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';

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
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as ComicData;
  const palette = paletteFor(theme, 'abstract');
  return (
    <NarrativeFrame {...props} title={data.title}>
      <div style={{display: 'flex', flexDirection: 'column', flex: 1, gap: SPACE.card, minHeight: 0}}>
        {data.panels.map((panel, i) => {
          const progress = interpolate(frame, [i * 10, i * 10 + 18], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          return (
            <div
              key={i}
              style={{
                position: 'relative',
                flex: 1,
                minHeight: 0,
                display: 'flex',
                gap: SPACE.card,
                alignItems: 'center',
                overflow: 'hidden',
                padding: SPACE.card,
                border: `4px solid ${theme.primary}`,
                borderRadius: SPACE.radius,
                background: theme.backgroundAccent,
                opacity: progress,
                transform: `translateX(${(1 - progress) * (i % 2 ? 48 : -48)}px)`,
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
                    background: `linear-gradient(135deg, ${alpha(palette.accent, 0.75)} 0%, ${alpha(
                      palette.primary,
                      0.25,
                    )} 100%)`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: theme.fontHeading,
                    fontSize: 96,
                    color: alpha(theme.background, 0.55),
                  }}
                >
                  {i + 1}
                </div>
              )}
              <div style={{flex: 1, minWidth: 0}}>
                {panel.speaker ? (
                  <div style={{fontSize: TYPE.kicker, fontWeight: 800, color: theme.accent, marginBottom: SPACE.small}}>
                    {panel.speaker}
                  </div>
                ) : null}
                <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.body, lineHeight: 1.18, overflowWrap: 'anywhere'}}>
                  {panel.caption}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </NarrativeFrame>
  );
};
