/**
 * Declared motion (`SceneSpec.motion`) → a character performance that a frame can show.
 *
 * ## What a beat means
 *
 * `motion.beats[]` is the only place the storyboard says "at frame N, this happens". Before this
 * module existed the beats were validated in Python and then dropped by the adapter, so a scene
 * that declared two beats rendered exactly like one that declared none.
 *
 * Each beat opens a **phase**: from its `atFrame` until the next beat for the same actor (or the
 * end of the scene), that actor performs the beat's pose/gesture/expression. The phase length is
 * what lets a gesture *hold* instead of snapping back — `gestureEnvelope` in `character/gestures.ts`
 * holds for the span it is given and releases in its last frames.
 *
 * ## Subject resolution, stated once
 *
 * `subject` is a name the storyboard already uses. It resolves in this order, and the result is
 * recorded on the cue so nothing is silently guessed:
 *
 * 1. `actor:<n>` — the actor at index n of `data.actors`.
 * 2. A text element id in `scene.text` — the beat is *about that line*, so the actor who performs
 *    it is the scene's primary actor (the first actor, which is the one a storyboard names first).
 * 3. A character id (`maya`) matching an actor's `character` — that actor.
 * 4. Anything else — the primary actor still performs it (a beat is a directing note, and a note
 *    with an unrecognised noun is not a reason to freeze the scene), and the subject is reported in
 *    `BeatPlan.unresolved` so a test or a QC log can see it.
 *
 * ## Determinism
 *
 * `planBeats` is a pure function of the scene and its actors; `performanceAt` is a pure function of
 * (plan, actorIndex, frame). Nothing accumulates state across frames, so Remotion's out-of-order
 * frame rendering produces identical pixels for the same frame number.
 */

import type {ExpressionId, GestureId, MotionPreset, PoseId} from './character/ids';
import {POSES} from './character/poses';
import type {IllustrationActor} from './scene-data';
import type {BeatKind, Continuity, MotionBeat, SceneSpec} from './types';

/** Frames a pose change takes to travel. `poseChangeBlend` completes at 0.6 × this. */
export const POSE_BLEND_FRAMES = 18;
/** Frames an `exit` beat takes to fade the actor out. */
export const EXIT_FRAMES = 12;

export type BeatResolution = 'actor' | 'text' | 'character' | 'primary';

export interface BeatCue {
  atFrame: number;
  kind: BeatKind;
  subject: string;
  actorIndex: number;
  resolution: BeatResolution;
  /**
   * The pose/expression/gesture **in force during this beat's phase**, already resolved against
   * the beats before it. Carrying the inherited value matters: an `emphasis` after an `action`
   * must keep the arm raised, not silently drop the actor back to the storyboard's opening pose.
   */
  pose: PoseId;
  expression: ExpressionId;
  gesture: GestureId;
  preset: MotionPreset;
  /** Pose the transition starts from; only meaningful when `preset` is `poseChange`. */
  fromPose?: PoseId;
  fromExpression?: ExpressionId;
  /** Length of the phase this beat opens. */
  durationInFrames: number;
  /**
   * The frame at which this beat's effect is fully visible — the frame a still should be taken at.
   *
   * It is not always `atFrame`. An `enter` beat is a *transition*: at `atFrame` the actor is still
   * at zero opacity, so a still taken there shows an empty stage and proves nothing. Its completion
   * is the interesting frame. Every other kind is visible from `atFrame` (a pose change travels
   * over `durationInFrames`, so `atFrame + durationInFrames` is its settled frame).
   */
  peakFrame: number;
  /** `exit` fades the actor out over `EXIT_FRAMES`; no other kind does. */
  fadesOut: boolean;
}

export interface BeatPlan {
  cues: BeatCue[];
  /** Beats whose `subject` named nothing in the scene. Empty is the expected state. */
  unresolved: {atFrame: number; subject: string}[];
  /**
   * Beats that could not be rendered because they sit at or past the scene's duration.
   *
   * The audio stage re-times every scene to its measured narration (`update_storyboard_from_audio`),
   * which shortens a scene the storyboard declared at 300 frames to roughly 110-130. A beat authored
   * against the pre-audio timeline therefore disappears at render time, and nothing used to say so.
   * These are reported instead of dropped, so a test or a QC log can assert the list is empty.
   */
  dropped: {atFrame: number; kind: BeatKind; subject: string; sceneDurationInFrames: number}[];
}

