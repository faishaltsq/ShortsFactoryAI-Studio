import type {IllustrationShot} from '../scene-data';

export interface ShotSpan {
  shot: IllustrationShot;
  index: number;
  start: number;
  duration: number;
  local: number;
}

const MIN_SHOT_FRAMES = 12;

/** Split a scene into weighted shots. Deterministic, gap-free, and never shorter than 12 frames. */
export const shotAt = (
  shots: IllustrationShot[],
  frame: number,
  durationInFrames: number,
): ShotSpan => {
  if (shots.length === 0) throw new Error('IllustratedStory requires at least one shot');
  const usable = durationInFrames >= MIN_SHOT_FRAMES * shots.length ? shots : [shots[0]];
  const weights = usable.map((s) => (s.weight > 0 ? s.weight : 1));
  const total = weights.reduce((a, b) => a + b, 0);
  const spans = weights.map((w) => Math.max(MIN_SHOT_FRAMES, Math.floor((w / total) * durationInFrames)));
  const drift = spans.reduce((a, b) => a + b, 0) - durationInFrames;
  spans[spans.length - 1] = Math.max(MIN_SHOT_FRAMES, spans[spans.length - 1] - drift);

  let start = 0;
  for (let i = 0; i < spans.length; i += 1) {
    const end = start + spans[i];
    if (frame < end || i === spans.length - 1) {
      return {
        shot: usable[i],
        index: i,
        start,
        duration: spans[i],
        local: Math.min(spans[i] - 1, Math.max(0, frame - start)),
      };
    }
    start = end;
  }
  throw new Error('shot lookup failed');
};

export const FRAMING_SCALE: Record<IllustrationShot['framing'], number> = {
  // Kept deliberately gentle: the stage anchors at the subject's ground line, so a
  // larger factor pushes the character's head into the title band.
  wide: 1,
  medium: 1.12,
  close: 1.3,
};
