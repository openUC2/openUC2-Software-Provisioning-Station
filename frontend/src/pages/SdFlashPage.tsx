import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Grid,
  Stack,
  Typography,
} from "@mui/material";
import SdCardIcon from "@mui/icons-material/SdCard";
import UsbIcon from "@mui/icons-material/Usb";
import MemoryIcon from "@mui/icons-material/Memory";
import ScienceIcon from "@mui/icons-material/Science";
import { api, fmtBytes, type BlockDevice } from "../api";
import { useJobs } from "../JobsContext";
import { useSelection } from "../SelectionContext";
import { JobPanel } from "../components/JobPanel";
import { ConfirmDialog } from "../components/Confirm";
import { PageHeader, SectionLabel } from "../components/PageHeader";
import { SelectCard } from "../components/SelectCard";

export function SdFlashPage() {
  const { images, imageVersion, setImageVersion, image, matched, setup } = useSelection();
  const { track, findActive } = useJobs();
  const [devices, setDevices] = useState<BlockDevice[]>([]);
  const [device, setDevice] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");

  // Re-attach to a write that is already running (e.g. started, then the
  // technician switched pages and came back).
  const runningJob = findActive("flash-sdcard");

  const refresh = useCallback(async () => {
    try {
      setDevices(await api.sdDevices());
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  const selectedDevice = devices.find((d) => d.device === device);

  const start = async () => {
    setConfirm(false);
    setError("");
    try {
      track(await api.sdFlash(device, imageVersion!, setup));
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <Box>
      <PageHeader
        title="Flash SD card"
        subtitle="Write an openUC2 OS image (ImSwitch + firmware server) to an SD card."
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      <SectionLabel>1 · Image version</SectionLabel>
      {images.length === 0 ? (
        <Alert severity="info">
          No images cached yet — download one from the Library first.
        </Alert>
      ) : (
        <Grid container spacing={1.5}>
          {images.map((v) => (
            <Grid key={v.version_id} size={{ xs: 12, sm: 6, md: 4 }}>
              <SelectCard
                icon={<MemoryIcon />}
                selected={imageVersion === v.version_id}
                onClick={() => setImageVersion(v.version_id)}
                title={v.version_id}
                badges={
                  v.channel ? (
                    <Chip
                      size="small"
                      label={v.channel}
                      color={v.channel === "stable" ? "success" : "default"}
                    />
                  ) : null
                }
                lines={[
                  fmtBytes(v.size_bytes),
                  v.pair?.imswitch ? `ImSwitch ${v.pair.imswitch.tag}` : null,
                  v.pair?.firmware_server ? `firmware ${v.pair.firmware_server.tag}` : null,
                ]}
              />
            </Grid>
          ))}
        </Grid>
      )}

      {image && matched && (
        <Alert
          severity={matched.cached ? "success" : "warning"}
          sx={{ mt: 2 }}
          action={
            !matched.cached ? (
              <Button
                color="inherit"
                onClick={async () => {
                  try {
                    track(await api.downloadMatchingFirmware(image.version_id));
                  } catch (e) {
                    setError(String(e));
                  }
                }}
              >
                Get firmware
              </Button>
            ) : undefined
          }
        >
          Matching ESP32 firmware <strong>{matched.tag}</strong>{" "}
          {matched.cached ? "is cached and ready to flash." : "is not cached yet."}
        </Alert>
      )}

      <SectionLabel>2 · ImSwitch configuration</SectionLabel>
      <Alert severity={setup ? "success" : "info"} icon={<ScienceIcon />}>
        {setup ? (
          <>
            <strong>{setup.replace(/\.json$/, "")}</strong> will be preloaded onto the card and
            applied on first boot.
          </>
        ) : (
          "No setup preloaded — choose one on the ImSwitch Config page to configure the microscope automatically."
        )}
      </Alert>

      <SectionLabel>3 · SD card</SectionLabel>
      {devices.length === 0 ? (
        <Alert severity="info">No removable drives detected — insert an SD card.</Alert>
      ) : (
        <Grid container spacing={1.5}>
          {devices.map((d) => (
            <Grid key={d.device} size={{ xs: 12, sm: 6, md: 4 }}>
              <SelectCard
                icon={d.transport === "usb" ? <UsbIcon /> : <SdCardIcon />}
                selected={device === d.device}
                disabled={!d.writable_target}
                onClick={() => setDevice(d.device)}
                title={d.device}
                badges={
                  !d.writable_target ? (
                    <Chip size="small" color="error" label="protected" />
                  ) : null
                }
                lines={[
                  `${d.model || "Unknown"} · ${fmtBytes(d.size_bytes)} · ${d.transport || "?"}`,
                  d.mountpoints.length ? `mounted: ${d.mountpoints.join(", ")}` : null,
                ]}
              />
            </Grid>
          ))}
        </Grid>
      )}

      <Box sx={{ mt: 3 }}>
        {runningJob ? (
          <JobPanel jobId={runningJob.id} onDone={refresh} />
        ) : (
          <Button
            variant="contained"
            size="large"
            fullWidth
            disabled={!device || !imageVersion}
            onClick={() => setConfirm(true)}
            startIcon={<SdCardIcon />}
          >
            Flash {imageVersion ?? "image"} → {device || "select a card"}
          </Button>
        )}
      </Box>

      <ConfirmDialog
        open={confirm && !!selectedDevice}
        title="Erase and write SD card?"
        danger
        confirmLabel="Erase & flash"
        onConfirm={start}
        onCancel={() => setConfirm(false)}
      >
        <Stack spacing={1}>
          <Typography>
            All data on <strong>{selectedDevice?.device}</strong> (
            {selectedDevice?.model || "unknown"}, {fmtBytes(selectedDevice?.size_bytes)}) will
            be erased and replaced with <strong>{imageVersion}</strong>.
          </Typography>
          {setup && (
            <Typography>
              ImSwitch setup <strong>{setup.replace(/\.json$/, "")}</strong> will be preloaded.
            </Typography>
          )}
          <Typography variant="body2" color="text.secondary">
            This takes several minutes and cannot be undone.
          </Typography>
        </Stack>
      </ConfirmDialog>
    </Box>
  );
}
