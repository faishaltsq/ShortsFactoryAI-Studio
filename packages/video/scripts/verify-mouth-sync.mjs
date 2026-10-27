/**
 * Mouth measurement, controlled. Renders stills through the real Remotion composition.
 *
 * Usage: node scripts/verify-mouth-sync.mjs <absolute-output-dir>
 *
 * Why stills and not two frames of one video: in a real render every other thing is moving too
 * (a declared camera push/pull, a beat's pose change, idle breathing). A mouth delta measured across
 * two arbitrary video frames therefore cannot be attributed to the mouth. This script holds the
 * frame fixed and varies only the speech window, so the difference it reports *is* the mouth.
 *
 * Four measurements, each of which fails the run when it regresses:
 *
 * 1. **Same frame, window over it vs window not over it.** One still where the scene declares a
 *    window covering the frame, one where it declares a window well after it. Everything else —
 *    pose, camera, effects, beat phase — is byte-identical input, so every differing pixel is the
 *    mouth. This is the claim "the mouth follows the data".
 * 2. **Same frame, two different window sets.** A third still whose windows are shifted; its mouth
 *    must differ from the first, proving the mouth is a function of the data and not of the frame.
 * 3. **No windows at all.** The mouth must match the "window not over it" still: a scene with no
 *    measurement renders a closed mouth, never a sine.
 * 4. **A real encoded render.** The two frames of the job's own `output.mp4` at the same positions,
 *    reported for the record. Their delta is larger than the mouth alone because the camera and the
 *    beats are also moving there; it is evidence the mouth region is not frozen, not proof of sync.
 *
 * The mouth crop is derived from the actor's placement and the manifest's face spec, not guessed.
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
const {mouthOpenAt} = await import('../src/speech.ts');
const {getCharacter} = await import('../src/character/registry.ts');

const product = JSON.parse(readFileSync(path.join(videoDir, 'fixtures/product-storyboard.json'), 'utf8'));
const storyboard = adaptProductStoryboard(product);
const scene = storyboard.scenes[0];
const fps = storyboard.fps;
const manifest = getCharacter('maya');

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
  return png;
};

const ffmpeg = (args) => {
  const result = spawnSync('ffmpeg', ['-hide_banner', '-nostats', ...args, '-f', 'null', '-'], {
    encoding: 'utf8',
    timeout: 60000,
  });
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.stderr.slice(-500)}`);
  return result.stderr;
};

/** Fraction of the crop's pixels whose luminance changed by more than `threshold`. */
const changedFraction = (a, b, crop, threshold = 8) => {
  const log = ffmpeg([
    '-i', a, '-i', b,
    '-filter_complex',
    `[0:v]crop=${crop}[x0];[1:v]crop=${crop}[x1];` +
      `[x0][x1]blend=all_mode=difference,format=gray,` +
      `geq=lum='if(gt(lum(X\,Y)\,${threshold})\,255\,0)',signalstats,metadata=print`,
  ]);
  const mean = Number(/lavfi\.signalstats\.YAVG=([0-9.]+)/.exec(log)?.[1]);
  return mean / 255;
};

const compare = (a, b, crop) => {
  const deltaLog = ffmpeg([
    '-i', a, '-i', b,
    '-filter_complex', `[0:v]crop=${crop}[x0];[1:v]crop=${crop}[x1];[x0][x1]blend=all_mode=difference,signalstats,metadata=print`,
  ]);
  const psnrLog = ffmpeg([
    '-i', a, '-i', b,
    '-filter_complex', `[0:v]crop=${crop},format=gray[x0];[1:v]crop=${crop},format=gray[x1];[x0][x1]psnr`,
  ]);
  return {
    delta: Number(/lavfi\.signalstats\.YAVG=([0-9.]+)/.exec(deltaLog)?.[1]),
    psnr: (() => {
      const value = /average:([0-9.]+|inf)/.exec(psnrLog)?.[1];
      return value === 'inf' ? Infinity : Number(value);
    })(),
  };
};

const actor = scene.data.actors[0];
const figureHeight = Math.min(1920, Math.round(0.52 * 1920 * actor.scale));
const figureWidth = Math.min(1080, Math.round(figureHeight * 1.15));
const figureLeft = Math.min(1080 - figureWidth, Math.max(0, Math.round(actor.x * 1080 - figureWidth / 2)));
const figureTop = Math.min(1920 - figureHeight, Math.max(0, Math.round(actor.ground * 1920 - figureHeight)));

// Mouth box in character space, from the manifest's face spec. `Face` puts the mouth centre at
// `anchor.y + height * 0.3`, the mouth is about `width * 0.3` wide and `mouthOpen` adds up to
// `height * 0.1` of opening, so the box is the mouth plus a margin — not a guess, a derivation.
const viewBox = manifest.viewBox;
const {anchor, width: faceWidth, height: faceHeight} = manifest.face;
const mouthCentreY = anchor.y + faceHeight * 0.3;
const pxPerUnitY = figureHeight / viewBox.height;
const pxPerUnitX = figureWidth / viewBox.width;
const halfW = (faceWidth * 0.22 + 8) * pxPerUnitX;
const halfH = (faceHeight * 0.11 + 10) * pxPerUnitY;
const centreX = figureLeft + (anchor.x - (viewBox.minX ?? 0)) * pxPerUnitX;
const centreY = figureTop + (mouthCentreY - (viewBox.minY ?? 0)) * pxPerUnitY;
const bandWidth = Math.max(24, Math.round(halfW * 2));
const bandHeight = Math.max(20, Math.round(halfH * 2));
const bandLeft = Math.min(1080 - bandWidth, Math.max(0, Math.round(centreX - bandWidth / 2)));
const bandTop = Math.min(1920 - bandHeight, Math.max(0, Math.round(centreY - bandHeight / 2)));
const MOUTH_CROP = `${bandWidth}:${bandHeight}:${bandLeft}:${bandTop}`;
/** The whole head, so the report can show the mouth delta is local and not the figure moving. */
const FACE_CROP = `${Math.round(figureWidth * 0.5)}:${Math.round(figureHeight * 0.22)}:${Math.max(0, Math.round(centreX - figureWidth * 0.25))}:${Math.max(0, Math.round(centreY - figureHeight * 0.17))}`;

