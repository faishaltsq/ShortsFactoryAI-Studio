"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { ErrorState, Loading } from "@/components/states";
import { api, type StudioBudget, type StudioRenderSettings, type StudioSettings } from "@/lib/api";
import styles from "./page.module.css";

type Draft = {
  tokens: string;
  cost: string;
  unlimited: boolean;
  ram: string;
  vram: string;
  unmeasuredGpu: boolean;
};

type FieldErrors = Partial<Record<"tokens" | "cost" | "ram" | "vram", string>>;

function toDraft(settings: { budget: StudioBudget; render: StudioRenderSettings }): Draft {
  return {
    tokens: settings.budget.max_daily_tokens === null ? "" : String(settings.budget.max_daily_tokens),
    cost: settings.budget.max_daily_cost_usd === null ? "" : String(settings.budget.max_daily_cost_usd),
    unlimited: settings.budget.unlimited,
    ram: String(settings.render.min_free_ram_mib),
    vram: String(settings.render.min_free_vram_mib),
    unmeasuredGpu: settings.render.allow_unmeasured_gpu,
  };
}

function positiveNumber(value: string, integer: boolean): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 && (!integer || Number.isSafeInteger(parsed))
    ? parsed
    : null;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<StudioSettings | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const errorSummary = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    void api.settings().then((result) => {
      if (cancelled) return;
      if (!result) {
        setLoadError("API tidak mengembalikan pengaturan. Coba muat ulang.");
        return;
      }
      setSettings(result);
      setDraft(toDraft(result));
    }).catch((error: unknown) => {
      if (!cancelled) setLoadError(error instanceof Error ? error.message : "Gagal memuat pengaturan.");
    });
    return () => { cancelled = true; };
  }, [attempt]);

  useEffect(() => {
    if (Object.keys(fieldErrors).length) errorSummary.current?.focus();
  }, [fieldErrors]);

  const patch = (change: Partial<Draft>) => {
    if (pending.current) return;
    setDraft((current) => current ? { ...current, ...change } : current);
    setFieldErrors({});
    setSaveError(null);
    setSaved(false);
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft || pending.current) return;
    const tokens = draft.unlimited ? null : positiveNumber(draft.tokens, true);
    const cost = draft.unlimited ? null : positiveNumber(draft.cost, false);
    const ram = positiveNumber(draft.ram, true);
    const vram = positiveNumber(draft.vram, true);
    const errors: FieldErrors = {};
    if (!draft.unlimited && draft.tokens.trim() && tokens === null) errors.tokens = "Isi token dengan bilangan bulat positif yang dapat direpresentasikan secara tepat.";
    if (!draft.unlimited && draft.cost.trim() && cost === null) errors.cost = "Isi biaya dengan angka positif dan terbatas.";
    if (ram === null) errors.ram = "RAM wajib diisi dengan bilangan bulat positif yang dapat direpresentasikan secara tepat.";
    if (vram === null) errors.vram = "VRAM wajib diisi dengan bilangan bulat positif yang dapat direpresentasikan secara tepat.";
    setFieldErrors(errors);
    setSaveError(null);
    setSaved(false);
    if (Object.keys(errors).length || ram === null || vram === null) return;

    pending.current = true;
    setSaving(true);
    try {
      const result = await api.saveSettings({
        budget: { max_daily_tokens: tokens, max_daily_cost_usd: cost, unlimited: draft.unlimited },
        render: { min_free_ram_mib: ram, min_free_vram_mib: vram, allow_unmeasured_gpu: draft.unmeasuredGpu },
      });
      setSettings((current) => current ? { ...current, ...result } : current);
      setDraft(toDraft(result));
      setSaved(true);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Gagal menyimpan pengaturan.");
    } finally {
      pending.current = false;
      setSaving(false);
    }
  };

  const dirty = settings !== null && draft !== null && JSON.stringify(draft) !== JSON.stringify(toDraft(settings));

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Pengaturan studio</h1>
          <p>Batas pemakaian provider dan syarat masuk antrean render pada mesin ini.</p>
        </div>
        <Link className={`btn ${styles.button}`} href="/providers">Atur provider</Link>
      </header>

      {loadError ? <ErrorState message={loadError} onRetry={() => setAttempt((value) => value + 1)} /> : !settings || !draft ? (
        <Loading label="Memuat pengaturan tersimpan…" />
      ) : (
        <>
          <form onSubmit={save} noValidate aria-label="Pengaturan studio" aria-busy={saving}>
            <fieldset disabled={saving} className={styles.form}>
              <legend className={styles.srOnly}>Pengaturan yang dapat diubah</legend>
              <section className={styles.section} aria-labelledby="budget-heading">
                <div className={styles.sectionHeading}>
                  <h2 id="budget-heading">Anggaran harian</h2>
                  <p>Batas token dan biaya diterapkan bersama. Batas yang kosong disimpan sebagai null, bukan nol.</p>
                </div>
                <label className={styles.check}>
                  <input type="checkbox" checked={draft.unlimited} onChange={(event) => patch({ unlimited: event.target.checked, ...(event.target.checked ? { tokens: "", cost: "" } : {}) })} aria-describedby="unlimited-help" />
                  Tanpa batas (unlimited)
                </label>
                <p id="unlimited-help" className={styles.hint}>Pilihan ini menghapus kedua batas saat disimpan. Nonaktifkan untuk menetapkan batas lagi.</p>
                <div className={styles.fields}>
                  <label className={styles.fieldLabel}>
                    Batas token per hari
                    <input className={`field ${styles.input}`} type="number" min="1" step="1" max={Number.MAX_SAFE_INTEGER} disabled={draft.unlimited} value={draft.tokens} onChange={(event) => patch({ tokens: event.target.value })} aria-invalid={!!fieldErrors.tokens} aria-describedby={fieldErrors.tokens ? "tokens-error" : "caps-help"} />
                    {fieldErrors.tokens ? <span id="tokens-error" className={styles.error}>{fieldErrors.tokens}</span> : null}
                  </label>
                  <label className={styles.fieldLabel}>
                    Batas biaya per hari (USD)
                    <input className={`field ${styles.input}`} type="number" min="0" step="any" disabled={draft.unlimited} value={draft.cost} onChange={(event) => patch({ cost: event.target.value })} aria-invalid={!!fieldErrors.cost} aria-describedby={fieldErrors.cost ? "cost-error" : "caps-help"} />
                    {fieldErrors.cost ? <span id="cost-error" className={styles.error}>{fieldErrors.cost}</span> : null}
                  </label>
                </div>
                <p id="caps-help" className={styles.hint}>Kosong berarti batas tersebut belum diatur. Jika keduanya kosong dan unlimited nonaktif, tidak ada batas pemakaian yang ditegakkan; ini bukan persetujuan unlimited.</p>
                {!draft.unlimited && !draft.tokens.trim() && !draft.cost.trim() ? <p className={styles.warning} role="note">Anggaran belum diatur. Tetapkan setidaknya satu batas atau pilih unlimited secara sadar.</p> : null}
                <p className={styles.hint}>Batas biaya memakai estimasi harga provider, bukan jaminan tagihan akhir. <Link href="/usage">Lihat pemakaian tercatat</Link>.</p>
              </section>

              <section className={styles.section} aria-labelledby="render-heading">
                <div className={styles.sectionHeading}>
                  <h2 id="render-heading">Penerimaan render</h2>
                  <p>Ambang memori bebas sebelum render diizinkan. Ini kebijakan admission, bukan hasil pengukuran mesin saat ini.</p>
                </div>
                <div className={styles.fields}>
                  <label className={styles.fieldLabel}>
                    Minimum RAM bebas (MiB)
                    <input className={`field ${styles.input}`} type="number" required min="1" step="1" max={Number.MAX_SAFE_INTEGER} value={draft.ram} onChange={(event) => patch({ ram: event.target.value })} aria-invalid={!!fieldErrors.ram} aria-describedby={fieldErrors.ram ? "ram-error" : undefined} />
                    {fieldErrors.ram ? <span id="ram-error" className={styles.error}>{fieldErrors.ram}</span> : null}
                  </label>
                  <label className={styles.fieldLabel}>
                    Minimum VRAM bebas (MiB)
                    <input className={`field ${styles.input}`} type="number" required min="1" step="1" max={Number.MAX_SAFE_INTEGER} value={draft.vram} onChange={(event) => patch({ vram: event.target.value })} aria-invalid={!!fieldErrors.vram} aria-describedby={fieldErrors.vram ? "vram-error" : undefined} />
                    {fieldErrors.vram ? <span id="vram-error" className={styles.error}>{fieldErrors.vram}</span> : null}
                  </label>
                </div>
                <label className={styles.check}>
                  <input type="checkbox" checked={draft.unmeasuredGpu} onChange={(event) => patch({ unmeasuredGpu: event.target.checked })} aria-describedby="gpu-warning" />
                  Izinkan render saat VRAM GPU tidak dapat diukur
                </label>
                <p id="gpu-warning" className={styles.warning}>Opt-in ini mengizinkan render tanpa bukti VRAM bebas. Risiko kehabisan memori tetap ada; ambang RAM dan VRAM yang terukur tetap berlaku.</p>
                <p className={styles.hint}>Konkurensi render: <strong>1 slot global</strong>, tetap dan hanya baca.</p>
              </section>

              {Object.keys(fieldErrors).length ? <div className={styles.warning} role="alert" tabIndex={-1} ref={errorSummary}>Pengaturan belum disimpan. Perbaiki kolom yang ditandai.</div> : null}
              {saveError ? <div className={styles.warning} role="alert"><strong>Penyimpanan belum terkonfirmasi.</strong> {saveError} Draf tetap tersedia; panel nilai tersimpan menampilkan konfirmasi API terakhir. Jika koneksi terputus, muat ulang halaman untuk memastikan hasilnya.</div> : null}
              <div className={styles.actions}>
                <button className={`btn btn-primary ${styles.button}`} type="submit" disabled={!dirty || saving}>{saving ? "Menyimpan…" : "Simpan pengaturan"}</button>
                <button className={`btn ${styles.button}`} type="button" disabled={!dirty || saving} onClick={() => { setDraft(toDraft(settings)); setFieldErrors({}); setSaveError(null); setSaved(false); }}>Batalkan perubahan</button>
                <p role="status">{saving ? "Menunggu konfirmasi API." : saved ? "Pengaturan tersimpan." : dirty ? "Ada perubahan yang belum disimpan." : "Menampilkan nilai tersimpan."}</p>
              </div>
            </fieldset>
          </form>

          <section className={styles.section} aria-labelledby="saved-heading">
            <h2 id="saved-heading">Nilai tersimpan</h2>
            <dl className={styles.details}>
              <dt>Anggaran</dt><dd>{settings.budget.unlimited ? "Unlimited disetujui" : "Unlimited nonaktif"}; token: {settings.budget.max_daily_tokens ?? "belum diatur"}; biaya USD: {settings.budget.max_daily_cost_usd ?? "belum diatur"}</dd>
              <dt>Admission</dt><dd>RAM {settings.render.min_free_ram_mib} MiB; VRAM {settings.render.min_free_vram_mib} MiB; GPU tidak terukur: {settings.render.allow_unmeasured_gpu ? "diizinkan" : "ditolak"}</dd>
            </dl>
          </section>
          <section className={styles.section} aria-labelledby="storage-heading">
            <h2 id="storage-heading">Lokasi penyimpanan</h2>
            <p className={styles.hint}>Jalur startup, hanya baca. Halaman ini tidak memindahkan atau menghapus berkas dan tidak menampilkan isi kredensial.</p>
            <dl className={styles.details}>
              <dt>Data</dt><dd>{settings.storage.data_dir || "Tidak dilaporkan API"}</dd>
              <dt>Job</dt><dd>{settings.storage.jobs_dir || "Tidak dilaporkan API"}</dd>
              <dt>Secret store</dt><dd>{settings.storage.secrets_dir || "Tidak dilaporkan API"}</dd>
            </dl>
          </section>
        </>
      )}
    </div>
  );
}
