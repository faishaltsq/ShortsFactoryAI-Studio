"use client";

import { ContactShadows, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Matrix4, Vector3, type Group, type OrthographicCamera } from "three";
import type { AgentView } from "@/lib/api";
import { characterState } from "@/lib/studioState";
import {
  AZIMUTH_MAX,
  AZIMUTH_MIN,
  FOCUS_MS,
  FRUSTUM_HALF,
  ISO_AZIMUTH,
  ISO_ELEVATION,
  POLAR_MAX,
  POLAR_MIN,
  ROOM,
  ROOM_TARGET_Y,
  ZOOM_BASE,
  ZOOM_MAX,
  ZOOM_MIN,
  isoDirection,
  easeInOutCubic,
  roomFrustum,
} from "./camera";
import {
  isWorking,
  motionFamilyFor,
  nextTierOnFrameTime,
  stateColor,
  type MotionFamily,
  type QualityTier,
} from "./sceneState";
import { Workstation, type Palette } from "./Workstation";
import { AGENT_LABEL, AGENT_ZONE, ZONES, agentPosition, zoneHref, type Zone, type ZoneId } from "./zones";

/**
 * The room. Clay materials, soft light, low poly.
 *
 * Everything drawn here comes from `agents`, which comes from persisted events. No animation
 * implies work: one sampler computes every character's motion from elapsed time and its derived
 * state, and the only predicate that enables a work cycle is `isWorking(state)`.
 *
 * The DOM mirror (`data-scene-mirror`) is a test seam, not UI — Playwright cannot read `userData`
 * from a WebGL scene, so without it every parity assertion about the 3D path is vacuous. It is
 * `aria-hidden` and clipped; the sidebar remains the accessible path (docs/STUDIO_3D.md §7).
 */

const CLAY_PALETTE: Palette = {
  wood: "#b08454",
  dark: "#4a4038",
  paper: "#efe6d8",
  accent: "#2f6f6a",
  metal: "#5c636e",
};

/** Breathing rate from the doc: 0.6 Hz. Work cycles are faster so the two read differently. */
const BREATH_HZ = 0.6;
const WORK_HZ = 1.8;
const REACTION_S = 1.2;

/** How far a character leans into its station while working, per zone. Small: clay, not mime. */
const LEAN: Record<MotionFamily, number> = {
  type: 0.1,
  operate: 0.14,
  read: 0.06,
  draw: 0.12,
  speak: 0.08,
  scrub: 0.1,
  pack: 0.15,
  walk: 0.18,
};

const MOTION_LABEL: Record<string, string> = {
  working: "working",
  waiting: "idle",
  idle: "idle",
  blocked: "blocked",
  failed: "failed",
  completed: "completed",
};

/**
 * The one sampler. Writes into a ref, never into React state: a per-frame `setState` would
 * re-reconcile the whole tree and blow any tier budget.
 *
 * `work` is computed from the derived state map, so a station can only receive a work cycle when
 * a persisted `working` state put it in that set.
 */
type Motions = {
  clock: number;
  breathing: Record<string, number>;
  stations: Record<string, number>;
  work: Record<string, boolean>;
};

function MotionSampler({
  motions,
  work,
  agentIds,
  reducedMotion,
}: {
  motions: { current: Motions };
  work: Record<string, boolean>;
  agentIds: string[];
  reducedMotion: boolean;
}) {
  const invalidate = useThree((state) => state.invalidate);

  // Demand rendering still needs one frame when the snapshot or motion preference changes.
  useEffect(() => {
    invalidate();
  }, [work, agentIds, reducedMotion, invalidate]);

  useFrame((state) => {
    const t = reducedMotion ? 0 : state.clock.elapsedTime;
    const live = motions.current;
    live.clock = t;
    for (const agentId of agentIds) {
      live.breathing[agentId] = reducedMotion ? 0 : Math.sin(t * Math.PI * 2 * BREATH_HZ) * 0.014;
    }
    for (const zoneId of Object.keys(live.stations)) {
      if (live.work[zoneId]) live.stations[zoneId] = (t * WORK_HZ) % 1;
      else live.stations[zoneId] = 0;
    }
  });

  return null;
}

