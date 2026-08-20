import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import SystemUpdateAltIcon from "@mui/icons-material/SystemUpdateAlt";
import RefreshIcon from "@mui/icons-material/Refresh";
import { api, type VersionInfo } from "../api";
import { useJobs } from "../JobsContext";
import { JobPanel } from "./JobPanel";
import { ConfirmDialog } from "./Confirm";

/**
 * Pull the latest commit and restart the station.
 *
 * The frontend bundle is built in CI and committed, so one `git reset --hard`
 * updates backend and UI together. After the service restarts, the page
 * reloads itself so the browser picks up the new bundle.
 */
export function UpdateCard() {
  const { track, findActive } = useJobs();
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [reboot, setReboot] = useState(false);
  const [error, setError] = useState("");
  const wasDown = useRef(false);

  const job = findActive("update");

  const load = useCallback(async (fetch: boolean) => {
    setChecking(fetch);
    try {
      setInfo(await api.version(fetch));
    } catch (e) {
      setError(String(e));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  // After the update the service restarts; once it answers again, reload so
  // the browser fetches the newly built bundle rather than the stale one.
  useEffect(() => {
    if (!job) return;
    const t = setInterval(async () => {
      try {
        await api.status();
        if (wasDown.current) window.location.reload();
      } catch {
        wasDown.current = true;
      }
    }, 2000);
    return () => clearInterval(t);
  }, [job]);

  const start = async () => {
    setConfirm(false);
    setError("");
    try {
      track(await api.update(reboot));
    } catch (e) {
      setError(String(e));
    }
  };

  const behind = info?.behind ?? null;
  const upToDate = behind === 0;

  return (
    <Card variant="outlined" sx={{ mb: 2, maxWidth: 760 }}>
      <CardContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
            {error}
          </Alert>
        )}

        {info && !info.update_supported ? (
          <Alert severity="warning">
            {info.error ?? "In-place updates are not available on this install."}
          </Alert>
        ) : (
          <>
            <Stack
              direction="row"
              spacing={1}
              useFlexGap
              sx={{ alignItems: "center", flexWrap: "wrap", mb: 1 }}
            >
              <Typography sx={{ fontWeight: 700 }}>Installed version</Typography>
              {info?.commit && <Chip size="small" label={info.commit} />}
              {info?.branch && (
                <Chip size="small" variant="outlined" label={info.branch} />
              )}
              {info?.dirty && (
                <Chip size="small" color="warning" label="local changes" />
              )}
              {behind !== null &&
                (upToDate ? (
                  <Chip size="small" color="success" label="up to date" />
                ) : (
                  <Chip size="small" color="primary" label={`${behind} behind`} />
                ))}
            </Stack>

            {info?.subject && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                {info.subject}
                {info.committed_at
                  ? ` · ${new Date(info.committed_at).toLocaleString()}`
                  : ""}
              </Typography>
            )}
            {!upToDate && info?.remote_subject && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Latest on {info.branch}: {info.remote_commit} — {info.remote_subject}
              </Typography>
            )}
            {info?.dirty && (
              <Alert severity="warning" sx={{ my: 1 }}>
                This checkout has local modifications; updating will discard them.
              </Alert>
            )}

            {job ? (
              <Box sx={{ mt: 2 }}>
                <JobPanel jobId={job.id} />
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
                  The station will restart and this page will reload automatically.
                </Typography>
              </Box>
            ) : (
              <Stack
                direction="row"
                spacing={2}
                useFlexGap
                sx={{ alignItems: "center", flexWrap: "wrap", mt: 2 }}
              >
                <Button
                  variant="outlined"
                  startIcon={<RefreshIcon />}
                  onClick={() => load(true)}
                  disabled={checking}
                >
                  {checking ? "Checking…" : "Check for updates"}
                </Button>
                <Button
                  variant="contained"
                  startIcon={<SystemUpdateAltIcon />}
                  onClick={() => setConfirm(true)}
                  disabled={!info?.update_supported}
                >
                  Update station
                </Button>
                <FormControlLabel
                  control={
                    <Switch checked={reboot} onChange={(e) => setReboot(e.target.checked)} />
                  }
                  label={<Typography variant="body2">Full reboot</Typography>}
                />
              </Stack>
            )}
          </>
        )}
      </CardContent>

      <ConfirmDialog
        open={confirm}
        title="Update station software?"
        confirmLabel={reboot ? "Update & reboot" : "Update & restart"}
        onConfirm={start}
        onCancel={() => setConfirm(false)}
      >
        <Stack spacing={1.5}>
          <Typography>
            Pulls the latest commit from <strong>origin/{info?.branch ?? "main"}</strong> and{" "}
            {reboot ? "reboots the Raspberry Pi" : "restarts the station service"}.
          </Typography>
          {info?.dirty && (
            <Alert severity="warning">Local modifications will be discarded.</Alert>
          )}
          <Typography variant="body2" color="text.secondary">
            Downloads and flashing jobs in progress will be interrupted.
          </Typography>
        </Stack>
      </ConfirmDialog>
    </Card>
  );
}
