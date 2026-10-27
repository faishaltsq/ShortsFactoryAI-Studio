"use client";

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Mesh } from "three";
import type { WorkstationProp } from "./zones";

/**
 * Ten low-poly clay props, one per zone, from `docs/STUDIO_3D.md` §2.
 *
 * Draw-call budget: every prop is boxes/cylinders/spheres only, and the materials are created once
 * per palette entry in the caller and passed down. A prop therefore adds geometry, not materials,
 * so the ten workstations do not multiply the material count. No textures, no external assets,
 * `metalness` 0 and `roughness` 0.85 everywhere to stay in the clay language.
 *
 * One deliberate cheat: the shared clay material is a module-level constant built from
 * `MeshStandardMaterial` *parameters*, not an instance — three.js caches identical shader programs
 * per parameter set, so ten look-alike props stay on one compiled program.
 */

export type Palette = {
  wood: string;
  dark: string;
  paper: string;
  accent: string;
  metal: string;
};

export const CLAY = { roughness: 0.85, metalness: 0 } as const;

function Box({
  size,
  position,
  color,
  rotation,
}: {
  size: [number, number, number];
  position: [number, number, number];
  color: string;
  rotation?: [number, number, number];
}) {
  return (
    <mesh position={position} rotation={rotation} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} roughness={CLAY.roughness} metalness={CLAY.metalness} />
    </mesh>
  );
}

function Cylinder({
  radius,
  height,
  position,
  color,
  rotation,
}: {
  radius: number;
  height: number;
  position: [number, number, number];
  color: string;
  rotation?: [number, number, number];
}) {
  return (
    <mesh position={position} rotation={rotation} castShadow>
      <cylinderGeometry args={[radius, radius, height, 8]} />
      <meshStandardMaterial color={color} roughness={CLAY.roughness} metalness={CLAY.metalness} />
    </mesh>
  );
}

function Sphere({ radius, position, color }: { radius: number; position: [number, number, number]; color: string }) {
  return (
    <mesh position={position} castShadow>
      <sphereGeometry args={[radius, 10, 8]} />
      <meshStandardMaterial color={color} roughness={CLAY.roughness} metalness={CLAY.metalness} />
    </mesh>
  );
}

function GlowPanel({
  size,
  position,
  color,
  rotation,
}: {
  size: [number, number, number];
  position: [number, number, number];
  color: string;
  rotation?: [number, number, number];
}) {
  return (
    <mesh position={position} rotation={rotation}>
      <boxGeometry args={size} />
      <meshStandardMaterial
        color="#1d2430"
        emissive={color}
        emissiveIntensity={0.4}
        roughness={0.6}
        metalness={0}
      />
    </mesh>
  );
}

/** Four legs at a fixed inset: every prop that stands on the floor uses the same footprint. */
function Legs({ inset, height, color }: { inset: number; height: number; color: string }) {
  return (
    <>
      {[-inset, inset].map((x) =>
        [-inset, inset].map((z) => (
          <Box key={`${x}-${z}`} size={[0.08, height, 0.08]} position={[x, height / 2, z]} color={color} />
        )),
      )}
    </>
  );
}