function Character({
  agentId,
  position,
  state,
  stale,
  motions,
  focused,
  reducedMotion,
  onSelect,
}: {
  agentId: string;
  position: [number, number];
  state: string;
  stale: boolean;
  motions: { current: Motions };
  focused: boolean;
  reducedMotion: boolean;
  onSelect: () => void;
}) {
  const body = useRef<Group>(null);
  const completedAt = useRef(0);
  const [hovered, setHovered] = useState(false);
  const color = stateColor(state);
  const working = isWorking(state);
  const lean = LEAN[motionFamilyFor(AGENT_ZONE[agentId] ?? "")];
  const zone = ZONES.find((candidate) => candidate.id === AGENT_ZONE[agentId]);
  const variant = Math.max(0, ZONES.findIndex((candidate) => candidate.id === zone?.id));
  const skin = ["#d8a579", "#b97c57", "#efd0a8"][variant % 3];
  const hair = ["#45372f", "#302e2b", "#79543d"][variant % 3];

  useEffect(() => {
    completedAt.current = motions.current.clock;
  }, [state, motions]);

  useFrame(() => {
    const group = body.current;
    if (!group) return;
    const t = motions.current.clock;
    group.rotation.set(0, Math.PI / 4, 0);
    group.position.y = 0;
    if (reducedMotion) return;
    if (working) {
      const cycle = Math.sin(t * WORK_HZ * Math.PI * 2);
      group.rotation.y += cycle * lean;
      group.rotation.x = Math.abs(cycle) * 0.035;
    } else if (state === "completed") {
      const progress = Math.min(1, Math.max(0, (t - completedAt.current) / REACTION_S));
      group.rotation.y += Math.sin(progress * Math.PI * 2) * 0.18 * (1 - progress);
      group.position.y = Math.sin(progress * Math.PI) * 0.05 * (1 - progress);
    } else {
      group.position.y = motions.current.breathing[agentId] ?? 0;
    }
    if (!working) group.rotation.x = 0;
  });

  return (
    <group
      position={[position[0], 0, position[1]]}
      userData={{ agentId, state }}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "default";
      }}
    >
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.022, 0]}>
        <circleGeometry args={[0.4, 16]} />
        <meshStandardMaterial color={hovered || focused ? "#4a938c" : "#746858"} roughness={1} />
      </mesh>
      {/* Oversized heads, separate hands and boots keep the crew legible at room scale. */}
      <group ref={body} rotation={[0, Math.PI / 4, 0]}>
        {[-1, 1].map((side) => (
          <group key={side}>
            <mesh position={[side * 0.13, 0.26, 0]} castShadow>
              <cylinderGeometry args={[0.095, 0.085, 0.38, 6]} />
              <meshStandardMaterial color="#454c4c" roughness={0.9} />
            </mesh>
            <mesh position={[side * 0.13, 0.085, 0.065]} castShadow>
              <boxGeometry args={[0.21, 0.15, 0.31]} />
              <meshStandardMaterial color="#343431" roughness={0.9} />
            </mesh>
            <group position={[side * 0.3, 0.73, working ? 0.13 : 0]} rotation={[working ? -0.65 : 0, 0, side * 0.13]}>
              <mesh castShadow>
                <capsuleGeometry args={[0.085, 0.25, 2, 6]} />
                <meshStandardMaterial color={color} roughness={0.9} />
              </mesh>
              <mesh position={[0, -0.22, 0]} castShadow>
                <sphereGeometry args={[0.085, 6, 4]} />
                <meshStandardMaterial color={skin} roughness={0.9} />
              </mesh>
            </group>
          </group>
        ))}
        <mesh position={[0, 0.7, 0]} castShadow>
          <cylinderGeometry args={[0.23, 0.26, 0.54, 8]} />
          <meshStandardMaterial color={color} roughness={0.9} />
        </mesh>
        <mesh position={[0, 1.02, 0]}>
          <cylinderGeometry args={[0.09, 0.11, 0.16, 6]} />
          <meshStandardMaterial color={skin} roughness={0.9} />
        </mesh>
        <mesh position={[0, 1.28, 0]} scale={[1, 1.08, 0.94]} castShadow>
          <sphereGeometry args={[0.265, 8, 6]} />
          <meshStandardMaterial color={skin} roughness={0.9} flatShading />
        </mesh>
        <mesh position={[0, 1.35, -0.025]} castShadow>
          <sphereGeometry args={[0.275, 8, 4, 0, Math.PI * 2, 0, Math.PI * 0.62]} />
          <meshStandardMaterial color={hair} roughness={1} flatShading />
        </mesh>
        {[-1, 1].map((side) => (
          <mesh key={`eye-${side}`} position={[side * 0.095, 1.3, 0.228]}>
            <boxGeometry args={[0.045, 0.055, 0.035]} />
            <meshStandardMaterial color="#302c28" roughness={1} />
          </mesh>
        ))}
        <mesh position={[0, 1.19, 0.239]}>
          <boxGeometry args={[0.085, 0.024, 0.025]} />
          <meshStandardMaterial color="#79503c" roughness={1} />
        </mesh>
        {zone?.id === "audio" ? (
          <mesh position={[0, 1.38, -0.005]} rotation={[0, 0, Math.PI / 2]}>
            <torusGeometry args={[0.285, 0.038, 4, 10, Math.PI]} />
            <meshStandardMaterial color="#384b4a" roughness={0.9} />
          </mesh>
        ) : null}
      </group>
      {state === "blocked" || state === "failed" ? (
        <mesh position={[0.35, 1.66, 0]} rotation={[0, 0, Math.PI / 4]}>
          <boxGeometry args={[0.1, 0.26, 0.1]} />
          <meshStandardMaterial color={color} roughness={0.85} />
        </mesh>
      ) : null}
      {stale ? (
        <mesh position={[-0.34, 1.6, 0]}>
          <sphereGeometry args={[0.075, 6, 4]} />
          <meshStandardMaterial color="#d9a03f" roughness={0.9} />
        </mesh>
      ) : null}
    </group>
  );
}

