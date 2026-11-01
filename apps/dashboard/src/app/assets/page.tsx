"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type StudioCatalog } from "@/lib/api";
import { Workspace, JobHeading, Notice, ArtifactNotice, Metadata, JsonDetails } from "@/components/artifact-workspace/Workspace";
import { useArtifactJob, failureMessage } from "@/components/artifact-workspace/useArtifactJob";
import { readAssets, readAudio, readStoryboard, isObject, type JsonObject, type Storyboard, type AssetsManifest, type AudioManifest } from "@/components/artifact-workspace/artifacts";
import styles from "@/components/artifact-workspace/workspace.module.css";

const ARTIFACTS = ["assets.json", "audio.json", "storyboard.json", "render-props.json"] as const;

export default function AssetsPage() {
  return <Workspace title="Aset produksi" description="Pisahkan kemampuan karakter terpasang dari manifest aset dan narasi yang benar-benar dihasilkan job. Referensi scene tidak berarti berkas aset sudah diproduksi." library={<InstalledObjects />}>
    {(id) => <JobAssets id={id} />}
  </Workspace>;
}

function InstalledObjects() {
  const [catalog, setCatalog] = useState<StudioCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    api.catalog().then((result) => {
      if (!Array.isArray(result.objects) || !result.objects.every((entry) => isObject(entry) && [entry.id, entry.label].every((item) => typeof item === "string"))) throw new Error("Daftar objek katalog tidak valid.");
      if (active) { setCatalog(result); setError(null); }
    }).catch((failure: unknown) => { if (active) setError(failureMessage(failure)); });
    return () => { active = false; };
  }, [revision]);
  return <section className={styles.section} aria-labelledby="installed-objects"><h2 id="installed-objects">Objek terpasang</h2>
    <p>Pustaka objek yang bisa digambar renderer. Katalog bukan bukti dependency, render, atau QA telah berhasil.</p>
    {error ? <Notice error onRetry={() => setRevision((value) => value + 1)}>Katalog tidak dapat dibaca: {error}</Notice> : !catalog ? <p role="status">Memuat pustaka objek…</p> : catalog.objects.length === 0 ? <Notice>Tidak ada objek dalam katalog terpasang.</Notice> : <div className={styles.cards}>{catalog.objects.map((entry) => <article className={styles.card} key={entry.id}>
      <h3>{entry.label}</h3><p>{entry.id}</p>
      <Metadata value={{ latar: (catalog.environments ?? []).join(", ") || "Tidak dicantumkan" }} />
    </article>)}</div>}
  </section>;
}

