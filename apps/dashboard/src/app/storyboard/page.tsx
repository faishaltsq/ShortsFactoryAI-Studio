"use client";

import Link from "next/link";
import { Workspace, JobHeading, Notice, ArtifactNotice, Metadata, JsonDetails } from "@/components/artifact-workspace/Workspace";
import { useArtifactJob, failureMessage } from "@/components/artifact-workspace/useArtifactJob";
import { readStoryboard, isObject, type Storyboard } from "@/components/artifact-workspace/artifacts";
import styles from "@/components/artifact-workspace/workspace.module.css";

const ARTIFACTS = ["storyboard.json", "render-props.json"] as const;

export default function StoryboardPage() {
  return <Workspace title="Storyboard" description="Baca urutan scene, teks, dan arahan gerak dari artefak job. Timing render ditampilkan bila render-props.json sudah tersedia; ini bukan pratinjau frame.">
    {(id) => <StoryboardJob id={id} />}
  </Workspace>;
}

function StoryboardJob({ id }: { id: string }) {
  const { detail, artifacts, error, loading, reload } = useArtifactJob(id, ARTIFACTS);
  if (loading) return <p role="status">Memuat storyboard untuk {id}…</p>;
  if (error || !detail) return <Notice error onRetry={reload}>Job {id} tidak dapat dibaca: {error ?? "Detail tidak tersedia."}</Notice>;

  const parsed: Partial<Record<(typeof ARTIFACTS)[number], Storyboard>> = {};
  const invalid: string[] = [];
  for (const name of ARTIFACTS) {
    const data = artifacts[name]?.data;
    if (!data) continue;
    try { parsed[name] = readStoryboard(name === "render-props.json" ? data.storyboard : data); }
    catch (failure) { invalid.push(`${name}: ${failureMessage(failure)}`); }
  }
  const board = parsed["render-props.json"] ?? parsed["storyboard.json"];
  const timed = !!parsed["render-props.json"];
  const totalFrames = board?.scenes.reduce((end, scene) => Math.max(end, scene.startFrame + scene.durationInFrames), 0) ?? 0;
  return <>
    <JobHeading detail={detail} reload={reload} />
    {ARTIFACTS.map((name) => <ArtifactNotice key={name} name={name} result={artifacts[name]} onRetry={reload} />)}
    {invalid.map((message) => <Notice key={message} error onRetry={reload}>Artefak tidak valid: {message}</Notice>)}
    {board && <>
      <section className={styles.section} aria-label="Sumber timeline">
        <h2>{timed ? "Timeline render dengan timing audio" : "Timeline rencana storyboard"}</h2>
        <p>Sumber: {timed ? "render-props.json" : "storyboard.json"}. {timed ? "Timing tersimpan untuk renderer, bukan bukti render atau QA berhasil." : "Durasi masih rencana; timing audio belum tersedia."}</p>
        <Metadata value={{ fps: board.fps, durasi: `${(totalFrames / board.fps).toFixed(2)} s`, frame: totalFrames, resolusi: typeof board.raw.width === "number" && typeof board.raw.height === "number" ? `${board.raw.width} × ${board.raw.height}` : "Tidak dicantumkan", tema: board.raw.theme }} />
      </section>
      {board.scenes.length === 0 ? <Notice>Artefak berisi daftar scene kosong.</Notice> : <div className={styles.columns}>
        <nav className={styles.index} aria-label="Timeline scene"><h2>Urutan scene</h2><p>Batang menunjukkan durasi relatif, bukan frame video.</p><ol>
          {board.scenes.map((scene, index) => <li key={scene.sceneId}><a className={styles.sceneLink} href={`#shot-${index}`}>
            <strong>{index + 1}. {scene.sceneId}</strong><small>{(scene.startFrame / board.fps).toFixed(2)} s · {(scene.durationInFrames / board.fps).toFixed(2)} s · {scene.template}</small>
            <span className={styles.track} aria-hidden="true"><span style={{ width: `${scene.durationInFrames / Math.max(totalFrames, 1) * 100}%` }} /></span>
          </a></li>)}
        </ol></nav>
        <div className={styles.shots}>{board.scenes.map((scene, index) => {
          const data = isObject(scene.data) ? scene.data : {};
          return <article key={scene.sceneId} id={`shot-${index}`} className={styles.shot}>
            <header><h2>{index + 1}. {scene.sceneId}</h2><span>{scene.template} · {scene.segment}</span></header>
            <Metadata value={{ mulai: `${(scene.startFrame / board.fps).toFixed(2)} s (frame ${scene.startFrame})`, durasi: `${(scene.durationInFrames / board.fps).toFixed(2)} s (${scene.durationInFrames} frame)` }} />
            <div className={styles.textList}>{scene.text.length ? scene.text.map((text, textIndex) => <div key={textIndex}><small>{typeof text.role === "string" ? text.role : "Teks"}{typeof text.atFrame === "number" ? ` · frame lokal ${text.atFrame}` : ""}</small><blockquote>{text.text}</blockquote></div>) : <p>Tidak ada elemen teks pada scene ini.</p>}</div>
            <h3>Kamera dan gerak yang dideklarasikan</h3>
            <Metadata value={{ shot: scene.camera?.shot, gerak: scene.camera?.move, target: scene.camera?.target, amplitudo: scene.camera?.amplitude, easing: scene.camera?.ease, kontinuitas: scene.motion?.continuity, energi: scene.motion?.energy, transisi: scene.transition?.kind, frame_transisi: scene.transition?.frames }} />
            <h4>Motion beats</h4>
            {scene.motion?.beats?.length ? <ol className={styles.refs}>{scene.motion.beats.map((beat, beatIndex) => <li key={beatIndex}><Metadata value={beat} /></li>)}</ol> : <p>Tidak ada motion beat yang dicantumkan.</p>}
            {Object.keys(data).length > 0 && <><h4>Arahan template</h4><Metadata value={data} /></>}
            <h4>Referensi aset</h4><p>{scene.assetRefs.length ? scene.assetRefs.join(", ") : "Tidak ada referensi aset."}</p>
            <Link className={styles.sceneLink} href={`/assets?job_id=${encodeURIComponent(id)}`}>Periksa aset job</Link>
            <JsonDetails label="JSON scene tersimpan" value={scene} />
          </article>;
        })}</div>
      </div>}
      {parsed["storyboard.json"] && <JsonDetails label="Storyboard asli sebelum timing audio" value={parsed["storyboard.json"].raw} />}
    </>}
  </>;
}
