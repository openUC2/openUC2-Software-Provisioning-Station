import { useCallback, useEffect, useState } from "react";
import {
  api,
  CachedVersion,
  FirmwareRelease,
  ImageArtifact,
  Status,
  fmtBytes,
} from "../api";
import { JobPanel } from "../components/JobPanel";
import { ConfirmDialog } from "../components/Modal";

/** Version library: browse GitHub versions, download, delete, manage disk. */
export function LibraryPage({ status }: { status: Status | null }) {
  const [images, setImages] = useState<ImageArtifact[]>([]);
  const [firmware, setFirmware] = useState<FirmwareRelease[]>([]);
  const [cachedImages, setCachedImages] = useState<CachedVersion[]>([]);
  const [cachedFirmware, setCachedFirmware] = useState<CachedVersion[]>([]);
  const [remoteError, setRemoteError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [toDelete, setToDelete] = useState<CachedVersion | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async (remote: boolean) => {
    setLoading(remote);
    try {
      const [imgs, fw] = await Promise.all([api.images(remote), api.firmware(remote)]);
      if (remote) {
        setImages(imgs.available);
        setFirmware(fw.available);
        setRemoteError(imgs.error || fw.error);
      }
      setCachedImages(imgs.cached);
      setCachedFirmware(fw.cached);
    } catch (e) {
      setRemoteError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh(true);
  }, [refresh]);

  const startJob = (p: Promise<{ id: string }>) => {
    setError("");
    p.then((job) => setJobIds((ids) => [...ids, job.id])).catch((e) => setError(String(e)));
  };

  const doDelete = async () => {
    if (!toDelete) return;
    try {
      await api.deleteVersion(toDelete.category, toDelete.version_id);
      setToDelete(null);
      refresh(false);
    } catch (e) {
      setError(String(e));
      setToDelete(null);
    }
  };

  const diskFree = status ? fmtBytes(status.disk_free_bytes) : "?";
  const cacheSize = status ? fmtBytes(status.cache_bytes) : "?";

  return (
    <div>
      <h1>Library</h1>
      <p className="subtitle">
        Cached versions and GitHub releases · cache {cacheSize} · disk free {diskFree}
      </p>

      {error && <div className="error-box">{error}</div>}
      {remoteError && (
        <div className="error-box">
          GitHub unreachable: {remoteError} — cached versions still work offline.
        </div>
      )}

      <div className="row" style={{ marginBottom: 16 }}>
        <button className="btn" disabled={loading} onClick={() => refresh(true)}>
          {loading ? "Checking…" : "↻ Check GitHub now"}
        </button>
        <button
          className="btn"
          onClick={() => startJob(api.checkUpdates(true).then(() => ({ id: "" })))}
        >
          ⬇ Auto-download latest
        </button>
      </div>

      {jobIds.map((id) =>
        id ? (
          <div className="panel" key={id}>
            <JobPanel
              jobId={id}
              onDone={() => {
                setJobIds((ids) => ids.filter((x) => x !== id));
                refresh(false);
              }}
            />
          </div>
        ) : null,
      )}

      <h2>SD card images — {status?.image_source ?? "openUC2/os-rpi"}</h2>
      <div className="panel">
        {!status?.github_token_set && (
          <div className="statusline" style={{ marginBottom: 10 }}>
            ⚠ Downloading images requires a GitHub token (Settings) — os-rpi images are CI
            artifacts, not public release files.
          </div>
        )}
        <div className="cardlist">
          {images.map((a) => (
            <div key={a.artifact_id} className="card" style={{ cursor: "default" }}>
              <div className="title">
                {a.version_id}
                <span className={`badge ${a.channel}`}>{a.channel}</span>
                {a.cached && <span className="badge cached">cached</span>}
              </div>
              <div className="sub">
                {fmtBytes(a.size_bytes)} · {new Date(a.created_at).toLocaleDateString()}
              </div>
              <div className="sub">expires {new Date(a.expires_at).toLocaleDateString()}</div>
              {!a.cached && (
                <button
                  className="btn"
                  style={{ marginTop: 8, width: "100%" }}
                  onClick={() => startJob(api.downloadImage(a.version_id))}
                >
                  ⬇ Download
                </button>
              )}
            </div>
          ))}
          {images.length === 0 && <div className="statusline">No downloadable images found.</div>}
        </div>
      </div>

      <h2>ESP32 firmware — {status?.firmware_source ?? "youseetoo/uc2-esp32"}</h2>
      <div className="panel">
        <div className="cardlist">
          {firmware.map((r) => (
            <div key={r.version_id} className="card" style={{ cursor: "default" }}>
              <div className="title">
                {r.version_id}
                <span className={`badge ${r.prerelease ? "prerelease" : "stable"}`}>
                  {r.prerelease ? "pre-release" : "stable"}
                </span>
                {r.cached && <span className="badge cached">cached</span>}
              </div>
              <div className="sub">
                {r.asset_count} assets · {new Date(r.published_at).toLocaleDateString()}
              </div>
              {!r.cached && (
                <button
                  className="btn"
                  style={{ marginTop: 8, width: "100%" }}
                  onClick={() => startJob(api.downloadFirmware(r.version_id))}
                >
                  ⬇ Download
                </button>
              )}
            </div>
          ))}
          {firmware.length === 0 && <div className="statusline">No firmware releases found.</div>}
        </div>
      </div>

      <h2>On this station</h2>
      <div className="panel">
        {[...cachedImages, ...cachedFirmware].length === 0 && (
          <div className="statusline">Nothing cached yet.</div>
        )}
        <div className="cardlist">
          {[...cachedImages, ...cachedFirmware].map((v) => (
            <div key={`${v.category}-${v.version_id}`} className="card" style={{ cursor: "default" }}>
              <div className="title">
                {v.version_id}
                <span className="badge cached">{v.category === "images" ? "image" : "firmware"}</span>
                {!v.complete && <span className="badge prerelease">incomplete</span>}
              </div>
              <div className="sub">{fmtBytes(v.size_bytes)}</div>
              {v.pair?.imswitch && (
                <div className="sub">imswitch: {v.pair.imswitch.tag}</div>
              )}
              {v.pair?.firmware_server && (
                <div className="sub">fw-server: {v.pair.firmware_server.tag}</div>
              )}
              {typeof v.head_sha === "string" && v.head_sha && (
                <div className="sub">commit: {(v.head_sha as string).slice(0, 7)}</div>
              )}
              <button
                className="btn danger"
                style={{ marginTop: 8, width: "100%" }}
                onClick={() => setToDelete(v)}
              >
                🗑 Delete
              </button>
            </div>
          ))}
        </div>
      </div>

      {toDelete && (
        <ConfirmDialog
          title="Delete cached version?"
          danger
          message={
            <p>
              Remove <strong>{toDelete.version_id}</strong> ({fmtBytes(toDelete.size_bytes)}) from
              the station cache? You can re-download it later from GitHub.
            </p>
          }
          confirmLabel="Delete"
          onConfirm={doDelete}
          onCancel={() => setToDelete(null)}
        />
      )}
    </div>
  );
}