type SceneCharacter = {
  agentId: string;
  state: string;
  stale: boolean;
  position: [number, number];
  zoneId: ZoneId | null;
};

/** React owns the labels outside Canvas; this sampler only projects their ordinary DOM nodes. */
function AgentLabelProjector({
  characters,
  focusId,
  buttons,
  lines,
}: {
  characters: SceneCharacter[];
  focusId: ZoneId | null;
  buttons: { current: Record<string, HTMLButtonElement | null> };
  lines: { current: Record<string, SVGLineElement | null> };
}) {
  const anchors = useMemo(() => characters.map((character) => ({
    ...character,
    world: new Vector3(character.position[0], 1.8, character.position[1]),
    projected: new Vector3(),
    x: 0,
    y: 0,
    placed: false,
  })), [characters]);
  const ordered = useMemo(() => [...anchors], [anchors]);
  const previousView = useRef(new Matrix4());
  const previousProjection = useRef(new Matrix4());
  const previousSize = useRef({ width: 0, height: 0 });
  const dirty = useRef(true);
  useLayoutEffect(() => {
    dirty.current = true;
  }, [anchors, focusId]);

  useFrame(({ camera, size }) => {
    camera.updateMatrixWorld();
    if (!dirty.current && previousView.current.equals(camera.matrixWorld) &&
      previousProjection.current.equals(camera.projectionMatrix) &&
      previousSize.current.width === size.width && previousSize.current.height === size.height) return;
    dirty.current = false;
    previousView.current.copy(camera.matrixWorld);
    previousProjection.current.copy(camera.projectionMatrix);
    previousSize.current.width = size.width;
    previousSize.current.height = size.height;
    const labelWidth = Math.min(104, size.width - 16);
    const labelHeight = 44;
    for (const anchor of anchors) {
      anchor.projected.copy(anchor.world).project(camera);
      anchor.x = Math.max(8, Math.min(size.width - labelWidth - 8,
        (anchor.projected.x + 1) * size.width / 2 - labelWidth / 2));
      anchor.y = Math.max(8, Math.min(size.height - labelHeight - 8,
        (1 - anchor.projected.y) * size.height / 2 - labelHeight - 4));
      anchor.placed = false;
    }
    ordered.sort((a, b) => a.y - b.y || a.x - b.x);
    for (const anchor of ordered) {
      const button = buttons.current[anchor.agentId];
      const line = lines.current[anchor.agentId];
      if (!button || !line) {
        dirty.current = true;
        continue;
      }
      const visible = focusId === null ? size.width >= 520 : anchor.zoneId === focusId;
      button.style.visibility = visible ? "visible" : "hidden";
      line.style.visibility = visible ? "visible" : "hidden";
      if (!visible) continue;
      let overlaps = false;
      for (const placed of ordered) {
        if (placed === anchor) break;
        if (placed.placed && Math.abs(anchor.x - placed.x) < labelWidth + 4 &&
          Math.abs(anchor.y - placed.y) < labelHeight + 4) overlaps = true;
      }
      if (overlaps) {
        // Prefer the closest unoccupied slot, rather than letting paired crew names cover each other.
        let bestDistance = Infinity;
        let bestX = anchor.x;
        let bestY = anchor.y;
        for (let y = 8; y + labelHeight <= size.height - 8; y += labelHeight + 4) {
          for (let x = 8; x + labelWidth <= size.width - 8; x += labelWidth + 8) {
            let occupied = false;
            for (const placed of ordered) {
              if (placed === anchor) break;
              if (placed.placed && Math.abs(x - placed.x) < labelWidth + 4 &&
                Math.abs(y - placed.y) < labelHeight + 4) occupied = true;
            }
            const distance = (x - anchor.x) ** 2 + (y - anchor.y) ** 2;
            if (!occupied && distance < bestDistance) {
              bestDistance = distance;
              bestX = x;
              bestY = y;
            }
          }
        }
        anchor.x = bestX;
        anchor.y = bestY;
      }
      anchor.placed = true;
      button.style.transform = `translate3d(${anchor.x}px, ${anchor.y}px, 0)`;
      line.setAttribute("x1", String((anchor.projected.x + 1) * size.width / 2));
      line.setAttribute("y1", String((1 - anchor.projected.y) * size.height / 2));
      line.setAttribute("x2", String(anchor.x + labelWidth / 2));
      line.setAttribute("y2", String(anchor.y + labelHeight));
    }
  });
  return null;
}

