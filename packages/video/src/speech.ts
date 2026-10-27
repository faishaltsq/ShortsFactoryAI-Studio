/**
 * Speech envelope: measured word windows → a mouth that opens on the voice.
 *
 * ## Why this module exists
 *
 * The rig used to open the mouth from `preset === 'talk'` with
 * `sin(local / 3.1) · 0.55 + sin(local / 1.7) · 0.3`. That is a synthetic clock: it moves the
 * mouth, but never with the voice, and it is indistinguishable from lip sync only if nobody
 * listens. The real timing is measured — SAPI reports a boundary per word, `tts.py` rebases them
 * onto the trimmed scene, and `audio.json` carries them per scene as `speech`.
 *
 * ## Envelope
 *
 * A window is `{startMs, endMs}` in scene-local milliseconds, the same clock as the scene's
 * subtitles and its `motion.beats[].atFrame`. The mouth ramps up over `ATTACK_MS` from `startMs`,
 * holds at full for the body of the word, and ramps down over `RELEASE_MS` *starting at* `endMs` —
 * so the mouth is still partly open on the frame after a word ends instead of snapping shut. Both
 * ramps are clamped to half the window so a 60 ms word still opens and closes inside its own span.
 *
 * ## Seekability
 *
 * `mouthOpenAt` is a pure function of `(windows, frame, fps)`. Nothing accumulates across frames,
 * so Remotion rendering frames out of order produces the same mouth for the same frame number.
 *
 * ## No speech means no mouth
 *
 * An empty window list returns 0 for every frame. It does **not** fall back to a clock: a storyboard
 * written before the boundaries were persisted (or the donor fixture, which has none) renders a
 * closed mouth. A closed mouth on unmeasured audio is honest; a sine is not.
 */

export interface SpeechWindow {
  /** Scene-local, inclusive. */
  startMs: number;
  /** Scene-local, exclusive. */
  endMs: number;
}

/** Ramp up from silence to full aperture. */
export const ATTACK_MS = 40;
/** Ramp back down to silence, starting at the window's end. */
export const RELEASE_MS = 70;

export interface SpeechEnvelope {
  /** Index of the window covering this frame, or -1 in a gap. */
  windowIndex: number;
  /** 0..1 aperture. 0 in a gap and before/after the whole scene's speech. */
  weight: number;
}

const clamp01 = (value: number): number =>
  Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;

/**
 * Resolve the envelope for one frame.
 *
 * `fps` converts the frame to the milliseconds the windows are measured in. A frame whose time
 * falls inside a window's release tail is attributed to that window, so `windowIndex` names the
 * word the mouth is still leaving.
 */
export const speechAt = (
  windows: readonly SpeechWindow[],
  frame: number,
  fps: number,
): SpeechEnvelope => {
  if (windows.length === 0 || fps <= 0 || !Number.isFinite(frame)) {
    return {windowIndex: -1, weight: 0};
  }
  const ms = (frame / fps) * 1000;

  for (const [index, window] of windows.entries()) {
    const length = window.endMs - window.startMs;
    if (length <= 0) continue;
    // Both ramps are clamped to half the window, so a short word is a triangle inside its own span
    // rather than a mouth that opens after the word has finished.
    const attack = Math.min(ATTACK_MS, length / 2);
    const release = Math.min(RELEASE_MS, length / 2);
    if (ms < window.startMs || ms >= window.endMs + release) continue;

    if (ms < window.startMs + attack) {
      return {windowIndex: index, weight: clamp01((ms - window.startMs) / attack)};
    }
    if (ms < window.endMs) {
      return {windowIndex: index, weight: 1};
    }
    return {windowIndex: index, weight: clamp01(1 - (ms - window.endMs) / release)};
  }
  return {windowIndex: -1, weight: 0};
};

/**
 * The mouth aperture at one frame. This is the number the rig multiplies into `mouthOpen`;
 * `withSpeech` in `character/expressions.ts` still owns how an expression shapes the mouth, so an
 * angry character speaking and a happy one speaking read differently at the same aperture.
 */
export const mouthOpenAt = (
  windows: readonly SpeechWindow[],
  frame: number,
  fps: number,
): number => speechAt(windows, frame, fps).weight;
