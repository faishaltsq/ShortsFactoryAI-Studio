/**
 * Beat measurement on a real render.
 *
 * Usage: node scripts/verify-render-beats.mjs <job-dir>
 *
 * `job-dir` is a job root produced by a real pipeline run: it must contain `output.mp4` and
 * `render-props.json`. Every number below comes from ffmpeg reading the encoded file, not from the
 * storyboard that asked for it.
 *
 * For each scene the script measures, over two regions:
 *
 *   character  the region `CharacterFigure` paints, derived from the actor's `x`/`ground`/`scale`
 *   background the top band, which no actor reaches
 *
 * at the two ends of each beat's own transition, plus one control window per scene:
 *
 *   atFrame    `BeatPlan.cues[].atFrame` — the frame the beat opens at
 *   peakFrame  the frame the beat is fully visible at. For `enter` that is the end of the
 *              entrance, not frame 0: at frame 0 the actor is at zero opacity, so a still there is
 *              an empty stage and proves nothing. For a pose change it is where the travel lands.
 *   idle       the *quietest* 15-frame window in the same scene. Sampling several windows and
 *              keeping the minimum is the conservative choice: a beat has to beat the calmest part
 *              of its own scene, not the average, or a control window that happens to catch a
 *              gesture release would raise the bar for no reason.
 *
 * The script also reports every beat that `planBeats` had to drop because it sits past the scene's
 * retimed duration, and fails if there are any: a beat that cannot be rendered is a fixture bug, not
 * a rendering detail.
 *
 * Exits non-zero when no scene shows a beat that beats its own control.
 */

import {register} from 'node:module';
import {spawnSync} from 'node:child_process';
import {mkdirSync, readFileSync, rmSync} from 'node:fs';
import path from 'node:path';

register('./ts-resolve-hook.mjs', import.meta.url);

const {planBeats} = await import('../src/motion-beats.ts');

const jobDir = process.argv[2];
if (!jobDir || !path.isAbsolute(jobDir)) throw new Error('Pass an absolute job directory');
const video = path.join(jobDir, 'output.mp4');
const props = JSON.parse(readFileSync(path.join(jobDir, 'render-props.json'), 'utf8'));
const storyboard = props.storyboard;
const framesDir = path.join(jobDir, '.beat-frames');
rmSync(framesDir, {recursive: true, force: true});
mkdirSync(framesDir, {recursive: true});