function ZoneFloor({
  zone,
  focused,
  onFocus,
}: {
  zone: Zone;
  focused: boolean;
  onFocus: () => void;
}) {
  return (
    <mesh
      position={[zone.position[0], 0.005, zone.position[1]]}
      rotation={[-Math.PI / 2, 0, 0]}
      receiveShadow
      onClick={(event) => {
        event.stopPropagation();
        onFocus();
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        document.body.style.cursor = "default";
      }}
    >
      <planeGeometry args={[2.8, 2.6]} />
      <meshStandardMaterial
        color={focused ? "#4a938c" : "#86745e"}
        transparent
        opacity={focused ? 0.4 : 0.18}
        roughness={1}
        metalness={0}
      />
    </mesh>
  );
}

const EYE = new Vector3(...isoDirection()).normalize().multiplyScalar(30);

/** Frustum, target and eye move together; a reset returns the complete rig to its home pose. */
function IsoRig({
  focus,
  resetKey,
  reducedMotion,
  onZoom,
}: {
  focus: Zone | null;
  resetKey: number;
  reducedMotion: boolean;
  onZoom: (zoom: number) => void;
}) {
  const camera = useThree((state) => state.camera) as OrthographicCamera & { manual?: boolean };
  const size = useThree((state) => state.size);
  const invalidate = useThree((state) => state.invalidate);
  const controls = useRef<{ target: Vector3; update: () => void } | null>(null);
  const from = useRef(new Vector3());
  const to = useRef(new Vector3());
  const fromEye = useRef(new Vector3());
  const toEye = useRef(new Vector3());
  const fromZoom = useRef(ZOOM_BASE);
  const toZoom = useRef(ZOOM_BASE);
  const started = useRef(0);
  const running = useRef(false);

  useLayoutEffect(() => {
    // Prevent R3F's pixel-sized resize frustum from replacing this world-unit fit.
    camera.manual = true;
    Object.assign(camera, roomFrustum(size.width, size.height));
    camera.updateProjectionMatrix();
    invalidate();
  }, [camera, size.width, size.height, invalidate]);

  useEffect(() => {
    const orbit = controls.current;
    if (!orbit) return;
    from.current.copy(orbit.target);
    to.current.set(focus?.position[0] ?? 0, ROOM_TARGET_Y, focus ? focus.position[1] + 0.45 : 0);
    fromEye.current.copy(camera.position);
    toEye.current.copy(EYE).add(to.current);
    fromZoom.current = camera.zoom;
    toZoom.current = focus ? ZOOM_MAX : ZOOM_BASE;
    started.current = performance.now();
    running.current = true;
    invalidate();
  }, [focus, resetKey, reducedMotion, camera, invalidate]);

  useFrame(() => {
    const orbit = controls.current;
    if (!orbit || !running.current) return;
    const progress = reducedMotion ? 1 : Math.min(1, (performance.now() - started.current) / FOCUS_MS);
    const eased = easeInOutCubic(progress);
    orbit.target.lerpVectors(from.current, to.current, eased);
    camera.position.lerpVectors(fromEye.current, toEye.current, eased);
    camera.zoom = fromZoom.current + (toZoom.current - fromZoom.current) * eased;
    camera.updateProjectionMatrix();
    orbit.update();
    onZoom(camera.zoom);
    if (progress >= 1) running.current = false;
    invalidate();
  });

  return (
    <OrbitControls
      ref={(instance) => {
        controls.current = instance;
      }}
      makeDefault
      target={[0, ROOM_TARGET_Y, 0]}
      enablePan={false}
      enableDamping={!reducedMotion}
      dampingFactor={0.12}
      minPolarAngle={POLAR_MIN}
      maxPolarAngle={POLAR_MAX}
      minAzimuthAngle={AZIMUTH_MIN}
      maxAzimuthAngle={AZIMUTH_MAX}
      minZoom={ZOOM_MIN}
      maxZoom={ZOOM_MAX}
      onStart={() => {
        running.current = false;
      }}
      onChange={() => {
        onZoom(camera.zoom);
        invalidate();
      }}
    />
  );
}

