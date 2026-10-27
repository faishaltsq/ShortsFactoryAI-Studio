"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type StudioSnapshot } from "./api";
import { COMPLETED_VISIBLE_MS, withResolvedStates } from "./studioState";

/** 250 ms: fine enough that a 2 s reaction never reads a whole tick stale, cheap enough to ignore. */
const DECAY_TICK_MS = 250;

/** How often the stream's liveness is checked. */
const STREAM_WATCHDOG_MS = 2000;
/** Silence longer than two server keepalives means the socket is gone. */
const SILENT_MS = 25_000;

/**
 * Live studio state over SSE, with a snapshot on connect.
 *
 * Two rules the donor learned the hard way:
 *  - the cursor from the snapshot is the resume point, so a reconnect cannot drop or duplicate an
 *    event;
 *  - the browser never decides staleness. Status comes from the server, which knows whether a
 *    worker still holds a lease.
 *
 * The one thing the browser does own is the display clock: `completed` decays to `idle` after two
 * seconds. That clock lives here and only here, and it ticks only while a decay could still happen,
 * so an idle studio costs no renders and the snapshot itself never changes on a timer.
 */
export function useStudio(pollMs = 2000) {
  const [snapshot, setSnapshot] = useState<StudioSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  // The resume point, monotonic. The snapshot seeds it and the stream raises it; neither may
  // lower it, because a snapshot read that started before an event arrived would rewind the
  // resume point and replay that event.
  const cursor = useRef(0);
  // Zero until the first snapshot lands. Connecting at `after=0` before it arrives replays the
  // whole log, which is exactly the duplicate the resume cursor exists to prevent.
  const synced = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const next = await api.snapshot();
      if (next.cursor > cursor.current) cursor.current = next.cursor;
      synced.current = true;
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
    let waiting: number | null = null;
    // A dead socket does not always call `onerror`: behind the Next proxy the SSE response stays
    // open, so a transport drop is silent and the stream never resumes. The watchdog reopens on
    // silence, which is the only signal the browser gives. The server emits a keepalive every
    // 10 s (20 idle ticks at POLL_S=0.5), so twice that is silence, not slowness.
    let lastByteAt = Date.now();
    let watchdog: number | null = null;

    const connect = () => {
      if (cancelled) return;
      if (!synced.current) {
        // Wait for the snapshot rather than opening a stream that would replay from zero.
        waiting = window.setTimeout(connect, 50);
        return;
      }
      source = new EventSource(`/api/studio/stream?after=${cursor.current}`);
      lastByteAt = Date.now();
      source.onopen = () => {
        lastByteAt = Date.now();
        setConnected(true);
      };
      source.onerror = () => {
        setConnected(false);
        source?.close();
        // Reconnect from the last cursor rather than from zero: no gaps, no duplicates.
        window.setTimeout(connect, 1500);
      };
      source.onmessage = (event: MessageEvent) => {
        lastByteAt = Date.now();
        // The resume point is the server's event id (the SSE `id:` field), never a message count.
        // A counter drifts the moment an event is filtered out or a keepalive arrives, and then a
        // reconnect either replays events or skips them.
        const lastSeen = Number(event.lastEventId);
        if (Number.isInteger(lastSeen) && lastSeen > cursor.current) cursor.current = lastSeen;
        void refresh();
      };
    };

    connect();
    const interval = window.setInterval(() => void refresh(), pollMs);
    watchdog = window.setInterval(() => {
      if (cancelled || Date.now() - lastByteAt < SILENT_MS) return;
      setConnected(false);
      source?.close();
      connect();
    }, STREAM_WATCHDOG_MS);
    return () => {
      cancelled = true;
      source?.close();
      if (waiting !== null) window.clearTimeout(waiting);
      if (watchdog !== null) window.clearInterval(watchdog);
      window.clearInterval(interval);
    };
  }, [refresh, pollMs]);

  // Tick at the completed window's resolution, and stop once nothing can still decay.
  const pendingDecay = useMemo(
    () =>
      (snapshot?.agents ?? []).some(
        (agent) =>
          agent.status === "completed" &&
          agent.updated_at !== null &&
          nowMs - Date.parse(agent.updated_at) < COMPLETED_VISIBLE_MS,
      ),
    [snapshot, nowMs],
  );

  useEffect(() => {
    if (!pendingDecay) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), DECAY_TICK_MS);
    return () => window.clearInterval(timer);
  }, [pendingDecay]);

  const agents = useMemo(
    () => withResolvedStates(snapshot?.agents ?? [], nowMs),
    [snapshot, nowMs],
  );

  return { snapshot, agents, nowMs, error, connected, refresh };
}
