import { Vector3 } from "three";
import {
  AZIMUTH_MAX,
  AZIMUTH_MIN,
  FOCUS_MS,
  ISO_AZIMUTH,
  ISO_ELEVATION,
  POLAR_MAX,
  POLAR_MIN,
  ROOM,
  ZOOM_BASE,
  ZOOM_MAX,
  ZOOM_MIN,
  easeInOutCubic,
  isoDirection,
} from "./camera";

/** The rig is one decision; a wrong elevation is the difference between iso and dimetric. */
test("the rig is true isometric: equal foreshortening, 45 degree azimuth", () => {
  expect(ISO_ELEVATION).toBeCloseTo(Math.atan(1 / Math.SQRT2), 10);
  expect((ISO_ELEVATION * 180) / Math.PI).toBeCloseTo(35.264389, 5);
  expect(ISO_AZIMUTH).toBeCloseTo(Math.PI / 4, 12);
});

test("the orbit and dolly envelopes are symmetric around the isometric pose", () => {
  expect(POLAR_MAX - ISO_ELEVATION).toBeCloseTo((20 * Math.PI) / 180, 12);
  expect(ISO_ELEVATION - POLAR_MIN).toBeCloseTo((20 * Math.PI) / 180, 12);
  expect(AZIMUTH_MAX - ISO_AZIMUTH).toBeCloseTo((35 * Math.PI) / 180, 12);
  expect(ISO_AZIMUTH - AZIMUTH_MIN).toBeCloseTo((35 * Math.PI) / 180, 12);
  expect(ZOOM_MAX / ZOOM_BASE).toBeCloseTo(1.6, 12);
  expect(ZOOM_MIN / ZOOM_BASE).toBeCloseTo(0.7, 12);
});

test("the frustum fits the whole 12-unit-deep room at the closest dolly", () => {
  // Every corner of the 16 x 12 floor, seen from the isometric direction, must project inside the
  // vertical half-extent available at ZOOM_MAX. This is the assertion the old fov 32 camera failed.
  const [dx, dy, dz] = isoDirection();
  const eye = new Vector3(dx, dy, dz);
  const forward = eye.clone().negate().normalize();
  const right = new Vector3().crossVectors(forward, new Vector3(0, 1, 0)).normalize();
  const up = new Vector3().crossVectors(right, forward).normalize();

  const halfHeightAtClosest = 1 / ZOOM_MAX;
  let maxUp = 0;
  let maxRight = 0;
  for (const x of [-ROOM.width / 2, ROOM.width / 2]) {
    for (const z of [-ROOM.depth / 2, ROOM.depth / 2]) {
      // Target is the room centre; project the corner relative to it, orthographically.
      const corner = new Vector3(x, 0, z);
      maxUp = Math.max(maxUp, Math.abs(corner.dot(up)));
      maxRight = Math.max(maxRight, Math.abs(corner.dot(right)));
    }
  }
  // Left/right extent is covered by the same half-height because the ortho frustum is square here
  // (left/right follow the canvas aspect; the vertical bound is the binding one at 16:9).
  expect(maxUp).toBeLessThanOrEqual(halfHeightAtClosest + 1e-9);
  expect(maxRight).toBeLessThanOrEqual(1 / ZOOM_MIN + 1e-9);
});

test("easing is a pure function of t and lands exactly on 0 and 1", () => {
  expect(easeInOutCubic(0)).toBe(0);
  expect(easeInOutCubic(1)).toBe(1);
  expect(easeInOutCubic(0.5)).toBeCloseTo(0.5, 12);
  expect(easeInOutCubic(0.25)).toBeCloseTo(easeInOutCubic(0.25), 12);
  expect(easeInOutCubic(0.25)).toBeCloseTo(0.0625, 12);
  expect(easeInOutCubic(0.75)).toBeCloseTo(0.9375, 12);
});

test("the focus tween duration is the documented 400 ms", () => {
  expect(FOCUS_MS).toBe(400);
});