/** How long one frame-time sample window runs. */
const TIER_WINDOW_MS = 3000;

/**
 * The auto-downgrade sampler (§6). One `useFrame` per scene, not one per character.
 *
 * It accumulates frame deltas into a window, and when 3 s have elapsed it reports the window's
 * median. The decision itself is `nextTierOnFrameTime`, which is pure and tested. Downgrading is
 * session state only: it never touches the operator's stored preference.
 */
function TierSampler({ onMedian }: { onMedian: (medianMs: number) => void }) {
  const samples = useRef<number[]>([]);
  const elapsed = useRef(0);

  useFrame((_, delta) => {
    // A tab restored from the background reports one huge delta. It is not a frame cost.
    if (delta <= 0 || delta > 1) return;
    samples.current.push(delta * 1000);
    elapsed.current += delta;
    if (elapsed.current < TIER_WINDOW_MS / 1000) return;
    const sorted = [...samples.current].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)] ?? 0;
    samples.current = [];
    elapsed.current = 0;
    onMedian(median);
  });

  return null;
}

const ZONE_LABEL: Record<ZoneId, string> = {
  director: "Direktur",
  research: "Riset",
  writing: "Tulis",
  review: "Review",
  storyboard: "Storyboard",
  animation: "Animasi",
  audio: "Audio",
  edit: "Editing",
  qc: "QC",
  publishing: "Publikasi",
};

/** `demand` is reserved for a hidden tab (ADR-008); the low tier renders continuously. */
function useHiddenFrameloop(): "always" | "demand" {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const update = () => setHidden(document.visibilityState === "hidden");
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return hidden ? "demand" : "always";
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(true);
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(preference.matches);
    update();
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);
  return reduced;
}

