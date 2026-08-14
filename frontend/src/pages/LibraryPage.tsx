import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Grid,
  IconButton,
  LinearProgress,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import DownloadIcon from "@mui/icons-material/Download";
import RefreshIcon from "@mui/icons-material/Refresh";
import CloudSyncIcon from "@mui/icons-material/CloudSync";
import MemoryIcon from "@mui/icons-material/Memory";
import InventoryIcon from "@mui/icons-material/Inventory2";
import {
  api,
  fmtBytes,
  type CachedVersion,
  type FirmwareBundle,
  type ImageArtifact,
  type Status,
} from "../api";
import { useJobs } from "../JobsContext";
import { useSelection } from "../SelectionContext";
import { ConfirmDialog } from "../components/Confirm";
import { PageHeader, SectionLabel } from "../components/PageHeader";
import { SelectCard } from "../components/SelectCard";

export function LibraryPage({ status }: { status: Status | null }) {
  const { track } = useJobs();
  const { refresh: refreshSelection } = useSelection();
  const [images, setImages] = useState<ImageArtifact[]>([]);
  const [bundles, setBundles] = useState<FirmwareBundle[]>([]);
  const [cached, setCached] = useState<CachedVersion[]>([]);
  const [remoteError, setRemoteError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [toDelete, setToDelete] = useState<CachedVersion | null>(null);
  const [error, setError] = useState("");
  const [pairs, setPairs] = useState<Record<string, string>>({});

  const refresh = useCallback(
    async (remote: boolean) => {
      setLoading(remote);
      try {
        const [imgs, fw] = await Promise.all([api.images(remote), api.firmware(remote)]);
        if (remote) {
          setImages(imgs.available);
          setRemoteError(imgs.error || fw.error);
        }
        setBundles(fw.available);
        setCached([...imgs.cached, ...fw.cached]);
      } catch (e) {
        setRemoteError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    refresh(true);
  }, [refresh]);

  const start = async (p: Promise<{ id: string }>) => {
    setError("");
    try {
      track((await p) as any);
      refresh(false);
      refreshSelection();
    } catch (e) {
      setError(String(e));
    }
  };

  const lookupPair = async (versionId: string) => {
    try {
      const res = await api.imagePair(versionId);
      const parts = [
        res.pair.imswitch ? `ImSwitch ${res.pair.imswitch.tag}` : null,
        res.pair.firmware_server ? `firmware ${res.pair.firmware_server.tag}` : null,
      ].filter(Boolean);
      setPairs((p) => ({ ...p, [versionId]: parts.join(" · ") || "no pins found" }));
    } catch (e) {
      setPairs((p) => ({ ...p, [versionId]: `lookup failed: ${e}` }));
    }
  };

  const doDelete = async () => {
    if (!toDelete) return;
    try {
      await api.deleteVersion(toDelete.category, toDelete.version_id);
      setToDelete(null);
      refresh(false);
      refreshSelection();
    } catch (e) {
      setError(String(e));
      setToDelete(null);
    }
  };

  return (
    <Box>
      <PageHeader
        title="Library"
        subtitle={
          status
            ? `Cache ${fmtBytes(status.cache_bytes)} · disk free ${fmtBytes(status.disk_free_bytes)}`
            : undefined
        }
        action={
          <Stack direction="row" spacing={1}>
            <Button
              startIcon={<RefreshIcon />}
              onClick={() => refresh(true)}
              disabled={loading}
              variant="outlined"
            >
              Check GitHub
            </Button>
            <Button
              startIcon={<CloudSyncIcon />}
              variant="contained"
              onClick={() => start(api.checkUpdates(true) as any)}
            >
              Get latest
            </Button>
          </Stack>
        }
      />

      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}
      {remoteError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          GitHub unreachable: {remoteError} — cached versions still work offline.
        </Alert>
      )}
      {!status?.github_token_set && (
        <Alert severity="info" sx={{ mb: 2 }}>
          SD images are CI artifacts and need a GitHub token to download — add one in Settings.
        </Alert>
      )}

      <SectionLabel>SD card images · {status?.image_source ?? "openUC2/os-rpi"}</SectionLabel>
      <Grid container spacing={1.5}>
        {images.map((a) => (
          <Grid key={a.artifact_id} size={{ xs: 12, sm: 6, md: 4 }}>
            <SelectCard
              icon={<MemoryIcon />}
              title={a.version_id}
              badges={
                <>
                  <Chip
                    size="small"
                    label={a.channel}
                    color={a.channel === "stable" ? "success" : "default"}
                  />
                  {a.cached && <Chip size="small" color="info" label="cached" />}
                </>
              }
              lines={[
                `${fmtBytes(a.size_bytes)} · ${new Date(a.created_at).toLocaleDateString()}`,
                `expires ${new Date(a.expires_at).toLocaleDateString()}`,
                pairs[a.version_id],
              ]}
              onClick={() => lookupPair(a.version_id)}
            />
            <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
              {!a.cached && (
                <Button
                  fullWidth
                  size="small"
                  startIcon={<DownloadIcon />}
                  onClick={() => start(api.downloadImage(a.version_id))}
                >
                  Download
                </Button>
              )}
              {a.cached && (
                <Button
                  fullWidth
                  size="small"
                  startIcon={<DownloadIcon />}
                  onClick={() => start(api.downloadMatchingFirmware(a.version_id))}
                >
                  Matching firmware
                </Button>
              )}
            </Stack>
          </Grid>
        ))}
        {images.length === 0 && !loading && (
          <Grid size={12}>
            <Alert severity="info">No downloadable images found.</Alert>
          </Grid>
        )}
      </Grid>

      <SectionLabel>ESP32 firmware bundles</SectionLabel>
      <Grid container spacing={1.5}>
        {bundles.map((b) => (
          <Grid key={b.version_id} size={{ xs: 12, sm: 6, md: 4 }}>
            <SelectCard
              icon={<InventoryIcon />}
              title={b.name}
              badges={
                <>
                  <Chip
                    size="small"
                    label={b.source_kind === "container" ? "matched" : b.source_kind}
                    color={b.source_kind === "container" ? "primary" : "default"}
                  />
                  {b.cached && <Chip size="small" color="info" label="cached" />}
                </>
              }
              lines={[
                b.container_ref,
                b.matches_image ? `matches ${b.matches_image}` : null,
                b.published_at ? new Date(b.published_at).toLocaleDateString() : null,
              ]}
            />
            {!b.cached && (
              <Button
                fullWidth
                size="small"
                startIcon={<DownloadIcon />}
                sx={{ mt: 0.5 }}
                onClick={() => start(api.downloadFirmware(b.version_id))}
              >
                Download
              </Button>
            )}
          </Grid>
        ))}
      </Grid>

      <SectionLabel>Stored on this station</SectionLabel>
      <Grid container spacing={1.5}>
        {cached.map((v) => (
          <Grid key={`${v.category}-${v.version_id}`} size={{ xs: 12, sm: 6, md: 4 }}>
            <Box sx={{ position: "relative" }}>
              <SelectCard
                icon={v.category === "images" ? <MemoryIcon /> : <InventoryIcon />}
                title={(v.tag as string) || v.version_id}
                badges={
                  <>
                    <Chip
                      size="small"
                      label={v.category === "images" ? "image" : "firmware"}
                    />
                    {!v.complete && <Chip size="small" color="warning" label="incomplete" />}
                  </>
                }
                lines={[
                  fmtBytes(v.size_bytes),
                  v.pair?.imswitch ? `ImSwitch ${v.pair.imswitch.tag}` : null,
                  v.pair?.firmware_server ? `firmware ${v.pair.firmware_server.tag}` : null,
                  v.container_ref,
                  typeof v.head_sha === "string" && v.head_sha
                    ? `commit ${(v.head_sha as string).slice(0, 7)}`
                    : null,
                ]}
              />
              <Tooltip title="Delete from cache">
                <IconButton
                  size="small"
                  color="error"
                  sx={{ position: "absolute", top: 4, right: 4 }}
                  onClick={() => setToDelete(v)}
                >
                  <DeleteIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Grid>
        ))}
        {cached.length === 0 && (
          <Grid size={12}>
            <Alert severity="info">Nothing cached yet.</Alert>
          </Grid>
        )}
      </Grid>

      <ConfirmDialog
        open={!!toDelete}
        title="Delete cached version?"
        danger
        confirmLabel="Delete"
        onConfirm={doDelete}
        onCancel={() => setToDelete(null)}
      >
        <Typography>
          Remove <strong>{toDelete?.version_id}</strong> ({fmtBytes(toDelete?.size_bytes)}) from
          the station cache? It can be downloaded again later.
        </Typography>
      </ConfirmDialog>
    </Box>
  );
}
