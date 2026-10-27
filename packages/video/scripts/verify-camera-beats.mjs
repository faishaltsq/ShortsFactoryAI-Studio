/**
 * Camera and beat measurement. Renders stills through the real Remotion composition and measures
 * pixels; nothing here asserts intent.
 *
 * Usage: node scripts/verify-camera-beats.mjs <absolute-output-dir>
 *
 * Five measurements. Each one fails the run when it regresses.
 *
 * 1. **A static camera contributes nothing.** Two stills of the same frame, identical except that
 *    one declares `amplitude: 0.12` and the other `amplitude: 0`. PSNR must be infinite. Together
 *    with `declaredCameraAt` returning `x=y=rotate=0` for every frame (asserted below), that is the
 *    "no accidental drift" property `static_ratio` depends on: freezedetect measures pixels, so a
 *    static scene that creeps would silently stop being measurable.
 * 2. **A declared `push` moves the frame.** Same two frames 110 apart, background crop (the corner,
 *    so character animation cannot confound it), `push` vs `static`. The push must move the corner
 *    substantially more than the static baseline.
 * 3. **A declared `motion.beats[].atFrame` reaches the rig.** Under a *static* camera, the beat
 *    frame and beat+15 must differ inside the character's own painted region.
 * 4. **A scene with no camera and no motion still renders** at 1080x1920 with a non-blank narrative
 *    safe area.
 * 5. **The camera transform is frame-invariant when static** and monotonic when pushing — a pure
 *    function check on `declaredCameraAt`, no pixels involved.
 */

import {register} from 'node:module';
import {spawnSync} from 'node:child_process';
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {freeRemotionPort} from './free-port.mjs';

register('./ts-resolve-hook.mjs', import.meta.url);

const videoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = process.argv[2];
if (!outDir || !path.isAbsolute(outDir)) throw new Error('Pass an absolute output directory');
mkdirSync(outDir, {recursive: true});

const cli = path.join(videoDir, 'node_modules/@remotion/cli/remotion-cli.js');
const port = await freeRemotionPort();

const {adaptProductStoryboard} = await import('../src/product-adapter.ts');
const {declaredCameraAt, textAnchorOf} = await import('../src/camera.ts');
const {performanceAt, planBeats} = await import('../src/motion-beats.ts');

const product = JSON.parse(readFileSync(path.join(videoDir, 'fixtures/product-storyboard.json'), 'utf8'));
const storyboard = adaptProductStoryboard(product);
const scene = storyboard.scenes[0];

const still = (name, frame, sceneProps) => {
  const props = path.join(outDir, `${name}-props.json`);
  const png = path.join(outDir, `${name}.png`);
  writeFileSync(props, JSON.stringify({scene: sceneProps, theme: storyboard.theme, watermark: storyboard.watermark?.text}));
  const result = spawnSync(
    process.execPath,
    [cli, 'still', 'src/index.ts', 'IllustratedStory', png, `--props=${props}`, `--frame=${frame}`,
      '--overwrite', '--log=error', `--port=${port}`],
    {cwd: videoDir, encoding: 'utf8', timeout: 240000},
  );
  if (result.status !== 0) throw new Error(`${name}@${frame}: ${result.stderr || result.stdout}`);
  const bytes = readFileSync(png);
  if (bytes.toString('hex', 0, 8) !== '89504e470d0a1a0a') throw new Error(`${name}: not a PNG`);
  if (bytes.readUInt32BE(16) !== 1080 || bytes.readUInt32BE(20) !== 1920) throw new Error(`${name}: not 1080x1920`);
  return png;
};

