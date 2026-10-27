/**
 * `motion.beats[]` → performance. Pure-function tests, no browser and no Remotion runtime.
 *
 * Usage: node scripts/test-motion-beats.mjs
 *
 * The properties here are the ones the render depends on and cannot re-check per frame:
 *
 * - a beat changes the pose/gesture/expression the rig is asked for, and the change is inherited
 *   by later beats instead of reverting to the storyboard's opening pose;
 * - `peakFrame` is the frame a still has to be taken at — the entrance's completion, not frame 0,
 *   because at frame 0 the actor is at zero opacity;
 * - a beat past the scene's end is reported in `dropped`, not silently discarded;
 * - `subject` resolution covers the element id, the `actor:<n>` selector, the character id, and
 *   reports the fallback instead of hiding it;
 * - the result is a pure function of (plan, actorIndex, frame), so Remotion's out-of-order frame
 *   rendering produces the same pixels for the same frame number.
 */

import {register} from 'node:module';

register('./ts-resolve-hook.mjs', import.meta.url);

const {planBeats, performanceAt, POSE_BLEND_FRAMES} = await import('../src/motion-beats.ts');

let failures = 0;
const pass = (message) => console.log(`PASS ${message}`);
const check = (condition, message) => {
  if (condition) pass(message);
  else {
    failures += 1;
    console.log(`FAIL ${message}`);
  }
};

const scene = (motion, overrides = {}) => ({
  sceneId: 'sc1',
  template: 'IllustratedStory',
  segment: 's1',
  assetRefs: [],
  text: [
    {id: 't1', text: 'judul', style: {role: 'title'}},
    {id: 't2', text: 'badan', style: {role: 'body'}},
  ],
  animation: {preset: 'fadeIn'},
  transition: {type: 'none'},
  startFrame: 0,
  durationInFrames: 120,
  motion,
  ...overrides,
});

const actors = [
  {
    character: 'maya',
    pose: 'stand',
    x: 0.5,
    ground: 0.72,
    scale: 1,
    facing: 'right',
    tone: 'primary',
    silhouette: false,
    expression: 'curious',
  },
];

const signature = (performance) =>
  JSON.stringify([
    performance.actor.pose,
    performance.actor.expression,
    performance.actor.gesture,
    performance.actor.motion,
    performance.opacity,
  ]);

console.log('# motion beats');

// --- a beat reaches the rig ----------------------------------------------------------------
const acted = scene({
  energy: 0.6,
  continuity: 'cut',
  beats: [
    {atFrame: 0, kind: 'enter', subject: 't1'},
    {atFrame: 30, kind: 'action', subject: 't1'},
  ],
});
const plan = planBeats(acted, actors);
const before = performanceAt(plan, 0, 29, actors[0], acted.motion.energy);
const after = performanceAt(plan, 0, 30 + POSE_BLEND_FRAMES, actors[0], acted.motion.energy);
check(plan.cues.length === 2, `two beats planned (${plan.cues.length})`);
check(before.actor.pose === 'stand', `before the action beat the pose is the storyboard's (${before.actor.pose})`);
check(after.actor.pose === 'point', `the action beat changes the pose (${after.actor.pose})`);
check(after.actor.gesture === 'pointForward', `the action beat adds a gesture (${after.actor.gesture})`);
check(after.cue?.kind === 'action', `the frame is attributed to the action cue (${after.cue?.kind})`);
check(after.actor.motion.delayInFrames === 30, 'the cue is delayed to its atFrame so the rig clock stays scene-local');

// --- inheritance, not reversion ------------------------------------------------------------
const inherited = scene({
  energy: 0.6,
  continuity: 'cut',
  beats: [
    {atFrame: 0, kind: 'action', subject: 't1'},
    {atFrame: 40, kind: 'emphasis', subject: 't1'},
  ],
});
const inheritedPlan = planBeats(inherited, actors);
const atAction = performanceAt(inheritedPlan, 0, 20, actors[0], inherited.motion.energy);
const atEmphasis = performanceAt(inheritedPlan, 0, 60, actors[0], inherited.motion.energy);
check(atAction.actor.pose === 'point', `the action beat sets point (${atAction.actor.pose})`);
check(
  atEmphasis.actor.pose === 'point' || atEmphasis.actor.pose === 'reach',
  `the emphasis keeps the raised arm instead of reverting (${atEmphasis.actor.pose})`,
);
check(
  atEmphasis.actor.pose !== 'stand',
  'the emphasis after an action does not drop back to the opening pose',
);

// --- emphasis over a locked-arm pose still moves a limb -------------------------------------
// `reach` and `walk` declare `armsLocked`, so a gesture cannot drive their arms. An emphasis there
// has to change the pose or the beat is a head tilt and nothing else.
const reachActor = [{...actors[0], pose: 'reach', gesture: 'openPalm'}];
const lockedEmphasis = scene({
  energy: 0.6,
  continuity: 'cut',
  beats: [{atFrame: 30, kind: 'emphasis', subject: 't1'}],
});
const lockedPlan = planBeats(lockedEmphasis, reachActor);
const emphasisCue = lockedPlan.cues[0];
check(
  emphasisCue.pose !== 'reach',
  `an emphasis over a locked-arm pose changes the pose, not just the head (${emphasisCue.pose})`,
);
check(
  emphasisCue.preset === 'poseChange',
  `that emphasis is a pose change, not a gesture it cannot drive (${emphasisCue.preset})`,
);

// A non-locked pose keeps the pose and gets a real gesture instead: the arm moves either way.
const openEmphasis = planBeats(
  scene({energy: 0.6, continuity: 'cut', beats: [{atFrame: 30, kind: 'emphasis', subject: 't1'}]}),
  actors,
);
check(
  openEmphasis.cues[0].pose === 'stand' && openEmphasis.cues[0].gesture === 'openPalm',
  `an emphasis on a free-arm pose gestures rather than reposing (${openEmphasis.cues[0].gesture})`,
);

