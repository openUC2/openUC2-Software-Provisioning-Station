import type { ReactNode } from "react";
import { Box, Stack, Typography } from "@mui/material";

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <Stack direction="row" spacing={2} sx={{ mb: 3, alignItems: "flex-start", flexWrap: "wrap" }} useFlexGap >
      <Box sx={{ flex: 1, minWidth: 240 }}>
        <Typography variant="h5" component="h1">
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {subtitle}
          </Typography>
        )}
      </Box>
      {action}
    </Stack>
  );
}

/** Section label used above card grids. */
export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <Typography
      variant="subtitle2"
      sx={{
        textTransform: "uppercase",
        letterSpacing: "0.5px",
        fontWeight: 700,
        color: "text.secondary",
        mt: 3,
        mb: 1,
      }}
    >
      {children}
    </Typography>
  );
}
