"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ROUTES = [
  { href: "/", label: "Studio", hint: "ruang produksi 3D" },
  { href: "/jobs", label: "Produksi", hint: "antrean & riwayat job" },
  { href: "/create", label: "Buat Video", hint: "topik & preferensi" },
  { href: "/storyboard", label: "Storyboard", hint: "adegan & kamera" },
  { href: "/assets", label: "Aset", hint: "karakter & latar" },
  { href: "/providers", label: "Provider", hint: "model & kredensial" },
  { href: "/agents", label: "Agent", hint: "penugasan model" },
  { href: "/skills", label: "Skills", hint: "motion skill" },
  { href: "/calendar", label: "Kalender", hint: "jadwal terbit" },
  { href: "/settings", label: "Setelan", hint: "batas & penyimpanan" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav aria-label="Navigasi utama" className="flex h-full flex-col gap-1 p-3">
      <div className="mb-3 px-2">
        <div className="text-sm font-semibold tracking-tight">ShortsFactoryAI</div>
        <div className="text-[11px] uppercase tracking-widest text-ink-400">Studio</div>
      </div>
      {ROUTES.map((route) => {
        const active = pathname === route.href;
        return (
          <Link
            key={route.href}
            href={route.href}
            aria-current={active ? "page" : undefined}
            className={[
              "rounded-md px-2.5 py-2 text-sm transition-colors",
              active
                ? "bg-teal-600/25 text-ink-100 border border-teal-500/40"
                : "text-ink-300 hover:bg-ink-800 hover:text-ink-100 border border-transparent",
            ].join(" ")}
          >
            <span className="block font-medium">{route.label}</span>
            <span className="block text-[11px] text-ink-400">{route.hint}</span>
          </Link>
        );
      })}
    </nav>
  );
}