const ACTOR_SELECTOR = /^actor:(\d+)$/;

const primaryActorIndex = (actors: readonly IllustrationActor[]): number => {
  const withCharacter = actors.findIndex((actor) => typeof actor.character === 'string');
  return withCharacter >= 0 ? withCharacter : 0;
};

interface Previous {
  pose: PoseId;
  expression: ExpressionId;
  gesture: GestureId;
}

type Performance = Pick<
  BeatCue,
  'pose' | 'expression' | 'gesture' | 'preset' | 'fromPose' | 'fromExpression'
>;

/**
 * Deterministic performance for one beat kind, layered on the state the previous beat left behind.
 *
 * Every branch states the full cue, including the fields it does not change, so there is no
 * "absent means inherit" rule for a reader to reconstruct.
 */
const perform = (beat: MotionBeat, previous: Previous, continuity: Continuity): Performance => {
  switch (beat.kind) {
    case 'enter':
      // A carried world means the actor was already on screen, so replaying the entrance fade
      // would pop them out and back in at the cut. The pose is the storyboard's own opening pose.
      return continuity === 'carry'
        ? {...previous, preset: 'idle'}
        : {pose: previous.pose, expression: 'curious', gesture: 'none', preset: 'enter'};
    case 'emphasis': {
      // The limb is the accent. `reach` and `walk` declare `armsLocked`, so an open-palm gesture
      // over either contributes only a head/chest accent — the arm would not move at all, and the
      // beat would be invisible. On those poses the accent is a different raised-arm pose;
      // everywhere else it is an open palm, which reads against the pose's own arm.
      if (POSES[previous.pose].armsLocked) {
        const pose: PoseId = previous.pose === 'point' ? 'reach' : 'point';
        return {
          pose,
          expression: previous.expression,
          gesture: 'pointForward',
          preset: 'poseChange',
          fromPose: previous.pose,
          fromExpression: previous.expression,
        };
      }
      return {...previous, gesture: 'openPalm', preset: 'gesture'};
    }
    case 'action': {
      // A real pose change, not a nudge: `point` unless the actor is already pointing, in which
      // case `reach` is the next action up the same axis.
      const pose: PoseId = previous.pose === 'point' ? 'reach' : 'point';
      return {
        pose,
        expression: 'determined',
        gesture: 'pointForward',
        preset: 'poseChange',
        fromPose: previous.pose,
        fromExpression: previous.expression,
      };
    }
    case 'reveal':
      return {
        pose: 'lookUp',
        expression: 'surprised',
        gesture: 'openPalm',
        preset: 'poseChange',
        fromPose: previous.pose,
        fromExpression: previous.expression,
      };
    case 'exit':
      return {...previous, gesture: 'none', preset: 'idle'};
    default:
      return {...previous, preset: 'idle'};
  }
};

/**
 * Turn a scene's declared beats into cues. Beats are sorted by frame (the contract does not require
 * them ordered, and a phase length depends on the next beat), and a beat at or past the scene's
 * duration is ignored: it could never be rendered.
 */
