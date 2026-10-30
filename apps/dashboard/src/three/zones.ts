/** Room layout and the agent↔zone mapping, in one place so the scene and the inspector agree. */

export type ZoneId =
  | "director"
  | "research"
  | "writing"
  | "review"
  | "storyboard"
  | "animation"
  | "audio"
  | "edit"
  | "qc"
  | "publishing";

export type Zone = {
  id: ZoneId;
  label: string;
  /** Isometric grid position, in room units. */
  position: [number, number];
  agents: string[];
  /** Existing operator surface for this production zone. */
  href: string;
  accent: string;
  /** Low-poly workstation prop, per `docs/STUDIO_3D.md` §2. */
  prop: WorkstationProp;
};

export type WorkstationProp =
  | "desk-storyboard"
  | "terminal"
  | "typewriter"
  | "armchair"
  | "drafting"
  | "dual-monitor"
  | "mic"
  | "timeline"
  | "preview-wall"
  | "chute";

export const ZONES: Zone[] = [
  { id: "director", label: "Ruang Direktur", position: [-4.5, -3], agents: ["DirectorAgent", "FactoryOrchestrator"], href: "/", accent: "#f4bc68", prop: "desk-storyboard" },
  { id: "research", label: "Meja Riset", position: [-1.5, -3], agents: ["ResearchAgent", "TopicSelectionAgent"], href: "/agents", accent: "#4a938c", prop: "terminal" },
  { id: "writing", label: "Ruang Tulis", position: [1.5, -3], agents: ["ScriptAgent"], href: "/agents", accent: "#f4bc68", prop: "typewriter" },
  { id: "review", label: "Sudut Review", position: [4.5, -3], agents: ["CreativeDirectorAgent"], href: "/agents", accent: "#d99a3f", prop: "armchair" },
  { id: "storyboard", label: "Meja Storyboard", position: [-4.5, 0], agents: ["StoryboardAgent"], href: "/storyboard", accent: "#4a938c", prop: "drafting" },
  { id: "animation", label: "Bay Animasi", position: [-1.5, 0], agents: ["AnimationAgent", "AssetAgent"], href: "/assets", accent: "#2f6f6a", prop: "dual-monitor" },
  { id: "audio", label: "Booth Audio", position: [1.5, 0], agents: ["AudioAgent"], href: "/assets", accent: "#4a938c", prop: "mic" },
  { id: "edit", label: "Suite Editing", position: [4.5, 0], agents: ["EditorAgent"], href: "/jobs", accent: "#2f6f6a", prop: "timeline" },
  { id: "qc", label: "Ruang QC", position: [-3, 3], agents: ["QualityAgent"], href: "/jobs", accent: "#d9a03f", prop: "preview-wall" },
  { id: "publishing", label: "Dermaga Publikasi", position: [3, 3], agents: ["MetadataAgent", "PublisherAgent"], href: "/agents", accent: "#f4bc68", prop: "chute" },
];

export function zoneHref(zone: Zone, jobId?: string): string {
  const scoped = ["/storyboard", "/assets", "/jobs"].includes(zone.href);
  return scoped && jobId ? `${zone.href}?job_id=${encodeURIComponent(jobId)}` : zone.href;
}

export const AGENT_ZONE: Record<string, ZoneId> = ZONES.reduce(
  (acc, zone) => {
    for (const agent of zone.agents) acc[agent] = zone.id;
    return acc;
  },
  {} as Record<string, ZoneId>,
);

export const AGENT_LABEL: Record<string, string> = {
  DirectorAgent: "Direktur",
  FactoryOrchestrator: "Orkestrator",
  ResearchAgent: "Riset",
  TopicSelectionAgent: "Pemilih Topik",
  ScriptAgent: "Penulis Skrip",
  CreativeDirectorAgent: "Direktur Kreatif",
  StoryboardAgent: "Storyboard",
  AnimationAgent: "Animator",
  AssetAgent: "Aset",
  AudioAgent: "Audio",
  EditorAgent: "Editor",
  QualityAgent: "Kontrol Kualitas",
  MetadataAgent: "Metadata",
  PublisherAgent: "Publisher",
};

/** Where an agent stands: its zone position, offset so two agents in one zone do not overlap. */
export function agentPosition(agentId: string): [number, number] {
  const zone = ZONES.find((candidate) => candidate.id === AGENT_ZONE[agentId]);
  if (!zone) return [0, 0];
  const index = zone.agents.indexOf(agentId);
  const offset = index <= 0 ? 0 : index * 0.9;
  return [zone.position[0] + offset, zone.position[1] + 0.8];
}
