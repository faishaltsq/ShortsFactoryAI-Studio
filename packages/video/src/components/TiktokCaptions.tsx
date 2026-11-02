import React, {useMemo} from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {WordTimestamp} from '../types';

export interface TiktokCaptionsProps {
  words: WordTimestamp[];
  wordsPerPage?: number;
  highlightColor?: string;
  fontFamily?: string;
}

interface CaptionPage {
  start: number;
  end: number;
  words: WordTimestamp[];
}

export const TiktokCaptions: React.FC<TiktokCaptionsProps> = ({
  words,
  wordsPerPage = 3,
  highlightColor = '#facc15',
  fontFamily = 'Montserrat, Inter, system-ui, sans-serif',
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const currentTime = frame / fps;

  const pages = useMemo<CaptionPage[]>(() => {
    if (!words || words.length === 0) return [];
    const result: CaptionPage[] = [];
    for (let i = 0; i < words.length; i += wordsPerPage) {
      const chunk = words.slice(i, i + wordsPerPage);
      if (chunk.length > 0) {
        result.push({
          start: chunk[0].start,
          end: chunk[chunk.length - 1].end,
          words: chunk,
        });
      }
    }
    return result;
  }, [words, wordsPerPage]);

  const activePage = useMemo(() => {
    for (let i = 0; i < pages.length; i++) {
      const page = pages[i];
      const nextPage = pages[i + 1];
      const thresholdEnd = nextPage ? nextPage.start : page.end + 0.2;
      if (currentTime >= page.start && currentTime < thresholdEnd) {
        return page;
      }
    }
    return undefined;
  }, [pages, currentTime]);

  if (!activePage) return null;

  const pageStartFrame = Math.max(0, Math.floor(activePage.start * fps));
  const pagePop = spring({
    frame: Math.max(0, frame - pageStartFrame),
    fps,
    config: {damping: 14, stiffness: 180, mass: 0.6},
  });

  const pageScale = interpolate(pagePop, [0, 1], [0.85, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'center',
        paddingBottom: 420, // Clear of YouTube Shorts bottom controls & audio title
        paddingLeft: 60,
        paddingRight: 130, // Clear of Like/Comment/Share buttons
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: '12px 16px',
          transform: `scale(${pageScale})`,
          maxWidth: 920,
        }}
      >
        {activePage.words.map((item, idx) => {
          const isCurrentWord =
            currentTime >= item.start && currentTime <= item.end;

          const wordStartFrame = Math.max(0, Math.floor(item.start * fps));
          const wordSpring = spring({
            frame: Math.max(0, frame - wordStartFrame),
            fps,
            config: {damping: 12, stiffness: 220, mass: 0.5},
          });

          const wordScale = isCurrentWord
            ? interpolate(wordSpring, [0, 1], [1, 1.14], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              })
            : 1;

          return (
            <span
              key={`${item.start}-${idx}`}
              style={{
                display: 'inline-block',
                fontFamily,
                fontSize: 48,
                fontWeight: 800,
                color: isCurrentWord ? '#0f172a' : '#ffffff',
                backgroundColor: isCurrentWord ? highlightColor : 'rgba(0, 0, 0, 0.45)',
                padding: '6px 16px',
                borderRadius: 14,
                transform: `scale(${wordScale})`,
                textShadow: isCurrentWord
                  ? 'none'
                  : '0px 4px 14px rgba(0, 0, 0, 0.9), 0px 2px 4px rgba(0, 0, 0, 0.95)',
                boxShadow: isCurrentWord
                  ? `0px 8px 24px ${highlightColor}66`
                  : 'none',
              }}
            >
              {item.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
