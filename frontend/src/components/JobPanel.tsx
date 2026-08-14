import { useEffect, useRef, useState } from "react";
import { api, Job } from "../api";

/** Polls a job until it reaches a terminal state; shows progress + log. */
export function JobPanel({
  jobId,
  onDone,
}: {
  jobId: string;
  onDone?: (job: Job) => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const doneRef = useRef(false);

  useEffect(() => {
    doneRef.current = false;
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (stop) return;
        setJob(j);
        const terminal = j.state === "success" || j.state === "failed" || j.state === "cancelled";
        if (terminal) {
          if (!doneRef.current) {
            doneRef.current = true;
            onDone?.(j);
          }
          return;
        }
      } catch {
        /* keep polling; backend may be busy */
      }
      if (!stop) setTimeout(tick, 700);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [jobId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [job?.log?.length]);

  if (!job) return <div className="statusline">Starting job…</div>;

  const pct = Math.round(job.progress * 100);
  const running = job.state === "pending" || job.state === "running";

  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <div className="grow">
          <strong>{job.title}</strong>
          <div className="statusline">
            {job.state === "success" && <span className="ok-text">✓ Done</span>}
            {job.state === "failed" && <span style={{ color: "var(--danger)" }}>✗ Failed</span>}
            {job.state === "cancelled" && "Cancelled"}
            {running && (job.phase || "Working…")}
            {" · "}
            {pct}%
          </div>
        </div>
        {running && (
          <button className="btn danger" onClick={() => api.cancelJob(job.id).catch(() => {})}>
            Cancel
          </button>
        )}
      </div>
      <div className="progress-outer">
        <div
          className={`progress-inner${job.state === "failed" ? " failed" : ""}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {job.error && <div className="error-box">{job.error}</div>}
      {job.log && job.log.length > 0 && (
        <div className="joblog" ref={logRef} style={{ marginTop: 10 }}>
          {job.log.join("\n")}
        </div>
      )}
    </div>
  );
}
