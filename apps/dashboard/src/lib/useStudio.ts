"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type StudioSnapshot } from "./api";
import { COMPLETED_VISIBLE_MS, withResolvedStates } from "./studioState";
import { renderingActive } from "../three/sceneState";

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
export function useStudio({ jobId, pollMs = 2000 }: { jobId?: string; pollMs?: number } = {}) {
  const scope = useMemo(() => ({ jobId }), [jobId]);
  const [view, setView] = useState<{
    scope: typeof scope;
    snapshot: StudioSnapshot | null;
    error: string | null;
    connected: boolean;
    rendering: boolean;
  }>({ scope, snapshot: null, error: null, connected: false, rendering: false });
  const [nowMs, setNowMs] = useState(() => Date.now());
  // The stream and snapshot cursors are global, even when the snapshot is job-scoped.
  const cursor = useRef(0);
  const session = useRef<{ scope: typeof scope; refresh: () => Promise<void> } | null>(null);
  const snapshot = view.scope === scope ? view.snapshot : null;
  const error = view.scope === scope ? view.error : null;
  const connected = view.scope === scope && view.connected;
  const rendering = view.scope === scope && view.rendering;

  const refresh = useCallback(async () => {
    const current = session.current;
    if (current?.scope === scope) await current.refresh();
  }, [scope]);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let reconnect: number | null = null;
    let lastByteAt = Date.now();
    let synced = false;
    let requested = 0;
    let applied = 0;
    let snapshot: StudioSnapshot | null = null;
    let error: string | null = null;
    let connected = false;
    let globalSnapshot: StudioSnapshot | null = null;
    let rendering = false;
    const isCurrent = (): boolean => !cancelled && session.current === current;
    const publish = () => setView({ scope, snapshot, error, connected, rendering });
    const current = {
      scope,
      refresh: async () => {
        if (!isCurrent()) return;
        const request = ++requested;
        try {
          const scopedRead = api.snapshot(jobId);
          const [next, global] = await Promise.all([
            scopedRead,
            jobId === undefined ? scopedRead : api.snapshot(),
          ]);
          if (!isCurrent()) return;
          // Neither half of a slower read may rewind the displayed scope or render safety.
          if (snapshot && globalSnapshot && (
            next.cursor < snapshot.cursor ||
            global.cursor < globalSnapshot.cursor ||
            (next.cursor === snapshot.cursor && global.cursor === globalSnapshot.cursor && request < applied)
          )) return;
          cursor.current = Math.max(cursor.current, next.cursor, global.cursor);
          synced = true;
          applied = Math.max(applied, request);
          snapshot = next;
          globalSnapshot = global;
          rendering = renderingActive(global.agents);
          error = null;
          publish();
        } catch (err) {
          if (!isCurrent() || request < applied) return;
          applied = request;
          error = err instanceof Error ? err.message : "gagal memuat studio";
          publish();
        }
      },
    };
    session.current = current;
    publish();
    void current.refresh();

    const closeSource = () => {
      if (!source) return;
      source.onopen = null;
      source.onerror = null;
      source.onmessage = null;
      source.close();
      source = null;
    };
    const schedule = (delay: number) => {
      if (reconnect !== null) window.clearTimeout(reconnect);
      reconnect = window.setTimeout(() => {
        reconnect = null;
        connect();
      }, delay);
    };
    const connect = () => {
      if (!isCurrent()) return;
      if (!synced) {
        // A scope must establish its own snapshot before the global stream can resume.
        schedule(50);
        return;
      }
      const opened = new EventSource(`/api/studio/stream?after=${cursor.current}`);
      source = opened;
      lastByteAt = Date.now();
      opened.onopen = () => {
        if (!isCurrent() || source !== opened) return;
        lastByteAt = Date.now();
        connected = true;
        publish();
      };
      opened.onerror = () => {
        if (!isCurrent() || source !== opened) return;
        connected = false;
        closeSource();
        publish();
        schedule(1500);
      };
      opened.onmessage = (event: MessageEvent) => {
        if (!isCurrent() || source !== opened) return;
        lastByteAt = Date.now();
        // SSE ids are server event ids, not message counts; keepalives have no id.
        const lastSeen = Number(event.lastEventId);
        if (Number.isInteger(lastSeen) && lastSeen > cursor.current) cursor.current = lastSeen;
        void current.refresh();
      };
    };

    connect();
    const interval = window.setInterval(() => void current.refresh(), pollMs);
    // Two missed server keepalives indicate a silently dead socket behind the proxy.
    const watchdog = window.setInterval(() => {
      if (!isCurrent() || !source || Date.now() - lastByteAt < SILENT_MS) return;
      connected = false;
      closeSource();
      publish();
      connect();
    }, STREAM_WATCHDOG_MS);
    return () => {
      cancelled = true;
      if (session.current === current) session.current = null;
      closeSource();
      if (reconnect !== null) window.clearTimeout(reconnect);
      window.clearInterval(watchdog);
      window.clearInterval(interval);
    };
  }, [scope, jobId, pollMs]);

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

  return { snapshot, agents, nowMs, error, connected, rendering, refresh };
}