const run = (args) => {
  const result = spawnSync('ffmpeg', ['-hide_banner', '-nostats', ...args, '-f', 'null', '-'], {
    encoding: 'utf8',
    timeout: 120000,
  });
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.stderr.slice(-500)}`);
  return result.stderr;
};

const frameAt = (frame) => {
  const png = path.join(framesDir, `f${frame}.png`);
  const result = spawnSync(
    'ffmpeg',
    ['-v', 'error', '-y', '-i', video, '-vf', `select=eq(n\\,${frame})`, '-fps_mode', 'passthrough', '-frames:v', '1', png],
    {encoding: 'utf8', timeout: 120000},
  );
  if (result.status !== 0) throw new Error(`frame ${frame}: ${result.stderr.slice(-400)}`);
  return png;
};

/** Mean absolute luminance difference and PSNR over a crop. Two passes: the filters cannot share
 * one graph because `metadata=print` needs its own output. */
const compare = (a, b, crop) => {
  const deltaLog = run([
    '-i', a, '-i', b,
    '-filter_complex', `[0:v]crop=${crop}[x0];[1:v]crop=${crop}[x1];[x0][x1]blend=all_mode=difference,signalstats,metadata=print`,
  ]);
  const psnrLog = run([
    '-i', a, '-i', b,
    '-filter_complex', `[0:v]crop=${crop},format=gray[x0];[1:v]crop=${crop},format=gray[x1];[x0][x1]psnr`,
  ]);
  const delta = Number(/lavfi\.signalstats\.YAVG=([0-9.]+)/.exec(deltaLog)?.[1]);
  const psnr = /average:([0-9.]+|inf)/.exec(psnrLog)?.[1];
  return {delta, psnr: psnr === 'inf' ? Infinity : Number(psnr)};
};

const characterCrop = (actor) => {
  const height = Math.min(1920, Math.round(0.52 * 1920 * actor.scale));
  const width = Math.min(1080, Math.round(height * 1.15));
  const left = Math.min(1080 - width, Math.max(0, Math.round(actor.x * 1080 - width / 2)));
  const top = Math.min(1920 - height, Math.max(0, Math.round(actor.ground * 1920 - height)));
  return `${width}:${height}:${left}:${top}`;
};

const BACKGROUND_CROP = '1080:384:0:0';
const rows = [];
const dropped = [];

for (const scene of storyboard.scenes) {
  const actors = scene.data?.actors ?? [];
  if (actors.length === 0) continue;
  const plan = planBeats(scene, actors);
  dropped.push(...plan.dropped.map((beat) => ({sceneId: scene.sceneId, ...beat})));

  for (const cue of plan.cues) {
    if (cue.peakFrame >= scene.durationInFrames) continue;
    const a = frameAt(scene.startFrame + cue.atFrame);
    const b = frameAt(scene.startFrame + cue.peakFrame);
    rows.push({
      sceneId: scene.sceneId,
      kind: cue.kind,
      subject: cue.subject,
      peakFrame: cue.peakFrame,
      atFrame: cue.atFrame,
      compareFrame: cue.peakFrame,
      camera: scene.camera ? `${scene.camera.move}/${scene.camera.shot}` : '(none)',
      character: compare(a, b, characterCrop(actors[0])),
      background: compare(a, b, BACKGROUND_CROP),
    });
  }

  // Idle floor: sample every 15-frame window that starts at least one frame after the previous one,
  // and keep the quietest. Frames are rendered once and reused across windows.
  const windowLength = 15;
  const crop = characterCrop(actors[0]);
  const backgroundCrop = BACKGROUND_CROP;
  const idleWindows = [];
  for (let start = 0; start + windowLength < scene.durationInFrames; start += 5) {
    const a = frameAt(scene.startFrame + start);
    const b = frameAt(scene.startFrame + start + windowLength);
    idleWindows.push({
      start,
      character: compare(a, b, crop),
      background: compare(a, b, backgroundCrop),
    });
  }
  const quietest = idleWindows.reduce((low, window) =>
    window.character.delta < low.character.delta ? window : low,
  );
  rows.push({
    sceneId: scene.sceneId,
    kind: 'idle',
    subject: `(quietest of ${idleWindows.length} windows)`,
    peakFrame: quietest.start + windowLength,
    atFrame: quietest.start,
    compareFrame: quietest.start + windowLength,
    camera: scene.camera ? `${scene.camera.move}/${scene.camera.shot}` : '(none)',
    character: quietest.character,
    background: quietest.background,
    windows: idleWindows.map((window) => ({
      start: window.start,
      delta: Number(window.character.delta.toFixed(3)),
    })),
  });
}

const table = rows.map((row) => ({
  scene: row.sceneId,
  kind: row.kind,
  subject: row.subject,
  atFrame: row.atFrame,
  peakFrame: row.peakFrame,
  frames: `${row.atFrame}->${row.compareFrame}`,
  camera: row.camera,
  characterDelta: Number(row.character.delta.toFixed(3)),
  characterPsnr: row.character.psnr === Infinity ? 'inf' : Number(row.character.psnr.toFixed(2)),
  backgroundDelta: Number(row.background.delta.toFixed(3)),
}));
console.table(table);

const controls = new Map(
  rows.filter((row) => row.kind === 'idle').map((row) => [row.sceneId, row.character.delta]),
);
const beatRows = rows.filter((row) => row.kind !== 'idle');
const visible = beatRows.filter((row) => {
  const control = controls.get(row.sceneId) ?? 0;
  // A beat counts only if the character moved more than twice its own idle in the same scene.
  return row.character.delta >= Math.max(2 * control, 0.5) && row.character.delta > 4 * row.background.delta;
});

console.log(
  JSON.stringify(
    {
      beatsMeasured: beatRows.length,
      beatsWithVisibleCharacterChange: visible.length,
      visibleBeats: visible.map((row) => `${row.sceneId}:${row.kind}@${row.atFrame}->${row.peakFrame}`),
      idleFloor: Object.fromEntries([...controls].map(([id, value]) => [id, Number(value.toFixed(3))])),
      droppedBeats: dropped,
    },
    null,
    2,
  ),
);

if (dropped.length > 0) {
  console.log(
    `FAIL ${dropped.length} beat(s) sit past their scene's retimed duration and can never render: ` +
      JSON.stringify(dropped),
  );
  process.exit(1);
}
if (visible.length === 0) {
  console.log('FAIL no declared beat produced a visible character change above the scene idle');
  process.exit(1);
}
console.log('PASS declared beats move the character in the encoded video');
