"use client";

import { Canvas } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";
import { useMemo } from "react";
import type { AgentView } from "@/lib/api";
import { AGENT_ZONE, ZONES, agentPosition } from "./zones";

/**
 * The room. Clay materials, soft light, low poly.
 *
 * Everything drawn here comes from `agents`, which comes from persisted events. There is no
 * animation that implies work: a character's motion state is a function of its status.
 */

const STATE_COLOR: Record<string, string> = {
  working: "#4a938c",
  waiting: "#8b95a6",
  reviewing: "#f4bc68",
  blocked: "#d9a03f",
  failed: "#c05c56",
  completed: "#4a9d7f",
};

function Desk({ position, accent }: { position: [number, number]; accent: string }) {
  return (
    <group position={[position[0], 0, position[1]]}>
      <mesh position={[0, 0.35, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.5, 0.1, 0.9]} />
        <meshStandardMaterial color="#b08454" roughness={0.85} metalness={0} />
      </mesh>
      {[-0.6, 0.6].map((x) =>
        [-0.35, 0.35].map((z) => (
          <mesh key={`${x}-${z}`} position={[x, 0.15, z]} castShadow>
            <boxGeometry args={[0.08, 0.3, 0.08]} />
            <meshStandardMaterial color="#8d6a44" roughness={0.9} metalness={0} />
          </mesh>
        )),
      )}
      {/* Monitor: a small glowing panel, the only emissive surface in the room. */}
      <mesh position={[0, 0.62, -0.2]} castShadow>
        <boxGeometry args={[0.7, 0.42, 0.04]} />
        <meshStandardMaterial
          color="#1d2430"
          emissive={accent}
          emissiveIntensity={0.35}
          roughness={0.6}
          metalness={0}
        />
      </mesh>
    </group>
  );
}

function Character({
  position,
  status,
  stale,
  onSelect,
  label,
}: {
  position: [number, number];
  status: string;
  stale: boolean;
  onSelect: () => void;
  label: string;
}) {
  const color = STATE_COLOR[status] ?? "#8b95a6";
  const working = status === "working" && !stale;
  // Only a working character moves. A waiting one is still — a bobbing idle would read as activity.
  const bob = working ? 0.02 : 0;
  return (
    <group
      position={[position[0], 0, position[1]]}
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
      <mesh position={[0, 0.55 + bob, 0]} castShadow>
        <capsuleGeometry args={[0.18, 0.35, 4, 8]} />
        <meshStandardMaterial color={color} roughness={0.8} metalness={0} />
      </mesh>
      <mesh position={[0, 0.92 + bob, 0]} castShadow>
        <sphereGeometry args={[0.16, 16, 16]} />
        <meshStandardMaterial color="#e8d7c3" roughness={0.75} metalness={0} />
      </mesh>
      {stale ? (
        <mesh position={[0, 1.2, 0]}>
          <sphereGeometry args={[0.04, 8, 8]} />
          <meshStandardMaterial color="#d9a03f" emissive="#d9a03f" emissiveIntensity={0.8} />
        </mesh>
      ) : null}
      <Html3D label={label} status={status} />
    </group>
  );
}

function Html3D({ label, status }: { label: string; status: string }) {
  // A tiny floating marker instead of a DOM overlay: keeps the scene self-contained and avoids
  // layout thrash during orbit.
  return (
    <mesh position={[0, 1.35, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[0.05, 0.08, 12]} />
      <meshBasicMaterial color={STATE_COLOR[status] ?? "#8b95a6"} transparent opacity={0.9} />
    </mesh>
  );
}

function ZoneFloor({ zone }: { zone: (typeof ZONES)[number] }) {
  return (
    <mesh
      position={[zone.position[0], 0.005, zone.position[1]]}
      rotation={[-Math.PI / 2, 0, 0]}
      receiveShadow
    >
      <planeGeometry args={[2.6, 2.2]} />
      <meshStandardMaterial color={zone.accent} transparent opacity={0.07} roughness={1} />
    </mesh>
  );
}

export function StudioScene({
  agents,
  onSelectAgent,
  quality,
}: {
  agents: AgentView[];
  onSelectAgent: (agentId: string) => void;
  quality: "high" | "medium" | "low";
}) {
  const dpr = quality === "high" ? 1.5 : quality === "medium" ? 1.25 : 1;
  const shadows = quality === "high";

  const characters = useMemo(
    () =>
      agents.map((agent) => ({
        agent,
        position: agentPosition(agent.agent_id),
      })),
    [agents],
  );

  return (
    <Canvas
      shadows={shadows}
      dpr={dpr}
      camera={{ position: [9, 9, 11], fov: 32 }}
      gl={{ antialias: quality !== "low", powerPreference: "default" }}
      frameloop={quality === "low" ? "demand" : "always"}
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

      {/* Floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[16, 12]} />
        <meshStandardMaterial color="#e2d7c6" roughness={1} metalness={0} />
      </mesh>

      {ZONES.map((zone) => (
        <ZoneFloor key={zone.id} zone={zone} />
      ))}
      {ZONES.map((zone) => (
        <Desk key={`desk-${zone.id}`} position={zone.position} accent={zone.accent} />
      ))}
      {characters.map(({ agent, position }) => (
        <Character
          key={agent.agent_id}
          position={position}
          status={agent.status}
          stale={agent.stale}
          label={agent.agent_id}
          onSelect={() => onSelectAgent(agent.agent_id)}
        />
      ))}

      {shadows ? (
        <ContactShadows position={[0, 0.01, 0]} opacity={0.35} scale={20} blur={2.4} far={6} />
      ) : null}

      <OrbitControls
        enablePan={false}
        minPolarAngle={Math.PI / 5}
        maxPolarAngle={Math.PI / 2.4}
        minAzimuthAngle={-Math.PI / 5}
        maxAzimuthAngle={Math.PI / 5}
        minDistance={9}
        maxDistance={18}
      />
    </Canvas>
  );
}
