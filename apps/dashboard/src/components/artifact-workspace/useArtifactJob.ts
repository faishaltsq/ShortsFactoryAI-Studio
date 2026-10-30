"use client";

import { useEffect, useState } from "react";
import { api, type JobDetail, type JobView } from "@/lib/api";

export type ArtifactResult = { data?: Record<string, unknown>; error?: string };
export const failureMessage = (error: unknown) => error instanceof Error ? error.message : String(error);

export function useJobSelection() {
  const [selectedId, setSelectedId] = useState("");
  const [jobs, setJobs] = useState<JobView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const readSelection = () => setSelectedId(new URLSearchParams(window.location.search).get("job_id") ?? "");
    readSelection();
    window.addEventListener("popstate", readSelection);
    return () => window.removeEventListener("popstate", readSelection);
  }, []);
  useEffect(() => {
    let active = true;
    api.jobs().then(({ jobs: result }) => {
      if (active) { setJobs(result); setError(null); }
    }).catch((failure: unknown) => { if (active) setError(failureMessage(failure)); });
    return () => { active = false; };
  }, [revision]);
  const select = (id: string) => {
    if (id === selectedId) return;
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("job_id", id);
    else url.searchParams.delete("job_id");
    window.history.pushState(window.history.state, "", url);
    setSelectedId(id);
  };
  return { selectedId, jobs, error, select, reload: () => setRevision((value) => value + 1) };
}

export function useArtifactJob(id: string, names: readonly string[]) {
  const [result, setResult] = useState<{
    id: string; detail?: JobDetail; artifacts: Record<string, ArtifactResult>; error?: string;
  }>({ id, artifacts: {} });
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setResult({ id, artifacts: {} });
    api.job(id).then(async (detail) => {
      if (!active) return;
      const artifacts: Record<string, ArtifactResult> = {};
      await Promise.all(names.filter((name) => detail.artifacts.includes(name)).map(async (name) => {
        try {
          const data = await api.artifact(id, name);
          if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Artefak bukan objek JSON.");
          artifacts[name] = { data };
        } catch (failure) { artifacts[name] = { error: failureMessage(failure) }; }
      }));
      if (active) { setResult({ id, detail, artifacts }); setLoading(false); }
    }).catch((failure: unknown) => {
      if (active) { setResult({ id, artifacts: {}, error: failureMessage(failure) }); setLoading(false); }
    });
    return () => { active = false; };
  }, [id, names, revision]);
  const current: typeof result = result.id === id ? result : { id, artifacts: {} };
  return { ...current, loading: loading || result.id !== id, reload: () => setRevision((value) => value + 1) };
}
