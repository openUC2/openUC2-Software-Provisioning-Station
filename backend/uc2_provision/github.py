"""GitHub artifact/release client.

Two distinct sources feed the station:

* **SD card images** (openUC2/os-rpi): the build workflow publishes images
  ONLY as GitHub Actions *artifacts* (never as release assets), so listing
  and downloading them requires a GitHub token with `repo`/`actions:read`
  scope.  Artifact names look like `os-rpi-v26.0.0.img.xz`,
  `os-rpi-pr-285-6d00c59.img.xz` or `os-rpi-6d00c59.img.xz`.

* **ESP32 firmware** (youseetoo/uc2-esp32): published as normal release
  assets (public, no token needed, though a token raises rate limits).

For any os-rpi commit we can also resolve the **matching pair** — the pinned
`ghcr.io/openuc2/imswitch:sha-...` and
`ghcr.io/youseetoo/firmware-image-server:v...` container refs — by reading
the deployment compose files at that commit.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

from .config import Settings

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"

ProgressCb = Callable[[int, int | None], None]  # (bytes_done, bytes_total)

# Compose files that pin the software versions baked into an os-rpi image.
PAIR_FILES = {
    "imswitch": "deployments/imswitch.pkg/deployment.compose.yml",
    "firmware_server": "deployments/firmware.pkg/deployment.compose.yml",
}
IMAGE_REF_RE = re.compile(
    r"image:\s*(?P<ref>[\w.\-/]+:(?P<tag>[\w.\-]+)(?:@sha256:(?P<digest>[0-9a-f]+))?)"
)


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "uc2-provision-station",
        }
        if self.settings.github_token:
            h["Authorization"] = f"Bearer {self.settings.github_token}"
        return h

    def _client(self, timeout: float = 30.0) -> httpx.Client:
        return httpx.Client(headers=self._headers(), timeout=timeout, follow_redirects=True)

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        with self._client() as c:
            r = c.get(url, params=params)
            if r.status_code == 401:
                raise GitHubError("GitHub token invalid or expired (401)")
            if r.status_code == 403 and "rate limit" in r.text.lower():
                raise GitHubError("GitHub API rate limit exceeded — configure a token in Settings")
            if r.status_code == 404:
                raise GitHubError(f"Not found: {url}")
            r.raise_for_status()
            return r.json()

    def check_auth(self) -> dict[str, Any]:
        """Returns token status + rate limit info."""
        with self._client() as c:
            r = c.get(f"{API}/rate_limit")
            r.raise_for_status()
            core = r.json().get("resources", {}).get("core", {})
        user = None
        if self.settings.github_token:
            try:
                user = self._get_json(f"{API}/user").get("login")
            except (GitHubError, httpx.HTTPError):
                user = None
        return {
            "authenticated": bool(user),
            "user": user,
            "rate_limit_remaining": core.get("remaining"),
            "rate_limit": core.get("limit"),
        }

    # ------------------------------------------------------------------
    # SD card images (Actions artifacts on openUC2/os-rpi)
    # ------------------------------------------------------------------
    def list_image_artifacts(self, limit: int = 40) -> list[dict[str, Any]]:
        """List downloadable .img.xz artifacts, newest first.

        Requires a token (the Actions artifacts API rejects anonymous
        requests for downloads; listing works but downloads won't).
        """
        src = self.settings.image_source
        data = self._get_json(
            f"{API}/repos/{src.owner}/{src.repo}/actions/artifacts",
            params={"per_page": 100},
        )
        out: list[dict[str, Any]] = []
        for a in data.get("artifacts", []):
            name = a.get("name", "")
            if a.get("expired"):
                continue
            if not any(fnmatch.fnmatch(name, p) for p in ("*.img.xz", "*.img.zip", "*.img")):
                continue
            run = a.get("workflow_run") or {}
            digest = (a.get("digest") or "").removeprefix("sha256:")
            out.append(
                {
                    "artifact_id": a["id"],
                    "name": name,
                    "version_id": name.removesuffix(".img.xz").removesuffix(".img.zip"),
                    "size_bytes": a.get("size_in_bytes"),
                    "digest_sha256": digest,
                    "created_at": a.get("created_at"),
                    "expires_at": a.get("expires_at"),
                    "head_branch": run.get("head_branch"),
                    "head_sha": run.get("head_sha"),
                    "workflow_run_id": run.get("id"),
                    "channel": self._channel_for(name, run.get("head_branch") or ""),
                }
            )
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _channel_for(name: str, head_branch: str) -> str:
        if re.search(r"-v\d", name) or head_branch.startswith("v"):
            if re.search(r"(alpha|beta|rc)", name + head_branch):
                return "prerelease"
            return "stable"
        if "-pr-" in name:
            return "pr"
        return "dev"

    def resolve_pair(self, ref: str) -> dict[str, Any]:
        """Resolve pinned imswitch/firmware-server container refs at an
        os-rpi git ref (tag, branch or commit sha)."""
        src = self.settings.image_source
        pair: dict[str, Any] = {}
        with self._client() as c:
            for key, path in PAIR_FILES.items():
                url = f"{RAW}/{src.owner}/{src.repo}/{ref}/{path}"
                try:
                    r = c.get(url)
                    if r.status_code != 200:
                        continue
                    m = IMAGE_REF_RE.search(r.text)
                    if m:
                        pair[key] = {
                            "image": m.group("ref").split("@")[0],
                            "tag": m.group("tag"),
                            "digest": m.group("digest"),
                        }
                except httpx.HTTPError:
                    continue
        return pair

    def download_artifact(
        self,
        artifact_id: int,
        dest_dir: Path,
        progress: ProgressCb,
        cancelled: Callable[[], bool] = lambda: False,
        fallback_name: str | None = None,
    ) -> list[Path]:
        """Download an Actions artifact and extract it into dest_dir.

        The `/zip` endpoint is documented to always return a zip wrapper,
        but for some single-file artifacts GitHub has been observed to
        redirect straight to the raw file instead (no zip framing at all).
        Detect that case and use the downloaded bytes as-is rather than
        failing the whole download after the multi-GB transfer already
        completed.

        Returns the list of extracted files.  Verifies nothing here — the
        caller compares sha256 against the reported artifact digest.
        """
        if not self.settings.github_token:
            raise GitHubError(
                "Downloading Actions artifacts requires a GitHub token — set one in Settings"
            )
        src = self.settings.image_source
        url = f"{API}/repos/{src.owner}/{src.repo}/actions/artifacts/{artifact_id}/zip"
        zip_path = dest_dir / f".artifact-{artifact_id}.zip"
        self._stream_download(url, zip_path, progress, cancelled)

        if not zipfile.is_zipfile(zip_path):
            target = dest_dir / (fallback_name or f"artifact-{artifact_id}.bin")
            zip_path.rename(target)
            return [target]

        extracted: list[Path] = []
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                target = dest_dir / Path(info.filename).name  # flatten
                with zf.open(info) as fsrc, open(target, "wb") as fdst:
                    while chunk := fsrc.read(1 << 20):
                        if cancelled():
                            fdst.close()
                            target.unlink(missing_ok=True)
                            raise GitHubError("cancelled")
                        fdst.write(chunk)
                extracted.append(target)
        zip_path.unlink(missing_ok=True)
        return extracted

    # ------------------------------------------------------------------
    # ESP32 firmware (release assets on youseetoo/uc2-esp32)
    # ------------------------------------------------------------------
    def list_firmware_releases(self, limit: int = 10) -> list[dict[str, Any]]:
        src = self.settings.firmware_source
        releases = self._get_json(
            f"{API}/repos/{src.owner}/{src.repo}/releases", params={"per_page": limit}
        )
        out = []
        for rel in releases:
            if rel.get("draft"):
                continue
            if rel.get("prerelease") and not src.include_prereleases:
                continue
            assets = [
                {
                    "name": a["name"],
                    "size_bytes": a["size"],
                    "download_url": a["browser_download_url"],
                    "digest_sha256": (a.get("digest") or "").removeprefix("sha256:"),
                }
                for a in rel.get("assets", [])
                if any(fnmatch.fnmatch(a["name"], p) for p in src.asset_patterns)
            ]
            if not assets:
                continue
            out.append(
                {
                    "version_id": rel["tag_name"],
                    "name": rel.get("name") or rel["tag_name"],
                    "prerelease": rel.get("prerelease", False),
                    "published_at": rel.get("published_at"),
                    "body": (rel.get("body") or "")[:2000],
                    "assets": assets,
                }
            )
        return out

    def download_url(
        self,
        url: str,
        dest: Path,
        progress: ProgressCb,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        self._stream_download(url, dest, progress, cancelled)
        return dest

    # ------------------------------------------------------------------
    def _stream_download(
        self,
        url: str,
        dest: Path,
        progress: ProgressCb,
        cancelled: Callable[[], bool],
    ) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with self._client(timeout=None) as c, c.stream("GET", url) as r:
            if r.status_code in (401, 403):
                raise GitHubError(f"Download rejected ({r.status_code}) — check GitHub token")
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0) or None
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1 << 20):
                    if cancelled():
                        f.close()
                        tmp.unlink(missing_ok=True)
                        raise GitHubError("cancelled")
                    f.write(chunk)
                    done += len(chunk)
                    progress(done, total)
        tmp.rename(dest)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def iter_hash_read(path: Path, chunk: int = 1 << 20) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while data := f.read(chunk):
            yield data
