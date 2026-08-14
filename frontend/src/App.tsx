import { useCallback, useEffect, useState } from "react";
import { api, Status } from "./api";
import { SdFlashPage } from "./pages/SdFlashPage";
import { EspFlashPage } from "./pages/EspFlashPage";
import { LibraryPage } from "./pages/LibraryPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ProductionPage } from "./pages/ProductionPage";

type Tab = "sd" | "esp" | "library" | "settings";

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: "sd", icon: "💾", label: "SD Card" },
  { id: "esp", icon: "🔌", label: "ESP32" },
  { id: "library", icon: "📚", label: "Library" },
  { id: "settings", icon: "⚙️", label: "Settings" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("sd");
  const [status, setStatus] = useState<Status | null>(null);
  const [backendDown, setBackendDown] = useState(false);

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

  if (status?.production_mode) {
    return (
      <div className="main" style={{ height: "100%" }}>
        <ProductionPage onExit={exitProduction} />
      </div>
    );
  }

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">openUC2</div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`navbtn${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            <span className="icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
        <div className="spacer" />
        <div className="footer">
          {backendDown ? "backend offline" : `v${status?.app_version ?? "…"}`}
        </div>
      </nav>
      <main className="main">
        {backendDown && (
          <div className="error-box">Backend not reachable — is the service running?</div>
        )}
        {tab === "sd" && <SdFlashPage />}
        {tab === "esp" && <EspFlashPage status={status} />}
        {tab === "library" && <LibraryPage status={status} />}
        {tab === "settings" && <SettingsPage onChanged={refreshStatus} />}
      </main>
    </div>
  );
}