function PropBody({ prop, palette }: { prop: WorkstationProp; palette: Palette }) {
  const { wood, dark, paper, accent } = palette;

  switch (prop) {
    case "desk-storyboard":
      // Director: a wide desk and a pinned storyboard wall behind it.
      return (
        <>
          <Legs inset={0.62} height={0.3} color={dark} />
          <Box size={[1.5, 0.1, 0.9]} position={[0, 0.35, 0]} color={wood} />
          <Box size={[1.1, 0.7, 0.06]} position={[0, 0.72, -0.42]} color={paper} />
          {[-0.36, 0, 0.36].map((x) => (
            <Box key={x} size={[0.26, 0.34, 0.02]} position={[x, 0.76, -0.38]} color={accent} />
          ))}
        </>
      );
    case "terminal":
      // Research: a terminal plus a stack of paper.
      return (
        <>
          <Legs inset={0.62} height={0.3} color={dark} />
          <Box size={[1.5, 0.1, 0.9]} position={[0, 0.35, 0]} color={wood} />
          <Box size={[0.12, 0.14, 0.12]} position={[0, 0.47, 0.14]} color={dark} />
          <GlowPanel size={[0.7, 0.42, 0.05]} position={[0, 0.75, 0.16]} color={accent} />
          {[0, 1, 2].map((index) => (
            <Box
              key={index}
              size={[0.3, 0.03, 0.22]}
              position={[-0.5, 0.42 + index * 0.035, -0.14]}
              color={paper}
            />
          ))}
        </>
      );
    case "typewriter":
      // Writing: typewriter with a lamp.
      return (
        <>
          <Legs inset={0.62} height={0.3} color={dark} />
          <Box size={[1.5, 0.1, 0.9]} position={[0, 0.35, 0]} color={wood} />
          <Box size={[0.5, 0.16, 0.36]} position={[-0.1, 0.5, 0]} color={dark} />
          {[-0.13, -0.05, 0.03, 0.11].map((x) => (
            <Box key={x} size={[0.05, 0.04, 0.05]} position={[x, 0.6, 0.05]} color={paper} />
          ))}
          <Box size={[0.06, 0.3, 0.06]} position={[-0.6, 0.74, -0.28]} color={dark} />
          <Sphere radius={0.09} position={[-0.6, 0.92, -0.28]} color={accent} />
        </>
      );
    case "armchair":
      // Review: an armchair and a tablet on a small side table.
      return (
        <>
          <Box size={[0.9, 0.28, 0.8]} position={[0, 0.22, 0]} color={accent} />
          <Box size={[0.9, 0.6, 0.16]} position={[0, 0.6, -0.34]} color={accent} />
          <Box size={[0.14, 0.34, 0.7]} position={[-0.42, 0.5, 0]} color={accent} />
          <Box size={[0.14, 0.34, 0.7]} position={[0.42, 0.5, 0]} color={accent} />
          <Box size={[0.16, 0.36, 0.16]} position={[0.72, 0.18, 0]} color={dark} />
          <Box size={[0.34, 0.03, 0.26]} position={[0.72, 0.37, 0]} color={dark} />
          <Box size={[0.3, 0.02, 0.22]} position={[0.72, 0.39, 0]} color={paper} />
        </>
      );
    case "drafting":
      // Storyboard: a tilted drafting table with a sheet and a pencil.
      return (
        <>
          <Legs inset={0.5} height={0.32} color={dark} />
          <Box size={[1.2, 0.06, 0.85]} position={[0, 0.42, 0]} color={wood} rotation={[-0.34, 0, 0]} />
          <Box size={[0.95, 0.02, 0.6]} position={[0, 0.47, 0.02]} color={paper} rotation={[-0.34, 0, 0]} />
          <Cylinder radius={0.03} height={0.34} position={[0.36, 0.55, 0.2]} color={accent} rotation={[0, 0, Math.PI / 2]} />
        </>
      );
    case "dual-monitor":
      // Animation: two monitors and a lightbox.
      return (
        <>
          <Legs inset={0.62} height={0.3} color={dark} />
          <Box size={[1.5, 0.1, 0.9]} position={[0, 0.35, 0]} color={wood} />
          {[-0.34, 0.34].map((x) => (
            <GlowPanel key={x} size={[0.54, 0.36, 0.04]} position={[x, 0.72, -0.16]} color={accent} />
          ))}
          <Box size={[0.5, 0.03, 0.34]} position={[0, 0.42, 0.28]} color={paper} />
        </>
      );
    case "mic":
      // Audio: a mic on a boom, headphones on a stand.
      return (
        <>
          <Cylinder radius={0.16} height={0.05} position={[0, 0.03, 0]} color={dark} />
          <Cylinder radius={0.03} height={0.85} position={[0, 0.44, 0]} color={dark} />
          <Cylinder radius={0.03} height={0.5} position={[0.22, 0.86, 0]} color={dark} rotation={[0, 0, Math.PI / 2.3]} />
          <Sphere radius={0.09} position={[0.42, 0.93, 0]} color={accent} />
          <Cylinder radius={0.03} height={0.4} position={[-0.45, 0.2, 0]} color={dark} />
          <Box size={[0.24, 0.1, 0.16]} position={[-0.45, 0.42, 0]} color={paper} />
          <Box size={[0.5, 0.02, 0.24]} position={[0, 0.02, 0.34]} color={accent} />
        </>
      );
    case "timeline":
      // Edit: a wide timeline monitor with a scrub track.
      return (
        <>
          <Legs inset={0.62} height={0.3} color={dark} />
          <Box size={[1.5, 0.1, 0.9]} position={[0, 0.35, 0]} color={wood} />
          <GlowPanel size={[1.1, 0.5, 0.05]} position={[0, 0.72, -0.2]} color={accent} />
          <Box size={[1.1, 0.04, 0.12]} position={[0, 0.4, 0.24]} color={dark} />
          <Box size={[0.05, 0.03, 0.2]} position={[0.28, 0.42, 0.24]} color={paper} />
        </>
      );
    case "preview-wall":
      // QC: a wall of previews.
      return (
        <>
          <Box size={[1.5, 0.9, 0.08]} position={[0, 0.85, -0.4]} color={dark} />
          {[-0.44, 0, 0.44].map((x) =>
            [0.62, 1.02].map((y) => (
              <GlowPanel key={`${x}-${y}`} size={[0.36, 0.3, 0.03]} position={[x, y, -0.35]} color={accent} />
            )),
          )}
          <Legs inset={0.62} height={0.3} color={dark} />
          <Box size={[1.2, 0.08, 0.5]} position={[0, 0.34, 0.16]} color={wood} />
        </>
      );
    case "chute":
      // Publishing: a parcel chute and a status screen.
      return (
        <>
          <Box size={[1.2, 0.08, 0.9]} position={[0, 0.62, 0]} color={wood} rotation={[0.5, 0, 0]} />
          <Box size={[0.1, 0.62, 0.1]} position={[-0.5, 0.31, 0.3]} color={dark} />
          <Box size={[0.1, 0.62, 0.1]} position={[0.5, 0.31, 0.3]} color={dark} />
          <Box size={[0.34, 0.26, 0.26]} position={[0.1, 0.82, -0.06]} color={accent} />
          <GlowPanel size={[0.5, 0.32, 0.04]} position={[-0.4, 0.52, -0.3]} color={accent} />
        </>
      );
    default: {
      // Exhaustive check: a new prop member without a case is a type error, not a blank zone.
      const unreachable: never = prop;
      return unreachable;
    }
  }
}

