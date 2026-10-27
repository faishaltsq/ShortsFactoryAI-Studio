import type {StoryboardSpec} from '../types';

/**
 * Sample storyboard used for Phase 2 engine validation.
 * Timing: 30 FPS, 1080x1920, three scenes = 30s total.
 * narration.src points at public/sample/narration-test.mp3 (test audio).
 */
export const SAMPLE_STORYBOARD: StoryboardSpec = {
  id: 'sample-0001',
  language: 'id-ID',
  width: 1080,
  height: 1920,
  fps: 30,
  theme: {
    id: 'midnight',
    background: '#0b1020',
    backgroundAccent: '#141b34',
    primary: '#f5f7ff',
    secondary: '#9fb0d8',
    accent: '#ffb02e',
    fontHeading: '"Arial Black", "Segoe UI", sans-serif',
    fontBody: '"Segoe UI", Arial, sans-serif',
  },
  scenes: [
    {
      sceneId: 'scene-01',
      template: 'KineticTypography',
      segment: 'Tahukah kau #cahaya butuh 8 menit untuk tiba dari matahari?',
      assetRefs: [],
      text: [
        {id: 't1', text: 'Tahukah kau cahaya butuh 8 menit untuk tiba dari matahari?', style: {role: 'title'}},
      ],
      animation: {preset: 'wordByWord', durationInFrames: 24},
      transition: {type: 'fade', durationInFrames: 10},
      startFrame: 0,
      durationInFrames: 300,
      data: {highlightIndex: 6},
    },
    {
      sceneId: 'scene-02',
      template: 'EducationalExplainer',
      segment: 'Sinar yang kau lihat sekarang adalah masa lalu. Jarak matahari ke bumi 149.6 juta kilometer.',
      assetRefs: [],
      text: [
        {id: 't2', text: 'Sinar Matahari Adalah Masa Lalu', style: {role: 'title'}},
        {id: 'k2', text: 'Fakta Angkasa', style: {role: 'kicker'}},
      ],
      animation: {preset: 'slideUp', durationInFrames: 24},
      transition: {type: 'slideUp', durationInFrames: 12},
      startFrame: 300,
      durationInFrames: 330,
      data: {
        bullets: [
          'Cahaya merentang 149,6 juta kilometer.',
          'Butuh 8 menit 20 detik sampai ke retina.',
          'Yang kau lihat selalu terjadi di masa lalu.',
        ],
      },
    },
    {
      sceneId: 'scene-03',
      template: 'KineticTypography',
      segment: 'Jadi setiap tatapan ke langit adalah perjalanan #menembus waktu.',
      assetRefs: [],
      text: [{id: 't3', text: 'Perjalanan menembus waktu', style: {role: 'title'}}],
      animation: {preset: 'popIn', durationInFrames: 24},
      transition: {type: 'fade', durationInFrames: 12},
      startFrame: 630,
      durationInFrames: 270,
      data: {highlightIndex: 4},
    },
    {
      sceneId: 'scene-04',
      template: 'IllustratedStory',
      segment: 'Malam ini, lihat bulan. Cahayanya butuh satu koma tiga detik untuk sampai ke matamu.',
      assetRefs: [],
      text: [{id: 't4', text: '1,3 Detik dari Bulan', style: {role: 'title'}}],
      animation: {preset: 'slideUp', durationInFrames: 20},
      transition: {type: 'fade', durationInFrames: 12},
      startFrame: 900,
      durationInFrames: 270,
      data: {
        title: '1,3 Detik dari Bulan',
        caption: 'Cahaya bulan selalu terlambat',
        setting: 'ocean',
        timeOfDay: 'night',
        actors: [{pose: 'stand', x: 0.68, ground: 0.88, scale: 1.05, facing: 'right', tone: 'secondary', silhouette: false}],
        props: [{kind: 'moon', x: 0.5, y: 0.2, scale: 1.4}],
        fx: ['stars', 'vignette'],
        shots: [{framing: 'wide', camera: 'pullOut', weight: 1.2}, {framing: 'close', camera: 'handheld', weight: 1}],
      },
    },
  ],
  subtitles: [
    {id: 's1', text: 'Tahukah kau, cahaya butuh 8 menit', startMs: 0, endMs: 2600},
    {id: 's2', text: 'untuk tiba dari matahari?', startMs: 2600, endMs: 5000},
    {id: 's3', text: 'Sinar yang kau lihat sekarang', startMs: 5000, endMs: 7800},
    {id: 's4', text: 'adalah masa lalu.', startMs: 7800, endMs: 10500},
    {id: 's5', text: 'Jaraknya 149,6 juta kilometer.', startMs: 10500, endMs: 14500},
    {id: 's6', text: 'Setiap tatapan ke langit', startMs: 15000, endMs: 18500},
    {id: 's7', text: 'adalah perjalanan menembus waktu.', startMs: 18500, endMs: 24000},
    {id: 's8', text: 'Cahayanya butuh 1,3 detik.', startMs: 24000, endMs: 29000},
  ],
  narration: {src: 'sample/narration-test.mp3', durationMs: 30000, volume: 1},
  watermark: {text: 'Shorts Factory', opacity: 0.5},
};
