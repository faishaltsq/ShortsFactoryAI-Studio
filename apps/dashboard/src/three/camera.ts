import { Vector3 } from "three";

/**
 * The isometric rig, in numbers, so the scene and its test agree.
 *
 * True isometric means the three axes are foreshortened equally: elevation `atan(1/√2)` above the
 * floor plane and azimuth 45°. That is the only pair that makes the room's square grid project to
 * 120° rhombi; an "isometric-looking" 35°/30° pair is a different (dimetric) projection.
 *
 * The camera is orthographic, so distance changes nothing about the framing. Instead of a fov we
 * fit a frustum: the room is 16 × 12, and its axis-aligned bounding box projects to a rectangle
 * whose extent is bounded by the half-diagonal `sqrt(16² + 12²) / 2 = 10` on both screen axes.
 * A half-height of 10 / cos(35.264°) ≈ 12.25 covers the diagonal in the vertical screen axis, and
 * `zoom` < 1 adds margin. The frustum is therefore a fixed half-height of 12.5 with `1 / zoom`
 * clamped to the dolly envelope below: no resizing event can clip the floor.
 */

export const ROOM = { width: 16, depth: 12 } as const;

export const ISO_ELEVATION = Math.atan(1 / Math.sqrt(2));
export const ISO_AZIMUTH = Math.PI / 4;

/** Half-extent of the room's projection onto either screen axis before the zoom margin. */
export const FRUSTUM_HALF = Math.hypot(ROOM.width, ROOM.depth) / 2 / Math.cos(ISO_ELEVATION);

/** Orbit envelope from `docs/STUDIO_3D.md` §5: ±35° azimuth, ±20° polar. */
export const POLAR_MIN = ISO_ELEVATION - (20 * Math.PI) / 180;
export const POLAR_MAX = ISO_ELEVATION + (20 * Math.PI) / 180;
export const AZIMUTH_MIN = ISO_AZIMUTH - (35 * Math.PI) / 180;
export const AZIMUTH_MAX = ISO_AZIMUTH + (35 * Math.PI) / 180;

/** Dolly envelope: 0.7×–1.6×, expressed as `zoom` rather than distance. */
export const DOLLY_MIN = 0.7;
export const DOLLY_MAX = 1.6;
export const ZOOM_BASE = 1 / (FRUSTUM_HALF * 1.02);
export const ZOOM_MIN = ZOOM_BASE * DOLLY_MIN;
export const ZOOM_MAX = ZOOM_BASE * DOLLY_MAX;

export const FOCUS_MS = 400;

/** Where the camera sits relative to its target. Unit direction × any distance is equivalent. */
export function isoDirection(): [number, number, number] {
  const horizontal = Math.cos(ISO_ELEVATION);
  return [
    horizontal * Math.sin(ISO_AZIMUTH),
    Math.sin(ISO_ELEVATION),
    horizontal * Math.cos(ISO_AZIMUTH),
  ];
}

export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

/**
 * Position at progress `t` of a focus tween. Pure in `t`, so a dropped frame or a re-render
 * changes nothing: the camera is a function of elapsed time since its own start, not an
 * accumulation of per-frame deltas.
 */
export function tweenPosition(
  from: Vector3,
  to: Vector3,
  t: number,
): { x: number; y: number; z: number } {
  const eased = easeInOutCubic(Math.min(1, Math.max(0, t)));
  return {
    x: from.x + (to.x - from.x) * eased,
    y: from.y + (to.y - from.y) * eased,
    z: from.z + (to.z - from.z) * eased,
  };
}
