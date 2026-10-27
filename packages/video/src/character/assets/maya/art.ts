import type {PaintRole} from '../../ids';
import type {LayerSpec, ShapeSpec} from '../../types';

/**
 * Maya — production character, rest pose.
 *
 * ## Coordinate system
 *
 * 600×760 character space, `minX = -100`, so the body is centred on x=200 and the
 * canvas extends to x=-100..500 for raised-arm gestures. Sole line y=740.
 *
 * ## Measured skeleton
 *
 * ```
 * crown       40        shoulder joint  143 / 257   (y 196)
 * chin       162        elbow           143 / 257   (y 340)
 * neck base  196        wrist           143 / 257   (y 464)
 * armpit     252        hip joint       172 / 228   (y 400)
 * waist      320        knee            172 / 228   (y 546)
 * hem        392        ankle           172 / 228   (y 698)
 *                       sole                            y 740
 * ```
 *
 * Head 96 wide, jacket 148 wide at the shoulder (1.54 head widths), 5.5 heads tall.
 * Stylised editorial proportion: correct enough to read as an adult, exaggerated
 * enough to survive a phone screen.
 *
 * ## The arm rule (this is the whole trick)
 *
 * The near upper arm is drawn BEHIND the jacket, with its centreline at x=143 and a
 * half-width of 17, so it spans x=126..160. The jacket spans x=126..274 at the
 * shoulder and x=146..254 at the armpit. Therefore:
 *
 * - at the shoulder the sleeve is flush with the garment edge, so the silhouette is
 *   continuous and nothing protrudes;
 * - below the armpit the sleeve emerges past the tucked waist, which is exactly where
 *   a real sleeve becomes visible in a three-quarter view;
 * - the sleeve's top edge (y=170) is entirely inside the jacket, so no socket, cap or
 *   rotation gap can ever be exposed.
 *
 * Drawing the arm in front instead forces a deltoid cap above the shoulder line,
 * which reads as a shoulder pad at every scale. That was the defect this rule fixes.
 *
 * ## Art rules
 *
 * - One light direction: key from upper screen-left. Near side lit, far side one
 *   shade darker. No rim light on the far side, because `facing: 'left'` mirrors the
 *   whole figure and a rim would land on the wrong edge.
 * - Hinge joints (elbow, knee) get a semicircular cap centred on the joint, so the
 *   silhouette is rotation-invariant and cannot open a notch when the limb bends.
 * - Limbs are separated from the torso by silhouette, not by outlines.
 *
 * Art is authored in rest space. The rig applies one matrix per bone.
 */

/** Semicircular cap centred on (x, y), bulging toward `dy`. */
const cap = (x: number, y: number, r: number, dy: 1 | -1): string =>
  `A${r} ${r} 0 0 ${dy < 0 ? 1 : 0} ${x + r} ${y}`;

/** Trousers thigh: hip socket to knee. Inner edge straight so the legs read as two masses. */
const thigh = (hipX: number, kneeX: number, fill: PaintRole): ShapeSpec[] => [
  {
    kind: 'path',
    d: `M${hipX - 26} 392
        C${hipX - 28} 438 ${kneeX - 23} 500 ${kneeX - 21} 546
        L${kneeX + 21} 546
        C${kneeX + 23} 500 ${hipX + 25} 440 ${hipX + 26} 392 Z`,
    fill,
  },
  {
    kind: 'path',
    // Outer seam: one stroke on the lit edge. Fabric drape without a texture map.
    d: `M${hipX + 13} 408 C${hipX + 17} 456 ${kneeX + 12} 508 ${kneeX + 10} 538`,
    stroke: 'trousersShade',
    strokeWidth: 2,
    fill: 'none',
    opacity: 0.4,
  },
];

/** Shin: knee cap, taper to the ankle, cuff break. */
const shin = (kneeX: number, ankleX: number, fill: PaintRole): ShapeSpec[] => [
  {
    kind: 'path',
    d: `M${kneeX - 18} 546 ${cap(kneeX, 546, 18, -1)}
        C${kneeX + 18} 594 ${ankleX + 14} 646 ${ankleX + 14} 700
        L${ankleX - 14} 700
        C${ankleX - 14} 646 ${kneeX - 18} 594 ${kneeX - 18} 546 Z`,
    fill,
  },
  {
    kind: 'path',
    d: `M${ankleX - 16.5} 676 L${ankleX + 16.5} 676 L${ankleX + 16} 700 L${ankleX - 16} 700 Z`,
    fill: 'trousersShade',
  },
];

