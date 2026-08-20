import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControlLabel,
  Grid,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import CloudSyncIcon from "@mui/icons-material/CloudSync";
import ScienceIcon from "@mui/icons-material/Science";
import SdCardIcon from "@mui/icons-material/SdCard";
import BlockIcon from "@mui/icons-material/Block";
import {
  api,
  fmtBytes,
  type BlockDevice,
  type ConfigListing,
  type ConfigPreview,
} from "../api";
import { useJobs } from "../JobsContext";
import { useSelection } from "../SelectionContext";
import { JobPanel } from "../components/JobPanel";
import { PageHeader, SectionLabel } from "../components/PageHeader";
import { SelectCard } from "../components/SelectCard";

/**
 * Pick the ImSwitch setup that gets preloaded onto a card.
 *
 * The chosen setup is written as an `init-root-*.tar.gz` archive into the
 * root of the boot partition; os-rpi extracts it onto `/` on first boot and
 * deletes it, so the microscope comes up already configured.
 */
export function ConfigPage() {
  const { setup, setSetup } = useSelection();
  const { track, findActive } = useJobs();
  const [listing, setListing] = useState<ConfigListing | null>(null);
  const [preview, setPreview] = useState<ConfigPreview | null>(null);
  const [devices, setDevices] = useState<BlockDevice[]>([]);
  const [device, setDevice] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");

  const applyJob = findActive("apply-config");

  const refresh = useCallback(async () => {
    try {
      const [l, d] = await Promise.all([api.configs(), api.sdDevices()]);
      setListing(l);
      setDevices(d.filter((x) => x.writable_target));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (!setup) {
      setPreview(null);
      return;
    }
    api.configPreview(setup).then(setPreview).catch(() => setPreview(null));
  }, [setup]);

  const doSync = async () => {
    setSyncing(true);
    setError("");
    try {
      await api.syncConfigs();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSyncing(false);
    }
  };

  const toggleShowAll = async (v: boolean) => {
    try {
      await api.putSettings({ imswitch_show_all_setups: v });
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const applyToCard = async () => {
    if (!device || !setup) return;
    setError("");
    try {
      track(await api.applyConfig(device, setup));
    } catch (e) {
      setError(String(e));
    }
  };

  const setups = listing?.setups ?? [];
  const neverSynced = listing !== null && !listing.synced_at;

  return (
    <Box>
      <PageHeader
        title="ImSwitch configuration"
        subtitle="Preload a microscope setup onto the SD card — applied automatically on first boot."
        action={
          <Stack direction="row" spacing={1}>
            <Button
              variant="outlined"
              startIcon={<CloudSyncIcon />}
              onClick={doSync}
              disabled={syncing}
            >
              {syncing ? "Syncing…" : "Sync from GitHub"}
            </Button>
          </Stack>
        }
      />

      {syncing && <LinearProgress sx={{ mb: 2 }} />}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}
      {neverSynced && (
        <Alert severity="info" sx={{ mb: 2 }}>
          No setups synced yet — press “Sync from GitHub” to fetch them from{" "}
          openUC2/ImSwitchConfig.
        </Alert>
      )}

      {listing && listing.synced_at && (
        <Stack
          direction="row"
          spacing={2}
          useFlexGap
          sx={{ alignItems: "center", flexWrap: "wrap", mb: 1 }}
        >
          <Typography variant="body2" color="text.secondary">
            {listing.source} · synced{" "}
            {new Date(listing.synced_at * 1000).toLocaleString()} ·{" "}
            {listing.total_upstream} available upstream
          </Typography>
          <Box sx={{ flex: 1 }} />
          <FormControlLabel
            control={
              <Switch
                checked={listing.show_all}
                onChange={(e) => toggleShowAll(e.target.checked)}
              />
            }
            label={<Typography variant="body2">Show all setups</Typography>}
          />
        </Stack>
      )}

      <SectionLabel>Setup</SectionLabel>
      <Grid container spacing={1.5}>
        <Grid size={{ xs: 12, sm: 6, md: 4 }}>
          <SelectCard
            icon={<BlockIcon />}
            selected={!setup}
            onClick={() => setSetup(null)}
            title="No preloaded config"
            lines={["Card boots with the image's built-in default"]}
          />
        </Grid>
        {setups.map((s) => (
          <Grid size={{ xs: 12, sm: 6, md: 4 }} key={s.name}>
            <SelectCard
              icon={<ScienceIcon />}
              selected={setup === s.name}
              disabled={!s.available}
              onClick={() => setSetup(s.name)}
              title={s.name.replace(/\.json$/, "")}
              badges={
                listing?.show_all && s.curated ? (
                  <Chip size="small" color="primary" label="curated" />
                ) : null
              }
              lines={[
                fmtBytes(s.size),
                s.summary?.cameras?.length ? `camera: ${s.summary.cameras.join(", ")}` : null,
                s.summary?.lasers?.length
                  ? `lasers: ${s.summary.lasers.join(", ")}`
                  : null,
                s.summary?.positioners?.length
                  ? `stage: ${s.summary.positioners.join(", ")}`
                  : null,
              ]}
            />
          </Grid>
        ))}
      </Grid>

      {preview && (
        <>
          <SectionLabel>What gets written</SectionLabel>
          <Alert severity="success" icon={<SdCardIcon />} sx={{ mb: 1 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>
              <strong>{preview.archive_name}</strong> ({fmtBytes(preview.archive_bytes)}) into
              the boot partition root, unpacked on first boot to:
            </Typography>
            <Box
              component="pre"
              className="selectable"
              sx={{ m: 0, fontSize: 12, fontFamily: "Consolas, Monaco, monospace" }}
            >
              {preview.paths.map((p) => `/${p}`).join("\n")}
              {"\n\nsetupFileName = "}
              {String((preview.options as any).setupFileName)}
            </Box>
          </Alert>
        </>
      )}

      <SectionLabel>Apply to an already-flashed card</SectionLabel>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Flashing an image from the SD Card page already includes the selected setup. Use this
        only to add a config to a card that is already written.
      </Typography>

      {applyJob ? (
        <JobPanel jobId={applyJob.id} onDone={refresh} />
      ) : (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ alignItems: "center" }}>
          <Select
            displayEmpty
            value={devices.some((d) => d.device === device) ? device : ""}
            onChange={(e) => setDevice(e.target.value)}
            sx={{ minWidth: 260 }}
          >
            <MenuItem value="">
              {devices.length ? "Select a card…" : "No removable card detected"}
            </MenuItem>
            {devices.map((d) => (
              <MenuItem key={d.device} value={d.device}>
                {d.device} · {d.model || "unknown"} · {fmtBytes(d.size_bytes)}
              </MenuItem>
            ))}
          </Select>
          <Button
            variant="contained"
            startIcon={<SdCardIcon />}
            disabled={!device || !setup}
            onClick={applyToCard}
          >
            Write config to card
          </Button>
        </Stack>
      )}
    </Box>
  );
}
