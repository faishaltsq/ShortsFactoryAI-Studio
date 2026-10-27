"use client";

import { ContactShadows, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import { Vector3, type Group, type Mesh } from "three";
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
  ZOOM_BASE,
  ZOOM_MAX,
  ZOOM_MIN,
  isoDirection,
  tweenPosition,
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
import { AGENT_ZONE, ZONES, agentPosition, type Zone, type ZoneId } from "./zones";

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
}: {
  motions: { current: Motions };
  work: Record<string, boolean>;
  agentIds: string[];
}) {
  const invalidate = useThree((state) => state.invalidate);

  // A prop change must produce a frame. Cheap insurance for the paused/hidden case, and the
  // reason `speed` below is not the only path to a repaint.
  useEffect(() => {
    invalidate();
  }, [work, agentIds, invalidate]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const live = motions.current;
    live.clock = t;
    for (const agentId of agentIds) {
      live.breathing[agentId] = Math.sin(t * Math.PI * 2 * BREATH_HZ) * 0.014;
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
  onSelect,
}: {
  agentId: string;
  position: [number, number];
  state: string;
  stale: boolean;
  motions: { current: Motions };
  onSelect: () => void;
}) {
  const body = useRef<Group>(null);
  const color = stateColor(state);
  const working = isWorking(state);
  const family = motionFamilyFor(AGENT_ZONE[agentId] ?? "");
  const lean = LEAN[family];

  useFrame(() => {
    const group = body.current;
    if (!group) return;
    const t = motions.current.clock;
    // Every branch is a pure function of elapsed time: a dropped frame changes nothing and no
    // value accumulates across renders.
    if (working) {
      const cycle = (t * WORK_HZ) % 1;
      group.rotation.y = Math.sin(cycle * Math.PI * 2) * lean;
      group.position.y = Math.abs(Math.sin(cycle * Math.PI * 2)) * 0.03;
    } else if (state === "completed") {
      // One short reaction that decays to rest: never a loop.
      const progress = (t % REACTION_S) / REACTION_S;
      const decay = 1 - progress;
      group.rotation.y = Math.sin(progress * Math.PI * 2) * 0.25 * decay;
      group.position.y = Math.sin(progress * Math.PI) * 0.12 * decay;
    } else {
      group.rotation.y = 0;
      group.position.y = motions.current.breathing[agentId] ?? 0;
    }
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
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        document.body.style.cursor = "default";
      }}
    >
      <group ref={body}>
        <mesh position={[0, 0.55, 0]} castShadow>
          <capsuleGeometry args={[0.18, 0.35, 4, 8]} />
          <meshStandardMaterial color={color} roughness={0.85} metalness={0} />
        </mesh>
        <mesh position={[0, 0.92, 0]} castShadow>
          <sphereGeometry args={[0.16, 12, 12]} />
          <meshStandardMaterial color="#e8d7c3" roughness={0.8} metalness={0} />
        </mesh>
        {/* The working tell: a raised arm that exists only while the persisted state is working. */}
        {working ? (
          <mesh position={[0.2, 0.6, 0.08]} castShadow>
            <capsuleGeometry args={[0.055, 0.16, 3, 6]} />
            <meshStandardMaterial color={color} roughness={0.85} metalness={0} />
          </mesh>
        ) : null}
      </group>
      {/* Sticky marker for blocked/failed: a raised bar, not a glow that reads as activity. */}
      {state === "blocked" || state === "failed" ? (
        <mesh position={[0, 1.42, 0]} rotation={[0, 0, Math.PI / 4]}>
          <boxGeometry args={[0.06, 0.24, 0.06]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.7}
            roughness={0.7}
            metalness={0}
          />
        </mesh>
      ) : null}
      {stale ? (
        <mesh position={[0.24, 1.2, 0]}>
          <sphereGeometry args={[0.045, 8, 8]} />
          <meshStandardMaterial
            color="#d9a03f"
            emissive="#d9a03f"
            emissiveIntensity={0.8}
            roughness={0.7}
            metalness={0}
          />
        </mesh>
      ) : null}
    </group>
  );
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
        color={zone.accent}
        transparent
        opacity={focused ? 0.22 : 0.07}
        roughness={1}
        metalness={0}
      />
    </mesh>
  );
}

const EYE = new Vector3(...isoDirection()).normalize().multiplyScalar(30);

/**
 * The camera rig. Orthographic, isometric direction, orbit clamped to the doc's envelope, and a
 * single tweened orbit target for focus moves.
 *
 * The tween is driven from its own start timestamp, so it is pure in elapsed time and cannot
 * drift when a snapshot re-render lands mid-move.
 */
