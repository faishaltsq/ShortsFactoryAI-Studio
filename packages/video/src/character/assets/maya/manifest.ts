import type {CharacterManifest} from '../../types';
import {MAYA_LAYERS} from './art';

/**
 * Maya — versioned character manifest.
 *
 * Character space is 400×760 with the sole line at y=740. Angles follow SVG
 * convention: positive rotates clockwise on screen. Maya faces screen-right, so a
 * forward limb raise is negative and a knee bend (heel travelling back) is positive.
 */
export const MAYA: CharacterManifest = {
  id: 'maya',
  version: '1.0.0',
  displayName: 'Maya',
  artStyle: 'editorial-vector',
  // 520 wide, centred on the body: a 400-unit box clips a raised arm, and an arm
  // that leaves the canvas is not a rendering bug you can art around.
  // 760 wide: a fully extended arm reaches 264 units from a shoulder at x=134/272,
  // so 180 units of side clearance is the minimum that does not clip a gesture.
  viewBox: {minX: -180, width: 760, height: 760},
  groundY: 740,
  poses: ['stand', 'point', 'reach', 'walk', 'lookUp', 'shrug', 'sit'],
  expressions: ['neutral', 'curious', 'happy', 'surprised', 'concerned', 'determined', 'thinking', 'sad'],
  gestures: ['none', 'pointForward', 'openPalm', 'bothOpen', 'wave', 'think', 'shrug'],
  layers: MAYA_LAYERS,
  rig: {
    bones: [
      // Joint y-values are the art's joint y-values. Moving one without the other
      // opens a seam at that joint, so this table and art.ts are one unit.
      // Elbow and knee are hinge joints: their limits are one-sided, so an angle on
      // the wrong side is clamped to ~0 and the limb renders straight. Elbows bend
      // forward (negative), knees bend backward (positive).
      //
      // The near arm is drawn behind the jacket (layer z=9) with its centreline at
      // x=143 and half-width 17. The jacket spans 126..274 at the shoulder, so the
      // sleeve is covered at the joint and emerges below the armpit. See art.ts.
      // Crown 40 · chin 162 · shoulder 196 · elbow 340 · wrist 464
      // hip 400 · knee 546 · ankle 698 · sole 740
      {id: 'root', parent: null, pivot: {x: 200, y: 740}},
      {id: 'hips', parent: 'root', pivot: {x: 200, y: 400}, limits: {min: -12, max: 12}},
      {id: 'spine', parent: 'hips', pivot: {x: 200, y: 348}, limits: {min: -14, max: 16}},
      {id: 'chest', parent: 'spine', pivot: {x: 200, y: 292}, limits: {min: -12, max: 14}},
      {id: 'neck', parent: 'chest', pivot: {x: 200, y: 198}, limits: {min: -16, max: 18}},
      {id: 'head', parent: 'neck', pivot: {x: 200, y: 156}, limits: {min: -24, max: 22}},
      {id: 'clavicleNear', parent: 'chest', pivot: {x: 158, y: 194}, limits: {min: -14, max: 14}},
      {id: 'armUpperNear', parent: 'clavicleNear', pivot: {x: 134, y: 200}, limits: {min: -172, max: 152}},
      {id: 'armForeNear', parent: 'armUpperNear', pivot: {x: 134, y: 340}, limits: {min: -155, max: 155}},
      {id: 'handNear', parent: 'armForeNear', pivot: {x: 134, y: 464}, limits: {min: -58, max: 58}},
      {id: 'clavicleFar', parent: 'chest', pivot: {x: 242, y: 194}, limits: {min: -14, max: 14}},
      {id: 'armUpperFar', parent: 'clavicleFar', pivot: {x: 272, y: 200}, limits: {min: -152, max: 172}},
      {id: 'armForeFar', parent: 'armUpperFar', pivot: {x: 272, y: 340}, limits: {min: -155, max: 155}},
      {id: 'handFar', parent: 'armForeFar', pivot: {x: 272, y: 464}, limits: {min: -58, max: 58}},
      {id: 'thighNear', parent: 'hips', pivot: {x: 170, y: 400}, limits: {min: -66, max: 34}},
      {id: 'shinNear', parent: 'thighNear', pivot: {x: 170, y: 546}, limits: {min: 0, max: 120}},
      {id: 'footNear', parent: 'shinNear', pivot: {x: 170, y: 698}, limits: {min: -30, max: 28}},
      {id: 'thighFar', parent: 'hips', pivot: {x: 232, y: 400}, limits: {min: -66, max: 34}},
      {id: 'shinFar', parent: 'thighFar', pivot: {x: 232, y: 546}, limits: {min: 0, max: 120}},
      {id: 'footFar', parent: 'shinFar', pivot: {x: 232, y: 698}, limits: {min: -30, max: 28}},
      {id: 'hairStrand', parent: 'head', pivot: {x: 246, y: 92}, limits: {min: -22, max: 22}},
      {id: 'hairTip', parent: 'hairStrand', pivot: {x: 250, y: 138}, limits: {min: -32, max: 32}},
    ],
  },
  face: {anchor: {x: 201, y: 96}, width: 92, height: 132, turn: 6},
  // zFar sits just under the near arm: a far hand is behind the body when it hangs
  // at the hip, but in front of it when the arm extends past the silhouette.
  hands: {length: 44, width: 26, zNear: 35.5, zFar: 33.5},
  palette: {
    skin: '#E8B58F',
    skinShade: '#C98F68',
    hair: '#3A2A2E',
    hairShade: '#241A1D',
    jacket: '#2E6E63',
    jacketShade: '#28635A',
    jacketLight: '#3D8A7C',
    shirt: '#F2E7D5',
    shirtShade: '#D3C3AC',
    trousers: '#2B3550',
    trousersShade: '#1D2438',
    shoe: '#4A2F27',
    shoeSole: '#2A1A16',
    ink: '#1A1418',
    accent: '#F2A63B',
  },
  provenance: {
    author: 'ShortsFactoryAI character engine',
    source: 'packages/video/src/character/assets/maya',
    createdAt: '2026-10-24',
  },
  license: {
    id: 'project-original',
    attribution: 'Original vector art authored for this project; no third-party assets.',
  },
};
