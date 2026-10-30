"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/states";
import { api, type StudioCatalog } from "@/lib/api";
import styles from "./page.module.css";

type Category = "all" | "renderers" | "templates" | "motion" | "characters";

const MOTION_GROUPS: Array<{ key: keyof StudioCatalog["motion"]; label: string }> = [
  { key: "poses", label: "Pose" },
  { key: "expressions", label: "Ekspresi" },
  { key: "presets", label: "Preset gerak" },
  { key: "beat_kinds", label: "Jenis beat" },
  { key: "camera_moves", label: "Gerak kamera" },
  { key: "transitions", label: "Transisi" },
];

function Values({ values, empty = "Tidak dilaporkan katalog." }: { values: string[]; empty?: string }) {
  return values.length ? <ul className={styles.values}>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <p className={styles.hint}>{empty}</p>;
}

export default function SkillsPage() {
  const [catalog, setCatalog] = useState<StudioCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category>("all");
  const [characterId, setCharacterId] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError(null);
    void api.catalog().then((result) => {
      if (cancelled) return;
      if (!result) {
        setError("API tidak mengembalikan katalog. Coba muat ulang.");
        return;
      }
      setCatalog(result);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : "Gagal memuat katalog bawaan.");
    });
    return () => { cancelled = true; };
  }, [attempt]);

  const needle = query.trim().toLocaleLowerCase();
  const matches = (...values: string[]) => values.some((value) => value.toLocaleLowerCase().includes(needle));
  const renderers = catalog?.renderers.filter((renderer) => matches(renderer.id, renderer.label, renderer.description)) ?? [];
  const templates = catalog?.templates.filter((template) => matches(template)) ?? [];
  const motion = MOTION_GROUPS.map((group) => ({ ...group, values: catalog?.motion[group.key].filter((value) => matches(value)) ?? [] }));
  const characters = catalog?.characters.filter((character) => matches(
    character.id, character.displayName, character.artStyle, character.version, character.license, character.provenance,
    ...character.poses, ...character.expressions, ...character.gestures, ...character.clothingVariants, ...character.mouthShapes,
  )) ?? [];
  const character = characters.find((candidate) => candidate.id === characterId) ?? characters[0];
  const show = (value: Category) => category === "all" || category === value;
  const resultCount = (show("renderers") ? renderers.length : 0)
    + (show("templates") ? templates.length : 0)
    + (show("motion") ? motion.reduce((total, group) => total + group.values.length, 0) : 0)
    + (show("characters") ? characters.length : 0);
  const isEmpty = catalog !== null && !catalog.renderers.length && !catalog.templates.length && !catalog.characters.length && MOTION_GROUPS.every((group) => !catalog.motion[group.key].length);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Katalog kemampuan bawaan</h1>
          <p>Referensi kontrak template, gerak, dan manifest karakter yang dikembalikan API lokal.</p>
        </div>
        <div className={styles.links}>
          <Link className={`btn btn-primary ${styles.button}`} href="/create">Buat job</Link>
          <Link className={`btn ${styles.button}`} href="/providers">Atur provider</Link>
        </div>
      </header>
      <p className={styles.boundary} role="note">Ini bukan MotionSkillRegistry atau daftar plugin terpasang. Isi katalog tidak membuktikan dependensi renderer tersedia atau render telah lolos validasi.</p>

      {error ? <ErrorState message={error} onRetry={() => setAttempt((value) => value + 1)} /> : !catalog ? <Loading label="Memuat katalog kemampuan bawaan…" /> : isEmpty ? (
        <Empty title="Katalog bawaan kosong" hint="API tidak melaporkan template, gerak, karakter, atau renderer. Periksa konfigurasi API lokal lalu muat ulang." />
      ) : (
        <>
          <div className={styles.filters} role="search" aria-label="Filter katalog">
            <label className={styles.fieldLabel}>
              Cari kemampuan
              <input className={`field ${styles.input}`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ID, pose, ekspresi, atau karakter" />
            </label>
            <label className={styles.fieldLabel}>
              Kelompok
              <select className={`field ${styles.input}`} value={category} onChange={(event) => setCategory(event.target.value as Category)}>
                <option value="all">Semua kelompok</option>
                <option value="renderers">Renderer</option>
                <option value="templates">Template</option>
                <option value="motion">Gerak</option>
                <option value="characters">Karakter</option>
              </select>
            </label>
            <button type="button" className={`btn ${styles.button}`} disabled={!query && category === "all"} onClick={() => { setQuery(""); setCategory("all"); }}>Reset filter</button>
          </div>
          <p className={styles.result} role="status">{resultCount} entri cocok dengan filter. Entri gerak dihitung per kelompok.</p>
          {!resultCount ? <Empty title="Tidak ada kemampuan yang cocok" hint="Ubah kata pencarian atau reset filter untuk melihat katalog kembali." /> : null}

          {show("renderers") && renderers.length ? (
            <section className={styles.section} aria-labelledby="renderers-heading">
              <h2 id="renderers-heading">Renderer bawaan</h2>
              <p className={styles.hint}>Pilihan renderer untuk job baru. Daftar ini bukan pemeriksaan kesiapan runtime.</p>
              <dl className={styles.renderers}>{renderers.map((renderer) => (
                <div key={renderer.id}>
                  <dt>{renderer.label} <span className={styles.identifier}>{renderer.id}</span></dt>
                  <dd>{renderer.description || "Deskripsi tidak dilaporkan API."}</dd>
                </div>
              ))}</dl>
            </section>
          ) : null}

          {show("templates") && templates.length ? (
            <section className={styles.section} aria-labelledby="templates-heading">
              <h2 id="templates-heading">ID template</h2>
              <p className={styles.hint}>Identifier kontrak scene. Pilihan renderer dibuat terpisah saat membuat job.</p>
              <Values values={templates} />
            </section>
          ) : null}

          {show("motion") && motion.some((group) => group.values.length) ? (
            <section className={styles.section} aria-labelledby="motion-heading">
              <h2 id="motion-heading">Kosakata gerak</h2>
              <p className={styles.hint}>Kemampuan kontrak dan emitter bawaan. Dukungan pose dan ekspresi karakter tertentu tercantum di manifest karakter di bawah.</p>
              <div className={styles.motion}>{motion.filter((group) => group.values.length).map((group) => (
                <div key={group.key}>
                  <h3>{group.label}</h3>
                  <Values values={group.values} />
                </div>
              ))}</div>
            </section>
          ) : null}

          {show("characters") && characters.length ? (
            <section className={styles.section} aria-labelledby="characters-heading">
              <h2 id="characters-heading">Manifest karakter</h2>
              <label className={`${styles.fieldLabel} ${styles.characterSelect}`}>
                Pilih karakter
                <select className={`field ${styles.input}`} value={character?.id ?? ""} onChange={(event) => setCharacterId(event.target.value)}>
                  {characters.map((item) => <option key={item.id} value={item.id}>{item.displayName || item.id} ({item.id})</option>)}
                </select>
              </label>
              {character ? (
                <article aria-label={`Manifest ${character.id}`}>
                  <h3 className={styles.characterName}>{character.displayName || character.id}</h3>
                  <dl className={styles.metadata}>
                    <dt>ID</dt><dd>{character.id}</dd>
                    <dt>Versi manifest</dt><dd>{character.version || "Tidak dilaporkan"}</dd>
                    <dt>Gaya</dt><dd>{character.artStyle || "Tidak dilaporkan"}</dd>
                    <dt>Lisensi</dt><dd>{character.license || "Tidak dilaporkan"}</dd>
                    <dt>Provenans</dt><dd>{character.provenance || "Tidak dilaporkan"}</dd>
                  </dl>
                  <div className={styles.motion}>
                    <div><h3>Pose karakter</h3><Values values={character.poses} /></div>
                    <div><h3>Ekspresi karakter</h3><Values values={character.expressions} /></div>
                    <div><h3>Gestur</h3><Values values={character.gestures} /></div>
                    <div><h3>Varian pakaian</h3><Values values={character.clothingVariants} /></div>
                    <div><h3>Bentuk mulut</h3><Values values={character.mouthShapes} /></div>
                  </div>
                </article>
              ) : null}
            </section>
          ) : null}
        </>
      )}
      {catalog && isEmpty ? <button type="button" className={`btn ${styles.button}`} onClick={() => { setCatalog(null); setAttempt((value) => value + 1); }}>Muat ulang katalog</button> : null}
    </div>
  );
}