const SPEECH_FRAME = 6; // 200 ms at 30 fps
const GAP_FRAME = 21; // 700 ms at 30 fps
const OVER = [{startMs: 0, endMs: 400}, {startMs: 900, endMs: 1300}];
const SHIFTED = [{startMs: 400, endMs: 900}, {startMs: 1300, endMs: 1700}];

const results = {mouthCrop: MOUTH_CROP, faceCrop: FACE_CROP, speechFrame: SPEECH_FRAME, gapFrame: GAP_FRAME};

// 1. Same frame, window over it vs not over it.
const overStill = still('mouth-over', SPEECH_FRAME, {...scene, speech: OVER});
const gapStill = still('mouth-gap', SPEECH_FRAME, {...scene, speech: SHIFTED});
results.mouthOverVsGap = compare(overStill, gapStill, MOUTH_CROP);
results.mouthChangedFraction = changedFraction(overStill, gapStill, MOUTH_CROP);
results.faceOverVsGap = compare(overStill, gapStill, FACE_CROP);

// 2. Same frame, two window sets, both covering it differently.
const shiftedStill = still('mouth-shifted', GAP_FRAME, {...scene, speech: OVER});
const shiftedOther = still('mouth-shifted-other', GAP_FRAME, {...scene, speech: SHIFTED});
results.shiftedMouth = compare(shiftedStill, shiftedOther, MOUTH_CROP);
results.shiftedChangedFraction = changedFraction(shiftedStill, shiftedOther, MOUTH_CROP);

// 3. No windows at all: the mouth must equal the closed one, not a sine.
const noSpeechStill = still('mouth-none', SPEECH_FRAME, {...scene, speech: undefined});
results.noSpeechVsGap = compare(noSpeechStill, gapStill, MOUTH_CROP);

// 4. The same two positions in a real encoded render, for the record.
const jobDir = process.env.MOUTH_JOB_DIR;
if (jobDir) {
  const video = path.join(jobDir, 'output.mp4');
  const jobProps = JSON.parse(readFileSync(path.join(jobDir, 'render-props.json'), 'utf8'));
  const jobScene = jobProps.storyboard.scenes[0];
  const encoded = (name, frame) => {
    const png = path.join(outDir, `${name}.png`);
    const result = spawnSync(
      'ffmpeg',
      ['-v', 'error', '-y', '-i', video, '-vf', `select=eq(n\\,${jobScene.startFrame + frame})`,
        '-fps_mode', 'passthrough', '-frames:v', '1', png],
      {encoding: 'utf8', timeout: 120000},
    );
    if (result.status !== 0) throw new Error(`${name}: ${result.stderr.slice(-300)}`);
    return png;
  };
  results.encodedSpeechVsGap = compare(encoded('encoded-speech', SPEECH_FRAME), encoded('encoded-gap', GAP_FRAME), MOUTH_CROP);
}

results.aperture = {
  overAtSpeechFrame: mouthOpenAt(OVER, SPEECH_FRAME, fps),
  shiftedAtSpeechFrame: mouthOpenAt(SHIFTED, SPEECH_FRAME, fps),
  noneAtSpeechFrame: mouthOpenAt([], SPEECH_FRAME, fps),
};

console.log(JSON.stringify(results, null, 2));

const failures = [];
// The mouth is a small feature, so a mean over its own tight crop is the honest number: a whole
// face is mostly unchanged skin, and averaging that in would hide a real mouth.
if (!(results.mouthOverVsGap.delta >= 0.5)) {
  failures.push(`the mouth does not differ between a window over the frame and one after it (delta ${results.mouthOverVsGap.delta})`);
}
if (!(results.mouthChangedFraction >= 0.02)) {
  failures.push(
    `too few mouth pixels changed to be a mouth (${(results.mouthChangedFraction * 100).toFixed(1)}% of the crop)`,
  );
}
if (results.mouthOverVsGap.psnr === Infinity) failures.push('the two stills are byte-identical, so the speech window had no effect');
if (!(results.shiftedMouth.delta >= 0.5)) {
  failures.push(`two window sets do not produce different mouths at one frame (delta ${results.shiftedMouth.delta})`);
}
if (!(results.noSpeechVsGap.delta < 0.5)) {
  failures.push(`a scene with no windows does not match the closed mouth (delta ${results.noSpeechVsGap.delta})`);
}

if (failures.length) {
  for (const failure of failures) console.log(`FAIL ${failure}`);
  process.exit(1);
}
console.log('PASS the mouth follows the measured windows, and stays closed without them');
