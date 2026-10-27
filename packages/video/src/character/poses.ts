import type {PoseId} from './ids';
import {solveLeg} from './rig';
import type {BoneId} from './ids';
import type {PoseTarget, Point, ResolvedPose} from './types';

/**
 * Pose library. Angles are rest-relative degrees.
 *
 * Maya faces screen-right. SVG rotation is clockwise on screen, so for a limb
 * hanging down: negative swings it forward (toward the face direction) and
 * positive swings it back. Knees and elbows only bend one way, which the rig's
 * joint limits also enforce.
 */
export const POSES: Record<PoseId, PoseTarget> = {
  // Contraposto, not symmetry: weight on the far leg, near knee soft, one shoulder
  // dropped. A dead-centre figure reads as a mannequin at any size.
  stand: {
    angles: {
      hips: -2,
      spine: 1.5,
      chest: -1,
      neck: 1,
      head: 2,
      clavicleNear: 1,
      armUpperNear: -7,
      armForeNear: -11,
      handNear: 6,
      clavicleFar: -1,
      armUpperFar: 5,
      armForeFar: -9,
      handFar: 2,
      thighNear: -3,
      shinNear: 4,
      footNear: -2,
      thighFar: 2,
      shinFar: 2,
      footFar: 1,
      hairStrand: 2,
      hairTip: 3,
    },
    hipsOffset: {x: 2, y: 0},
    lean: 0,
    hands: {near: 'relaxed', far: 'relaxed'},
    contact: 'both',
    feet: {near: {x: 172, y: 698}, far: {x: 232, y: 698}},
  },

  // Arm at shoulder height, elbow almost straight, finger extended. Chest opens
  // first and the head leads the gesture, so the whole body points, not just the arm.
  point: {
    angles: {
      hips: -1,
      spine: -3,
      chest: -5,
      neck: -2,
      head: -4,
      clavicleNear: -5,
      armUpperNear: -64,
      armForeNear: -18,
      handNear: -6,
      clavicleFar: 2,
      armUpperFar: 9,
      armForeFar: -14,
      handFar: 3,
      thighNear: -5,
      shinNear: 6,
      footNear: -3,
      thighFar: 4,
      shinFar: 3,
      footFar: 1,
      hairStrand: -3,
      hairTip: -4,
    },
    hipsOffset: {x: -1, y: 0},
    lean: -1.5,
    hands: {near: 'point', far: 'relaxed'},
    contact: 'both',
    feet: {near: {x: 168, y: 698}, far: {x: 238, y: 698}},
  },

  // Reaching up and forward, ribcage lifted, back foot loaded. Reads as effort
  // because the pelvis pushes away from the hand.
  reach: {
    angles: {
      hips: 2,
      spine: -4,
      chest: -6,
      neck: -4,
      head: -6,
      clavicleNear: -10,
      // Up and out, forearm nearly straight. A vertical reach puts the hand behind the head in
      // three-quarter view, which reads as a broken arm rather than a reach.
      // Raised out to the near side (+112), forearm nearly straight. A negative raise
      // would sweep the near arm across the head in this three-quarter turn.
      armUpperNear: 138,
      armForeNear: 6,
      handNear: -8,
      clavicleFar: 3,
      armUpperFar: 16,
      armForeFar: -22,
      handFar: 4,
      thighNear: -8,
      shinNear: 10,
      footNear: -4,
      thighFar: 8,
      shinFar: 6,
      footFar: -2,
      hairStrand: -6,
      hairTip: -8,
    },
    // The pelvis stays at ground level: lifting it puts the ankle target beyond leg
    // length, IK refuses, and the pose floats. A reach is carried by the spine and arm.
    hipsOffset: {x: -3, y: 0},
    lean: -1.5,
    hands: {near: 'open', far: 'relaxed'},
    armsLocked: true,
    contact: 'far',
    // Near heel lifts onto the ball of the boot; the far sole stays planted.
    feet: {near: {x: 166, y: 690, pitch: 16}, far: {x: 238, y: 698}},
  },

  // Mid-stride contact pose: near heel forward, far toe back. The motion layer
  // animates around this shape; the pose alone must already read as walking.
  walk: {
    angles: {
      hips: 2,
      spine: -1,
      chest: -2,
      neck: 2,
      head: 3,
      clavicleNear: 1,
      armUpperNear: 12,
      armForeNear: -20,
      handNear: 4,
      clavicleFar: -1,
      armUpperFar: -13,
      armForeFar: -26,
      handFar: 2,
      thighNear: -24,
      shinNear: 8,
      footNear: -8,
      thighFar: 18,
      shinFar: 16,
      footFar: 12,
      hairStrand: 4,
      hairTip: 6,
    },
    hipsOffset: {x: 0, y: -2},
    lean: -1,
    hands: {near: 'relaxed', far: 'relaxed'},
    armsLocked: true,
    contact: 'near',
    // Mid-stride: near heel forward and planted, far toe still on the ground.
    feet: {near: {x: 124, y: 698, pitch: -12}, far: {x: 248, y: 690, pitch: 20}},
  },

  // Chin up: the head rotates back and the chest follows, otherwise it reads as
  // staring at the ceiling with a stiff neck.
  lookUp: {
    angles: {
      hips: -1,
      spine: 3,
      chest: 2,
      neck: -7,
      head: -14,
      clavicleNear: -2,
      armUpperNear: -4,
      armForeNear: -14,
      handNear: 6,
      clavicleFar: 1,
      armUpperFar: 6,
      armForeFar: -12,
      handFar: 2,
      thighNear: -2,
      shinNear: 3,
      footNear: -1,
      thighFar: 1,
      shinFar: 2,
      footFar: 1,
      hairStrand: 5,
      hairTip: 8,
    },
    hipsOffset: {x: 2, y: 0},
    lean: 1,
    hands: {near: 'relaxed', far: 'relaxed'},
    // Gaze up is what sells the pose; the head rotation alone reads as a tilt.
    gaze: {x: 1, y: -5.5},
    contact: 'both',
    feet: {near: {x: 172, y: 698}, far: {x: 232, y: 698}},
  },

  // Shoulders up, elbows out, palms turned up. The shrug must sit in the
  // clavicles; raising only the arms looks like a scarecrow.
  shrug: {
    angles: {
      hips: 0,
      spine: 2,
      chest: 3,
      neck: 3,
      head: 6,
      // Shoulders lift (clavicles), upper arms stay near the ribs, forearms rotate OUT
      // and up so the palms end at chest height on either side. Positive forearm on the
      // near side sends the hand toward screen-left, away from the body.
      clavicleNear: -9,
      armUpperNear: 6,
      armForeNear: 88,
      handNear: 24,
      clavicleFar: 9,
      armUpperFar: -4,
      armForeFar: -84,
      handFar: -24,
      thighNear: -2,
      shinNear: 3,
      footNear: -1,
      thighFar: 2,
      shinFar: 2,
      footFar: 1,
      hairStrand: 3,
      hairTip: 4,
    },
    hipsOffset: {x: 0, y: 1},
    lean: 0,
    hands: {near: 'open', far: 'open'},
    contact: 'both',
    feet: {near: {x: 174, y: 698}, far: {x: 230, y: 698}},
  },

  // Seated: pelvis drops, thighs go horizontal, shins vertical, feet flat. The
  // torso leans forward slightly so the pose has a direction of attention.
  sit: {
    angles: {
      hips: -6,
      spine: 6,
      chest: 4,
      neck: -2,
      head: -3,
      clavicleNear: 2,
      armUpperNear: -18,
      armForeNear: -34,
      handNear: 10,
      clavicleFar: -2,
      armUpperFar: 14,
      armForeFar: -30,
      handFar: 6,
      hairStrand: 4,
      hairTip: 6,
    },
    // Seated on a 440-unit-high surface: hips drop 96 and the knees travel forward,
    // with the ankles directly under them so the soles are flat on the floor.
    hipsOffset: {x: 0, y: 78},
    lean: 2,
    hands: {near: 'relaxed', far: 'relaxed'},
    contact: 'both',
    // Seated with the ankles forward of the knees, which is what makes the pose read
    // as sitting rather than crouching. Targets stay inside the 298-unit leg.
    feet: {near: {x: 196, y: 690}, far: {x: 204, y: 690}},
  },
};

