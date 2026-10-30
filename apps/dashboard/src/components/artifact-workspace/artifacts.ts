export type JsonObject = Record<string, unknown>;
export function isObject(value: unknown): value is JsonObject {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
export function objectRows(value: unknown, field: string): JsonObject[] {
  if (!Array.isArray(value) || !value.every(isObject)) throw new Error(`${field} harus berupa daftar objek.`);
  return value;
}
export type Scene = JsonObject & {
  sceneId: string; template: string; segment: string; startFrame: number; durationInFrames: number;
  text: Array<JsonObject & { text: string }>; assetRefs: string[];
  camera?: JsonObject; motion?: JsonObject & { beats?: JsonObject[] }; transition?: JsonObject;
};
export type Storyboard = { fps: number; scenes: Scene[]; raw: JsonObject };
export function readStoryboard(value: unknown): Storyboard {
  if (!isObject(value)) throw new Error("Storyboard harus berupa objek.");
  if (typeof value.fps !== "number" || !Number.isFinite(value.fps) || value.fps <= 0) throw new Error("FPS storyboard tidak valid.");
  const seen = new Set<string>();
  const scenes = objectRows(value.scenes, "scenes").map((scene) => {
    if (typeof scene.sceneId !== "string" || !scene.sceneId || seen.has(scene.sceneId)) throw new Error("ID scene kosong atau duplikat.");
    seen.add(scene.sceneId);
    if (typeof scene.template !== "string" || typeof scene.segment !== "string") throw new Error(`Template/segmen ${scene.sceneId} tidak valid.`);
    if (typeof scene.startFrame !== "number" || !Number.isInteger(scene.startFrame) || scene.startFrame < 0 || typeof scene.durationInFrames !== "number" || !Number.isInteger(scene.durationInFrames) || scene.durationInFrames <= 0) throw new Error(`Timing ${scene.sceneId} tidak valid.`);
    const text = objectRows(scene.text, "text");
    if (!text.every((item) => typeof item.text === "string")) throw new Error(`Teks ${scene.sceneId} tidak valid.`);
    if (!Array.isArray(scene.assetRefs) || !scene.assetRefs.every((ref) => typeof ref === "string")) throw new Error(`Referensi aset ${scene.sceneId} tidak valid.`);
    for (const field of ["camera", "motion", "transition"]) {
      if (scene[field] !== undefined && !isObject(scene[field])) throw new Error(`${field} ${scene.sceneId} tidak valid.`);
    }
    if (isObject(scene.motion) && scene.motion.beats !== undefined) objectRows(scene.motion.beats, "motion.beats");
    return scene as Scene;
  });
  return { fps: value.fps, scenes, raw: value };
}

export type AssetsManifest = JsonObject & { characters: JsonObject[]; backgrounds: JsonObject[]; audio: JsonObject[] };
export type AudioManifest = JsonObject & { narration: JsonObject; mix: JsonObject; scenes: JsonObject[] };
export function readAssets(value: unknown): AssetsManifest {
  if (!isObject(value)) throw new Error("Manifest aset harus berupa objek.");
  for (const field of ["characters", "backgrounds", "audio"]) objectRows(value[field], field);
  return value as AssetsManifest;
}
export function readAudio(value: unknown): AudioManifest {
  if (!isObject(value) || !isObject(value.narration) || !isObject(value.mix)) throw new Error("Narasi/mix audio tidak valid.");
  if (typeof value.narration.src !== "string" || typeof value.narration.durationMs !== "number" || !Number.isFinite(value.narration.durationMs) || value.narration.durationMs <= 0) throw new Error("Sumber/durasi narasi tidak valid.");
  const scenes = objectRows(value.scenes, "audio.scenes");
  let previousEnd = 0;
  for (const scene of scenes) {
    if (typeof scene.sceneId !== "string" || typeof scene.startMs !== "number" || !Number.isFinite(scene.startMs) || typeof scene.endMs !== "number" || !Number.isFinite(scene.endMs) || scene.startMs < previousEnd || scene.endMs <= scene.startMs || scene.endMs > value.narration.durationMs) throw new Error("Timing scene audio tidak valid.");
    previousEnd = scene.endMs;
  }
  return value as AudioManifest;
}
