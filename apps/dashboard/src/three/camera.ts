import { Vector3 } from "three";

/**
 * World-unit orthographic framing. R3F's default orthographic frustum uses canvas pixels,
 * so a world-scale zoom on that frustum makes the entire room smaller than two pixels.
 * The rig applies `roomFrustum` explicitly on every resize instead.
 */

export const ROOM = { width: 16, depth: 12 } as const;

export const ISO_ELEVATION = Math.atan(1 / Math.sqrt(2));
export const ISO_AZIMUTH = Math.PI / 4;

/** OrbitControls measures polar angle down from Y, not up from the floor. */
export const ISO_POLAR = Math.PI / 2 - ISO_ELEVATION;
export const ROOM_TARGET_Y = 0.55;
export const ROOM_HEIGHT = 2.4;

/** Vertical extent about the room target, including the upper edge of the low walls. */
export const FRUSTUM_HALF =
  ((ROOM.width + ROOM.depth) * Math.sin(ISO_ELEVATION)) / (2 * Math.SQRT2) +
  Math.max(ROOM_TARGET_Y, ROOM_HEIGHT - ROOM_TARGET_Y) * Math.cos(ISO_ELEVATION);

/** Orbit envelope from `docs/STUDIO_3D.md` §5: ±35° azimuth, ±20° polar. */
export const POLAR_MIN = ISO_POLAR - (20 * Math.PI) / 180;
export const POLAR_MAX = ISO_POLAR + (20 * Math.PI) / 180;
export const AZIMUTH_MIN = ISO_AZIMUTH - (35 * Math.PI) / 180;
export const AZIMUTH_MAX = ISO_AZIMUTH + (35 * Math.PI) / 180;

/** Dolly envelope: 0.7×–1.6×, expressed as `zoom` rather than distance. */
export const DOLLY_MIN = 0.7;
export const DOLLY_MAX = 1.6;
export const ZOOM_BASE = 1;
export const ZOOM_MIN = ZOOM_BASE * DOLLY_MIN;
export const ZOOM_MAX = ZOOM_BASE * DOLLY_MAX;

export const FOCUS_MS = 400;

/** Fit both axes, including a little breathing room, at any canvas aspect ratio. */
export function roomFrustum(width: number, height: number) {
  const aspect = Math.max(1, width) / Math.max(1, height);
  const halfWidth = (ROOM.width + ROOM.depth) / (2 * Math.SQRT2);
  const halfHeight = Math.max(FRUSTUM_HALF, halfWidth / aspect) * 1.12;
  return {
    left: -halfHeight * aspect,
    right: halfHeight * aspect,
    top: halfHeight,
    bottom: -halfHeight,
  };
}

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