// --- peakFrame is the frame a still can prove something at ---------------------------------
const entering = scene({
  energy: 0.5,
  continuity: 'cut',
  beats: [{atFrame: 0, kind: 'enter', subject: 't1'}],
});
const enterCue = planBeats(entering, actors).cues[0];
check(enterCue.atFrame === 0, 'the enter beat opens at frame 0');
check(enterCue.peakFrame > 0, `its peak is after frame 0 (${enterCue.peakFrame}): at frame 0 the actor is invisible`);
const atZero = performanceAt(planBeats(entering, actors), 0, 0, actors[0], entering.motion.energy);
check(atZero.actor.motion.preset === 'enter', 'frame 0 still declares the entrance, so the fade has something to run');

// --- continuity ----------------------------------------------------------------------------
const carried = planBeats(
  scene({energy: 0.5, continuity: 'carry', beats: [{atFrame: 0, kind: 'enter', subject: 't1'}]}),
  actors,
);
check(
  carried.cues[0].preset === 'idle',
  `continuity=carry does not replay an entrance (${carried.cues[0].preset})`,
);

// --- a beat past the scene end is reported, never silently dropped -------------------------
const late = planBeats(
  scene({energy: 0.5, continuity: 'cut', beats: [{atFrame: 200, kind: 'action', subject: 't1'}]}),
  actors,
);
check(late.cues.length === 0, 'a beat past the end produces no cue');
check(
  late.dropped.length === 1 && late.dropped[0].atFrame === 200 && late.dropped[0].sceneDurationInFrames === 120,
  `the dropped beat is reported with its scene duration (${JSON.stringify(late.dropped)})`,
);

// --- subject resolution --------------------------------------------------------------------
const selector = planBeats(
  scene({
    energy: 0.5,
    continuity: 'cut',
    beats: [{atFrame: 10, kind: 'action', subject: 'actor:0'}],
  }),
  actors,
);
check(selector.cues[0].resolution === 'actor', `actor:0 resolves by selector (${selector.cues[0].resolution})`);

const byText = planBeats(
  scene({energy: 0.5, continuity: 'cut', beats: [{atFrame: 10, kind: 'action', subject: 't2'}]}),
  actors,
);
check(byText.cues[0].resolution === 'text', `a text element id resolves by text (${byText.cues[0].resolution})`);

const byCharacter = planBeats(
  scene({energy: 0.5, continuity: 'cut', beats: [{atFrame: 10, kind: 'action', subject: 'maya'}]}),
  actors,
);
check(
  byCharacter.cues[0].resolution === 'character',
  `a character id resolves to its actor (${byCharacter.cues[0].resolution})`,
);

const unknown = planBeats(
  scene({energy: 0.5, continuity: 'cut', beats: [{atFrame: 10, kind: 'action', subject: 'nothing'}]}),
  actors,
);
check(unknown.cues.length === 1, 'an unrecognised subject still performs, so a scene does not freeze');
check(unknown.unresolved.length === 1, `but the fallback is reported (${JSON.stringify(unknown.unresolved)})`);
check(unknown.cues[0].actorIndex === 0, 'and it lands on the primary actor');

const badSelector = planBeats(
  scene({energy: 0.5, continuity: 'cut', beats: [{atFrame: 10, kind: 'action', subject: 'actor:7'}]}),
  actors,
);
check(badSelector.unresolved.length === 1, 'actor:7 with one actor is reported as unresolved');

// --- determinism and seekability -----------------------------------------------------------
const many = scene({
  energy: 0.7,
  continuity: 'cut',
  beats: [
    {atFrame: 0, kind: 'enter', subject: 't1'},
    {atFrame: 30, kind: 'action', subject: 't1'},
    {atFrame: 70, kind: 'emphasis', subject: 't1'},
    {atFrame: 100, kind: 'exit', subject: 't1'},
  ],
});
const manyPlan = planBeats(many, actors);
const forward = Array.from({length: many.durationInFrames}, (_, frame) =>
  performanceAt(manyPlan, 0, frame, actors[0], many.motion.energy),
);
const reversed = [...forward.keys()]
  .reverse()
  .map((frame) => performanceAt(manyPlan, 0, frame, actors[0], many.motion.energy))
  .reverse();
check(
  forward.every((performance, frame) => signature(performance) === signature(reversed[frame])),
  'every frame resolves identically regardless of the order frames are asked for',
);
check(
  forward.every(
    (performance, frame) =>
      signature(performance) === signature(performanceAt(planBeats(many, actors), 0, frame, actors[0], many.motion.energy)),
  ),
  'the same frame resolves identically across independent plans (no accumulated state)',
);

// --- exit fades ----------------------------------------------------------------------------
const exitCue = manyPlan.cues.find((cue) => cue.kind === 'exit');
const atExit = performanceAt(manyPlan, 0, exitCue.atFrame, actors[0], many.motion.energy);
const afterExit = performanceAt(manyPlan, 0, exitCue.atFrame + 60, actors[0], many.motion.energy);
check(atExit.opacity === 1, 'the exit beat starts fully opaque');
check(afterExit.opacity === 0, `the exit beat fades to nothing (${afterExit.opacity})`);

// --- an empty or actor-less scene is not an error ------------------------------------------
check(planBeats(scene(undefined), actors).cues.length === 0, 'a scene with no motion plans nothing');
check(planBeats(acted, []).cues.length === 0, 'a scene with no actors plans nothing');

console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} motion beats: ${failures} failure(s)`);
process.exit(failures === 0 ? 0 : 1);
