/** Typed client for the provisioning-station backend API. */

export interface Status {
  app_version: string;
  production_mode: boolean;
  image_source: string;
  firmware_source: string;
  github_token_set: boolean;
  baud_choices: number[];
  esp_default_baud: number;
  disk_total_bytes: number;
  disk_free_bytes: number;
  cache_bytes: number;
}

export interface ImageArtifact {
  artifact_id: number;
  name: string;
  version_id: string;
  size_bytes: number | null;
  digest_sha256: string;
  created_at: string;
  expires_at: string;
  head_branch: string | null;
  head_sha: string | null;
  channel: "stable" | "prerelease" | "pr" | "dev";
  cached: boolean;
}

export interface PairInfo {
  image: string;
  tag: string;
  digest: string | null;
}

export interface CachedVersion {
  category: "images" | "firmware";
  version_id: string;
  size_bytes: number;
  files: string[];
  complete?: boolean;
  downloaded_at?: number;
  channel?: string;
  head_sha?: string;
  tag?: string;
  prerelease?: boolean;
  pair?: { imswitch?: PairInfo; firmware_server?: PairInfo };
  [k: string]: unknown;
}

export interface FirmwareRelease {
  version_id: string;
  name: string;
  prerelease: boolean;
  published_at: string;
  cached: boolean;
  asset_count: number;
}

export interface FirmwareVariant {
  id: string;
  name: string;
  chip_family: string | null;
  file: string;
  category: "standalone" | "can-master" | "can-slave" | "bridge" | "other";
}

export interface BlockDevice {
  device: string;
  size_bytes: number;
  model: string;
  removable: boolean;
  transport: string;
  mountpoints: string[];
  is_system: boolean;
  writable_target: boolean;
}

export interface SerialPort {
  device: string;
  description: string;
  adapter: string | null;
  vid: string | null;
  pid: string | null;
  serial_number: string | null;
}

export interface Job {
  id: string;
  kind: string;
  title: string;
  state: "pending" | "running" | "success" | "failed" | "cancelled";
  progress: number;
  phase: string;
  error: string;
  created_at: number;
  finished_at: number | null;
  meta: Record<string, unknown>;
  log?: string[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export const api = {
  status: () => request<Status>("/api/status"),
  githubStatus: () =>
    request<{ authenticated: boolean; user?: string; error?: string }>("/api/github/status"),
  getSettings: () => request<Record<string, unknown>>("/api/settings"),
  putSettings: (patch: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  images: (remote = true) =>
    request<{ available: ImageArtifact[]; cached: CachedVersion[]; error: string | null }>(
      `/api/versions/images?remote=${remote}`,
    ),
  firmware: (remote = true) =>
    request<{ available: FirmwareRelease[]; cached: CachedVersion[]; error: string | null }>(
      `/api/versions/firmware?remote=${remote}`,
    ),
  firmwareVariants: (versionId: string) =>
    request<FirmwareVariant[]>(`/api/versions/firmware/${encodeURIComponent(versionId)}/variants`),
  downloadImage: (versionId: string) =>
    request<Job>(`/api/versions/images/${encodeURIComponent(versionId)}/download`, {
      method: "POST",
    }),
  downloadFirmware: (versionId: string) =>
    request<Job>(`/api/versions/firmware/${encodeURIComponent(versionId)}/download`, {
      method: "POST",
    }),
  deleteVersion: (category: string, versionId: string) =>
    request<{ deleted: string }>(
      `/api/versions/${category}/${encodeURIComponent(versionId)}`,
      { method: "DELETE" },
    ),
  checkUpdates: (auto = false) =>
    request<Record<string, unknown>>(`/api/versions/check?auto_download=${auto}`, {
      method: "POST",
    }),

  sdDevices: () => request<BlockDevice[]>("/api/sdcard/devices"),
  sdFlash: (device: string, versionId: string) =>
    request<Job>("/api/sdcard/flash", {
      method: "POST",
      body: JSON.stringify({ device, version_id: versionId }),
    }),

  espPorts: () => request<SerialPort[]>("/api/esp/ports"),
  espFlash: (body: {
    port: string;
    version_id: string;
    variant_id: string;
    baud?: number;
    erase_first?: boolean;
  }) => request<Job>("/api/esp/flash", { method: "POST", body: JSON.stringify(body) }),
  espSerial: (body: { port: string; payload: string; baud?: number; read_seconds?: number }) =>
    request<{ response: string }>("/api/esp/serial", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  production: () =>
    request<{
      image: CachedVersion | null;
      firmware: CachedVersion | null;
      firmware_variants: FirmwareVariant[];
    }>("/api/production"),

  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<{ cancelled: string }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
};

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "?";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)} kB`;
  return `${n} B`;
}