/** Boot: heel block, instep, toe box. The toe leads the facing direction. */
const foot = (ankleX: number, toeX: number, fill: PaintRole = 'shoe'): ShapeSpec[] => [
  {
    kind: 'path',
    d: `M${ankleX - 18} 690
        L${ankleX + 17} 690
        C${ankleX + 20} 706 ${toeX - 16} 714 ${toeX} 722
        C${toeX + 12} 727 ${toeX + 10} 737 ${toeX - 4} 739
        L${ankleX - 21} 739
        C${ankleX - 26} 730 ${ankleX - 24} 706 ${ankleX - 18} 690 Z`,
    fill,
  },
  {
    kind: 'path',
    d: `M${ankleX - 21} 730 L${toeX - 3} 730 C${toeX + 6} 732 ${toeX + 5} 739 ${toeX - 4} 739 L${ankleX - 21} 739 Z`,
    fill: 'shoeSole',
  },
  {
    kind: 'path',
    // Ankle seam, so the boot is not read as an extension of the trouser.
    d: `M${ankleX - 18} 692 C${ankleX - 6} 699 ${ankleX + 6} 699 ${ankleX + 17} 692`,
    stroke: 'shoeSole',
    strokeWidth: 2.4,
    fill: 'none',
    opacity: 0.6,
  },
];

/** Upper sleeve. Top edge is hidden inside the jacket; width 34 tapering to 32. */
const upperArm = (x: number, tone: 'near' | 'far'): ShapeSpec[] => [
  {
    kind: 'path',
    d: `M${x - 14} 200 ${cap(x, 200, 14, -1)}
        C${x + 15} 234 ${x + 15} 292 ${x + 14} 344
        L${x - 14} 344
        C${x - 15} 292 ${x - 15} 234 ${x - 14} 200 Z`,
    fill: 'jacket',
  },
  {
    kind: 'path',
    // Core shadow along the inner edge of the sleeve. Follows the taper and stops at
    // the elbow; it is the only internal shading the upper arm needs.
    d: `M${x - 14} 204 C${x - 15} 240 ${x - 15} 296 ${x - 14} 340
        L${x - 6} 340 C${x - 7} 296 ${x - 7} 240 ${x - 6} 206 Z`,
    fill: tone === 'near' ? 'jacketShade' : 'ink',
    opacity: tone === 'near' ? 0.45 : 0.22,
  },
];

/** Forearm sleeve: elbow cap on the joint, taper to a shirt cuff. */
const foreArm = (x: number, tone: 'near' | 'far'): ShapeSpec[] => [
  {
    kind: 'path',
    d: `M${x - 13} 340 ${cap(x, 340, 13, -1)}
        C${x + 12} 382 ${x + 11} 424 ${x + 11} 464
        L${x - 11} 464
        C${x - 11} 424 ${x - 12} 382 ${x - 13} 340 Z`,
    fill: 'jacket',
  },
  {
    kind: 'path',
    // Inner-edge core shadow: flat fill, follows the taper, stops at the cuff.
    d: `M${x - 14} 356 C${x - 14} 392 ${x - 13} 424 ${x - 13} 452
        L${x - 4} 452 C${x - 4} 424 ${x - 5} 392 ${x - 5} 358 Z`,
    fill: tone === 'near' ? 'jacketShade' : 'ink',
    opacity: tone === 'near' ? 0.7 : 0.2,
  },
  {
    kind: 'path',
    d: `M${x - 11.5} 452 C${x - 4} 454 ${x + 4} 454 ${x + 11.5} 452 L${x + 11} 470 C${x + 4} 472 ${x - 4} 472 ${x - 11} 470 Z`,
    fill: 'shirt',
  },
];