/**
 * One workstation. When its zone has a persisted `working` character, a lit bead sweeps the
 * station; the sweep position and the lamp glow are read from the shared sampler ref, so they are
 * a pure function of elapsed time and a re-render cannot restart or desync them. A station whose
 * zone has no working character renders no bead at all: the motion does not merely stop, it does
 * not exist.
 */
export function Workstation({
  prop,
  palette,
  position,
  zoneId,
  motions,
}: {
  prop: WorkstationProp;
  palette: Palette;
  position: [number, number];
  zoneId: string;
  motions: { current: { stations: Record<string, number> } };
}) {
  const bead = useRef<Mesh>(null);
  const lamp = useRef<Mesh>(null);

  useFrame(() => {
    const progress = motions.current.stations[zoneId] ?? 0;
    if (bead.current) bead.current.position.x = -0.5 + progress;
    if (lamp.current) {
      // A lit lamp that pulses with the same phase: one clock, no independent timers.
      const glow = 0.5 + 0.5 * Math.sin(progress * Math.PI * 2);
      lamp.current.scale.setScalar(0.9 + glow * 0.25);
    }
  });

  return (
    <group position={[position[0], 0, position[1]]}>
      <PropBody prop={prop} palette={palette} />
      <mesh ref={bead} position={[-0.5, 0.98, 0]}>
        <sphereGeometry args={[0.045, 8, 6]} />
        <meshStandardMaterial
          color={palette.accent}
          emissive={palette.accent}
          emissiveIntensity={0.9}
          roughness={0.6}
          metalness={0}
        />
      </mesh>
      <mesh ref={lamp} position={[0, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.12, 10]} />
        <meshStandardMaterial
          color={palette.accent}
          emissive={palette.accent}
          emissiveIntensity={0.6}
          roughness={1}
          metalness={0}
        />
      </mesh>
    </group>
  );
}
