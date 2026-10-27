/**
 * Mouth sync: the character's mouth follows the measured speech windows, not a sine wave.
 *
 * Usage: node scripts/test-speech-sync.mjs
 *
 * The bug this guards: `motion.ts` opened the mouth from `preset === 'talk'` with
 * `sin(local / 3.1) * 0.55 + sin(local / 1.7) * 0.3` — a synthetic clock. The real word boundaries
 * were measured by SAPI, persisted per scene as `speech: [{startMs, endMs}, …]`, and never read by
 * the renderer. A sine wave that happens to move the mouth is not lip sync.
 *
 * What is asserted:
 *
 * 1. A storyboard whose scene declares speech windows `[0,400], [900,1300]` has a **closed** mouth
 *    at frame 21 (700 ms, in the gap) and an **open** mouth at frame 6 (200 ms, mid-word).
 * 2. Two different window sets give different mouth values at the same frame — the mouth is a
 *    function of the data, not of the frame alone.
 * 3. The same frame always gives the same mouth, in any order (Remotion renders out of order).
 * 4. No speech windows → the mouth stays closed. It never falls back to the sine.
 * 5. `withSpeech` still modulates the expression's own mouth shape; only the *timing* comes from
 *    the windows.
 */

import {register} from 'node:module';

register('./ts-resolve-hook.mjs', import.meta.url);

const {speechAt, mouthOpenAt} = await import('../src/speech.ts');
const {planBeats, performanceAt} = await import('../src/motion-beats.ts');
const {characterFrameAt} = await import('../src/character/motion.ts');

let failures = 0;
const pass = (message) => console.log(`PASS ${message}`);
const check = (condition, message) => {
  if (condition) pass(message);
  else {
    failures += 1;
    console.log(`FAIL ${message}`);
  }
};

const FPS = 30;
const WINDOWS = [
  {startMs: 0, endMs: 400},
  {startMs: 900, endMs: 1300},
];

console.log('# speech sync');

// --- the core claim: the gap is closed, the word is open ------------------------------------
// Frame 21 at 30 fps is 700 ms, which is inside the 400..900 ms gap. Frame 6 is 200 ms, mid-word.
const inGap = mouthOpenAt(WINDOWS, 21, FPS);
const midWord = mouthOpenAt(WINDOWS, 6, FPS);
check(inGap === 0, `frame 21 (700 ms) is in the gap, mouth closed (mouthOpen=${inGap})`);
check(midWord > 0.5, `frame 6 (200 ms) is mid-word, mouth open (mouthOpen=${midWord})`);
check(
  midWord - inGap > 0.5,
  `the two frames are clearly different (${midWord} vs ${inGap})`,
);

// --- the mouth is a function of the data, not of the frame ---------------------------------
const shifted = [
  {startMs: 400, endMs: 900},
  {startMs: 1300, endMs: 1700},
];
const otherAt21 = mouthOpenAt(shifted, 21, FPS);
const otherAt6 = mouthOpenAt(shifted, 6, FPS);
check(
  otherAt21 !== inGap,
  `a different window set gives a different mouth at frame 21 (${inGap} vs ${otherAt21})`,
);
check(
  otherAt6 !== midWord,
  `a different window set gives a different mouth at frame 6 (${midWord} vs ${otherAt6})`,
);
check(otherAt21 > 0.5, 'the shifted set opens the mouth at 700 ms, where the first set closes it');
check(otherAt6 === 0, 'and closes it at 200 ms, where the first set opens it');

// --- attack/release: no chatter at window edges --------------------------------------------
// The first frame of a window must not be fully open, and the frame after the window must not be
// fully shut, or the mouth snaps once per word.
const firstFrame = mouthOpenAt(WINDOWS, 0, FPS);
const oneFrameIn = mouthOpenAt(WINDOWS, 1, FPS);
check(firstFrame < oneFrameIn, `attack is gradual (${firstFrame} at 0 ms, ${oneFrameIn} one frame later)`);
const lastWordFrame = mouthOpenAt(WINDOWS, 11, FPS); // 366 ms, still inside [0,400]
const justAfter = mouthOpenAt(WINDOWS, 13, FPS); // 433 ms, just past 400
check(lastWordFrame > justAfter, `release is gradual (${lastWordFrame} inside, ${justAfter} after)`);
check(justAfter > 0, 'the mouth is not slammed shut on the frame after the window');

// --- seekability ---------------------------------------------------------------------------
const frames = Array.from({length: 60}, (_, i) => i);
const forward = frames.map((frame) => mouthOpenAt(WINDOWS, frame, FPS));
const backward = [...frames].reverse().map((frame) => mouthOpenAt(WINDOWS, frame, FPS)).reverse();
check(
  forward.every((value, i) => value === backward[i]),
  'every frame resolves identically regardless of the order frames are asked for',
);
check(
  forward.every((value, i) => value === mouthOpenAt(WINDOWS, i, FPS)),
  'the mouth is a pure function of (windows, frame, fps) — no accumulated state',
);

// --- the honest fallback: no windows means closed, never a sine ----------------------------
check(mouthOpenAt([], 6, FPS) === 0, 'no speech windows -> the mouth stays closed at 200 ms');
check(mouthOpenAt([], 21, FPS) === 0, 'no speech windows -> the mouth stays closed at 700 ms');
check(
  frames.every((frame) => mouthOpenAt([], frame, FPS) === 0),
  'no speech windows -> the mouth never opens, so a sine cannot sneak back in',
);

