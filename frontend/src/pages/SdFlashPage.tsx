import { useCallback, useEffect, useState } from "react";
import { api, BlockDevice, CachedVersion, fmtBytes } from "../api";
import { JobPanel } from "../components/JobPanel";
import { ConfirmDialog } from "../components/Modal";

/** Flash a cached os-rpi image onto an SD card. */
export function SdFlashPage() {
  const [devices, setDevices] = useState<BlockDevice[]>([]);
  const [cached, setCached] = useState<CachedVersion[]>([]);
  const [device, setDevice] = useState<string>("");
  const [versionId, setVersionId] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      const [devs, imgs] = await Promise.all([api.sdDevices(), api.images(false)]);
      setDevices(devs);
      setCached(imgs.cached.filter((v) => v.complete));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  const selectedDevice = devices.find((d) => d.device === device);
  const selectedVersion = cached.find((v) => v.version_id === versionId);

  const start = async () => {
    setConfirm(false);
    setError("");
    try {
      const job = await api.sdFlash(device, versionId);
      setJobId(job.id);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div>
      <h1>Flash SD card</h1>
      <p className="subtitle">Write an openUC2 OS image (ImSwitch + firmware server) to an SD card.</p>

      {error && <div className="error-box">{error}</div>}

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>1 · Image version</h2>
        {cached.length === 0 && (
          <div className="statusline">
            No images cached yet — download one in the Library tab first.
          </div>
        )}
        <div className="cardlist">
          {cached.map((v) => (
            <div
              key={v.version_id}
              className={`card${versionId === v.version_id ? " selected" : ""}`}
              onClick={() => setVersionId(v.version_id)}
            >
              <div className="title">
                {v.version_id}
                {v.channel && <span className={`badge ${v.channel}`}>{v.channel}</span>}
              </div>
              <div className="sub">{fmtBytes(v.size_bytes)}</div>
              {v.pair?.imswitch && (
                <div className="sub">imswitch: {v.pair.imswitch.tag}</div>
              )}
              {v.pair?.firmware_server && (
                <div className="sub">fw-server: {v.pair.firmware_server.tag}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>2 · SD card</h2>
        {devices.length === 0 && (
          <div className="statusline">No removable drives detected — insert an SD card.</div>
        )}
        <div className="cardlist">
          {devices.map((d) => (
            <div
              key={d.device}
              className={`card${device === d.device ? " selected" : ""}${
                d.writable_target ? "" : " disabled"
              }`}
              onClick={() => d.writable_target && setDevice(d.device)}
            >
              <div className="title">{d.device}</div>
              <div className="sub">
                {d.model || "Unknown"} · {fmtBytes(d.size_bytes)} · {d.transport || "?"}
              </div>
              {d.mountpoints.length > 0 && <div className="sub">mounted: {d.mountpoints.join(", ")}</div>}
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <button
          className="btn primary big"
          disabled={!device || !versionId || !!jobId}
          onClick={() => setConfirm(true)}
        >
          Flash {selectedVersion?.version_id ?? "image"} → {device || "…"}
        </button>
        {jobId && (
          <div style={{ marginTop: 16 }}>
            <JobPanel jobId={jobId} onDone={() => { setJobId(null); refresh(); }} />
          </div>
        )}
      </div>

      {confirm && selectedDevice && (
        <ConfirmDialog
          title="Erase and write SD card?"
          danger
          message={
            <>
              <p>
                ALL DATA on <strong>{selectedDevice.device}</strong> (
                {selectedDevice.model || "unknown"}, {fmtBytes(selectedDevice.size_bytes)}) will be
                erased and replaced with <strong>{versionId}</strong>.
              </p>
            </>
          }
          confirmLabel="Erase & Flash"
          onConfirm={start}
          onCancel={() => setConfirm(false)}
        />
      )}
    </div>
  );
}
