import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  ButtonGroup,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Slider,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import LinkIcon from "@mui/icons-material/Link";
import LinkOffIcon from "@mui/icons-material/LinkOff";
import HubIcon from "@mui/icons-material/Hub";
import {
  api,
  type SerialPort,
  type TestConnection,
  type TestGroup,
} from "../api";
import { PageHeader, SectionLabel } from "../components/PageHeader";

type Verdict = "pass" | "fail";

/**
 * Hardware test bench for one device group (motor / laser / LED / galvo /
 * CAN / board).  Commands go through UC2-REST on the backend; the
 * technician confirms the physical result, which is what actually decides
 * pass or fail.
 */
export function TestPage({ groupId }: { groupId: string }) {
  const [groups, setGroups] = useState<TestGroup[]>([]);
  const [conn, setConn] = useState<TestConnection>({ connected: false });
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [port, setPort] = useState("");
  const [baud, setBaud] = useState(115200);
  const [axis, setAxis] = useState("X");
  const [channel, setChannel] = useState(1);
  const [sliderValue, setSliderValue] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [output, setOutput] = useState<string>("");
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [pending, setPending] = useState<{ key: string; question: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [g, p] = await Promise.all([api.testGroups(), api.espPorts()]);
      setGroups(g.groups);
      setConn(g.connection);
      setPorts(p);
      if (g.connection.connected && g.connection.port) setPort(g.connection.port);
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
    if (!port && ports.length > 0) setPort(ports[0].device);
  }, [ports, port]);

  const group = useMemo(() => groups.find((g) => g.id === groupId), [groups, groupId]);

  useEffect(() => {
    if (group?.slider && sliderValue === null) setSliderValue(group.slider.default);
  }, [group, sliderValue]);

  const connect = async () => {
    setError("");
    setBusy("connect");
    try {
      setConn(await api.testConnect(port, baud));
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    setBusy("connect");
    try {
      setConn(await api.testDisconnect());
    } finally {
      setBusy(null);
    }
  };

  const run = async (actionId: string, args: Record<string, unknown>, confirm?: string) => {
    const key = `${actionId}:${JSON.stringify(args)}`;
    setBusy(key);
    setError("");
    try {
      const res = await api.testRun(groupId, actionId, args);
      setOutput(JSON.stringify(res.result, null, 2));
      if (confirm) setPending({ key, question: confirm });
    } catch (e) {
      setError(String(e));
      setVerdicts((v) => ({ ...v, [key]: "fail" }));
    } finally {
      setBusy(null);
    }
  };

  const answer = (verdict: Verdict) => {
    if (!pending) return;
    setVerdicts((v) => ({ ...v, [pending.key]: verdict }));
    setPending(null);
  };

  if (!group) {
    return (
      <Box>
        <PageHeader title="Hardware test" />
        <Alert severity="info">Loading test catalog…</Alert>
      </Box>
    );
  }

  const masterBlocked = group.master_only && conn.connected && !conn.is_master;
  const results = Object.entries(verdicts);
  const passed = results.filter(([, v]) => v === "pass").length;
  const failed = results.filter(([, v]) => v === "fail").length;

  return (
    <Box>
      <PageHeader
        title={`Test · ${group.name}`}
        subtitle={group.prompt}
        action={
          results.length > 0 ? (
            <Stack direction="row" spacing={1}>
              <Chip color="success" icon={<CheckCircleIcon />} label={`${passed} passed`} />
              {failed > 0 && (
                <Chip color="error" icon={<CancelIcon />} label={`${failed} failed`} />
              )}
            </Stack>
          ) : undefined
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      {/* ---- connection ---- */}
      <Card variant="outlined" sx={{ mb: 2 }}>
        <CardContent>
          <Stack
            direction={{ xs: "column", md: "row" }}
            spacing={2}
            sx={{ alignItems: { md: "center" } }}
          >
            <FormControl sx={{ minWidth: 220 }} disabled={conn.connected}>
              <InputLabel id="tport">Board port</InputLabel>
              <Select
                labelId="tport"
                label="Board port"
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

            <FormControl sx={{ minWidth: 150 }} disabled={conn.connected}>
              <InputLabel id="tbaud">Baud</InputLabel>
              <Select
                labelId="tbaud"
                label="Baud"
                value={baud}
                onChange={(e) => setBaud(Number(e.target.value))}
              >
                {[115200, 921600].map((b) => (
                  <MenuItem key={b} value={b}>
                    {b}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {conn.connected ? (
              <Button
                variant="outlined"
                color="error"
                startIcon={<LinkOffIcon />}
                onClick={disconnect}
                disabled={busy === "connect"}
              >
                Disconnect
              </Button>
            ) : (
              <Button
                variant="contained"
                startIcon={<LinkIcon />}
                onClick={connect}
                disabled={!port || busy === "connect"}
              >
                {busy === "connect" ? "Connecting…" : "Connect"}
              </Button>
            )}

            <Box sx={{ flex: 1 }} />

            {conn.connected && (
              <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
                {conn.is_master && (
                  <Chip color="primary" icon={<HubIcon />} label="CAN master (HAT)" />
                )}
                {conn.board_hint && <Chip label={conn.board_hint} variant="outlined" />}
              </Stack>
            )}
          </Stack>

          {conn.connected && conn.is_master && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
              Commands sent to the master are forwarded over CAN to the addressed module, so
              motor, laser and LED tests reach the whole microscope.
            </Typography>
          )}
        </CardContent>
      </Card>

      {!conn.connected && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Connect a board to run tests.
        </Alert>
      )}
      {masterBlocked && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          The connected board is not a CAN master — bus tests are unavailable.
        </Alert>
      )}

      {/* ---- target selector ---- */}
      {group.axes && (
        <>
          <SectionLabel>Axis</SectionLabel>
          <ToggleButtonGroup
            exclusive
            value={axis}
            onChange={(_, v) => v && setAxis(v)}
            sx={{ mb: 1 }}
          >
            {group.axes.map((a) => (
              <ToggleButton key={a} value={a} sx={{ px: 3, fontWeight: 700 }}>
                {a}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </>
      )}

      {group.channels && (
        <>
          <SectionLabel>Channel</SectionLabel>
          <ToggleButtonGroup
            exclusive
            value={channel}
            onChange={(_, v) => v && setChannel(v)}
            sx={{ mb: 1 }}
          >
            {group.channels.map((c) => (
              <ToggleButton key={c} value={c} sx={{ px: 3, fontWeight: 700 }}>
                {c === 1 ? "1 · R" : c === 2 ? "2 · G" : c === 3 ? "3 · B" : c}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </>
      )}

      {group.slider && (
        <>
          <SectionLabel>{group.slider.label}</SectionLabel>
          <Card variant="outlined" sx={{ mb: 1, px: 3, py: 1 }}>
            <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
              <Slider
                value={sliderValue ?? group.slider.default}
                min={group.slider.min}
                max={group.slider.max}
                onChange={(_, v) => setSliderValue(v as number)}
                sx={{ flex: 1 }}
              />
              <Chip
                label={sliderValue ?? group.slider.default}
                sx={{ minWidth: 72, fontWeight: 700, fontFamily: "monospace" }}
              />
            </Stack>
          </Card>
        </>
      )}

      {/* ---- actions ---- */}
      <SectionLabel>Tests</SectionLabel>
      <Grid container spacing={1.5}>
        {group.actions.map((a) => {
          const args: Record<string, unknown> = {};
          if (a.per_axis) args.axis = axis;
          if (a.per_channel) args.channel = channel;
          if (a.uses_value && group.slider) {
            const v = sliderValue ?? group.slider.default;
            // The laser API takes a single 0-1023 value; the LED matrix API
            // takes an RGB triple, so drive it as a grayscale intensity.
            if (group.id === "led") args.intensity = [v, v, v];
            else args.value = v;
          }
          const key = `${a.id}:${JSON.stringify(args)}`;
          const verdict = verdicts[key];
          return (
            <Grid key={a.id} size={{ xs: 6, sm: 4, md: 3 }}>
              <Button
                fullWidth
                size="large"
                variant={verdict === "pass" ? "contained" : "outlined"}
                color={
                  verdict === "pass"
                    ? "success"
                    : verdict === "fail"
                      ? "error"
                      : a.danger
                        ? "warning"
                        : "primary"
                }
                disabled={!conn.connected || masterBlocked || busy !== null}
                onClick={() => run(a.id, args, a.confirm)}
                sx={{ minHeight: 72, flexDirection: "column", gap: 0.5 }}
              >
                {a.name}
                {(a.per_axis || a.per_channel || a.uses_value) && (
                  <Typography variant="caption" sx={{ opacity: 0.8 }}>
                    {[
                      a.per_axis ? axis : null,
                      a.per_channel ? `ch ${channel}` : null,
                      a.uses_value ? String(args.value ?? (args.intensity as number[])?.[0]) : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </Typography>
                )}
              </Button>
            </Grid>
          );
        })}
      </Grid>

      {/* ---- pass/fail prompt ---- */}
      {pending && (
        <Card variant="outlined" sx={{ mt: 3, borderColor: "warning.main", borderWidth: 2 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              {pending.question}
            </Typography>
            <ButtonGroup fullWidth size="large" sx={{ mt: 1 }}>
              <Button
                color="success"
                variant="contained"
                startIcon={<CheckCircleIcon />}
                onClick={() => answer("pass")}
              >
                Yes — pass
              </Button>
              <Button
                color="error"
                variant="contained"
                startIcon={<CancelIcon />}
                onClick={() => answer("fail")}
              >
                No — fail
              </Button>
            </ButtonGroup>
          </CardContent>
        </Card>
      )}

      {output && (
        <>
          <Divider sx={{ my: 3 }} />
          <SectionLabel>Last response</SectionLabel>
          <Box
            component="pre"
            className="selectable"
            sx={{
              p: 1.5,
              m: 0,
              maxHeight: 240,
              overflow: "auto",
              bgcolor: "#1e1e1e",
              color: "#4ec9b0",
              borderRadius: 2,
              fontFamily: "Consolas, Monaco, monospace",
              fontSize: 12,
            }}
          >
            {output}
          </Box>
        </>
      )}
    </Box>
  );
}
