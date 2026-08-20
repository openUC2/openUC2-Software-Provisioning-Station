import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControlLabel,
  Grid,
  MenuItem,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import SaveIcon from "@mui/icons-material/Save";
import { api } from "../api";
import { PageHeader, SectionLabel } from "../components/PageHeader";
import { UpdateCard } from "../components/UpdateCard";

export function SettingsPage({ onChanged }: { onChanged: () => void }) {
  const [form, setForm] = useState<Record<string, any> | null>(null);
  const [github, setGithub] = useState<{
    authenticated: boolean;
    user?: string;
    error?: string;
  } | null>(null);
  const [params, setParams] = useState<Record<string, any> | null>(null);
  const [schema, setSchema] = useState<Record<string, any> | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getSettings().then(setForm).catch((e) => setError(String(e)));
    api.githubStatus().then(setGithub).catch(() => {});
    api
      .testParams()
      .then((r) => {
        setParams(r.values);
        setSchema(r.schema);
      })
      .catch(() => {});
  }, []);

  if (!form) return <Typography color="text.secondary">Loading…</Typography>;

  const set = (k: string, v: unknown) => setForm({ ...form, [k]: v });
  const setParam = (group: string, key: string, v: unknown) =>
    setParams((p) => (p ? { ...p, [group]: { ...p[group], [key]: v } } : p));

  const save = async () => {
    setError("");
    try {
      setForm(await api.putSettings(form));
      if (params) {
        const { motor, laser, led, galvo, baud } = params;
        const r = await api.putTestParams({ motor, laser, led, galvo, baud });
        setParams(r.values);
      }
      setSaved(true);
      onChanged();
      api.githubStatus().then(setGithub).catch(() => {});
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <Box>
      <PageHeader
        title="Settings"
        subtitle="Station configuration — stored locally on this device."
        action={
          <Button variant="contained" size="large" startIcon={<SaveIcon />} onClick={save}>
            Save
          </Button>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      <Card variant="outlined" sx={{ mb: 2, maxWidth: 760 }}>
        <CardContent>
          <Stack spacing={2.5}>
            <Box>
              <TextField
                fullWidth
                type="password"
                label="GitHub token"
                helperText="Needed to download os-rpi images (CI artifacts). Scope: actions:read / repo."
                value={form.github_token ?? ""}
                onChange={(e) => set("github_token", e.target.value)}
              />
              {github && (
                <Chip
                  sx={{ mt: 1 }}
                  size="small"
                  color={github.authenticated ? "success" : "default"}
                  label={
                    github.authenticated
                      ? `Authenticated as ${github.user}`
                      : `Not authenticated${github.error ? ` — ${github.error}` : ""}`
                  }
                />
              )}
            </Box>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                fullWidth
                type="number"
                label="Versions to keep"
                helperText="Older cached versions are pruned"
                value={form.keep_versions ?? 3}
                onChange={(e) => set("keep_versions", Number(e.target.value))}
              />
              <TextField
                fullWidth
                type="number"
                label="Check interval (minutes)"
                helperText="0 disables automatic checks"
                value={form.check_interval_min ?? 60}
                onChange={(e) => set("check_interval_min", Number(e.target.value))}
              />
              <TextField
                fullWidth
                select
                label="Default flash baud"
                value={form.esp_default_baud ?? 460800}
                onChange={(e) => set("esp_default_baud", Number(e.target.value))}
              >
                {[115200, 230400, 460800, 921600].map((b) => (
                  <MenuItem key={b} value={b}>
                    {b}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>

            <FormControlLabel
              control={
                <Switch
                  checked={Boolean(form.esp_erase_before_flash)}
                  onChange={(e) => set("esp_erase_before_flash", e.target.checked)}
                />
              }
              label="Erase flash before writing"
            />

            <Divider />

            <FormControlLabel
              control={
                <Switch
                  checked={Boolean(form.production_mode)}
                  onChange={(e) => set("production_mode", e.target.checked)}
                />
              }
              label={
                <Box>
                  <Typography sx={{ fontWeight: 700 }}>Production mode</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Locked one-button screen for assembly — latest cached version only.
                  </Typography>
                </Box>
              }
            />
          </Stack>
        </CardContent>
      </Card>

      {/* ---- station software update ---- */}
      <SectionLabel>Station software</SectionLabel>
      <UpdateCard />

      {/* ---- hardware test parameters ---- */}
      {params && schema && (
        <>
          <SectionLabel>Hardware test parameters</SectionLabel>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Values the Testing pages use for each command — tune these per production batch.
          </Typography>

          <Card variant="outlined" sx={{ mb: 2, maxWidth: 760 }}>
            <CardContent>
              <TextField
                select
                label="Test serial baud"
                helperText="UC2 firmware console: 115200 standard, 921600 for fast-console boards"
                value={params.baud ?? 115200}
                onChange={(e) =>
                  setParams((p) => (p ? { ...p, baud: Number(e.target.value) } : p))
                }
                sx={{ minWidth: 260 }}
              >
                {[115200, 921600].map((b) => (
                  <MenuItem key={b} value={b}>
                    {b}
                  </MenuItem>
                ))}
              </TextField>
            </CardContent>
          </Card>

          {Object.entries(schema).map(([group, fields]) => (
            <Card variant="outlined" key={group} sx={{ mb: 2, maxWidth: 760 }}>
              <CardContent>
                <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 700 }}>
                  {group[0].toUpperCase() + group.slice(1)}
                </Typography>
                <Grid container spacing={2}>
                  {Object.entries(fields as Record<string, any>).map(([key, meta]) => {
                    const value = params[group]?.[key];
                    if (meta.type === "bool") {
                      return (
                        <Grid key={key} size={{ xs: 12, sm: 6 }}>
                          <FormControlLabel
                            control={
                              <Switch
                                checked={Boolean(value)}
                                onChange={(e) => setParam(group, key, e.target.checked)}
                              />
                            }
                            label={meta.description || key}
                          />
                        </Grid>
                      );
                    }
                    return (
                      <Grid key={key} size={{ xs: 12, sm: 6 }}>
                        <TextField
                          fullWidth
                          label={key}
                          helperText={meta.description}
                          value={
                            Array.isArray(value) ? value.join(", ") : (value ?? "")
                          }
                          onChange={(e) => {
                            const raw = e.target.value;
                            if (meta.type === "list") {
                              setParam(
                                group,
                                key,
                                raw
                                  .split(",")
                                  .map((s) => Number(s.trim()))
                                  .filter((n) => !Number.isNaN(n)),
                              );
                            } else {
                              setParam(group, key, raw === "" ? null : Number(raw));
                            }
                          }}
                        />
                      </Grid>
                    );
                  })}
                </Grid>
              </CardContent>
            </Card>
          ))}
        </>
      )}

      <Snackbar
        open={saved}
        autoHideDuration={2500}
        onClose={() => setSaved(false)}
        message="Settings saved"
      />
    </Box>
  );
}
