"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type StudioSnapshot } from "./api";

/**
 * Live studio state over SSE, with a snapshot on connect.
 *
 * Two rules the donor learned the hard way:
 *  - the cursor from the snapshot is the resume point, so a reconnect cannot drop or duplicate an
 *    event;
 *  - the browser never decides staleness. Status comes from the server, which knows whether a
 *    worker still holds a lease.
 */
export function useStudio(pollMs = 2000) {
  const [snapshot, setSnapshot] = useState<StudioSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const cursor = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const next = await api.snapshot();
      cursor.current = next.cursor;
      setSnapshot(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "gagal memuat studio");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    let source: EventSource | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      source = new EventSource(`/api/studio/stream?after=${cursor.current}`);
      source.onopen = () => setConnected(true);
      source.onerror = () => {
        setConnected(false);
        source?.close();
        // Reconnect from the last cursor rather than from zero: no gaps, no duplicates.
        window.setTimeout(connect, 1500);
      };
      source.onmessage = () => {
        cursor.current += 1;
        void refresh();
      };
    };

    connect();
    const interval = window.setInterval(() => void refresh(), pollMs);
    return () => {
      cancelled = true;
      source?.close();
      window.clearInterval(interval);
    };
  }, [refresh, pollMs]);

  return { snapshot, error, connected, refresh };
}
