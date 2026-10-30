import type { Metadata } from "next";
import "./globals.css";
import { MobileNavigation, Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "ShortsFactoryAI Studio",
  description: "Local-first autonomous animation studio for YouTube Shorts",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body className="min-h-dvh">
        <a href="#main-content" className="skip-link">Langsung ke konten</a>
        <MobileNavigation />
        <div className="grid min-h-dvh grid-cols-1 md:grid-cols-[min(15rem,38vw)_minmax(0,1fr)]">
          <aside className="hidden border-r border-ink-700 bg-ink-900/60 md:block">
            <Sidebar />
          </aside>
          <main id="main-content" className="min-w-0" tabIndex={-1}>{children}</main>
        </div>
      </body>
    </html>
  );
}
