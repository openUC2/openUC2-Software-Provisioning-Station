"""Download orchestration: GitHub ⇄ local cache.

Images: one Actions artifact (a zip containing the .img.xz) per version.
Firmware: per release we fetch `firmware-index.json` (the machine-readable
board catalog the uc2-esp32 release pipeline publishes) plus every listed
merged binary, and additionally the per-axis CAN motor builds
(esp32_UC2_canopen_slave_motor_release_mot{X,Y,Z,A}_merged.bin) which are
not in the index but are needed to provision motor X/Y/Z/A boards.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .cache import ArtifactCache, safe_id
from .config import Settings
from .github import GitHubClient, GitHubError, sha256_file
from .jobs import Job, JobManager

AXIS_BIN_RE = re.compile(
    r"esp32_UC2_canopen_slave_motor_release_mot(?P<axis>[XYZA])_merged\.bin"
)


class SyncService:
    def __init__(self, settings: Settings, cache: ArtifactCache, jobs: JobManager) -> None:
        self.settings = settings
        self.cache = cache
        self.jobs = jobs
        self.github = GitHubClient(settings)
        self.last_check: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Listings (remote + cached merged view)
    # ------------------------------------------------------------------
    def list_images(self, remote: bool = True) -> dict[str, Any]:
        cached = {v.version_id: v.to_dict() for v in self.cache.list_versions("images")}
        available: list[dict[str, Any]] = []
        error = None
        if remote:
            try:
                available = self.github.list_image_artifacts()
            except (GitHubError, Exception) as exc:  # noqa: BLE001 - degrade to cache-only
                error = str(exc)
        for a in available:
            vid = safe_id(a["version_id"])
            a["cached"] = bool(cached.get(vid, {}).get("complete"))
        return {"available": available, "cached": list(cached.values()), "error": error}

    def list_firmware(self, remote: bool = True) -> dict[str, Any]:
        cached = {v.version_id: v.to_dict() for v in self.cache.list_versions("firmware")}
        available: list[dict[str, Any]] = []
        error = None
        if remote:
            try:
                available = self.github.list_firmware_releases()
            except (GitHubError, Exception) as exc:  # noqa: BLE001
                error = str(exc)
        for r in available:
            vid = safe_id(r["version_id"])
            r["cached"] = bool(cached.get(vid, {}).get("complete"))
            # Don't ship the heavy asset list to the UI.
            r["asset_count"] = len(r.get("assets", []))
        return {"available": available, "cached": list(cached.values()), "error": error}

    # ------------------------------------------------------------------
    # Firmware variant catalog from a cached release
    # ------------------------------------------------------------------
    def firmware_variants(self, version_id: str) -> list[dict[str, Any]]:
        v = self.cache.get("firmware", version_id)
        if not v or not v.meta.get("complete"):
            return []
        variants: list[dict[str, Any]] = []
        index_file = v.path / "firmware-index.json"
        if index_file.exists():
            try:
                index = json.loads(index_file.read_text())
            except (OSError, json.JSONDecodeError):
                index = {}
            for fw in index.get("firmware", []):
                binary = fw.get("binary") or f"{fw.get('id')}.bin"
                if not (v.path / binary).exists():
                    continue
                variants.append(
                    {
                        "id": fw.get("id"),
                        "name": fw.get("name") or fw.get("id"),
                        "chip_family": fw.get("chipFamily"),
                        "file": binary,
                        "category": _category(fw.get("id") or ""),
                    }
                )
        # Per-axis CAN motor builds (not part of firmware-index.json).
        for f in sorted(v.path.iterdir()):
            m = AXIS_BIN_RE.fullmatch(f.name)
            if m:
                axis = m.group("axis")
                variants.append(
                    {
                        "id": f"uc2-can-slave-motor-{axis.lower()}",
                        "name": f"CAN Slave Motor {axis}",
                        "chip_family": "ESP32-S3",
                        "file": f.name,
                        "category": "can-slave",
                    }
                )
        return variants

    # ------------------------------------------------------------------
    # Downloads (as jobs)
    # ------------------------------------------------------------------
    def download_image(self, artifact: dict[str, Any]) -> Job:
        vid = safe_id(artifact["version_id"])

        def work(job: Job) -> None:
            job.set_progress(0.0, "Preparing")
            meta = {
                "source": self.settings.image_source.slug,
                "kind": "sdcard-image",
                "artifact_id": artifact.get("artifact_id"),
                "head_sha": artifact.get("head_sha"),
                "head_branch": artifact.get("head_branch"),
                "channel": artifact.get("channel"),
                "reported_digest": artifact.get("digest_sha256"),
                "created_at_remote": artifact.get("created_at"),
            }
            dest = self.cache.begin("images", vid, meta)
            job.log_line(f"Downloading artifact {artifact['name']} "
                         f"({(artifact.get('size_bytes') or 0) / 1e9:.2f} GB) ...")

            def progress(done: int, total: int | None) -> None:
                if total:
                    job.set_progress(0.02 + 0.85 * done / total,
                                     f"Downloading — {done / 1e9:.2f} GB")

            files = self.github.download_artifact(
                artifact["artifact_id"], dest, progress,
                cancelled=lambda: job.cancel_requested,
            )
            job.set_progress(0.88, "Verifying checksum")
            extra: dict[str, Any] = {"files_sha256": {}}
            for f in files:
                digest = sha256_file(f)
                extra["files_sha256"][f.name] = digest
                job.log_line(f"sha256 {f.name} = {digest}")
                reported = artifact.get("digest_sha256")
                if reported and reported not in (digest,):
                    # GitHub's artifact digest is computed over the artifact
                    # archive, which may differ from the single file hash —
                    # record both, warn, don't fail.
                    job.log_line(f"note: reported artifact digest {reported} "
                                 f"differs from file hash (archive vs file)")
            job.set_progress(0.93, "Resolving software pair")
            if artifact.get("head_sha"):
                pair = self.github.resolve_pair(artifact["head_sha"])
                if pair:
                    extra["pair"] = pair
                    for k, p in pair.items():
                        job.log_line(f"pinned {k}: {p['image']}")
            self.cache.finalize("images", vid, extra)
            job.log_line("Image cached.")
            self._prune(job)

        return self.jobs.submit(
            "download-image", f"Download {artifact['name']}", work,
            meta={"version_id": vid}, exclusive="download-image",
        )

    def download_image_by_version(self, version_id: str) -> Job:
        for a in self.github.list_image_artifacts():
            if safe_id(a["version_id"]) == safe_id(version_id):
                return self.download_image(a)
        raise GitHubError(f"No downloadable artifact found for {version_id}")

    def download_firmware(self, version_id: str) -> Job:
        releases = self.github.list_firmware_releases(limit=20)
        release = next(
            (r for r in releases if safe_id(r["version_id"]) == safe_id(version_id)), None
        )
        if release is None:
            raise GitHubError(f"Firmware release {version_id} not found")
        vid = safe_id(release["version_id"])

        def work(job: Job) -> None:
            assets = {a["name"]: a for a in release["assets"]}
            index_asset = assets.get("firmware-index.json")
            wanted: list[dict[str, Any]] = []
            if index_asset:
                wanted.append(index_asset)
            dest = self.cache.begin("firmware", vid, {
                "source": self.settings.firmware_source.slug,
                "kind": "esp32-firmware",
                "tag": release["version_id"],
                "prerelease": release.get("prerelease"),
                "published_at": release.get("published_at"),
            })

            # Download index first to know which binaries the release declares.
            declared: set[str] = set()
            if index_asset:
                job.set_progress(0.02, "Fetching firmware index")
                self.github.download_url(
                    index_asset["download_url"], dest / "firmware-index.json",
                    lambda d, t: None, cancelled=lambda: job.cancel_requested,
                )
                try:
                    index = json.loads((dest / "firmware-index.json").read_text())
                    for fw in index.get("firmware", []):
                        declared.add(fw.get("binary") or f"{fw.get('id')}.bin")
                except (OSError, json.JSONDecodeError):
                    pass

            for name, a in assets.items():
                if name in declared or AXIS_BIN_RE.fullmatch(name):
                    wanted.append(a)
            bins = [a for a in wanted if a["name"].endswith(".bin")]
            if not bins:
                # Release without an index: fall back to all merged bins.
                bins = [a for a in assets.values() if a["name"].endswith("_merged.bin")]
                wanted += bins
            job.log_line(f"Downloading {len(bins)} firmware binaries ...")
            digests: dict[str, str] = {}
            for i, a in enumerate(bins):
                job.check_cancelled()
                job.set_progress(0.05 + 0.9 * i / max(len(bins), 1),
                                 f"{a['name']} ({i + 1}/{len(bins)})")
                path = self.github.download_url(
                    a["download_url"], dest / a["name"], lambda d, t: None,
                    cancelled=lambda: job.cancel_requested,
                )
                digest = sha256_file(path)
                digests[a["name"]] = digest
                reported = a.get("digest_sha256")
                if reported and reported != digest:
                    raise RuntimeError(
                        f"Checksum mismatch for {a['name']}: {digest} != {reported}"
                    )
            self.cache.finalize("firmware", vid, {"files_sha256": digests})
            job.log_line(f"Firmware {release['version_id']} cached "
                         f"({len(bins)} binaries).")
            self._prune(job)

        return self.jobs.submit(
            "download-firmware", f"Download firmware {release['version_id']}", work,
            meta={"version_id": vid}, exclusive="download-firmware",
        )

    # ------------------------------------------------------------------
    def check_updates(self, auto_download: bool = False) -> dict[str, Any]:
        """Compare newest remote versions against the cache; optionally kick
        off downloads for anything new. Called manually and by the periodic
        background task."""
        result: dict[str, Any] = {"images": None, "firmware": None, "started_jobs": []}
        images = self.list_images()
        firmware = self.list_firmware()
        stable_images = [a for a in images["available"] if a["channel"] == "stable"]
        newest_image = (stable_images or images["available"] or [None])[0]
        newest_fw = (firmware["available"] or [None])[0]
        result["images"] = {
            "newest": newest_image,
            "error": images["error"],
            "up_to_date": bool(newest_image and newest_image.get("cached")),
        }
        result["firmware"] = {
            "newest": newest_fw,
            "error": firmware["error"],
            "up_to_date": bool(newest_fw and newest_fw.get("cached")),
        }
        if auto_download:
            if newest_image and not newest_image.get("cached"):
                try:
                    job = self.download_image(newest_image)
                    result["started_jobs"].append(job.id)
                except (GitHubError, RuntimeError):
                    pass
            if newest_fw and not newest_fw.get("cached"):
                try:
                    job = self.download_firmware(newest_fw["version_id"])
                    result["started_jobs"].append(job.id)
                except (GitHubError, RuntimeError):
                    pass
        self.last_check = result
        return result

    def _prune(self, job: Job) -> None:
        keep = self.settings.keep_versions
        if keep <= 0:
            return
        for cat in ("images", "firmware"):
            deleted = self.cache.prune(cat, keep)  # type: ignore[arg-type]
            for vid in deleted:
                job.log_line(f"Pruned old {cat} version: {vid}")


def _category(board_id: str) -> str:
    if "standalone" in board_id:
        return "standalone"
    if "master" in board_id:
        return "can-master"
    if "slave" in board_id:
        return "can-slave"
    if "bridge" in board_id:
        return "bridge"
    return "other"