export type PivotLookup = (bone: BoneId) => Point | undefined;

/**
 * Resolve a pose to angles, solving leg IK when the pose declares foot targets and
 * the caller supplies pivots.
 *
 * Without pivots the authored leg angles are used, which keeps this module usable
 * in tests that only care about arm and torso data. With pivots, a lowered hip
 * (sit, crouch) or a raised heel (reach, walk) still lands its feet on the ground.
 */
export const resolvePose = (id: PoseId, pivot?: PivotLookup): ResolvedPose => {
  const pose = POSES[id];
  const angles = {...pose.angles};
  const hips = {...(pose.hipsOffset ?? {x: 0, y: 0})};

  if (pivot && pose.feet) {
    for (const side of ['Near', 'Far'] as const) {
      const target = pose.feet[side === 'Near' ? 'near' : 'far'];
      const hipPivot = pivot(`thigh${side}` as BoneId);
      const kneePivot = pivot(`shin${side}` as BoneId);
      const anklePivot = pivot(`foot${side}` as BoneId);
      if (!target || !hipPivot || !kneePivot || !anklePivot) continue;
      // The whole leg chain translates with the pelvis, so the knee and ankle pivots
      // move by the same offset. Using static pivots here shortens the thigh and makes
      // a seated pose report "out of reach", which then silently floats the character.
      const solved = solveLeg(
        {x: hipPivot.x + hips.x, y: hipPivot.y + hips.y},
        {x: kneePivot.x + hips.x, y: kneePivot.y + hips.y},
        {x: anklePivot.x + hips.x, y: anklePivot.y + hips.y},
        target,
        target.pitch ?? 0,
      );
      if (!solved) continue;
      // solveLeg returns an absolute bearing from vertical; the hips bone also
      // rotates the leg, so the applied thigh angle is the difference.
      angles[`thigh${side}` as BoneId] = solved.thigh - (pose.angles.hips ?? 0);
      angles[`shin${side}` as BoneId] = solved.shin;
      angles[`foot${side}` as BoneId] = solved.foot;
    }
  }

  return {
    angles,
    hips,
    lean: pose.lean ?? 0,
    hands: {near: pose.hands?.near ?? 'relaxed', far: pose.hands?.far ?? 'relaxed'},
    ...(pose.gaze ? {gaze: {...pose.gaze}} : {}),
  };
};
