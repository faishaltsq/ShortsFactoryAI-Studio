import { OrthographicCamera, Vector3 } from "three";
import {
  AZIMUTH_MAX,
  AZIMUTH_MIN,
  ISO_AZIMUTH,
  ISO_ELEVATION,
  ISO_POLAR,
  POLAR_MAX,
  POLAR_MIN,
  ROOM,
  ROOM_HEIGHT,
  ROOM_TARGET_Y,
  ZOOM_BASE,
  ZOOM_MAX,
  ZOOM_MIN,
  easeInOutCubic,
  isoDirection,
  roomFrustum,
} from "./camera";

/** The rig is one decision; a wrong elevation is the difference between iso and dimetric. */
test("the rig is true isometric: equal foreshortening, 45 degree azimuth", () => {
  expect(ISO_ELEVATION).toBeCloseTo(Math.atan(1 / Math.SQRT2), 10);
  expect((ISO_ELEVATION * 180) / Math.PI).toBeCloseTo(35.264389, 5);
  expect(ISO_AZIMUTH).toBeCloseTo(Math.PI / 4, 12);
});

test("the orbit and dolly envelopes are symmetric around the isometric pose", () => {
  const polarFromDirection = Math.acos(new Vector3(...isoDirection()).normalize().y);
  expect(polarFromDirection).toBeCloseTo(ISO_POLAR, 12);
  expect(POLAR_MAX - polarFromDirection).toBeCloseTo((20 * Math.PI) / 180, 12);
  expect(polarFromDirection - POLAR_MIN).toBeCloseTo((20 * Math.PI) / 180, 12);
  expect(AZIMUTH_MAX - ISO_AZIMUTH).toBeCloseTo((35 * Math.PI) / 180, 12);
  expect(ISO_AZIMUTH - AZIMUTH_MIN).toBeCloseTo((35 * Math.PI) / 180, 12);
  expect(ZOOM_MAX / ZOOM_BASE).toBeCloseTo(1.6, 12);
  expect(ZOOM_MIN / ZOOM_BASE).toBeCloseTo(0.7, 12);
});

test.each([
  { width: 1120, height: 620, minCrewPixels: 38 },
  { width: 820, height: 520, minCrewPixels: 34 },
  { width: 390, height: 460, minCrewPixels: 21 },
  { width: 320, height: 360, minCrewPixels: 18 },
])("the real orthographic projection fills a $width × $height canvas", ({ width, height, minCrewPixels }) => {
  // Start with R3F's actual pixel-sized frustum, then apply the same fit used by IsoRig.
  // The former zoom (~0.08) on this default frustum made the 20-unit room < 2 pixels wide.
  const camera = new OrthographicCamera(-width / 2, width / 2, height / 2, -height / 2, 0.1, 200);
  Object.assign(camera, roomFrustum(width, height));
  camera.zoom = ZOOM_BASE;
  const target = new Vector3(0, ROOM_TARGET_Y, 0);
  camera.position.copy(new Vector3(...isoDirection()).multiplyScalar(30).add(target));
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);

  const projected: Vector3[] = [];
  for (const x of [-ROOM.width / 2, ROOM.width / 2]) {
    for (const z of [-ROOM.depth / 2, ROOM.depth / 2]) {
      for (const y of [0, ROOM_HEIGHT]) {
        const point = new Vector3(x, y, z).project(camera);
        expect(Math.abs(point.x)).toBeLessThan(1);
        expect(Math.abs(point.y)).toBeLessThan(1);
        projected.push(point);
      }
    }
  }
  const roomWidthPixels =
    (Math.max(...projected.map((point) => point.x)) - Math.min(...projected.map((point) => point.x))) * width / 2;
  const roomHeightPixels =
    (Math.max(...projected.map((point) => point.y)) - Math.min(...projected.map((point) => point.y))) * height / 2;
  expect(Math.max(roomWidthPixels / width, roomHeightPixels / height)).toBeGreaterThan(0.8);
  expect(roomWidthPixels).toBeGreaterThan(width * 0.6);

  const feet = new Vector3(0, 0, 0).project(camera);
  const head = new Vector3(0, 1.55, 0).project(camera);
  const crewHeightPixels = Math.abs(head.y - feet.y) * height / 2;
  expect(crewHeightPixels).toBeGreaterThan(minCrewPixels);

  camera.zoom = ZOOM_MAX;
  camera.updateProjectionMatrix();
  const focusedFeet = new Vector3(0, 0, 0).project(camera);
  const focusedHead = new Vector3(0, 1.55, 0).project(camera);
  expect(Math.abs(focusedHead.y - focusedFeet.y) * height / 2).toBeCloseTo(crewHeightPixels * 1.6, 8);
});

test("easing is a pure function of t and lands exactly on 0 and 1", () => {
  expect(easeInOutCubic(0)).toBe(0);
  expect(easeInOutCubic(1)).toBe(1);
  expect(easeInOutCubic(0.5)).toBeCloseTo(0.5, 12);
  expect(easeInOutCubic(0.25)).toBeCloseTo(0.0625, 12);
  expect(easeInOutCubic(0.75)).toBeCloseTo(0.9375, 12);
});