// --- `talk` no longer moves the mouth on its own -------------------------------------------
// A talk preset with no windows must leave the mouth at the expression's own value. This is the
// regression the whole change exists for: the sine lived in `preset === 'talk'`.
const talkNoSpeech = characterFrameAt({
  input: {pose: 'stand', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'talk'}},
  frame: 20,
  fps: FPS,
  durationInFrames: 120,
});
const idleSameExpression = characterFrameAt({
  input: {pose: 'stand', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'idle'}},
  frame: 20,
  fps: FPS,
  durationInFrames: 120,
});
check(
  talkNoSpeech.expression.mouthOpen === idleSameExpression.expression.mouthOpen,
  `talk without speech windows does not open the mouth (talk ${talkNoSpeech.expression.mouthOpen} vs idle ${idleSameExpression.expression.mouthOpen})`,
);

// With a window at that frame, the same talk preset opens it.
const talkWithSpeech = characterFrameAt({
  input: {pose: 'stand', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'talk'}, speech: WINDOWS},
  frame: 6,
  fps: FPS,
  durationInFrames: 120,
});
check(
  talkWithSpeech.expression.mouthOpen > 0.5,
  `the same preset opens the mouth when a window covers the frame (${talkWithSpeech.expression.mouthOpen})`,
);

// --- the envelope is reported, so a caller can see what drove the mouth --------------------
const active = speechAt(WINDOWS, 6, FPS);
check(active.windowIndex === 0, `frame 6 is attributed to window 0 (${active.windowIndex})`);
check(active.weight > 0 && active.weight <= 1, `its weight is in 0..1 (${active.weight})`);
const idleWindow = speechAt(WINDOWS, 21, FPS);
check(idleWindow.windowIndex === -1, `frame 21 is attributed to no window (${idleWindow.windowIndex})`);
check(idleWindow.weight === 0, `and carries zero weight (${idleWindow.weight})`);

// --- the clock: scene-local, never absolute ------------------------------------------------
// `speech` is scene-local ms, exactly like the subtitles and `motion.beats[].atFrame`. If the
// renderer ever added a scene's `startFrame` to the frame before converting to milliseconds, the
// mouth would drift by a whole scene and still look plausible in a single still. So the same window
// must produce the same mouth at the same *scene-local* frame in every scene, whatever the scene's
// absolute position on the timeline.
const lateSceneWindows = [{startMs: 0, endMs: 400}];
const perScene = [
  {sceneIndex: 0, startFrame: 0, durationInFrames: 120},
  {sceneIndex: 1, startFrame: 120, durationInFrames: 131},
  {sceneIndex: 2, startFrame: 251, durationInFrames: 115},
].map((scene) => ({
  ...scene,
  mouthAt6: mouthOpenAt(lateSceneWindows, 6, FPS),
  mouthAt21: mouthOpenAt(lateSceneWindows, 21, FPS),
}));
check(
  perScene.every((scene) => scene.mouthAt6 > 0.5),
  `a 0..400 ms window opens the mouth at scene frame 6 in every scene (${perScene.map((s) => s.mouthAt6).join(', ')})`,
);
check(
  perScene.every((scene) => scene.mouthAt21 === 0),
  `and closes it at scene frame 21 in every scene (${perScene.map((s) => s.mouthAt21).join(', ')})`,
);
check(
  new Set(perScene.map((scene) => scene.mouthAt6)).size === 1,
  'the mouth is identical across scenes at the same scene-local frame — no absolute-clock drift',
);

// The same check through the real rig, which is what a render actually calls.
//
// Two clocks meet here and must not be confused. `frame` is what the rig animates on and a beat's
// `delayInFrames` re-bases it to the beat's own start. `speechFrame` is the scene-local clock the
// word windows are measured against. A beat starting at frame 66 must not shift the speech clock,
// or the mouth would restart mid-sentence every time a beat fired.
const rigMouth = ({speechFrame, frame, delay = 0}) =>
  characterFrameAt({
    input: {
      pose: 'stand',
      expression: 'neutral',
      gesture: 'none',
      seed: 1,
      motion: {preset: 'talk', delayInFrames: delay},
      speech: lateSceneWindows,
      speechFrame,
    },
    frame,
    fps: FPS,
    durationInFrames: 120,
  }).expression.mouthOpen;
check(
  rigMouth({speechFrame: 6, frame: 6}) > 0.5 && rigMouth({speechFrame: 6, frame: 90}) > 0.5,
  'the rig opens the mouth on the speech clock, whatever frame the rig itself is animating on',
);
check(
  rigMouth({speechFrame: 6, frame: 6}) === rigMouth({speechFrame: 6, frame: 90, delay: 84}),
  'a beat starting at frame 84 does not shift the speech clock (same aperture on both sides)',
);
check(
  rigMouth({speechFrame: 21, frame: 21}) === 0,
  'and the same rig closes the mouth in the measured gap',
);

// --- the beat plan carries the windows through to the performance ---------------------------
const scene = {
  sceneId: 'sc1',
  template: 'IllustratedStory',
  segment: 's1',
  assetRefs: [],
  text: [{id: 't1', text: 'judul', style: {role: 'title'}}],
  animation: {preset: 'fadeIn'},
  transition: {type: 'none'},
  startFrame: 0,
  durationInFrames: 120,
  speech: WINDOWS,
  motion: {
    energy: 0.6,
    continuity: 'cut',
    beats: [{atFrame: 0, kind: 'enter', subject: 't1'}],
  },
};
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
    expression: 'neutral',
  },
];
const plan = planBeats(scene, actors);
const performed = performanceAt(plan, 0, 6, actors[0], scene.motion.energy);
check(
  performed.actor.motion.preset === 'talk' || performed.cue?.kind === 'enter',
  `the beat plan still resolves a preset (${performed.actor.motion.preset})`,
);

console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} speech sync: ${failures} failure(s)`);
process.exit(failures === 0 ? 0 : 1);
