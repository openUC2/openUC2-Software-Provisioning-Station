import { useState } from "react";
import {
  Box,
  Collapse,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useJobs } from "../JobsContext";
import { JobPanel } from "./JobPanel";

/**
 * Always-visible strip showing everything the station is currently doing.
 *
 * This is what keeps a multi-gigabyte download visible after the technician
 * switches to another screen — the work never belonged to the page.
 */
export function ActivityBar() {
  const { active } = useJobs();
  const [open, setOpen] = useState(false);

  if (active.length === 0) return null;

  const primary = active[0];
  const pct = Math.round(primary.progress * 100);

  return (
    <Paper
      elevation={8}
      square
      sx={{
        borderTop: 1,
        borderColor: "divider",
        flexShrink: 0,
        maxHeight: "50vh",
        overflowY: "auto",
      }}
    >
      <Stack direction="row" spacing={2} sx={{ px: 2, py: 1, cursor: "pointer", alignItems: "center" }} onClick={() => setOpen((v) => !v)} >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 700 }}>
            {primary.title}
            {active.length > 1 && ` (+${active.length - 1} more)`}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap>
            {primary.phase || "Working…"} · {pct}%
          </Typography>
          <LinearProgress
            variant={pct === 0 ? "indeterminate" : "determinate"}
            value={pct}
            sx={{ mt: 0.5, height: 6, borderRadius: 3 }}
          />
        </Box>
        <IconButton size="small" aria-label={open ? "Collapse" : "Expand"}>
          {open ? <ExpandMoreIcon /> : <ExpandLessIcon />}
        </IconButton>
      </Stack>

      <Collapse in={open}>
        <Stack spacing={1.5} sx={{ p: 2, pt: 0 }}>
          {active.map((job) => (
            <JobPanel key={job.id} jobId={job.id} />
          ))}
        </Stack>
      </Collapse>
    </Paper>
  );
}