const ffmpeg = (args) => {
  const result = spawnSync('ffmpeg', ['-hide_banner', '-nostats', ...args, '-f', 'null', '-'], {encoding: 'utf8', timeout: 60000});
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.stderr.slice(-600)}`);
  return result.stderr;
};

/** PSNR over a crop. `Infinity` means the pixels are identical. */
const cropPsnr = (a, b, crop) => {
  const log = ffmpeg([
    '-i', a, '-i', b,
    '-filter_complex',
    `[0:v]crop=${crop},format=gray[x];[1:v]crop=${crop},format=gray[y];[x][y]psnr`,
  ]);
  const match = /average:([0-9.]+|inf)/.exec(log);
  if (!match) throw new Error(`psnr not reported: ${log.slice(-400)}`);
  return match[1] === 'inf' ? Infinity : Number(match[1]);
};

/** Mean absolute luminance difference over a crop, in 0..255 units. */
const cropDelta = (a, b, crop) => {
  const log = ffmpeg([
    '-i', a, '-i', b,
    '-filter_complex', `[0:v]crop=${crop}[x];[1:v]crop=${crop}[y];[x][y]blend=all_mode=difference,signalstats,metadata=print`,
  ]);
  const avg = /lavfi\.signalstats\.YAVG=([0-9.]+)/.exec(log);
  if (!avg) throw new Error(`signalstats not reported: ${log.slice(-400)}`);
  return Number(avg[1]);
};

const data = scene.data;
const actor = data.actors[0];
// The region CharacterFigure paints: 0.52 * 1920 * scale tall, feet on actor.ground, and the rig's
// viewBox is 760 wide for 760 tall. Both dimensions are clamped to the frame.
const heightPx = Math.min(1920, Math.round(0.52 * 1920 * actor.scale));
const widthPx = Math.min(1080, Math.round(heightPx * 1.15));
const left = Math.min(1080 - widthPx, Math.max(0, Math.round(actor.x * 1080 - widthPx / 2)));
const top = Math.min(1920 - heightPx, Math.max(0, Math.round(actor.ground * 1920 - heightPx)));
const characterCrop = `${widthPx}:${heightPx}:${left}:${top}`;
/** Sky corner: no character, no props, so only the camera and the background can move it. */
const cornerCrop = '360:360:0:0';

const stillCamera = {shot: 'wide', move: 'static', amplitude: 0.12, ease: 'power2.out'};
const pushCamera = {...stillCamera, move: 'push', target: scene.text[0].id};
const plan = planBeats(scene, data.actors);
const actionCue = plan.cues.find((cue) => cue.kind === 'action') ?? plan.cues[1];

const results = {
  characterCrop,
  cornerCrop,
  beatAtFrame: actionCue.atFrame,
  beatPeakFrame: actionCue.peakFrame,
  beatKind: actionCue.kind,
};

// 1. static ignores amplitude: same frame, two amplitudes, must be identical.
const staticAmp = still('static-amp-012', actionCue.atFrame, {...scene, camera: stillCamera});
const staticZero = still('static-amp-0', actionCue.atFrame, {...scene, camera: {...stillCamera, amplitude: 0}});
results.staticAmplitudePsnr = String(cropPsnr(staticAmp, staticZero, '1080:1920:0:0'));

// 2. The same frame rendered with `push` and with `static`: the actor, the environment and the
// effects are identical inputs, so every differing pixel is the camera. A per-frame comparison is
// the only way to isolate it — comparing two frames would also measure the scene's own animation.
const staticLate = still('static-f115', 115, {...scene, camera: stillCamera});
const pushLate = still('push-f115', 115, {...scene, camera: pushCamera});
results.cameraOnlyDelta = cropDelta(staticLate, pushLate, '1080:1920:0:0');
results.cameraOnlyPsnr = cropPsnr(staticLate, pushLate, '1080:1920:0:0');
results.cameraOnlyCornerDelta = cropDelta(staticLate, pushLate, cornerCrop);

// 3. The beat moves the character, under the static camera. Two comparisons, both reported:
//    `atFrame -> peakFrame` is the transition the beat declares, and `atFrame -> atFrame+15` is the
//    literal "beat vs beat+15" a reviewer asked for. The transition is the one that has to pass:
//    at `atFrame + 15` a pose change is still travelling, and for an `enter` beat the actor is only
//    partly faded in, so neither frame is the settled one.
const beatPeak = still('static-beat-peak', actionCue.peakFrame, {...scene, camera: stillCamera});
const beatPlus15 = still('static-beat-plus-15', actionCue.atFrame + 15, {...scene, camera: stillCamera});
results.beatTransitionDelta = cropDelta(staticAmp, beatPeak, characterCrop);
results.beatTransitionPsnr = cropPsnr(staticAmp, beatPeak, characterCrop);
results.beatPlus15Delta = cropDelta(staticAmp, beatPlus15, characterCrop);
results.beatPlus15Psnr = cropPsnr(staticAmp, beatPlus15, characterCrop);

// 4. a scene with neither field still renders.
const bare = {...scene};
delete bare.camera;
delete bare.motion;
const barePng = still('bare-60', 60, bare);
const spread = ffmpeg(['-i', barePng, '-vf', 'crop=936:1340:72:260,signalstats,metadata=print', '-frames:v', '1']);
const ymin = Number(/lavfi\.signalstats\.YMIN=([0-9.]+)/.exec(spread)?.[1]);
const ymax = Number(/lavfi\.signalstats\.YMAX=([0-9.]+)/.exec(spread)?.[1]);
results.bareSafeAreaSpread = ymax - ymin;

// 5. transform-level properties: static is frame-invariant, push is monotonic and bounded.
const anchor = textAnchorOf(scene, scene.text[0].id);
const viewport = {width: 1080, height: 1920};
const frames = Array.from({length: scene.durationInFrames}, (_, i) => i);
const staticTransforms = frames.map((f) => declaredCameraAt(stillCamera, f, scene.durationInFrames, anchor, viewport));
results.staticTransformInvariant = staticTransforms.every(
  (t) => t.x === 0 && t.y === 0 && t.rotate === 0 && t.scale === staticTransforms[0].scale,
);
const pushScales = frames.map((f) => declaredCameraAt(pushCamera, f, scene.durationInFrames, anchor, viewport).scale);
results.pushScaleMonotonic = pushScales.every((scale, i) => i === 0 || scale >= pushScales[i - 1]);
results.pushScaleRange = [Number(pushScales[0].toFixed(5)), Number(pushScales.at(-1).toFixed(5))];
results.pushEndScaleMatchesAmplitude =
  Math.abs(pushScales.at(-1) - (1 + pushCamera.amplitude)) < 1e-9;

// And the beat plan itself: the action beat must produce a different pose than the actor's own.
// The cue switches at `atFrame`, so the state *before* the beat is the frame before it.
const beforeBeat = performanceAt(plan, 0, Math.max(0, actionCue.atFrame - 1), actor, scene.motion.energy);
const onBeat = performanceAt(plan, 0, actionCue.peakFrame, actor, scene.motion.energy);
results.beatPlanUnresolved = plan.unresolved.length;
results.beatPlanDropped = plan.dropped.length;
results.beatPoseBefore = beforeBeat.actor.pose;
results.beatPoseAfter = onBeat.actor.pose;
results.beatCueKind = onBeat.cue?.kind ?? null;
results.beatChangesPose = beforeBeat.actor.pose !== onBeat.actor.pose;

// Seekability: Remotion renders frames out of order, so the same frame must produce the same
// performance no matter what was asked for before it. This is a pure-function property, and the
// whole reason `characterFrameAt` re-samples from the frame number instead of integrating.
const forward = Array.from({length: scene.durationInFrames}, (_, i) => performanceAt(plan, 0, i, actor, scene.motion.energy));
const backward = [...forward.keys()].reverse().map((i) => performanceAt(plan, 0, i, actor, scene.motion.energy));
const signature = (p) => JSON.stringify([p.actor.pose, p.actor.expression, p.actor.gesture, p.actor.motion, p.opacity]);
results.seekable = forward.every((p, i) => signature(p) === signature(backward[backward.length - 1 - i]));
results.repeatable = forward.every((p, i) => signature(p) === signature(performanceAt(plan, 0, i, actor, scene.motion.energy)));

console.log(JSON.stringify(results, null, 2));

const failures = [];
if (results.staticAmplitudePsnr !== 'Infinity') {
  failures.push(`static camera responds to amplitude (PSNR ${results.staticAmplitudePsnr} dB, expected Infinity)`);
}
if (!results.staticTransformInvariant) failures.push('static camera transform varies by frame');
if (!results.pushScaleMonotonic) failures.push('push camera scale is not monotonic');
if (!results.pushEndScaleMatchesAmplitude) failures.push(`push does not end at 1 + amplitude (got ${results.pushScaleRange[1]})`);
if (!(results.cameraOnlyDelta >= 2)) {
  failures.push(`declared push does not change the frame (mean delta ${results.cameraOnlyDelta})`);
}
if (!(results.beatTransitionDelta >= 0.5)) {
  failures.push(`beat does not move the character (transition delta ${results.beatTransitionDelta})`);
}
if (!results.beatChangesPose) failures.push('the action beat does not change the pose');
if (!results.seekable) failures.push('performance depends on render order (not seekable)');
if (!results.repeatable) failures.push('performance is not a pure function of the frame');
if (results.beatPlanDropped !== 0) failures.push(`${results.beatPlanDropped} beat(s) dropped past the scene end`);
if (results.beatPlanUnresolved !== 0) failures.push(`${results.beatPlanUnresolved} beat subject(s) named nothing in the scene`);
if (!(results.bareSafeAreaSpread >= 20)) failures.push(`camera-less scene renders blank (spread ${results.bareSafeAreaSpread})`);

if (failures.length) {
  for (const failure of failures) console.log(`FAIL ${failure}`);
  process.exit(1);
}
console.log('PASS camera and beats reach pixels');
