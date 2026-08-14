import { useEffect, useState } from "react";
import { api } from "../api";

export function SettingsPage({ onChanged }: { onChanged: () => void }) {
  const [form, setForm] = useState<Record<string, unknown> | null>(null);
  const [github, setGithub] = useState<{ authenticated: boolean; user?: string; error?: string } | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getSettings().then(setForm).catch((e) => setError(String(e)));
    api.githubStatus().then(setGithub).catch(() => {});
  }, []);

  if (!form) return <div className="statusline">Loading…</div>;

  const set = (k: string, v: unknown) => setForm({ ...form, [k]: v });

  const save = async () => {
    setError("");
    setSaved(false);
    try {
      const result = await api.putSettings(form);
      setForm(result);
      setSaved(true);
      onChanged();
      api.githubStatus().then(setGithub).catch(() => {});
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div>
      <h1>Settings</h1>
      <p className="subtitle">Station configuration — stored locally on this device.</p>

      {error && <div className="error-box">{error}</div>}

      <div className="panel" style={{ maxWidth: 640 }}>
        <label className="field">
          <span>
            GitHub token (needed to download os-rpi CI images; scope: repo / actions:read)
          </span>
          <input
            type="password"
            value={String(form.github_token ?? "")}
            placeholder="ghp_… or github_pat_…"
            onChange={(e) => set("github_token", e.target.value)}
          />
        </label>
        {github && (
          <div className="statusline" style={{ marginBottom: 14 }}>
            {github.authenticated
              ? `✓ Authenticated as ${github.user}`
              : `Not authenticated${github.error ? ` — ${github.error}` : ""}`}
          </div>
        )}

        <label className="field">
          <span>Keep this many versions per source (older ones are pruned)</span>
          <input
            type="number"
            min={1}
            max={20}
            value={Number(form.keep_versions ?? 3)}
            onChange={(e) => set("keep_versions", Number(e.target.value))}
          />
        </label>

        <label className="field">
          <span>Check GitHub every … minutes (0 = manual only)</span>
          <input
            type="number"
            min={0}
            value={Number(form.check_interval_min ?? 60)}
            onChange={(e) => set("check_interval_min", Number(e.target.value))}
          />
        </label>

        <label className="field">
          <span>Default ESP32 flash baud rate</span>
          <select
            value={Number(form.esp_default_baud ?? 460800)}
            onChange={(e) => set("esp_default_baud", Number(e.target.value))}
          >
            {[115200, 230400, 460800, 921600].map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>

        <label className="field row" style={{ gap: 10, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={Boolean(form.esp_erase_before_flash)}
            onChange={(e) => set("esp_erase_before_flash", e.target.checked)}
            style={{ width: 28, height: 28 }}
          />
          <span style={{ color: "var(--text)", fontSize: 16 }}>Erase flash before writing (default)</span>
        </label>

        <hr className="section-divider" />

        <label className="field row" style={{ gap: 10, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={Boolean(form.production_mode)}
            onChange={(e) => set("production_mode", e.target.checked)}
            style={{ width: 28, height: 28 }}
          />
          <span style={{ color: "var(--text)", fontSize: 16 }}>
            <strong>Production mode</strong> — locked one-button flashing of the latest stable
            versions (exit via Settings gear on the production screen)
          </span>
        </label>

        <button className="btn primary big" onClick={save} style={{ marginTop: 10 }}>
          Save settings
        </button>
        {saved && <div className="ok-text" style={{ marginTop: 10 }}>✓ Saved</div>}
      </div>
    </div>
  );
}