export function StudioScene({
  agents,
  onSelectAgent,
  quality,
  focusZoneId,
  onFocusZone,
  onUnavailable,
  jobId,
  paused = false,
}: {
  agents: AgentView[];
  onSelectAgent: (agentId: string) => void;
  quality: "high" | "medium" | "low";
  onFocusZone?: (zoneId: ZoneId | null) => void;
  focusZoneId?: ZoneId | null;
  onUnavailable?: () => void;
  jobId?: string;
  /**
   * ADR-008: a render job has priority. While a `RENDERING` event is active the studio stops
   * drawing, so it cannot contend with the renderer. ADR-008 also asks for free GPU memory below
   * 1 GB, which the browser cannot read; `page.tsx` says so in the banner instead of inventing it.
   */
  paused?: boolean;
}) {
  // The operator's choice is the starting tier; this session may only lower it. Nothing here
  // writes back: `shorts-studio-quality` stays the operator's alone (§6, session-only).
  const [effective, setEffective] = useState<QualityTier>(quality);
  useEffect(() => setEffective(quality), [quality]);

  const dpr = effective === "high" ? 1.5 : effective === "medium" ? 1.25 : 1;
  const shadows = effective === "high";
  const hiddenFrameloop = useHiddenFrameloop();
  const frameloop = paused ? "demand" : hiddenFrameloop;
  const reducedMotion = useReducedMotion();
  const [localFocusId, setLocalFocusId] = useState<ZoneId | null>(null);
  const focusId = focusZoneId === undefined ? localFocusId : focusZoneId;
  const [resetKey, setResetKey] = useState(0);
  const [contextLost, setContextLost] = useState(false);
  const contextCleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => contextCleanup.current?.(), []);
  const [zoom, setZoom] = useState(ZOOM_BASE);
  const labelButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const labelLines = useRef<Record<string, SVGLineElement | null>>({});

  const focus = useMemo(() => ZONES.find((zone) => zone.id === focusId) ?? null, [focusId]);

  const characters = useMemo<SceneCharacter[]>(
    () =>
      agents.map((agent) => {
        const state = characterState(agent);
        return {
          agentId: agent.agent_id,
          state,
          stale: agent.stale,
          position: agentPosition(agent.agent_id),
          zoneId: AGENT_ZONE[agent.agent_id] ?? null,
        };
      }),
    [agents],
  );

  const work = useMemo(() => {
    const result: Record<string, boolean> = {};
    for (const zone of ZONES) result[zone.id] = false;
    for (const character of characters) {
      if (character.zoneId && isWorking(character.state)) result[character.zoneId] = true;
    }
    return result;
  }, [characters]);

  const agentIds = useMemo(() => characters.map((character) => character.agentId), [characters]);

  const motions = useRef<Motions>({ clock: 0, breathing: {}, stations: {}, work });

  useEffect(() => {
    motions.current.work = work;
    const stations: Record<string, number> = {};
    for (const zone of ZONES) stations[zone.id] = motions.current.stations[zone.id] ?? 0;
    motions.current.stations = stations;
  }, [work]);

  const focusZone = (zoneId: ZoneId | null) => {
    if (focusZoneId === undefined) setLocalFocusId(zoneId);
    setResetKey((value) => value + 1);
    onFocusZone?.(zoneId);
  };

  const recovery = (
    <div className="flex h-full min-h-48 flex-col items-center justify-center gap-3 p-6 text-center" role="status">
      <p className="text-sm text-ink-200">
        {contextLost ? "Koneksi grafis studio terputus." : "WebGL tidak tersedia untuk studio 3D."}
      </p>
      <button type="button" className="btn min-h-11" onClick={onUnavailable ?? (() => window.location.reload())}>
        {onUnavailable ? "Gunakan studio 2D" : "Muat ulang studio"}
      </button>
    </div>
  );

  return (
    <div
      className="relative flex h-full w-full min-w-0 flex-col"
      data-studio-scene
      data-quality={quality}
      data-effective-quality={effective}
      data-camera="isometric"
      data-camera-elevation={ISO_ELEVATION.toFixed(6)}
      data-camera-azimuth={ISO_AZIMUTH.toFixed(6)}
      data-camera-frustum={FRUSTUM_HALF.toFixed(4)}
      data-camera-zoom={zoom.toFixed(4)}
      data-camera-target={focusId ?? "none"}
      data-frameloop={frameloop}
    >
      <div className="relative min-h-0 flex-1">
      {contextLost ? recovery : (
      <Canvas
        shadows={shadows}
        dpr={dpr}
        orthographic
        camera={{
          manual: true,
          ...roomFrustum(1, 1),
          position: [EYE.x, EYE.y + ROOM_TARGET_Y, EYE.z],
          zoom: ZOOM_BASE,
          near: 0.1,
          far: 200,
        }}
        gl={{ antialias: effective !== "low", powerPreference: "default" }}
        frameloop={frameloop}
        fallback={recovery}
        onCreated={({ gl }) => {
          contextCleanup.current?.();
          const canvas = gl.domElement;
          const lost = (event: Event) => {
            event.preventDefault();
            setContextLost(true);
            onUnavailable?.();
          };
          canvas.addEventListener("webglcontextlost", lost, { once: true });
          contextCleanup.current = () => canvas.removeEventListener("webglcontextlost", lost);
        }}
        onPointerMissed={() => focusZone(null)}
      >
        <color attach="background" args={["#191e1e"]} />
        <ambientLight intensity={0.65} />
        <hemisphereLight args={["#f4e6d2", "#4d5553", 0.6]} />
        <directionalLight
          position={[6, 10, 6]}
          intensity={1.1}
          color="#fff2dc"
          castShadow={shadows}
          shadow-mapSize={[1024, 1024]}
        />

        <group>
          <mesh position={[0, -0.22, 0]} receiveShadow>
            <boxGeometry args={[ROOM.width + 0.16, 0.42, ROOM.depth + 0.16]} />
            <meshStandardMaterial color="#786a58" roughness={1} />
          </mesh>
          <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
            <planeGeometry args={[ROOM.width, ROOM.depth]} />
            <meshStandardMaterial color="#baa68d" roughness={1} />
          </mesh>
          <mesh position={[0, 0.85, -ROOM.depth / 2]} receiveShadow castShadow>
            <boxGeometry args={[ROOM.width, 1.7, 0.18]} />
            <meshStandardMaterial color="#d5c2a8" roughness={1} />
          </mesh>
          <mesh position={[-ROOM.width / 2, 0.85, 0]} receiveShadow castShadow>
            <boxGeometry args={[0.18, 1.7, ROOM.depth]} />
            <meshStandardMaterial color="#c5b194" roughness={1} />
          </mesh>
          <mesh position={[-ROOM.width / 2 + 0.12, 0.15, 0]}>
            <boxGeometry args={[0.08, 0.3, ROOM.depth]} />
            <meshStandardMaterial color="#6c736a" roughness={1} />
          </mesh>
        </group>

        <MotionSampler motions={motions} work={work} agentIds={agentIds} reducedMotion={reducedMotion} />
        <TierSampler
          onMedian={(median) =>
            setEffective((current) => nextTierOnFrameTime(current, median))
          }
        />

        {ZONES.map((zone) => (
          <ZoneFloor
            key={zone.id}
            zone={zone}
            focused={focusId === zone.id}
            onFocus={() => focusZone(zone.id)}
          />
        ))}
        {ZONES.map((zone) => (
          <group key={`station-${zone.id}`} position={[zone.position[0], 0, zone.position[1]]} scale={[1.12, 1.4, 1.08]}
            onClick={(event) => {
              event.stopPropagation();
              focusZone(zone.id);
            }}
          >
            <Workstation
              prop={zone.prop}
              palette={CLAY_PALETTE}
              position={[0, 0]}
              zoneId={zone.id}
              motions={motions}
            />
          </group>
        ))}
        {characters.map((character) => (
          <Character
            key={character.agentId}
            agentId={character.agentId}
            position={character.position}
            state={character.state}
            stale={character.stale}
            motions={motions}
            focused={focusId === character.zoneId}
            reducedMotion={reducedMotion}
            onSelect={() => onSelectAgent(character.agentId)}
          />
        ))}

        <IsoRig focus={focus} resetKey={resetKey} reducedMotion={reducedMotion} onZoom={setZoom} />
        <AgentLabelProjector characters={characters} focusId={focusId} buttons={labelButtons} lines={labelLines} />
        {effective !== "low" ? (
          <ContactShadows position={[0, 0.01, 0]} opacity={0.35} scale={20} blur={2.4} far={6} />
        ) : null}
      </Canvas>
      )}
      {!contextLost ? (
        <div className="pointer-events-none absolute inset-0" data-agent-labels>
          <svg aria-hidden="true" className="absolute inset-0 h-full w-full">
            {characters.map((character) => (
              <line key={character.agentId} ref={(line) => { labelLines.current[character.agentId] = line; }}
                stroke="#f2e4d0" strokeOpacity={0.35} strokeWidth={1} style={{ visibility: "hidden" }} />
            ))}
          </svg>
          {characters.map((character) => (
            <button
              key={character.agentId}
              ref={(button) => { labelButtons.current[character.agentId] = button; }}
              type="button"
              data-agent-label={character.agentId}
              aria-label={`Pilih agen ${AGENT_LABEL[character.agentId] ?? character.agentId}`}
              title={`${AGENT_LABEL[character.agentId] ?? character.agentId}: ${character.state}${character.stale ? " (status terlambat)" : ""}`}
              onClick={() => onSelectAgent(character.agentId)}
              className="pointer-events-auto absolute left-0 top-0 flex h-11 w-[104px] items-center justify-center rounded text-center text-[10px] leading-tight text-[#f2e4d0] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#f4bc68]"
              style={{ visibility: "hidden" }}
            >
              <span className="rounded border border-[#746858] bg-[#252824] px-1.5 py-1">
                {AGENT_LABEL[character.agentId] ?? character.agentId}
              </span>
            </button>
          ))}
        </div>
      ) : null}
      </div>

      {/* Module links stay in the DOM, independently of camera projection and WebGL recovery. */}
      <ul
        aria-label="Modul per zona"
        className="pointer-events-auto flex flex-wrap gap-x-2 gap-y-1 border-t border-white/10 px-3 py-2"
      >
        {ZONES.map((zone) => (
          <li key={`landmark-${zone.id}`}>
              <a
                href={zoneHref(zone, jobId)}
                data-zone-link
                data-zone-link-disabled="false"
                data-zone={zone.id}
                aria-label={`Buka modul ${ZONE_LABEL[zone.id]}`}
                className="zone-anchor inline-flex min-h-11 items-center text-center text-[11px]"
              >
                {ZONE_LABEL[zone.id]}
              </a>
          </li>
        ))}
      </ul>

      {/* Test seam, not UI: one row per character, from the same derived state the meshes read.
          Clipped and aria-hidden so it never appears, never takes focus, never duplicates the
          sidebar for a screen reader. */}
      <ul
        data-scene-mirror
        aria-hidden="true"
        className="pointer-events-none absolute left-0 top-0 h-px w-px overflow-hidden opacity-0"
        style={{ clipPath: "inset(50%)" }}
      >
        {characters.map((character) => (
          <li
            key={character.agentId}
            data-agent={character.agentId}
            data-state={character.state}
            data-motion={MOTION_LABEL[character.state] ?? "idle"}
          >
            {character.agentId}
          </li>
        ))}
      </ul>

      {/* Keyboard-reachable focus, because a WebGL floor is not addressable from a role locator
          and a screen reader cannot click a mesh. This is also what the E2E test drives. */}
      <div className="pointer-events-auto flex flex-wrap gap-1 px-3 pb-3" aria-label="Fokus kamera">
        <button type="button" className="btn min-h-11 px-3 text-xs" aria-pressed={focusId === null} onClick={() => focusZone(null)}>
          Seluruh studio
        </button>
        {ZONES.map((zone) => (
          <button
            key={`focus-${zone.id}`}
            type="button"
            className="btn min-h-11 px-2 text-[11px]"
            aria-pressed={focusId === zone.id}
            aria-label={`Fokus zona ${ZONE_LABEL[zone.id]}`}
            onClick={() => focusZone(zone.id)}
          >
            {ZONE_LABEL[zone.id]}
          </button>
        ))}
      </div>
    </div>
  );
}
