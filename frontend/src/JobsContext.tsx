import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, isActive, type Job } from "./api";

/**
 * Station-wide job tracking.
 *
 * Jobs live on the backend, so a download keeps running when the technician
 * navigates away.  This context polls the job list continuously and makes it
 * available everywhere, which is what lets any page re-attach to work that
 * was started on another page (and what powers the persistent progress bar).
 */
interface JobsState {
  jobs: Job[];
  active: Job[];
  byId: (id: string | null | undefined) => Job | undefined;
  /** Newest job of a kind, optionally filtered by a meta field. */
  find: (kind: string, match?: (job: Job) => boolean) => Job | undefined;
  /** Newest *running* job of a kind. */
  findActive: (kind: string, match?: (job: Job) => boolean) => Job | undefined;
  refresh: () => Promise<void>;
  track: (job: Job) => void;
  logFor: (id: string) => string[] | undefined;
  cancel: (id: string) => Promise<void>;
}

const JobsContext = createContext<JobsState | null>(null);

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.jobs();
      setJobs(list);
      // Pull full logs for whatever is running so any page can show them
      // without needing its own polling loop.
      const running = list.filter(isActive);
      if (running.length > 0) {
        const detailed = await Promise.all(
          running.map((j) => api.job(j.id).catch(() => null)),
        );
        setLogs((prev) => {
          const next = { ...prev };
          for (const d of detailed) if (d?.log) next[d.id] = d.log;
          return next;
        });
      }
    } catch {
      /* backend momentarily unavailable — keep the last known state */
    }
  }, []);

  useEffect(() => {
    refresh();
    // 1 s is responsive enough for progress bars and cheap for the Pi.
    pollRef.current = window.setInterval(refresh, 1000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [refresh]);

  const track = useCallback(
    (job: Job) => {
      setJobs((prev) => [job, ...prev.filter((j) => j.id !== job.id)]);
      refresh();
    },
    [refresh],
  );

  const value = useMemo<JobsState>(() => {
    const byId = (id: string | null | undefined) =>
      id ? jobs.find((j) => j.id === id) : undefined;
    const find = (kind: string, match?: (job: Job) => boolean) =>
      jobs.find((j) => j.kind === kind && (!match || match(j)));
    return {
      jobs,
      active: jobs.filter(isActive),
      byId,
      find,
      findActive: (kind, match) =>
        jobs.find((j) => j.kind === kind && isActive(j) && (!match || match(j))),
      refresh,
      track,
      logFor: (id: string) => logs[id] ?? byId(id)?.log,
      cancel: async (id: string) => {
        await api.cancelJob(id).catch(() => {});
        await refresh();
      },
    };
  }, [jobs, logs, refresh, track]);

  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>;
}

export function useJobs(): JobsState {
  const ctx = useContext(JobsContext);
  if (!ctx) throw new Error("useJobs must be used inside <JobsProvider>");
  return ctx;
}

/** Fetch a job's full log once it is finished (running logs come from the poll). */
export function useJobLog(id: string | null): string[] {
  const { logFor } = useJobs();
  const [finished, setFinished] = useState<string[]>([]);
  const live = id ? logFor(id) : undefined;

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    api
      .job(id)
      .then((j) => {
        if (!cancelled && j.log) setFinished(j.log);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id]);

  return live && live.length >= finished.length ? live : finished;
}
