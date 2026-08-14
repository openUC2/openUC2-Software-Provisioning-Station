import { useCallback, useEffect, useState } from "react";
import {
  api,
  BlockDevice,
  CachedVersion,
  FirmwareVariant,
  SerialPort,
  fmtBytes,
} from "../api";
import { JobPanel } from "../components/JobPanel";
import { ConfirmDialog } from "../components/Modal";

/** Locked production screen: one-button flashing of the latest cached
 * versions. No version dropdowns — just "what am I flashing" buttons. */
export function ProductionPage({ onExit }: { onExit: () => void }) {
  const [image, setImage] = useState<CachedVersion | null>(null);
  const [firmware, setFirmware] = useState<CachedVersion | null>(null);
  const [variants, setVariants] = useState<FirmwareVariant[]>([]);
  const [devices, setDevices] = useState<BlockDevice[]>([]);
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [confirmSd, setConfirmSd] = useState<BlockDevice | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [prod, devs, prts] = await Promise.all([
        api.production(),
        api.sdDevices(),
        api.espPorts(),
      ]);
      setImage(prod.image);
      setFirmware(prod.firmware);
      setVariants(prod.firmware_variants);
      setDevices(devs.filter((d) => d.writable_target));
      setPorts(prts);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  const flashSd = async (device: BlockDevice) => {
    setConfirmSd(null);
    if (!image) return;
    try {
      const job = await api.sdFlash(device.device, image.version_id);
      setJobId(job.id);
    } catch (e) {
      setError(String(e));
    }
  };

  const flashEsp = async (variant: FirmwareVariant) => {
    if (!firmware || ports.length === 0) return;
    try {
      const job = await api.espFlash({
        port: ports[0].device,
        version_id: firmware.version_id,
        variant_id: variant.id,
      });
      setJobId(job.id);
    } catch (e) {
      setError(String(e));
    }
  };

  const imswitchTag = image?.pair?.imswitch?.tag;
  const fwServerTag = image?.pair?.firmware_server?.tag;

  return (
    <div className="production">
      <button
        className="btn"
        style={{ position: "fixed", top: 14, right: 14 }}
        onClick={onExit}
        title="Exit production mode"
      >
        ⚙
      </button>

      <h1>openUC2 Production Flasher</h1>

      {error && <div className="error-box">{error}</div>}

      {jobId ? (
        <div className="panel" style={{ textAlign: "left" }}>
          <JobPanel
            jobId={jobId}
            onDone={() => {
              setJobId(null);
              refresh();
            }}
          />
        </div>
      ) : (
        <>
          <div className="panel">
            <div className="statusline">SD card image</div>
            <div className="version-display">{image?.version_id ?? "no image cached"}</div>
            {(imswitchTag || fwServerTag) && (
              <div className="hash">
                {imswitchTag && <>imswitch {imswitchTag}</>}
                {imswitchTag && fwServerTag && " · "}
                {fwServerTag && <>fw-server {fwServerTag}</>}
              </div>
            )}
            <div style={{ marginTop: 16 }}>
              {devices.length === 0 && (
                <div className="statusline">Insert an SD card to flash.</div>
              )}
              {devices.map((d) => (
                <button
                  key={d.device}
                  className="btn primary big"
                  style={{ marginTop: 8 }}
                  disabled={!image}
                  onClick={() => setConfirmSd(d)}
                >
                  Flash SD card ({fmtBytes(d.size_bytes)} · {d.model || d.device})
                </button>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="statusline">ESP32 firmware</div>
            <div className="version-display">
              {(firmware?.tag as string) ?? firmware?.version_id ?? "no firmware cached"}
            </div>
            <div className="statusline" style={{ marginTop: 4 }}>
              {ports.length > 0
                ? `Board connected on ${ports[0].device}`
                : "Connect a board via USB to flash."}
            </div>
            <div className="cardlist" style={{ marginTop: 16, textAlign: "left" }}>
              {variants.map((v) => (
                <div
                  key={v.id}
                  className={`card${ports.length === 0 ? " disabled" : ""}`}
                  onClick={() => flashEsp(v)}
                >
                  <div className="title">{v.name}</div>
                  <div className="sub">{v.chip_family ?? "auto"}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {confirmSd && image && (
        <ConfirmDialog
          title="Erase and write SD card?"
          danger
          message={
            <p>
              ALL DATA on <strong>{confirmSd.device}</strong> ({fmtBytes(confirmSd.size_bytes)})
              will be replaced with <strong>{image.version_id}</strong>.
            </p>
          }
          confirmLabel="Erase & Flash"
          onConfirm={() => flashSd(confirmSd)}
          onCancel={() => setConfirmSd(null)}
        />
      )}
    </div>
  );
}
