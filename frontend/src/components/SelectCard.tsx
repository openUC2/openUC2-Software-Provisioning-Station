import type { ReactNode } from "react";
import { Box, Card, CardActionArea, Stack, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";

/** Large touch target used for picking devices, versions and boards. */
export function SelectCard({
  selected,
  disabled,
  onClick,
  icon,
  title,
  lines,
  badges,
}: {
  selected?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  icon?: ReactNode;
  title: ReactNode;
  lines?: ReactNode[];
  badges?: ReactNode;
}) {
  return (
    <Card
      variant="outlined"
      sx={{
        borderWidth: 2,
        borderColor: selected ? "primary.main" : "divider",
        bgcolor: selected ? "action.selected" : "background.paper",
        opacity: disabled ? 0.45 : 1,
        height: "100%",
      }}
    >
      <CardActionArea
        disabled={disabled}
        onClick={onClick}
        sx={{ p: 2, height: "100%", alignItems: "flex-start", justifyContent: "flex-start" }}
      >
        <Stack direction="row" spacing={1.5} sx={{ width: "100%", alignItems: "flex-start" }}>
          {icon && <Box sx={{ color: "primary.main", display: "flex", pt: 0.25 }}>{icon}</Box>}
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Stack direction="row" spacing={0.75} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Typography sx={{ wordBreak: "break-word", fontWeight: 700 }}>
                {title}
              </Typography>
              {badges}
            </Stack>
            {lines?.map((line, i) =>
              line ? (
                <Typography key={i} variant="caption" color="text.secondary" sx={{ wordBreak: "break-all", display: "block" }} >
                  {line}
                </Typography>
              ) : null,
            )}
          </Box>
          {selected && <CheckCircleIcon color="primary" />}
        </Stack>
      </CardActionArea>
    </Card>
  );
}