export const planBeats = (scene: SceneSpec, actors: readonly IllustrationActor[]): BeatPlan => {
  const beats = scene.motion?.beats ?? [];
  const continuity = scene.motion?.continuity ?? 'cut';
  const dropped = beats
    .filter((beat) => beat.atFrame >= scene.durationInFrames)
    .map((beat) => ({
      atFrame: beat.atFrame,
      kind: beat.kind,
      subject: beat.subject,
      sceneDurationInFrames: scene.durationInFrames,
    }));
  if (beats.length === 0 || actors.length === 0) return {cues: [], unresolved: [], dropped};

  const primary = primaryActorIndex(actors);
  const resolved = beats
    .map((beat) => {
      const selector = ACTOR_SELECTOR.exec(beat.subject);
      if (selector) {
        const index = Number(selector[1]);
        return index < actors.length
          ? {beat, actorIndex: index, resolution: 'actor' as const}
          : {beat, actorIndex: primary, resolution: 'primary' as const, unknown: true};
      }
      if (scene.text.some((element) => element.id === beat.subject)) {
        return {beat, actorIndex: primary, resolution: 'text' as const};
      }
      const byCharacter = actors.findIndex((actor) => actor.character === beat.subject);
      if (byCharacter >= 0) {
        return {beat, actorIndex: byCharacter, resolution: 'character' as const};
      }
      return {beat, actorIndex: primary, resolution: 'primary' as const, unknown: true};
    })
    .filter((entry) => entry.beat.atFrame < scene.durationInFrames)
    .sort((a, b) => a.beat.atFrame - b.beat.atFrame || a.actorIndex - b.actorIndex);

  const cues: BeatCue[] = [];
  const unresolved: BeatPlan['unresolved'] = [];
  // Per-actor memory of what the actor is currently doing, so `fromPose` is the pose the previous
  // beat left them in rather than the storyboard's opening pose.
  const current = new Map<number, Previous>();

  for (const [position, entry] of resolved.entries()) {
    if ('unknown' in entry) unresolved.push({atFrame: entry.beat.atFrame, subject: entry.beat.subject});
    const actor = actors[entry.actorIndex];
    const previous: Previous = current.get(entry.actorIndex) ?? {
      pose: actor.pose,
      expression: actor.expression ?? 'neutral',
      gesture: actor.gesture ?? 'none',
    };
    const nextSameActor = resolved
      .slice(position + 1)
      .find((candidate) => candidate.actorIndex === entry.actorIndex);
    const phaseEnd = nextSameActor ? nextSameActor.beat.atFrame : scene.durationInFrames;
    const phase = Math.max(1, phaseEnd - entry.beat.atFrame);
    const performance = perform(entry.beat, previous, continuity);
    // A pose change travels in `POSE_BLEND_FRAMES`; a sustained accent lasts its whole phase.
    const durationInFrames = performance.pose ? Math.min(phase, POSE_BLEND_FRAMES) : phase;

    cues.push({
      atFrame: entry.beat.atFrame,
      kind: entry.beat.kind,
      subject: entry.beat.subject,
      actorIndex: entry.actorIndex,
      resolution: entry.resolution,
      ...performance,
      durationInFrames,
      // An entrance is at zero opacity on its own frame; its completion is what a still can show.
      peakFrame:
        entry.beat.kind === 'enter' || performance.pose
          ? entry.beat.atFrame + durationInFrames
          : entry.beat.atFrame,
      fadesOut: entry.beat.kind === 'exit',
    });
    current.set(entry.actorIndex, {
      pose: performance.pose,
      expression: performance.expression,
      gesture: performance.gesture,
    });
  }

  return {cues, unresolved, dropped};
};

export interface ActorPerformance {
  actor: IllustrationActor;
  /** Multiplier on the figure's own opacity, for `exit`. */
  opacity: number;
  /** The cue driving this frame, or `null` before the actor's first beat. */
  cue: BeatCue | null;
}

const cueFor = (plan: BeatPlan, actorIndex: number, frame: number): BeatCue | null => {
  let found: BeatCue | null = null;
  for (const cue of plan.cues) {
    if (cue.actorIndex === actorIndex && cue.atFrame <= frame) found = cue;
  }
  return found;
};

/**
 * The actor as they must look at `frame`. Before their first beat the declared actor is returned
 * untouched, so a scene whose first beat is at frame 30 still shows the storyboard's own pose.
 */
export const performanceAt = (
  plan: BeatPlan,
  actorIndex: number,
  frame: number,
  actor: IllustrationActor,
  energy: number,
): ActorPerformance => {
  const cue = cueFor(plan, actorIndex, frame);
  if (!cue) return {actor, opacity: 1, cue: null};

  const intensity = Math.min(1, Math.max(0, energy));
  const performed: IllustrationActor = {
    ...actor,
    pose: cue.pose,
    expression: cue.expression,
    gesture: cue.gesture,
    motion: {
      preset: cue.preset,
      durationInFrames: cue.durationInFrames,
      intensity,
      delayInFrames: cue.atFrame,
      ...(cue.fromPose ? {fromPose: cue.fromPose} : {}),
      ...(cue.fromExpression ? {fromExpression: cue.fromExpression} : {}),
    },
  };

  const opacity = cue.fadesOut
    ? Math.max(0, 1 - Math.max(0, frame - cue.atFrame) / EXIT_FRAMES)
    : 1;

  return {actor: performed, opacity, cue};
};
