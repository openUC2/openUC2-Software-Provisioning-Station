import { useEffect, useRef } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Stack,
  Typography,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import StopCircleIcon from "@mui/icons-material/StopCircle";
import { useJobLog, useJobs } from "../JobsContext";
import { isActive } from "../api";

/**
 * Shows a backend job's progress and log.  State comes from the shared jobs
 * poll, so this re-attaches instantly to work started on another page.
 */
export function JobPanel({
  jobId,
  onDone,
  compact,
}: {
  jobId: string;
  onDone?: () => void;
  compact?: boolean;
}) {
  const { byId, cancel } = useJobs();
  const job = byId(jobId);
  const log = useJobLog(jobId);
  const logRef = useRef<HTMLPreElement>(null);
  const notified = useRef(false);

  useEffect(() => {
    if (job && !isActive(job) && !notified.current) {
      notified.current = true;
      onDone?.();
    }
  }, [job, onDone]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [log.length]);

  if (!job) {
    return (
      <Typography variant="body2" color="text.secondary">
        Starting…
      </Typography>
    );
  }

  const pct = Math.round(job.progress * 100);
  const running = isActive(job);

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={2} sx={{ mb: 1.5, alignItems: "center" }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" noWrap sx={{ fontWeight: 700 }}>
              {job.title}
            </Typography>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
              {job.state === "success" && (
                <Chip
                  size="small"
                  color="success"
                  icon={<CheckCircleIcon />}
                  label="Done"
                />
              )}
              {job.state === "failed" && (
                <Chip size="small" color="error" icon={<ErrorIcon />} label="Failed" />
              )}
              {job.state === "cancelled" && (
                <Chip size="small" icon={<StopCircleIcon />} label="Cancelled" />
              )}
              <Typography variant="body2" color="text.secondary" noWrap>
                {running ? job.phase || "Working…" : ""} {running ? `· ${pct}%` : ""}
              </Typography>
            </Stack>
          </Box>
          {running && (
            <Button color="error" variant="outlined" onClick={() => cancel(job.id)}>
              Cancel
            </Button>
          )}
        </Stack>

        <LinearProgress
          variant={running && pct === 0 ? "indeterminate" : "determinate"}
          value={pct}
          color={job.state === "failed" ? "error" : "primary"}
          sx={{ height: 12, borderRadius: 6 }}
        />

        {job.error && (
          <Alert severity="error" sx={{ mt: 2 }} className="selectable">
            {job.error}
          </Alert>
        )}

        {!compact && log.length > 0 && (
          <Box
            component="pre"
            ref={logRef}
            className="selectable"
            sx={{
              mt: 2,
              mb: 0,
              p: 1.5,
              maxHeight: 220,
              overflowY: "auto",
              bgcolor: "#1e1e1e",
              color: "#d4d4d4",
              borderRadius: 2,
              fontFamily: "Consolas, Monaco, monospace",
              fontSize: 12,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {log.join("\n")}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
