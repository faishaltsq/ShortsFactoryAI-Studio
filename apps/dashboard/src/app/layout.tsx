import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "ShortsFactoryAI Studio",
  description: "Local-first autonomous animation studio for YouTube Shorts",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body className="min-h-dvh">
        <div className="grid min-h-dvh grid-cols-1 md:grid-cols-[15rem_1fr]">
          <aside className="hidden border-r border-ink-700 bg-ink-900/60 md:block">
            <Sidebar />
          </aside>
          <main className="min-w-0">{children}</main>
        </div>
      </body>
    </html>
  );
}
