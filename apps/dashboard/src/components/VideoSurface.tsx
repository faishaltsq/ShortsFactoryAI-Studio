"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { videoUrl } from "@/lib/api";

/**
 * The job's video surface: exactly one `<video>`, four explicit states, and an honest note on a
 * mock job.
 *
 * Why this is a component and not an inline element: a bare `<video src controls>` renders a
 * black rectangle with a spinner and no explanation when the file is missing, still being muxed,
 * or the range request failed. The operator cannot tell "not rendered yet" from "render broke",
 * and neither can a test. The state is mirrored onto the wrapper as `data-video-state`, so
 * Playwright asserts the same fact a human reads instead of guessing from pixels.
 *
 * Playback rules:
 * - No `autoPlay` and no `muted`. The MP4 carries the narration; a muted autoplay would be a
 *   silent video pretending to be the product, and an unmuted autoplay is a sound the operator
 *   did not ask for.
 * - `preload="metadata"` plus a `#t=` media fragment is the first-frame handling: the browser
 *   paints a real frame from the render before anyone presses play, and it gets there with a
 *   Range request, which is the same 206 path a seek uses.
 */
export type VideoPhase = "empty" | "loading" | "ready" | "error";

export function VideoSurface({
  jobId,
  title,
  hasVideo,
  isMock,
}: {
  jobId: string;
  title: string;
  hasVideo: boolean;
  isMock: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [phase, setPhase] = useState<VideoPhase>(hasVideo ? "loading" : "empty");
  const [detail, setDetail] = useState<string | null>(null);

  // A poll can flip `has_video` from false to true while the panel stays mounted. Reset to
  // loading on that edge; do not reset on every poll, or a playing video would be re-created
  // once a second.
  useEffect(() => {
    setPhase(hasVideo ? "loading" : "empty");
    setDetail(null);
  }, [hasVideo, jobId]);

  const handleLoadedMetadata = useCallback(() => {
    setPhase("ready");
    setDetail(null);
  }, []);

  const handleError = useCallback(() => {
    const code = videoRef.current?.error?.code;
    setPhase("error");
    setDetail(code ? `kode media ${code}` : "sumber video tidak dapat dibaca");
  }, []);

  const retry = useCallback(() => {
    const element = videoRef.current;
    if (!element) return;
    setPhase("loading");
    setDetail(null);
    // A dropped range request or a half-written file is recoverable; `load()` re-runs the
    // resource selection algorithm instead of leaving the operator with a dead player.
    element.load();
  }, []);

  return (
    <section
      className="panel p-4 sm:p-5"
      aria-labelledby="video-heading"
      data-video-state={phase}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="video-heading" className="text-sm font-semibold text-ink-100">
          Video hasil render
        </h3>
        <span className="text-xs text-ink-400">
          {phase === "ready" ? "siap diputar" : phase === "loading" ? "memuat" : phase === "error" ? "gagal" : "belum ada"}
        </span>
      </div>

      {isMock ? (
        <p
          role="note"
          className="mt-3 rounded-md border border-warn-500 p-3 text-sm text-ink-200"
        >
          Job mock: video ini bukti lokal dan tidak dapat dipublikasikan.
        </p>
      ) : null}

      {!hasVideo ? (
        <p className="mt-3 text-sm text-ink-400">
          Belum ada video untuk job ini. Berkas muncul setelah stage render selesai dan lolos
          pemeriksaan ffprobe.
        </p>
      ) : null}

      {hasVideo && phase === "loading" ? (
        <p role="status" aria-live="polite" className="mt-3 text-sm text-ink-400">
          Memuat metadata video…
        </p>
      ) : null}

      {hasVideo && phase === "error" ? (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-bad-500 p-3 text-sm text-ink-200"
        >
          <span className="break-words">
            Video gagal dimuat{detail ? ` (${detail})` : ""}. Berkas mungkin belum selesai ditulis
            atau permintaan rentang byte ditolak.
          </span>
          <button type="button" className="btn min-h-9" onClick={retry}>
            Muat ulang video
          </button>
        </div>
      ) : null}

      {hasVideo ? (
        <video
          ref={videoRef}
          className="mt-3 max-h-[70dvh] w-full bg-black"
          // The fragment asks the browser for frame 0.1s instead of a black frame 0 after a
          // fade-in; it is a media fragment, never sent to the server.
          src={`${videoUrl(jobId)}#t=0.1`}
          controls
          preload="metadata"
          playsInline
          aria-label={`Video job ${title}`}
          onLoadedMetadata={handleLoadedMetadata}
          onError={handleError}
        >
          Browser tidak mendukung pemutaran video.
        </video>
      ) : null}
    </section>
  );
}
