import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Avatar,
  Badge,
  Box,
  Chip,
  CssBaseline,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  ThemeProvider,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import MenuOpenIcon from "@mui/icons-material/MenuOpen";
import SdCardIcon from "@mui/icons-material/SdCard";
import BoltIcon from "@mui/icons-material/Bolt";
import InventoryIcon from "@mui/icons-material/Inventory2";
import SettingsIcon from "@mui/icons-material/Settings";
import PrecisionManufacturingIcon from "@mui/icons-material/PrecisionManufacturing";
import HighlightIcon from "@mui/icons-material/Highlight";
import LightbulbIcon from "@mui/icons-material/Lightbulb";
import WifiTetheringIcon from "@mui/icons-material/WifiTethering";
import HubIcon from "@mui/icons-material/Hub";
import DeveloperBoardIcon from "@mui/icons-material/DeveloperBoard";
import CircleIcon from "@mui/icons-material/Circle";

import { api, type Status } from "./api";
import { JobsProvider, useJobs } from "./JobsContext";
import { SelectionProvider, useSelection } from "./SelectionContext";
import { ActivityBar } from "./components/ActivityBar";
import { SdFlashPage } from "./pages/SdFlashPage";
import { EspFlashPage } from "./pages/EspFlashPage";
import { LibraryPage } from "./pages/LibraryPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ProductionPage } from "./pages/ProductionPage";
import { TestPage } from "./pages/TestPage";
import { darkTheme, groupColors } from "./theme";

const DRAWER_WIDE = 240;
const DRAWER_NARROW = 88;

interface NavItem {
  id: string;
  label: string;
  icon: JSX.Element;
  group: string;
}

const NAV: { group: string; label: string; items: NavItem[] }[] = [
  {
    group: "provision",
    label: "Provision",
    items: [
      { id: "sd", label: "SD Card", icon: <SdCardIcon />, group: "provision" },
      { id: "esp", label: "ESP32", icon: <BoltIcon />, group: "provision" },
    ],
  },
  {
    group: "testing",
    label: "Testing",
    items: [
      { id: "test:motor", label: "Motor", icon: <PrecisionManufacturingIcon />, group: "testing" },
      { id: "test:laser", label: "Laser", icon: <HighlightIcon />, group: "testing" },
      { id: "test:led", label: "LED", icon: <LightbulbIcon />, group: "testing" },
      { id: "test:galvo", label: "Galvo", icon: <WifiTetheringIcon />, group: "testing" },
      { id: "test:can", label: "CAN bus", icon: <HubIcon />, group: "testing" },
      { id: "test:state", label: "Board", icon: <DeveloperBoardIcon />, group: "testing" },
    ],
  },
  {
    group: "library",
    label: "Library",
    items: [{ id: "library", label: "Versions", icon: <InventoryIcon />, group: "library" }],
  },
  {
    group: "system",
    label: "System",
    items: [{ id: "settings", label: "Settings", icon: <SettingsIcon />, group: "system" }],
  },
];

