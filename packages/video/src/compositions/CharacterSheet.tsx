import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import type {ThemeSpec} from '../types';
import type {ExpressionId, GestureId, PoseId} from '../character/ids';
import {CharacterFigure} from '../character/render/CharacterFigure';
import {getCharacter, resolveCharacter} from '../character/registry';
import {paletteFor} from '../art/palette';

export interface SheetCell {
  pose: PoseId;
  expression: ExpressionId;
  gesture?: GestureId;
  label: string;
}

export const SHEET_CELLS: SheetCell[] = [
  {pose: 'stand', expression: 'neutral', label: 'stand / neutral'},
  {pose: 'stand', expression: 'happy', label: 'stand / happy'},
  {pose: 'stand', expression: 'curious', label: 'stand / curious'},
  {pose: 'point', expression: 'determined', gesture: 'pointForward', label: 'point / determined'},
  {pose: 'reach', expression: 'surprised', gesture: 'openPalm', label: 'reach / surprised'},
  {pose: 'shrug', expression: 'concerned', gesture: 'shrug', label: 'shrug / concerned'},
  {pose: 'walk', expression: 'neutral', label: 'walk / neutral'},
  {pose: 'sit', expression: 'thinking', gesture: 'think', label: 'sit / thinking'},
  {pose: 'lookUp', expression: 'sad', label: 'lookUp / sad'},
  {pose: 'stand', expression: 'determined', gesture: 'bothOpen', label: 'stand / determined'},
  {pose: 'stand', expression: 'happy', gesture: 'wave', label: 'stand / wave'},
  {pose: 'point', expression: 'surprised', label: 'point / surprised'},
];

/**
 * CharacterSheet — visual QA surface.
 *
 * Renders a grid of character states in one still so a pose, expression or rig
 * regression is visible without scrubbing a video. Each cell is a full
 * CharacterFigure with its own actor index, which also exercises the per-actor
 * blink seed.
 */
export const CharacterSheet: React.FC<{
  theme: ThemeSpec;
  characterId?: string;
  cells?: SheetCell[];
  frame?: number;
}> = ({theme, characterId = 'maya', cells = SHEET_CELLS}) => {
  const frame = useCurrentFrame();
  const palette = paletteFor(theme, 'day');
  const {character} = resolveCharacter(characterId);
  const manifest = character ?? getCharacter('maya')!;
  const columns = 3;
  const rows = Math.ceil(cells.length / columns);
  const cellWidth = 1080 / columns;
  const cellHeight = 1920 / rows;

  return (
    <AbsoluteFill style={{backgroundColor: palette.skyTop}}>
      {cells.map((cell, index) => {
        const column = index % columns;
        const row = Math.floor(index / columns);
        return (
          <div
            key={`${cell.pose}-${cell.expression}-${index}`}
            style={{
              position: 'absolute',
              left: column * cellWidth,
              top: row * cellHeight,
              width: cellWidth,
              height: cellHeight,
              backgroundColor: index % 2 === 0 ? palette.skyTop : palette.skyBottom,
              overflow: 'hidden',
            }}
          >
            <CharacterFigure
              actor={{
                pose: cell.pose,
                x: 0.5,
                ground: 1,
                scale: 1,
                facing: 'right',
                tone: 'primary',
                silhouette: false,
                character: manifest.id,
                expression: cell.expression,
                gesture: cell.gesture ?? 'none',
                motion: {preset: 'idle', durationInFrames: 300},
              }}
              palette={palette}
              frame={frame}
              index={index}
              manifest={manifest}
              fit="box"
            />
            <div
              style={{
                position: 'absolute',
                left: 8,
                top: 8,
                fontFamily: theme.fontBody,
                fontSize: 16,
                letterSpacing: 0.6,
                color: palette.figure,
                opacity: 0.72,
              }}
            >
              {cell.label}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