function JobAssets({ id }: { id: string }) {
  const { detail, artifacts, error, loading, reload } = useArtifactJob(id, ARTIFACTS);
  if (loading) return <p role="status">Memuat aset untuk {id}…</p>;
  if (error || !detail) return <Notice error onRetry={reload}>Job {id} tidak dapat dibaca: {error ?? "Detail tidak tersedia."}</Notice>;
  let assets: AssetsManifest | undefined;
  let audio: AudioManifest | undefined;
  let board: Storyboard | undefined;
  const invalid: string[] = [];
  for (const name of ARTIFACTS) {
    const data = artifacts[name]?.data;
    if (!data) continue;
    try {
      if (name === "assets.json") assets = readAssets(data);
      else if (name === "audio.json") audio = readAudio(data);
      else board = readStoryboard(name === "render-props.json" ? data.storyboard : data);
    } catch (failure) { invalid.push(`${name}: ${failureMessage(failure)}`); }
  }
  const groups = assets ? [{ name: "Objek job", prefix: "object", rows: assets.objects }, { name: "Latar job", prefix: "bg", rows: assets.backgrounds }, { name: "Musik dan efek job", prefix: "audio", rows: assets.audio }] : [];
  return <>
    <JobHeading detail={detail} reload={reload} />
    {ARTIFACTS.map((name) => <ArtifactNotice key={name} name={name} result={artifacts[name]} onRetry={reload} />)}
    {invalid.map((message) => <Notice key={message} error onRetry={reload}>Artefak tidak valid: {message}</Notice>)}
    {assets && <section className={styles.section}><h2>Manifest aset job</h2><p>assets.json tersedia. Entri berikut adalah catatan manifest, bukan jaminan berkas media dapat dibuka.</p>
      <Metadata value={{ manifest_sha256: assets.manifest_sha256 || "Tidak dicantumkan", dibuat: assets.created_at }} />
      {groups.map((group) => <section className={styles.section} key={group.prefix}><h3>{group.name}</h3>{group.rows.length === 0 ? <p>Tidak ada entri pada manifest job.</p> : <div className={styles.cards}>{group.rows.map((asset, index) => <article key={index} className={styles.card}>
        <h3>{typeof asset.id === "string" ? asset.id : `Entri ${index + 1}`}</h3>
        <Metadata value={{ ...asset, license: asset.license ?? "Tidak dicantumkan pada manifest job" }} />
        <h4>Dipakai pada scene</h4><SceneReferences board={board} asset={asset} prefix={group.prefix} />
      </article>)}</div>}</section>)}
      <Provenance value={assets.provenance} />
    </section>}
    {audio && <section className={styles.section}><h2>Audio job</h2><p>audio.json tersedia. Nama berkas narasi adalah referensi lokal; halaman ini tidak mengubahnya menjadi URL eksternal.</p>
      <div className={styles.cards}><article className={styles.card}><h3>Narasi</h3><Metadata value={{ ...audio.narration, berkas_tercatat: typeof audio.narration.src === "string" ? detail.artifacts.includes(audio.narration.src) ? "Ada pada daftar berkas job" : "Tidak ada pada daftar berkas job" : "Tidak dicantumkan" }} /></article>
      <article className={styles.card}><h3>Mix tersimpan</h3><Metadata value={audio.mix} /></article></div>
      <h3>Timing per scene</h3>{audio.scenes.length ? <ol className={styles.refs}>{audio.scenes.map((scene, index) => <li key={index}><Metadata value={scene} /></li>)}</ol> : <p>Tidak ada timing scene dalam audio.json.</p>}
      <Provenance value={audio.provenance} />
      <JsonDetails label="JSON audio tersimpan" value={audio} />
    </section>}
    {board && <section className={styles.section}><h2>Referensi per scene</h2><p>Referensi yang dideklarasikan storyboard; latar prosedural dapat disebut tanpa entri berkas di assets.json.</p>
      <ol className={styles.refs}>{board.scenes.map((scene) => <li key={scene.sceneId}><strong>{scene.sceneId}</strong> · {scene.template}
        {scene.assetRefs.length ? <ul className={styles.refs}>{scene.assetRefs.map((ref, index) => {
          const present = groups.some((group) => group.rows.some((asset) => typeof asset.id === "string" && `${group.prefix}:${asset.id}` === ref));
          return <li key={index}>{ref} · {!assets ? "Manifest job belum dapat dibaca" : present ? "Entri tersedia di manifest job" : "Tidak tercantum di manifest job"}</li>;
        })}</ul> : <p>Tidak ada referensi aset.</p>}
      </li>)}</ol>
      <Link className={styles.sceneLink} href={`/storyboard?job_id=${encodeURIComponent(id)}`}>Baca storyboard job</Link>
    </section>}
  </>;
}

function SceneReferences({ board, asset, prefix }: { board?: Storyboard; asset: JsonObject; prefix: string }) {
  if (!board) return <p>Storyboard belum dapat dibaca.</p>;
  const scenes = board.scenes.filter((scene) => typeof asset.id === "string" && scene.assetRefs.includes(`${prefix}:${asset.id}`));
  return <p>{scenes.length ? scenes.map((scene) => scene.sceneId).join(", ") : "Tidak dirujuk lewat assetRefs pada storyboard."}</p>;
}

function Provenance({ value }: { value: unknown }) {
  return <section className={styles.section}><h3>Provenance tersimpan</h3>{isObject(value) && Object.keys(value).length ? <Metadata value={value} /> : <p>Tidak dicantumkan dalam artefak. Tidak ada lisensi atau sumber yang diasumsikan.</p>}</section>;
}