function Shell() {
  const [tab, setTab] = useState("sd");
  const [collapsed, setCollapsed] = useState(() => window.innerWidth < 900);
  const [status, setStatus] = useState<Status | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const { active } = useJobs();
  const { image, matched } = useSelection();

  const refreshStatus = useCallback(() => {
    api
      .status()
      .then((s) => {
        setStatus(s);
        setBackendDown(false);
      })
      .catch(() => setBackendDown(true));
  }, []);

  useEffect(() => {
    refreshStatus();
    const t = setInterval(refreshStatus, 10000);
    return () => clearInterval(t);
  }, [refreshStatus]);

  const exitProduction = async () => {
    await api.putSettings({ production_mode: false }).catch(() => {});
    refreshStatus();
    setTab("settings");
  };

  const width = collapsed ? DRAWER_NARROW : DRAWER_WIDE;

  const content = useMemo(() => {
    if (tab.startsWith("test:")) return <TestPage groupId={tab.slice(5)} key={tab} />;
    switch (tab) {
      case "sd":
        return <SdFlashPage />;
      case "esp":
        return <EspFlashPage status={status} />;
      case "library":
        return <LibraryPage status={status} />;
      case "settings":
        return <SettingsPage onChanged={refreshStatus} />;
      default:
        return null;
    }
  }, [tab, status, refreshStatus]);

  if (status?.production_mode) {
    return (
      <Box sx={{ height: "100%", overflowY: "auto", p: 3 }}>
        <ProductionPage onExit={exitProduction} />
      </Box>
    );
  }

  return (
    <Box sx={{ display: "flex", height: "100%" }}>
      <Drawer
        variant="permanent"
        sx={{
          width,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width,
            boxSizing: "border-box",
            overflowX: "hidden",
            transition: "width 150ms ease",
            scrollbarWidth: "none",
            "&::-webkit-scrollbar": { width: 0 },
          },
        }}
      >
        <Toolbar sx={{ px: 1.5, gap: 1, minHeight: 64 }}>
          <Avatar
            src="/logo.png"
            alt="openUC2"
            variant="rounded"
            sx={{ width: 36, height: 36, bgcolor: "transparent", "& img": { objectFit: "contain" } }}
          />
          {!collapsed && (
            <Typography variant="h6" noWrap sx={{ flex: 1, fontWeight: 800 }}>
              openUC2
            </Typography>
          )}
          <IconButton size="small" onClick={() => setCollapsed((c) => !c)}>
            <MenuOpenIcon sx={{ transform: collapsed ? "scaleX(-1)" : "none" }} />
          </IconButton>
        </Toolbar>
        <Divider />

        <Box sx={{ overflowY: "auto", flex: 1, py: 1 }}>
          {NAV.map((section) => (
            <Box key={section.group} sx={{ mb: 1 }}>
              {!collapsed && (
                <Typography
                  variant="caption"
                  sx={{
                    display: "block",
                    px: 2,
                    py: 0.5,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    color: groupColors[section.group],
                  }}
                >
                  {section.label}
                </Typography>
              )}
              <List dense disablePadding>
                {section.items.map((item) => {
                  const selected = tab === item.id;
                  const button = (
                    <ListItemButton
                      selected={selected}
                      onClick={() => setTab(item.id)}
                      sx={{
                        mx: 1,
                        borderLeft: 2,
                        borderColor: selected ? groupColors[item.group] : "transparent",
                        justifyContent: collapsed ? "center" : "flex-start",
                      }}
                    >
                      <ListItemIcon
                        sx={{
                          minWidth: collapsed ? 0 : 40,
                          color: selected ? groupColors[item.group] : "text.secondary",
                        }}
                      >
                        {item.icon}
                      </ListItemIcon>
                      {!collapsed && (
                        <ListItemText
                          primary={item.label}
                          slotProps={{
                            primary: { sx: { fontWeight: selected ? 700 : 500 } },
                          }}
                        />
                      )}
                    </ListItemButton>
                  );
                  return (
                    <ListItem key={item.id} disablePadding sx={{ display: "block" }}>
                      {collapsed ? (
                        <Tooltip title={item.label} placement="right">
                          {button}
                        </Tooltip>
                      ) : (
                        button
                      )}
                    </ListItem>
                  );
                })}
              </List>
            </Box>
          ))}
        </Box>

        <Divider />
        <Box sx={{ p: 1.5 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "center" }}>
            <CircleIcon
              sx={{ fontSize: 10, color: backendDown ? "error.main" : "success.main" }}
            />
            {!collapsed && (
              <Typography variant="caption" color="text.secondary" noWrap>
                {backendDown ? "backend offline" : `v${status?.app_version ?? "…"}`}
              </Typography>
            )}
          </Stack>
        </Box>
      </Drawer>

      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* top bar */}
        <Box
          sx={{
            borderBottom: 1,
            borderColor: "divider",
            bgcolor: "background.paper",
            px: 3,
            py: 1,
            flexShrink: 0,
          }}
        >
          <Stack direction="row" spacing={1.5} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
            <Typography variant="subtitle2" color="text.secondary">
              Provisioning Station
            </Typography>
            <Box sx={{ flex: 1 }} />
            {image && (
              <Chip
                size="small"
                icon={<SdCardIcon />}
                label={image.version_id}
                sx={{ maxWidth: 280 }}
              />
            )}
            {matched && (
              <Chip
                size="small"
                icon={<BoltIcon />}
                color={matched.cached ? "primary" : "warning"}
                variant={matched.cached ? "filled" : "outlined"}
                label={matched.tag}
              />
            )}
            {active.length > 0 && (
              <Badge color="primary" badgeContent={active.length}>
                <Chip size="small" label="working" color="primary" variant="outlined" />
              </Badge>
            )}
          </Stack>
        </Box>

        <Box sx={{ flex: 1, overflowY: "auto", p: 3 }}>
          {backendDown && (
            <Alert severity="error" sx={{ mb: 2 }}>
              Backend not reachable — is the uc2-provision service running?
            </Alert>
          )}
          {content}
        </Box>

        <ActivityBar />
      </Box>
    </Box>
  );
}

export default function App() {
  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
      <JobsProvider>
        <SelectionProvider>
          <Shell />
        </SelectionProvider>
      </JobsProvider>
    </ThemeProvider>
  );
}
