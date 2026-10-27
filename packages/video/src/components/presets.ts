import {Easing, interpolate, spring} from 'remotion';

export interface AnimateArgs {
  frame: number;
  fps: number;
  durationInFrames: number;
  intensity?: number;
}

export const popIn = ({frame, fps, durationInFrames, intensity = 1}: AnimateArgs) => {
  const s = spring({frame, fps, config: {damping: 12 + 6 * (1 - intensity), stiffness: 160}});
  return {opacity: interpolate(frame, [0, Math.max(1, durationInFrames * 0.35)], [0, 1], {extrapolateRight: 'clamp'}), transform: `scale(${interpolate(s, [0, 1], [0.6, 1])})`};
};

export const slideUp = ({frame, fps, durationInFrames, intensity = 1}: AnimateArgs) => {
  const s = spring({frame, fps, config: {damping: 20, stiffness: 120}});
  return {opacity: interpolate(frame, [0, Math.max(1, durationInFrames * 0.3)], [0, 1], {extrapolateRight: 'clamp'}), transform: `translateY(${interpolate(s, [0, 1], [80 * intensity, 0])}px)`};
};

export const wipeIn = ({frame, durationInFrames}: AnimateArgs) => ({
  opacity: interpolate(frame, [0, Math.max(1, durationInFrames * 0.4)], [0, 1], {extrapolateRight: 'clamp'}),
  clipPath: `inset(0 ${interpolate(frame, [0, durationInFrames * 0.5], [100, 0], {
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  })}% 0 0)`,
});

export const fadeIn = ({frame, durationInFrames}: AnimateArgs) => ({
  opacity: interpolate(frame, [0, Math.max(1, durationInFrames * 0.5)], [0, 1], {extrapolateRight: 'clamp'}),
});

export const PRESETS = {popIn, slideUp, wipeIn, fadeIn, wordByWord: fadeIn, countUp: fadeIn};
