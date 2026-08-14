import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import BoltIcon from "@mui/icons-material/Bolt";
import CableIcon from "@mui/icons-material/Cable";
import DeveloperBoardIcon from "@mui/icons-material/DeveloperBoard";
import HubIcon from "@mui/icons-material/Hub";
import SettingsInputComponentIcon from "@mui/icons-material/SettingsInputComponent";
import ScienceIcon from "@mui/icons-material/Science";
import LockOpenIcon from "@mui/icons-material/LockOpen";
import {
  api,
  type FirmwareBundle,
  type FirmwareVariant,
  type SerialPort,
  type Status,
} from "../api";
import { useJobs } from "../JobsContext";
import { useSelection } from "../SelectionContext";
import { JobPanel } from "../components/JobPanel";
import { PageHeader, SectionLabel } from "../components/PageHeader";
import { SelectCard } from "../components/SelectCard";

const CATEGORY_LABEL: Record<string, string> = {
  standalone: "Standalone controllers",
  "can-master": "CAN master (HAT)",
  "can-slave": "CAN modules",
  bridge: "Bridges",
  odmr: "ODMR boards",
  other: "Other boards",
};

const CATEGORY_ICON: Record<string, JSX.Element> = {
  standalone: <DeveloperBoardIcon />,
  "can-master": <HubIcon />,
  "can-slave": <SettingsInputComponentIcon />,
  bridge: <CableIcon />,
  odmr: <ScienceIcon />,
  other: <DeveloperBoardIcon />,
};

