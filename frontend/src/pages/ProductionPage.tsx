import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import SettingsIcon from "@mui/icons-material/Settings";
import SdCardIcon from "@mui/icons-material/SdCard";
import BoltIcon from "@mui/icons-material/Bolt";
import {
  api,
  fmtBytes,
  type BlockDevice,
  type CachedVersion,
  type FirmwareVariant,
  type SerialPort,
} from "../api";
import { useJobs } from "../JobsContext";
import { JobPanel } from "../components/JobPanel";
import { ConfirmDialog } from "../components/Confirm";

/** Locked assembly-line screen: latest cached versions, one button each. */
export function ProductionPage({ onExit }: { onExit: () => void }) {
  const { track, active } = useJobs();
  const [image, setImage] = useState<CachedVersion | null>(null);
  const [firmware, setFirmware] = useState<CachedVersion | null>(null);
  const [variants, setVariants] = useState<FirmwareVariant[]>([]);
  const [devices, setDevices] = useState<BlockDevice[]>([]);
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [confirmSd, setConfirmSd] = useState<BlockDevice | null>(null);
  const [paired, setPaired] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [prod, devs, prts] = await Promise.all([
        api.production(),
        api.sdDevices(),
        api.espPorts(),
      ]);
      setImage(prod.image);
      setFirmware(prod.firmware);
      setPaired(prod.paired ?? true);
      setVariants(prod.firmware_variants);
      setDevices(devs.filter((d) => d.writable_target));
      setPorts(prts);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  const flashSd = async (device: BlockDevice) => {
    setConfirmSd(null);
    if (!image) return;
    try {
      track(await api.sdFlash(device.device, image.version_id));
    } catch (e) {
      setError(String(e));
    }
  };

  const flashEsp = async (variant: FirmwareVariant) => {
    if (!firmware || ports.length === 0) return;
    try {
      track(
        await api.espFlash({
          port: ports[0].device,
          version_id: firmware.version_id,
          variant_id: variant.id,
        }),
      );
    } catch (e) {
      setError(String(e));
    }
  };

  const job = active[0];

  return (
    <Box sx={{ maxWidth: 900, mx: "auto", position: "relative" }}>
      <IconButton
        onClick={onExit}
        sx={{ position: "absolute", top: 0, right: 0 }}
        aria-label="Exit production mode"
      >
        <SettingsIcon />
      </IconButton>

      <Stack sx={{ mb: 3, alignItems: "center" }}>
        <Box component="img" src="/logo.png" alt="openUC2" sx={{ height: 64, mb: 1 }} />
        <Typography variant="h5" sx={{ fontWeight: 800 }}>
          Production Flasher
        </Typography>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      {job ? (
        <JobPanel jobId={job.id} onDone={refresh} />
      ) : (
        <Stack spacing={2}>
          <Card variant="outlined">
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                SD card image
              </Typography>
              <Typography variant="h5" color="primary" sx={{ wordBreak: "break-all", fontWeight: 800 }}>
                {image?.version_id ?? "no image cached"}
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }} useFlexGap>
                {image?.pair?.imswitch && (
                  <Chip size="small" label={`ImSwitch ${image.pair.imswitch.tag}`} />
                )}
                {image?.pair?.firmware_server && (
                  <Chip size="small" label={`firmware ${image.pair.firmware_server.tag}`} />
                )}
              </Stack>

              {devices.length === 0 ? (
                <Alert severity="info" sx={{ mt: 2 }}>
                  Insert an SD card to flash.
                </Alert>
              ) : (
                devices.map((d) => (
                  <Button
                    key={d.device}
                    fullWidth
                    size="large"
                    variant="contained"
                    startIcon={<SdCardIcon />}
                    disabled={!image}
                    onClick={() => setConfirmSd(d)}
                    sx={{ mt: 2, minHeight: 72 }}
                  >
                    Flash SD card · {fmtBytes(d.size_bytes)} · {d.model || d.device}
                  </Button>
                ))
              )}
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                ESP32 firmware
              </Typography>
              <Typography variant="h5" color="primary" sx={{ wordBreak: "break-all", fontWeight: 800 }}>
                {(firmware?.tag as string) ?? firmware?.version_id ?? "no firmware cached"}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {ports.length > 0
                  ? `Board connected on ${ports[0].device}`
                  : "Connect a board via USB to flash."}
              </Typography>

              {image && firmware && !paired && (
                <Alert severity="warning" sx={{ mt: 1.5 }}>
                  This firmware is not the bundle pinned by the cached image — download the
                  matching one before shipping units.
                </Alert>
              )}

              <Grid container spacing={1.5} sx={{ mt: 1 }}>
                {variants.map((v) => (
                  <Grid key={v.id} size={{ xs: 12, sm: 6 }}>
                    <Button
                      fullWidth
                      variant="outlined"
                      startIcon={<BoltIcon />}
                      disabled={ports.length === 0}
                      onClick={() => flashEsp(v)}
                      sx={{ minHeight: 64, justifyContent: "flex-start" }}
                    >
                      <Box sx={{ textAlign: "left" }}>
                        <Typography sx={{ fontWeight: 700 }}>{v.name}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {v.chip_family ?? "auto"}
                        </Typography>
                      </Box>
                    </Button>
                  </Grid>
                ))}
              </Grid>
            </CardContent>
          </Card>
        </Stack>
      )}

      <ConfirmDialog
        open={!!confirmSd}
        title="Erase and write SD card?"
        danger
        confirmLabel="Erase & flash"
        onConfirm={() => confirmSd && flashSd(confirmSd)}
        onCancel={() => setConfirmSd(null)}
      >
        <Typography>
          All data on <strong>{confirmSd?.device}</strong> ({fmtBytes(confirmSd?.size_bytes)})
          will be replaced with <strong>{image?.version_id}</strong>.
        </Typography>
      </ConfirmDialog>
    </Box>
  );
}
