import React from 'react';
import {Img, staticFile} from 'remotion';
import type {IllustrationData} from '../scene-data';
import {Environment} from './Environment';
import {Figure} from './Figure';
import {Prop} from './Prop';
import type {ArtPalette} from './palette';
import {CharacterFigure} from '../character/render/CharacterFigure';
import {resolveCharacter} from '../character/registry';
import type {ActorPerformance} from '../motion-beats';
import type {SpeechWindow} from '../speech';

export const Stage: React.FC<{
  data: IllustrationData;
  palette: ArtPalette;
  frame: number;
  progress: number;
  scale: number;
  /**
   * Scene-absolute frame. Character blink/idle seeds derive from it so a cut to a
   * new shot does not reset an actor's phase.
   */
  sceneFrame?: number;
  /**
   * Clock the character rigs animate on. `motion.beats[].atFrame` is scene-local by contract, so a
   * scene with beats must pass the scene frame here; otherwise a shot cut would reset the beat
   * clock and a beat at frame 96 would fire once per shot.
   *
   * Defaults to `frame`, which is what a scene with no beats keeps using: the shot-local clock.
   */
  characterFrame?: number;
  /**
   * One entry per actor, from `performanceAt`. When present it replaces the actor's declared
   * pose/expression/gesture for this frame, which is how `motion.beats[]` reaches the rig.
   */
  performances?: readonly ActorPerformance[];
  /** Measured word windows, scene-local. Empty or absent means the mouth stays closed. */
  speech?: readonly SpeechWindow[];
}> = ({data, palette, frame, progress, scale, sceneFrame, characterFrame, performances, speech}) => (
  // transformOrigin sits on the subject's ground line, so a tighter framing crops
  // the sky instead of pushing the character's head into the title band.
  <div style={{position: 'absolute', inset: 0, transform: `scale(${scale})`, transformOrigin: '50% 78%'}}>
    {data.imageRef ? (
      <Img
        src={staticFile(data.imageRef)}
        style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
      />
    ) : null}
    <div style={{position: 'absolute', inset: 0, opacity: data.imageRef ? 0.72 : 1}}>
      <Environment
        setting={data.setting}
        timeOfDay={data.timeOfDay ?? 'night'}
        palette={palette}
        progress={progress}
      />
    </div>
    {(data.props ?? []).map((prop, i) => (
      <Prop key={`prop-${i}`} prop={prop} palette={palette} frame={frame} index={i} />
    ))}
    {(data.actors ?? []).map((declared, i) => {
      const performance = performances?.[i];
      const actor = performance?.actor ?? declared;
      // A resolved character renders through the rig. Anything else — no cue, or an
      // id that does not exist — keeps the procedural figure, so an old storyboard
      // and an invented character name both still render.
      const {character} = resolveCharacter(actor.character);
      // `exit` is the only beat kind that changes how much of the actor is on screen; every other
      // kind is already carried by the rig, so wrapping the figure would double-count it.
      const fade = performance ? performance.opacity : 1;
      return character ? (
        <CharacterFigure
          key={`actor-${i}`}
          actor={actor}
          palette={palette}
          frame={characterFrame ?? frame}
          index={i}
          manifest={character}
          sceneFrame={sceneFrame}
          opacity={fade}
          speech={speech}
        />
      ) : (
        <Figure key={`actor-${i}`} actor={actor} palette={palette} frame={frame} index={i} opacity={fade} />
      );
    })}
  </div>
);