function IsoRig({
  focus,
  onZoom,
}: {
  focus: Zone | null;
  onZoom: (zoom: number) => void;
}) {
  const camera = useThree((state) => state.camera);
  const invalidate = useThree((state) => state.invalidate);
  const controls = useRef<{ target: Vector3; update: () => void } | null>(null);
  const from = useRef(new Vector3());
  const to = useRef(new Vector3());
  const started = useRef(0);
  const running = useRef(false);
  const current = useRef(new Vector3());

  useEffect(() => {
    if (!focus) return;
    from.current.copy(current.current);
    to.current.set(focus.position[0], 0, focus.position[1]);
    started.current = performance.now();
    running.current = true;
    invalidate();
  }, [focus, invalidate]);

  useFrame(() => {
    const orbit = controls.current;
    if (!orbit) return;
    if (!running.current) return;
    const progress = (performance.now() - started.current) / FOCUS_MS;
    if (progress >= 1) {
      current.current.copy(to.current);
      running.current = false;
    } else {
      const next = tweenPosition(from.current, to.current, progress);
      current.current.set(next.x, next.y, next.z);
    }
    orbit.target.copy(current.current);
    orbit.update();
    invalidate();
  });

  return (
    <OrbitControls
      // drei forwards every three-stdlib option here; the ref type is the imperative controls
      // object, which the tween mutates directly.
      ref={(instance) => {
        if (instance) controls.current = instance;
      }}
      makeDefault
      target={[0, 0, 0]}
      enablePan={false}
      enableDamping
      dampingFactor={0.12}
      minPolarAngle={POLAR_MIN}
      maxPolarAngle={POLAR_MAX}
      minAzimuthAngle={AZIMUTH_MIN}
      maxAzimuthAngle={AZIMUTH_MAX}
      minZoom={ZOOM_MIN}
      maxZoom={ZOOM_MAX}
      // Orthographic dolly is `camera.zoom`; publish it so the wrapper can report the envelope.
      onChange={() => {
        const zoomed = camera;
        if ("zoom" in zoomed && typeof zoomed.zoom === "number") onZoom(zoomed.zoom);
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

export function StudioScene({
  agents,
  onSelectAgent,
  quality,
  onFocusZone,
  paused = false,
}: {
  agents: AgentView[];
  onSelectAgent: (agentId: string) => void;
  quality: "high" | "medium" | "low";
  onFocusZone?: (zoneId: ZoneId | null) => void;
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
  const [focusId, setFocusId] = useState<ZoneId | null>(null);
  const [zoom, setZoom] = useState(ZOOM_BASE);

  const focus = useMemo(() => ZONES.find((zone) => zone.id === focusId) ?? null, [focusId]);

  const characters = useMemo(
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

  const focusZone = (zoneId: ZoneId) => {
    setFocusId(zoneId);
    onFocusZone?.(zoneId);
  };

  return (
    <div
      className="relative h-full w-full"
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
      <Canvas
        shadows={shadows}
        dpr={dpr}
        orthographic
        camera={{ position: [EYE.x, EYE.y, EYE.z], zoom: ZOOM_BASE, near: 0.1, far: 200 }}
        gl={{ antialias: effective !== "low", powerPreference: "default" }}
        frameloop={frameloop}
        onPointerMissed={() => {
          setFocusId(null);
          onFocusZone?.(null);
        }}
      >
        <color attach="background" args={["#0e1117"]} />
        <ambientLight intensity={0.45} />
        <hemisphereLight args={["#f4f1ea", "#1d2430", 0.35]} />
        <directionalLight
          position={[6, 10, 6]}
          intensity={1.1}
          color="#fff2dc"
          castShadow={shadows}
          shadow-mapSize={[1024, 1024]}
        />

        <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[16, 12]} />
          <meshStandardMaterial color="#e2d7c6" roughness={1} metalness={0} />
        </mesh>

        <MotionSampler motions={motions} work={work} agentIds={agentIds} />
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
          <Workstation
            key={`station-${zone.id}`}
            prop={zone.prop}
            palette={{ ...CLAY_PALETTE, accent: zone.accent }}
            position={zone.position}
            zoneId={zone.id}
            motions={motions}
          />
        ))}
        {characters.map((character) => (
          <Character
            key={character.agentId}
            agentId={character.agentId}
            position={character.position}
            state={character.state}
            stale={character.stale}
            motions={motions}
            onSelect={() => onSelectAgent(character.agentId)}
          />
        ))}

        <IsoRig focus={focus} onZoom={setZoom} />
        <ContactShadows position={[0, 0.01, 0]} opacity={0.35} scale={20} blur={2.4} far={6} />
      </Canvas>

      {/* Zone anchors. Deliberately a DOM list beside the canvas rather than one drei `<Html>` per
          zone: drei projects every portal into a single absolutely-positioned wrapper, and a portal
          whose projected position falls outside that wrapper's containing block is created and then
          dropped on the next frame. Measured on the `director` zone — the first entry, at the room's
          far corner — whose `<Html>` never mounted at all, leaving nine of ten anchors in the DOM.

          A list that does not depend on camera projection cannot be culled by it, it is the same
          contract the 2D fallback already offers, and it is what the E2E spec asserts. A zone whose
          module does not exist is an honest disabled span, never a dead anchor. */}
      <ul
        aria-label="Modul per zona"
        className="pointer-events-auto absolute right-1 top-1 flex max-h-24 w-28 flex-col gap-0.5 overflow-auto"
      >
        {ZONES.map((zone) => (
          <li key={`landmark-${zone.id}`}>
            {zone.href ? (
              <a
                href={zone.href}
                data-zone-link
                data-zone-link-disabled="false"
                data-zone={zone.id}
                aria-label={`Buka modul ${ZONE_LABEL[zone.id]}`}
                className="zone-anchor block w-full text-center"
              >
                {ZONE_LABEL[zone.id]}
              </a>
            ) : (
              <span
                data-zone-link
                data-zone-link-disabled="true"
                data-zone={zone.id}
                title="rute belum ada"
                aria-label={`${ZONE_LABEL[zone.id]} — rute belum ada`}
                aria-disabled="true"
                className="zone-anchor zone-anchor-off block w-full text-center"
              >
                {ZONE_LABEL[zone.id]}
              </span>
            )}
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
      <div className="pointer-events-auto absolute bottom-2 left-2 flex flex-wrap gap-1">
        {ZONES.map((zone) => (
          <button
            key={`focus-${zone.id}`}
            type="button"
            className="btn min-h-8 px-2 text-[10px] uppercase tracking-wide"
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