export function EspFlashPage({ status }: { status: Status | null }) {
  const { image, matched, unlocked, setUnlocked } = useSelection();
  const { track, findActive } = useJobs();
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [bundles, setBundles] = useState<FirmwareBundle[]>([]);
  const [variants, setVariants] = useState<FirmwareVariant[]>([]);
  const [bundleId, setBundleId] = useState("");
  const [port, setPort] = useState("");
  const [variantId, setVariantId] = useState("");
  const [baud, setBaud] = useState(0);
  const [erase, setErase] = useState(true);
  const [error, setError] = useState("");

  const runningJob = findActive("flash-esp");

  const refresh = useCallback(async () => {
    try {
      const [p, fw] = await Promise.all([api.espPorts(), api.firmware(false)]);
      setPorts(p);
      setBundles(fw.cached.filter((v) => v.complete).map((v) => ({
        version_id: v.version_id,
        name: (v.tag as string) || v.version_id,
        source_kind: (v.source_kind as FirmwareBundle["source_kind"]) ?? "release",
        tag: (v.tag as string) ?? v.version_id,
        cached: true,
      })));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  // The pairing rule: unless explicitly unlocked, the only firmware offered
  // is the bundle pinned by the selected SD image.
  const allowedBundles = useMemo(() => {
    if (unlocked || !matched) return bundles;
    return bundles.filter((b) => b.version_id === matched.version_id);
  }, [bundles, matched, unlocked]);

  useEffect(() => {
    if (allowedBundles.length === 0) {
      setBundleId("");
      return;
    }
    if (!allowedBundles.some((b) => b.version_id === bundleId)) {
      setBundleId(allowedBundles[0].version_id);
    }
  }, [allowedBundles, bundleId]);

  useEffect(() => {
    if (!bundleId) {
      setVariants([]);
      return;
    }
    api.firmwareVariants(bundleId).then(setVariants).catch(() => setVariants([]));
    setVariantId("");
  }, [bundleId]);

  useEffect(() => {
    if (status && !baud) setBaud(status.esp_default_baud);
  }, [status, baud]);

  const grouped = useMemo(() => {
    const g: Record<string, FirmwareVariant[]> = {};
    for (const v of variants) (g[v.category] ??= []).push(v);
    return g;
  }, [variants]);

  const variant = variants.find((v) => v.id === variantId);

  const start = async () => {
    setError("");
    try {
      track(
        await api.espFlash({
          port,
          version_id: bundleId,
          variant_id: variantId,
          baud: baud || undefined,
          erase_first: erase,
        }),
      );
    } catch (e) {
      setError(String(e));
    }
  };

  const matchedMissing = matched && !matched.cached && !unlocked;

  return (
    <Box>
      <PageHeader
        title="Flash ESP32"
        subtitle="Erase and program UC2 boards — motors, laser, LED, standalone controllers."
        action={
          matched ? (
            <FormControlLabel
              control={
                <Switch checked={unlocked} onChange={(e) => setUnlocked(e.target.checked)} />
              }
              label={
                <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
                  <LockOpenIcon fontSize="small" />
                  <Typography variant="body2">Any firmware</Typography>
                </Stack>
              }
            />
          ) : undefined
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      {matched && !unlocked && (
        <Alert severity={matched.cached ? "info" : "warning"} sx={{ mb: 2 }}
          action={
            matchedMissing && image ? (
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
                Download
              </Button>
            ) : undefined
          }
        >
          Locked to the firmware matching <strong>{image?.version_id}</strong> — bundle{" "}
          <strong>{matched.tag}</strong>
          {matched.imswitch_tag ? ` (ImSwitch ${matched.imswitch_tag})` : ""}.
          {matchedMissing && " It is not cached yet."}
        </Alert>
      )}

      {!matched && (
        <Alert severity="info" sx={{ mb: 2 }}>
          No SD image selected, so firmware is not constrained. Select an image on the SD Card
          page to enforce a matching pair.
        </Alert>
      )}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 1 }}>
        <FormControl fullWidth>
          <InputLabel id="bundle-label">Firmware bundle</InputLabel>
          <Select
            labelId="bundle-label"
            label="Firmware bundle"
            value={allowedBundles.some((b) => b.version_id === bundleId) ? bundleId : ""}
            onChange={(e) => setBundleId(e.target.value)}
          >
            {allowedBundles.map((b) => (
              <MenuItem key={b.version_id} value={b.version_id}>
                {b.name} · {b.source_kind}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl fullWidth>
          <InputLabel id="port-label">Serial port</InputLabel>
          <Select
            labelId="port-label"
            label="Serial port"
            value={ports.some((p) => p.device === port) ? port : ""}
            onChange={(e) => setPort(e.target.value)}
          >
            {ports.map((p) => (
              <MenuItem key={p.device} value={p.device}>
                {p.device}
                {p.adapter ? ` (${p.adapter})` : ""}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {allowedBundles.length === 0 && (
        <Alert severity="warning">
          No firmware cached. Download a bundle from the Library.
        </Alert>
      )}
      {ports.length === 0 && (
        <Alert severity="info" sx={{ mt: 1 }}>
          No board detected — connect one over USB.
        </Alert>
      )}

      {Object.entries(grouped).map(([cat, list]) => (
        <Box key={cat}>
          <SectionLabel>{CATEGORY_LABEL[cat] ?? cat}</SectionLabel>
          <Grid container spacing={1.5}>
            {list.map((v) => (
              <Grid key={v.id} size={{ xs: 12, sm: 6, md: 4 }}>
                <SelectCard
                  icon={CATEGORY_ICON[v.category]}
                  selected={variantId === v.id}
                  onClick={() => setVariantId(v.id)}
                  title={v.name}
                  badges={
                    v.can_axis ? <Chip size="small" label={`axis ${v.can_axis}`} /> : null
                  }
                  lines={[v.chip_family ?? "chip auto-detect", v.description]}
                />
              </Grid>
            ))}
          </Grid>
        </Box>
      ))}

      <Stack direction="row" spacing={2} sx={{ mt: 3, mb: 2, alignItems: "center", flexWrap: "wrap" }} useFlexGap>
        <FormControl sx={{ minWidth: 180 }}>
          <InputLabel id="baud-label">Flash baud</InputLabel>
          <Select
            labelId="baud-label"
            label="Flash baud"
            value={baud || ""}
            onChange={(e) => setBaud(Number(e.target.value))}
          >
            {(status?.baud_choices ?? [115200, 230400, 460800, 921600]).map((b) => (
              <MenuItem key={b} value={b}>
                {b}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControlLabel
          control={<Switch checked={erase} onChange={(e) => setErase(e.target.checked)} />}
          label="Erase flash first (recommended)"
        />
      </Stack>

      {runningJob ? (
        <JobPanel jobId={runningJob.id} />
      ) : (
        <Button
          variant="contained"
          size="large"
          fullWidth
          startIcon={<BoltIcon />}
          disabled={!port || !variantId}
          onClick={start}
        >
          {erase ? "Erase & flash" : "Flash"} {variant?.name ?? "board"} → {port || "select port"}
        </Button>
      )}
    </Box>
  );
}
