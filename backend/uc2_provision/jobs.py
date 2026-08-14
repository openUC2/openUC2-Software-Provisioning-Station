"""Job engine.

Long-running operations (downloads, SD writes, ESP flashes) run in worker
threads.  Each job exposes progress (0..1), a human-readable phase, a rolling
log, and a terminal state.  The frontend polls GET /api/jobs/{id} or holds a
WebSocket on /api/jobs/{id}/ws.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class JobState(StrEnum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class Job:
    kind: str
    title: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: JobState = JobState.pending
    progress: float = 0.0
    phase: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    log: deque[str] = field(default_factory=lambda: deque(maxlen=400))
    _cancel: threading.Event = field(default_factory=threading.Event)

    # -- worker-side API -------------------------------------------------
    def set_progress(self, value: float, phase: str | None = None) -> None:
        self.progress = max(0.0, min(1.0, value))
        if phase is not None:
            self.phase = phase

    def log_line(self, line: str) -> None:
        line = line.rstrip()
        if line:
            self.log.append(f"[{time.strftime('%H:%M:%S')}] {line}")

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    # -- serialization ---------------------------------------------------
    def to_dict(self, with_log: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
            "progress": round(self.progress, 4),
            "phase": self.phase,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "meta": self.meta,
        }
        if with_log:
            d["log"] = list(self.log)
        return d


class JobCancelled(Exception):
    pass


class JobManager:
    def __init__(self, max_history: int = 50) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque(maxlen=max_history)
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        title: str,
        target: Callable[[Job], None],
        meta: dict[str, Any] | None = None,
        exclusive: str | None = None,
    ) -> Job:
        """Start `target(job)` in a thread.

        `exclusive` names a resource group (e.g. "sdcard", "esp:/dev/ttyUSB0");
        submitting while another job in the same group is active raises.
        """
        with self._lock:
            if exclusive:
                for j in self._jobs.values():
                    if (
                        j.meta.get("exclusive") == exclusive
                        and j.state in (JobState.pending, JobState.running)
                    ):
                        raise RuntimeError(
                            f"A {j.kind} job is already running on {exclusive}"
                        )
            job = Job(kind=kind, title=title, meta=meta or {})
            if exclusive:
                job.meta["exclusive"] = exclusive
            self._jobs[job.id] = job
            self._order.append(job.id)
            # Evict jobs that fell out of history.
            live = set(self._order)
            for jid in list(self._jobs):
                if jid not in live:
                    del self._jobs[jid]

        def runner() -> None:
            job.state = JobState.running
            try:
                target(job)
                if job.state == JobState.running:
                    job.state = JobState.success
                    job.progress = 1.0
            except JobCancelled:
                job.state = JobState.cancelled
                job.log_line("Cancelled.")
            except Exception as exc:  # noqa: BLE001 - report any worker failure
                job.state = JobState.failed
                job.error = str(exc)
                job.log_line(f"ERROR: {exc}")
                job.log_line(traceback.format_exc(limit=5))
            finally:
                job.finished_at = time.time()

        threading.Thread(target=runner, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job.state in (JobState.pending, JobState.running):
            job._cancel.set()
            return True
        return False

    def list(self) -> list[Job]:
        return [self._jobs[jid] for jid in reversed(self._order) if jid in self._jobs]


jobs = JobManager()
