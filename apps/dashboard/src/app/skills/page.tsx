"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/states";
import { api, type StudioCatalog } from "@/lib/api";
import styles from "./page.module.css";

type Category = "all" | "renderers" | "templates" | "objects" | "visual";

const VISUAL_GROUPS: Array<{ key: keyof StudioCatalog["visual"]; label: string }> = [
  { key: "beat_kinds", label: "Jenis beat" },
  { key: "camera_moves", label: "Gerak kamera" },
  { key: "transitions", label: "Transisi" },
  { key: "text_roles", label: "Peran teks" },
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
  const objects = catalog?.objects.filter((object) => matches(object.id, object.label)) ?? [];
  const environments = catalog?.environments.filter((environment) => matches(environment)) ?? [];
  const visual = VISUAL_GROUPS.map((group) => ({ ...group, values: catalog?.visual[group.key].filter((value) => matches(value)) ?? [] }));
  const show = (value: Category) => category === "all" || category === value;
  const resultCount = (show("renderers") ? renderers.length : 0)
    + (show("templates") ? templates.length : 0)
    + (show("objects") ? objects.length : 0)
    + (show("visual") ? visual.reduce((total, group) => total + group.values.length, 0) + environments.length : 0);
  const isEmpty = catalog !== null && !catalog.renderers.length && !catalog.templates.length && !catalog.objects.length;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Katalog kemampuan bawaan</h1>
          <p>Referensi kontrak template, pustaka objek, dan latar yang dikembalikan API lokal.</p>
        </div>
        <div className={styles.links}>
          <Link className={`btn btn-primary ${styles.button}`} href="/create">Buat job</Link>
          <Link className={`btn ${styles.button}`} href="/providers">Atur provider</Link>
        </div>
      </header>
      <p className={styles.boundary} role="note">Ini bukan MotionSkillRegistry atau daftar plugin terpasang. Isi katalog tidak membuktikan dependensi renderer tersedia atau render telah lolos validasi.</p>

      {error ? <ErrorState message={error} onRetry={() => setAttempt((value) => value + 1)} /> : !catalog ? <Loading label="Memuat katalog kemampuan bawaan…" /> : isEmpty ? (
        <Empty title="Katalog bawaan kosong" hint="API tidak melaporkan template, objek, atau renderer. Periksa konfigurasi API lokal lalu muat ulang." />
      ) : (
        <>
          <div className={styles.filters} role="search" aria-label="Filter katalog">
            <label className={styles.fieldLabel}>
              Cari kemampuan
              <input className={`field ${styles.input}`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ID objek, template, atau latar" />
            </label>
            <label className={styles.fieldLabel}>
              Kelompok
              <select className={`field ${styles.input}`} value={category} onChange={(event) => setCategory(event.target.value as Category)}>
                <option value="all">Semua kelompok</option>
                <option value="renderers">Renderer</option>
                <option value="templates">Template</option>
                <option value="objects">Objek</option>
                <option value="visual">Kosakata visual</option>
              </select>
            </label>
            <button type="button" className={`btn ${styles.button}`} disabled={!query && category === "all"} onClick={() => { setQuery(""); setCategory("all"); }}>Reset filter</button>
          </div>
          <p className={styles.result} role="status">{resultCount} entri cocok dengan filter. Entri visual dihitung per kelompok.</p>
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

          {show("objects") && objects.length ? (
            <section className={styles.section} aria-labelledby="objects-heading">
              <h2 id="objects-heading">Pustaka objek</h2>
              <p className={styles.hint}>Objek yang bisa digambar renderer. Storyboard memilih dari daftar ini; jenis di luar daftar ditolak gerbang QC.</p>
              <dl className={styles.renderers}>{objects.map((object) => (
                <div key={object.id}>
                  <dt>{object.label} <span className={styles.identifier}>{object.id}</span></dt>
                </div>
              ))}</dl>
            </section>
          ) : null}

          {show("visual") && (visual.some((group) => group.values.length) || environments.length) ? (
            <section className={styles.section} aria-labelledby="visual-heading">
              <h2 id="visual-heading">Kosakata visual</h2>
              <p className={styles.hint}>Kemampuan kontrak scene dan latar yang bisa dipakai objek.</p>
              <div className={styles.motion}>
                <div>
                  <h3>Latar</h3>
                  <Values values={environments} />
                </div>
                {visual.filter((group) => group.values.length).map((group) => (
                  <div key={group.key}>
                    <h3>{group.label}</h3>
                    <Values values={group.values} />
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}
      {catalog && isEmpty ? <button type="button" className={`btn ${styles.button}`} onClick={() => { setCatalog(null); setAttempt((value) => value + 1); }}>Muat ulang katalog</button> : null}
    </div>
  );
}
