import { useCallback, useEffect, useMemo, useState } from "react";
import { api, CachedVersion, FirmwareVariant, SerialPort, Status } from "../api";
import { JobPanel } from "../components/JobPanel";

const CATEGORY_LABEL: Record<string, string> = {
  standalone: "Standalone boards",
  "can-master": "CAN master",
  "can-slave": "CAN modules (motor / laser / LED …)",
  bridge: "Bridges",
  other: "Other",
};

/** Flash a uc2-esp32 firmware variant onto a connected board. */
export function EspFlashPage({ status }: { status: Status | null }) {
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [cached, setCached] = useState<CachedVersion[]>([]);
  const [variants, setVariants] = useState<FirmwareVariant[]>([]);
  const [port, setPort] = useState("");
  const [versionId, setVersionId] = useState("");
  const [variantId, setVariantId] = useState("");
  const [baud, setBaud] = useState<number>(0);
  const [erase, setErase] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [p, fw] = await Promise.all([api.espPorts(), api.firmware(false)]);
      setPorts(p);
      setCached(fw.cached.filter((v) => v.complete));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  // Default to newest cached firmware.
  useEffect(() => {
    if (!versionId && cached.length > 0) setVersionId(cached[0].version_id);
  }, [cached, versionId]);

  useEffect(() => {
    if (!versionId) return;
    api.firmwareVariants(versionId).then(setVariants).catch(() => setVariants([]));
    setVariantId("");
  }, [versionId]);

  useEffect(() => {
    if (status && !baud) setBaud(status.esp_default_baud);
  }, [status, baud]);

  const grouped = useMemo(() => {
    const g: Record<string, FirmwareVariant[]> = {};
    for (const v of variants) (g[v.category] ??= []).push(v);
    return g;
  }, [variants]);

  const start = async () => {
    setError("");
    try {
      const job = await api.espFlash({
        port,
        version_id: versionId,
        variant_id: variantId,
        baud: baud || undefined,
        erase_first: erase,
      });
      setJobId(job.id);
    } catch (e) {
      setError(String(e));
    }
  };

  const variant = variants.find((v) => v.id === variantId);

  return (
    <div>
      <h1>Flash ESP32</h1>
      <p className="subtitle">
        Erase and program UC2 boards — motors, laser, LED, standalone controllers.
      </p>

      {error && <div className="error-box">{error}</div>}

      <div className="panel">
        <div className="row">
          <label className="field grow">
            <span>Firmware release</span>
            <select value={versionId} onChange={(e) => setVersionId(e.target.value)}>
              <option value="">— select —</option>
              {cached.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  {(v.tag as string) || v.version_id}
                  {v.prerelease ? " (pre-release)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="field grow">
            <span>Serial port</span>
            <select value={port} onChange={(e) => setPort(e.target.value)}>
              <option value="">— select —</option>
              {ports.map((p) => (
                <option key={p.device} value={p.device}>
                  {p.device}
                  {p.adapter ? ` (${p.adapter})` : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        {cached.length === 0 && (
          <div className="statusline">
            No firmware cached yet — download a release in the Library tab first.
          </div>
        )}
      </div>

      {versionId && (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Board / module</h2>
          {Object.entries(grouped).map(([cat, list]) => (
            <div key={cat}>
              <h2 style={{ fontSize: 15, color: "var(--muted)" }}>
                {CATEGORY_LABEL[cat] ?? cat}
              </h2>
              <div className="cardlist">
                {list.map((v) => (
                  <div
                    key={v.id}
                    className={`card${variantId === v.id ? " selected" : ""}`}
                    onClick={() => setVariantId(v.id)}
                  >
                    <div className="title">{v.name}</div>
                    <div className="sub">
                      {v.chip_family ?? "auto"} · {v.file}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {variants.length === 0 && (
            <div className="statusline">No variants found in this release.</div>
          )}
        </div>
      )}

      <div className="panel">
        <div className="row" style={{ marginBottom: 14 }}>
          <label className="field" style={{ width: 200 }}>
            <span>Baud rate</span>
            <select value={baud} onChange={(e) => setBaud(Number(e.target.value))}>
              {(status?.baud_choices ?? [115200, 230400, 460800, 921600]).map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <label className="field row" style={{ gap: 10, alignItems: "center", marginTop: 18 }}>
            <input
              type="checkbox"
              checked={erase}
              onChange={(e) => setErase(e.target.checked)}
              style={{ width: 28, height: 28 }}
            />
            <span style={{ fontSize: 16, color: "var(--text)" }}>Erase flash first (recommended)</span>
          </label>
        </div>
        <button
          className="btn primary big"
          disabled={!port || !variantId || !!jobId}
          onClick={start}
        >
          {erase ? "Erase & flash" : "Flash"} {variant?.name ?? ""} → {port || "…"}
        </button>
        {jobId && (
          <div style={{ marginTop: 16 }}>
            <JobPanel jobId={jobId} onDone={() => setJobId(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
