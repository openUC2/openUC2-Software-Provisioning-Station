import { createTheme, type Theme } from "@mui/material/styles";

/**
 * openUC2 design tokens.
 *
 * Brand palette is taken from the openUC2 website theme (openuc2-next);
 * density, drawer layout and touch-target sizing follow the ImSwitch device
 * UI, which is what technicians already use on the microscopes.
 *
 * `uc2Blue` is very dark, so on dark surfaces the interactive colour is the
 * brand lime; the navy is reserved for the top bar and light surfaces.
 */
export const uc2 = {
  blue: "#023773",
  green: "#85b918",
  turquoise: "#1f9c7c",
  accent: "#e8792f",
  light: "#FAF9F9",
  dark: "#0f172a",
  surface: "#1e293b",
  gray: "#999999",
  danger: "#dc3545",
  warning: "#ffc107",
  success: "#198754",
} as const;

/** Category accent colours for the drawer groups (ImSwitch convention). */
export const groupColors: Record<string, string> = {
  provision: "#90caf9",
  testing: "#43a047",
  library: "#eba400",
  system: "#90a4ae",
};

const shared = {
  typography: {
    fontFamily:
      '"Objectivity", Roboto, system-ui, -apple-system, "Segoe UI", sans-serif',
    fontSize: 14,
    fontWeightBold: 700,
    h1: { fontWeight: 800, letterSpacing: "-0.02em" },
    h2: { fontWeight: 700, letterSpacing: "-0.01em" },
    h5: { fontWeight: 700 },
    h6: { fontWeight: 700 },
    button: { textTransform: "none" as const, fontWeight: 700 },
  },
  spacing: 8,
  shape: { borderRadius: 12 },
};

const components = (mode: "dark" | "light") => ({
  MuiButton: {
    styleOverrides: {
      root: {
        minHeight: 48,
        padding: "10px 20px",
        touchAction: "manipulation" as const,
      },
      sizeLarge: { minHeight: 64, fontSize: "1.05rem" },
    },
  },
  MuiIconButton: {
    styleOverrides: { root: { minHeight: 48, minWidth: 48 } },
  },
  MuiToggleButton: {
    styleOverrides: { root: { minHeight: 48, textTransform: "none" as const } },
  },
  MuiCard: {
    styleOverrides: {
      root: {
        backgroundImage: "none",
        border: `1px solid ${mode === "dark" ? "rgba(255,255,255,0.10)" : "#e5e7eb"}`,
      },
    },
  },
  MuiListItemButton: {
    styleOverrides: { root: { minHeight: 48, borderRadius: 10 } },
  },
  MuiChip: {
    styleOverrides: { root: { fontWeight: 700 } },
  },
  MuiTooltip: {
    styleOverrides: { tooltip: { fontSize: "0.85rem" } },
  },
});

export const darkTheme: Theme = createTheme({
  ...shared,
  palette: {
    mode: "dark",
    primary: { main: uc2.green, contrastText: "#0f172a" },
    secondary: { main: "#4aa8ff", contrastText: "#0f172a" },
    warning: { main: uc2.accent },
    success: { main: uc2.success },
    error: { main: uc2.danger },
    info: { main: uc2.turquoise },
    background: { default: uc2.dark, paper: uc2.surface },
    text: { primary: "#e2e8f0", secondary: "#94a3b8" },
    divider: "rgba(255,255,255,0.10)",
  },
  components: components("dark"),
});

export const lightTheme: Theme = createTheme({
  ...shared,
  palette: {
    mode: "light",
    primary: { main: uc2.blue, contrastText: "#ffffff" },
    secondary: { main: uc2.turquoise, contrastText: "#ffffff" },
    warning: { main: uc2.accent },
    success: { main: uc2.success },
    error: { main: uc2.danger },
    background: { default: uc2.light, paper: "#ffffff" },
    text: { primary: "#333333", secondary: "#777777" },
    divider: "#e5e7eb",
  },
  components: components("light"),
});