export const MAYA_LAYERS: LayerSpec[] = [
  // --- far side: behind everything, one shade darker -------------------------------
  {id: 'far-upper-arm', bone: 'armUpperFar', z: 1, far: true, shapes: upperArm(272, 'far')},
  {id: 'far-forearm', bone: 'armForeFar', z: 2, far: true, shapes: foreArm(272, 'far')},
  {id: 'far-thigh', bone: 'thighFar', z: 3, far: true, shapes: thigh(232, 232, 'trousersShade')},
  {id: 'far-shin', bone: 'shinFar', z: 4, far: true, shapes: shin(232, 232, 'trousersShade')},
  {id: 'far-foot', bone: 'footFar', z: 5, far: true, shapes: foot(232, 280, 'shoeSole')},

  // --- hips and seat, behind the jacket hem ----------------------------------------
  {
    id: 'hips',
    bone: 'hips',
    z: 6,
    shapes: [
      {
        kind: 'path',
        d: 'M148 316 L252 316 L256 392 C256 406 252 412 244 412 L214 412 L200 402 L186 412 L156 412 C148 412 144 406 144 392 Z',
        fill: 'trousers',
      },
      {
        kind: 'path',
        d: 'M149 320 L251 320 L252 336 L148 336 Z',
        fill: 'trousersShade',
        opacity: 0.4,
      },
      {
        kind: 'path',
        // Crotch shadow. Without it two same-coloured trouser legs read as one column.
        d: 'M200 392 C204 400 204 410 200 418 C196 410 196 400 200 392 Z',
        fill: 'trousersShade',
        opacity: 0.75,
      },
    ],
  },

  // --- neck, behind head and torso -------------------------------------------------
  {
    id: 'neck',
    bone: 'neck',
    z: 7,
    shapes: [
      {
        kind: 'path',
        d: 'M185 138 L215 138 L217 186 C217 192 213 196 206 196 L194 196 C187 196 183 192 183 186 Z',
        fill: 'skin',
      },
      {
        kind: 'path',
        // Jaw shadow across the top of the neck: the one shape that separates a head
        // from a body without drawing a hard outline.
        d: 'M185 140 L215 140 L215 156 C206 164 194 164 185 156 Z',
        fill: 'skinShade',
        opacity: 0.8,
      },
    ],
  },

  // --- head group ------------------------------------------------------------------
  {
    id: 'hair-back',
    bone: 'head',
    z: 8,
    shapes: [
      {
        kind: 'path',
        // Bob: close at the crown, flaring at the jaw, tucked behind the ear.
        d: 'M201 26 C246 26 259 60 257 94 C256 118 252 140 244 154 C238 164 227 166 221 156 C233 140 237 116 235 92 C233 68 221 56 201 56 C181 56 169 68 167 92 C165 116 170 140 182 156 C176 166 165 164 159 154 C151 140 147 118 146 94 C144 60 157 26 201 26 Z',
        fill: 'hair',
      },
    ],
  },
  {
    id: 'head',
    bone: 'head',
    z: 20,
    shapes: [
      {
        kind: 'path',
        // Skull plus jaw in one silhouette: taller than wide, chin narrowed.
        d: 'M201 34 C230 34 249 56 249 86 C249 110 246 128 239 138 C230 152 216 162 201 162 C186 162 172 152 163 138 C156 128 153 110 153 86 C153 56 172 34 201 34 Z',
        fill: 'skin',
      },
      {
        kind: 'path',
        // Ear on the far side; the near ear is covered by the bob.
        d: 'M247 92 C255 90 259 97 258 105 C257 113 251 117 246 114 Z',
        fill: 'skinShade',
      },
    ],
  },
  {
    id: 'hair-front',
    bone: 'head',
    z: 22,
    shapes: [
      {
        kind: 'path',
        // Side-swept fringe: heavy over the near temple, lifting on the far side.
        // The asymmetry is the difference between "styled" and "helmet".
        d: 'M201 28 C236 28 253 50 252 76 C252 82 251 86 249 90 C246 68 236 58 220 55 C206 52 191 55 181 62 C172 68 167 76 165 84 C160 74 158 66 159 58 C162 36 178 28 201 28 Z',
        fill: 'hair',
      },
      {
        kind: 'path',
        // Crown shadow where the fringe meets the skull. A flat shape reads as a
        // styled part; a single stroke reads as a scratch at phone size.
        d: 'M209 30 C224 33 236 42 243 56 C236 46 224 39 208 38 Z',
        fill: 'hairShade',
        opacity: 0.75,
      },
    ],
  },
  {
    id: 'hair-strand',
    bone: 'hairStrand',
    z: 23,
    shapes: [
      {
        kind: 'path',
        d: 'M247 92 C253 104 254 122 251 140 C249 152 243 160 239 162 C243 146 245 124 243 100 Z',
        fill: 'hair',
      },
    ],
  },
  {
    id: 'hair-tip',
    bone: 'hairTip',
    z: 24,
    shapes: [
      {kind: 'path', d: 'M251 140 C249 152 243 161 239 163 C241 155 243 146 244 137 Z', fill: 'hairShade'},
    ],
  },

  // --- torso -----------------------------------------------------------------------
  {
    id: 'torso',
    bone: 'chest',
    z: 10,
    shapes: [
      // Jacket. 148 wide at the shoulder, tucked to 104 at the waist, 108 at the hem.
      // The shoulder is wider than the sleeve centreline, so the sleeve is covered at
      // the joint and emerges below the armpit. See "The arm rule" above.
      {
        kind: 'path',
        // Jacket body, one continuous silhouette from neck to armpit.
        //
        // The shoulder line slopes (190,154) → (156,164) → (128,178) → (116,196): a
        // 21-degree drop over 74 units, which is what an adult shoulder looks like.
        // It reaches x=116 because the sleeve behind it must be fully covered at the
        // joint; the sleeve only emerges below the armpit at (150,262).
        d: 'M190 154 C176 155 164 158 156 164 C148 168 138 173 130 180 C124 185 121 192 122 200 C124 220 133 242 146 258 C149 263 151 268 151 276 L150 320 L146 392 L254 392 L250 320 L249 276 C249 268 251 263 256 258 C272 240 284 216 284 196 C284 188 280 182 272 178 C264 172 252 168 244 164 C236 158 224 155 210 154 C206 172 194 172 190 154 Z',
        fill: 'jacket',
      },
      // Shirt in the open V: ends at the sternum, not at the waistband.
      {
        kind: 'path',
        d: 'M191 174 C193 198 196 230 199 266 L203 266 C206 230 209 198 211 174 C205 186 197 186 191 174 Z',
        fill: 'shirt',
      },
      // Far-side core shadow: one flat shape following the far edge.
      {
        kind: 'path',
        d: 'M244 164 C252 168 262 173 270 180 C276 185 279 192 278 200 C276 220 267 242 254 258 C251 263 249 268 249 276 L250 320 L254 392 L247 392 L244 320 L244 276 C244 268 246 263 251 258 C267 240 279 216 279 196 C279 190 276 185 270 181 C262 175 250 171 242 167 Z',
        fill: 'jacketShade',
      },
      // Armpit crease on the near side: gives the flat jacket a sleeve opening.
      {
        kind: 'path',
        d: 'M120 200 C132 224 143 246 149 264',
        stroke: 'jacketShade',
        strokeWidth: 2.4,
        fill: 'none',
        opacity: 0.5,
      },
      // Waist darts: two short strokes instead of a belt line.
      {
        kind: 'path',
        d: 'M168 306 C173 322 174 338 172 354',
        stroke: 'jacketShade',
        strokeWidth: 2,
        fill: 'none',
        opacity: 0.38,
      },
      {
        kind: 'path',
        d: 'M232 306 C227 322 226 338 228 354',
        stroke: 'jacketShade',
        strokeWidth: 2,
        fill: 'none',
        opacity: 0.38,
      },
      // Hem shadow: one flat band, not a belt.
      {
        kind: 'path',
        d: 'M147 386 L253 386 L254 392 L146 392 Z',
        fill: 'jacketShade',
        opacity: 0.6,
      },
    ],
  },
  {
    id: 'jacket-skirt',
    bone: 'spine',
    z: 11,
    shapes: [
      {
        kind: 'path',
        d: 'M152 300 L248 300 L250 320 L246 386 L154 386 L150 320 Z',
        fill: 'jacket',
      },
      {
        kind: 'path',
        // Hem shadow, on the skirt so it stays put when the chest turns.
        d: 'M150 380 L250 380 L251 386 L149 386 Z',
        fill: 'jacketShade',
        opacity: 0.55,
      },
    ],
  },
  {
    id: 'collar',
    bone: 'chest',
    z: 12,
    shapes: [
      // Near lapel: wider, because the body is turned away from the viewer.
      {
        kind: 'path',
        d: 'M191 174 C187 192 181 208 174 220 C184 225 194 234 200 248 C198 220 194 192 192 174 Z',
        fill: 'jacketLight',
      },
      // Far lapel: narrower, in shade.
      {
        kind: 'path',
        d: 'M211 174 C215 192 219 206 225 216 C217 222 209 232 205 246 C206 218 209 192 210 174 Z',
        fill: 'jacketShade',
      },
      // Shirt collar: two small points. A closed band here reads as a bib in close-up.
      {
        kind: 'path',
        d: 'M192 168 L201 186 L197 190 L190 176 Z',
        fill: 'shirt',
      },
      {
        kind: 'path',
        d: 'M210 168 L201 186 L205 190 L212 176 Z',
        fill: 'shirtShade',
      },
    ],
  },

  // --- near leg --------------------------------------------------------------------
  {id: 'near-thigh', bone: 'thighNear', z: 30, shapes: thigh(170, 170, 'trousers')},
  {id: 'near-shin', bone: 'shinNear', z: 31, shapes: shin(170, 170, 'trousers')},
  {id: 'near-foot', bone: 'footNear', z: 32, shapes: foot(170, 218)},

  // --- near arm: upper arm behind the jacket, forearm in front ----------------------
  {id: 'near-upper-arm', bone: 'armUpperNear', z: 34, shapes: upperArm(134, 'near')},
  {id: 'near-forearm', bone: 'armForeNear', z: 35, shapes: foreArm(134, 'near')},
];
