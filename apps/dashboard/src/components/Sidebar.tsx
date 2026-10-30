"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef } from "react";
import styles from "./Sidebar.module.css";

const ROUTES = [
  { href: "/", label: "Studio", hint: "ruang produksi 3D" },
  { href: "/jobs", label: "Produksi", hint: "antrean & riwayat job" },
  { href: "/create", label: "Buat Video", hint: "topik & preferensi" },
  { href: "/storyboard", label: "Storyboard", hint: "alur adegan & kamera" },
  { href: "/assets", label: "Aset", hint: "karakter & berkas produksi" },
  { href: "/providers", label: "Provider", hint: "model & kredensial" },
  { href: "/usage", label: "Pemakaian", hint: "token & biaya" },
  { href: "/agents", label: "Agent", hint: "penugasan model" },
  { href: "/skills", label: "Skills", hint: "template & gerak bawaan" },
  { href: "/calendar", label: "Kalender", hint: "jadwal produksi" },
  { href: "/settings", label: "Setelan", hint: "batas biaya & render" },
];

function NavigationLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return ROUTES.map((route) => (
    <Link
      key={route.href}
      href={route.href}
      onClick={onNavigate}
      aria-current={pathname === route.href ? "page" : undefined}
      className={styles.link}
    >
      <span className={styles.label}>{route.label}</span>
      <span className={styles.hint}>{route.hint}</span>
    </Link>
  ));
}

export function Sidebar() {
  return (
    <nav aria-label="Navigasi utama" className={styles.sidebar}>
      <div className={styles.brand}>
        <div>ShortsFactoryAI</div>
        <span>Studio</span>
      </div>
      <NavigationLinks />
    </nav>
  );
}

export function MobileNavigation() {
  const menu = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();
  const current = ROUTES.find((route) => route.href === pathname);
  return (
    <details ref={menu} className={styles.mobile} key={pathname}>
      <summary>
        <span>Menu studio</span>
        <span className={styles.current}>{current?.label ?? "ShortsFactoryAI"}</span>
      </summary>
      <nav aria-label="Navigasi utama seluler" className={styles.mobileLinks}>
        <NavigationLinks onNavigate={() => {
          if (menu.current) {
            menu.current.open = false;
            menu.current.querySelector("summary")?.focus();
          }
        }} />
      </nav>
    </details>
  );
}
