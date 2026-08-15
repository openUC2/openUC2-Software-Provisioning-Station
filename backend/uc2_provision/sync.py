"""Download orchestration: GitHub / GHCR ⇄ local cache.

**SD card images** come from openUC2/os-rpi Actions artifacts.

**Firmware bundles** come from one of three sources:

`container`
    The `firmware-image-server` image pinned in the os-rpi deployment at the
    image's commit.  This container *is* the firmware that belongs to that SD
    image — pulling it is how we guarantee a matching pair rather than
    guessing from release names.  This is the preferred source.

`release`
    A youseetoo/uc2-esp32 GitHub release.  Used when flashing boards without
    a specific SD image in hand.

`odmr`
    The ODMR quantum-sensing boards, whose full 4 MB images are published in
    youseetoo.github.io rather than in the uc2-esp32 release.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .boards import resolve_variants
from .cache import ArtifactCache, safe_id
from .config import Settings
from .github import GitHubClient, GitHubError, sha256_file
from .jobs import Job, JobManager
from .oci import OCIClient, OCIError, parse_ref

ODMR_BASE = (
    "https://raw.githubusercontent.com/youseetoo/youseetoo.github.io"
    "/main/static/firmware_build"
)
ODMR_BOARDS = ["odmr-xiao-esp32s3", "odmr-xiao-esp32c3"]


def container_version_id(tag: str) -> str:
    return safe_id(f"fws-{tag}")


def release_version_id(tag: str) -> str:
    return safe_id(f"rel-{tag}")


class SyncService:
    def __init__(self, settings: Settings, cache: ArtifactCache, jobs: JobManager) -> None:
        self.settings = settings
        self.cache = cache
        self.jobs = jobs
        self.github = GitHubClient(settings)
        self.last_check: dict[str, Any] = {}

    @property
    def oci(self) -> OCIClient:
        # Token may change at runtime via Settings; build per use.
        return OCIClient(self.settings.github_token)

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    def list_images(self, remote: bool = True) -> dict[str, Any]:
        cached = {v.version_id: v.to_dict() for v in self.cache.list_versions("images")}
        available: list[dict[str, Any]] = []
        error = None
        if remote:
            try:
                available = self.github.list_image_artifacts()
            except Exception as exc:  # noqa: BLE001 - degrade to cache-only
                error = str(exc)
        for a in available:
            vid = safe_id(a["version_id"])
            a["cached"] = bool(cached.get(vid, {}).get("complete"))
        for entry in cached.values():
            entry["matched_firmware"] = self.matched_firmware_for(entry)
        return {"available": available, "cached": list(cached.values()), "error": error}

    def matched_firmware_for(self, image_meta: dict[str, Any]) -> dict[str, Any] | None:
        """Which firmware bundle belongs to this cached image."""
        pair = image_meta.get("pair") or {}
        fws = pair.get("firmware_server")
        if not fws:
            return None
        vid = container_version_id(fws["tag"])
        cached = self.cache.get("firmware", vid)
        return {
            "version_id": vid,
            "container_ref": fws["image"],  # already "registry/repo:tag"
            "tag": fws["tag"],
            "cached": bool(cached and cached.meta.get("complete")),
            "imswitch_tag": (pair.get("imswitch") or {}).get("tag"),
        }

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
            job.log_line(
                f"Downloading artifact {artifact['name']} "
                f"({(artifact.get('size_bytes') or 0) / 1e9:.2f} GB) ..."
            )

            def progress(done: int, total: int | None) -> None:
                if total:
                    job.set_progress(
                        0.02 + 0.85 * done / total, f"Downloading — {done / 1e9:.2f} GB"
                    )

            files = self.github.download_artifact(
                artifact["artifact_id"], dest, progress,
                cancelled=lambda: job.cancel_requested,
                fallback_name=artifact.get("name"),
            )
            job.set_progress(0.88, "Verifying checksum")
            extra: dict[str, Any] = {"files_sha256": {}}
            for f in files:
                digest = sha256_file(f)
                extra["files_sha256"][f.name] = digest
                job.log_line(f"sha256 {f.name} = {digest}")

            job.set_progress(0.93, "Resolving matching software versions")
            if artifact.get("head_sha"):
                pair = self.github.resolve_pair(artifact["head_sha"])
                if pair:
                    extra["pair"] = pair
                    for k, p in pair.items():
                        job.log_line(f"pinned {k}: {p['image']}:{p['tag']}")
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

    def resolve_pair_for_version(self, version_id: str) -> dict[str, Any]:
        """Which ImSwitch build and firmware bundle an image pins.

        Works for cached images (from stored metadata) and for images still
        on GitHub (resolved live from the commit), so the library can show
        the pairing before committing to a multi-GB download.
        """
        cached = self.cache.get("images", version_id)
        if cached and cached.meta.get("pair"):
            return {
                "version_id": version_id,
                "pair": cached.meta["pair"],
                "matched_firmware": self.matched_firmware_for(cached.meta),
                "cached": True,
            }
        head_sha = (cached.meta.get("head_sha") if cached else None)
        if not head_sha:
            for a in self.github.list_image_artifacts():
                if safe_id(a["version_id"]) == safe_id(version_id):
                    head_sha = a.get("head_sha")
                    break
        if not head_sha:
            raise GitHubError(f"Cannot determine the commit behind {version_id}")
        pair = self.github.resolve_pair(head_sha)
        meta = {"pair": pair}
        return {
            "version_id": version_id,
            "pair": pair,
            "matched_firmware": self.matched_firmware_for(meta),
            "cached": bool(cached),
        }

    # ------------------------------------------------------------------
    # Firmware bundles
    # ------------------------------------------------------------------
    def list_firmware(self, remote: bool = True) -> dict[str, Any]:
        cached = [v.to_dict() for v in self.cache.list_versions("firmware")]
        available: list[dict[str, Any]] = []
        error = None

        # Container bundles worth offering = those pinned by cached images.
        cached_ids = {c["version_id"] for c in cached}
        for img in self.cache.list_versions("images"):
            match = self.matched_firmware_for(img.meta)
            if not match:
                continue
            if any(a["version_id"] == match["version_id"] for a in available):
                continue
            available.append(
                {
                    "version_id": match["version_id"],
                    "name": match["tag"],
                    "source_kind": "container",
                    "container_ref": match["container_ref"],
                    "tag": match["tag"],
                    "cached": match["version_id"] in cached_ids,
                    "matches_image": img.version_id,
                }
            )

        if remote:
            try:
                for rel in self.github.list_firmware_releases():
                    vid = release_version_id(rel["version_id"])
                    available.append(
                        {
                            "version_id": vid,
                            "name": rel["version_id"],
                            "source_kind": "release",
                            "tag": rel["version_id"],
                            "prerelease": rel.get("prerelease"),
                            "published_at": rel.get("published_at"),
                            "asset_count": len(rel.get("assets", [])),
                            "cached": vid in cached_ids,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                error = str(exc)

        available.append(
            {
                "version_id": "odmr-latest",
                "name": "ODMR boards (latest)",
                "source_kind": "odmr",
                "tag": "latest",
                "cached": "odmr-latest" in cached_ids,
            }
        )
        return {"available": available, "cached": cached, "error": error}

    def firmware_variants(self, version_id: str) -> list[dict[str, Any]]:
        v = self.cache.get("firmware", version_id)
        if not v or not v.meta.get("complete"):
            return []
        files = [f.name for f in v.path.iterdir() if f.is_file() and f.name != "meta.json"]
        return resolve_variants(files)

    # -- container bundle -------------------------------------------------
    def download_container_firmware(self, ref_str: str) -> Job:
        ref = parse_ref(ref_str)
        vid = container_version_id(ref.tag)

        def work(job: Job) -> None:
            job.set_progress(0.0, "Contacting registry")
            job.log_line(f"Pulling firmware bundle from {ref} ...")
            dest = self.cache.begin(
                "firmware", vid,
                {
                    "kind": "esp32-firmware",
                    "source_kind": "container",
                    "container_ref": str(ref),
                    "tag": ref.tag,
                },
            )
            files = self.oci.extract_files(
                ref,
                dest,
                want=lambda name: name.endswith(".bin"),
                progress=lambda frac, msg: job.set_progress(0.05 + 0.8 * frac, msg),
                cancelled=lambda: job.cancel_requested,
            )
            if not files:
                raise RuntimeError(f"No firmware binaries found inside {ref}")
            job.set_progress(0.9, "Hashing binaries")
            digests = {f.name: sha256_file(f) for f in files}
            variants = resolve_variants(list(digests))
            self.cache.finalize(
                "firmware", vid,
                {"files_sha256": digests, "variant_count": len(variants)},
            )
            job.log_line(
                f"Extracted {len(files)} binaries → {len(variants)} flashable boards."
            )
            self._prune(job)

        return self.jobs.submit(
            "download-firmware", f"Pull firmware bundle {ref.tag}", work,
            meta={"version_id": vid}, exclusive="download-firmware",
        )

    def download_firmware_for_image(self, image_version_id: str) -> Job:
        img = self.cache.get("images", image_version_id)
        if not img:
            raise GitHubError(f"Image {image_version_id} is not cached")
        match = self.matched_firmware_for(img.meta)
        if not match:
            raise GitHubError(
                f"No firmware-server pin found for {image_version_id} — "
                "the image metadata has no matching pair"
            )
        return self.download_container_firmware(match["container_ref"])

    # -- release bundle ---------------------------------------------------
    def download_release_firmware(self, tag: str) -> Job:
        releases = self.github.list_firmware_releases(limit=20)
        release = next(
            (r for r in releases if safe_id(r["version_id"]) == safe_id(tag)), None
        )
        if release is None:
            raise GitHubError(f"Firmware release {tag} not found")
        vid = release_version_id(release["version_id"])

        def work(job: Job) -> None:
            assets = {a["name"]: a for a in release["assets"]}
            dest = self.cache.begin(
                "firmware", vid,
                {
                    "kind": "esp32-firmware",
                    "source_kind": "release",
                    "source": self.settings.firmware_source.slug,
                    "tag": release["version_id"],
                    "prerelease": release.get("prerelease"),
                    "published_at": release.get("published_at"),
                },
            )
            # Only flashable-at-zero images are useful to us; the catalog
            # decides which of the available names those are.
            wanted = [
                a for name, a in assets.items()
                if name.endswith(".bin")
                and (not name.startswith("esp32_") or name.endswith("_merged.bin"))
            ]
            job.log_line(f"Downloading {len(wanted)} firmware binaries ...")
            digests: dict[str, str] = {}
            for i, a in enumerate(wanted):
                job.check_cancelled()
                job.set_progress(
                    0.05 + 0.9 * i / max(len(wanted), 1),
                    f"{a['name']} ({i + 1}/{len(wanted)})",
                )
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
            job.log_line(f"Firmware {release['version_id']} cached.")
            self._prune(job)

        return self.jobs.submit(
            "download-firmware", f"Download firmware {release['version_id']}", work,
            meta={"version_id": vid}, exclusive="download-firmware",
        )

    # -- ODMR bundle ------------------------------------------------------
    def download_odmr_firmware(self) -> Job:
        vid = "odmr-latest"

        def work(job: Job) -> None:
            dest = self.cache.begin(
                "firmware", vid,
                {"kind": "esp32-firmware", "source_kind": "odmr",
                 "source": "youseetoo/youseetoo.github.io", "tag": "latest"},
            )
            digests: dict[str, str] = {}
            versions: dict[str, str] = {}
            for i, board in enumerate(ODMR_BOARDS):
                job.check_cancelled()
                job.set_progress(0.05 + 0.9 * i / len(ODMR_BOARDS), f"{board}.bin")
                job.log_line(f"Downloading {board}.bin (4 MB full image) ...")
                path = self.github.download_url(
                    f"{ODMR_BASE}/{board}.bin", dest / f"{board}.bin",
                    lambda d, t: None, cancelled=lambda: job.cancel_requested,
                )
                digests[path.name] = sha256_file(path)
                try:
                    mpath = self.github.download_url(
                        f"{ODMR_BASE}/{board}-manifest.json",
                        dest / f"{board}-manifest.json",
                        lambda d, t: None, cancelled=lambda: job.cancel_requested,
                    )
                    versions[board] = json.loads(mpath.read_text()).get("version", "")
                except Exception:  # noqa: BLE001 - manifest is informational
                    pass
            self.cache.finalize(
                "firmware", vid, {"files_sha256": digests, "board_versions": versions}
            )
            job.log_line(f"ODMR firmware cached: {', '.join(versions.values()) or 'ok'}")

        return self.jobs.submit(
            "download-firmware", "Download ODMR firmware", work,
            meta={"version_id": vid}, exclusive="download-firmware",
        )

    def download_firmware(self, version_id: str) -> Job:
        """Dispatch by version id prefix, so the UI has one download call."""
        if version_id == "odmr-latest":
            return self.download_odmr_firmware()
        if version_id.startswith("fws-"):
            tag = version_id.removeprefix("fws-")
            # Recover the full ref from whichever image pinned it.
            for img in self.cache.list_versions("images"):
                match = self.matched_firmware_for(img.meta)
                if match and match["version_id"] == version_id:
                    return self.download_container_firmware(match["container_ref"])
            return self.download_container_firmware(
                f"ghcr.io/youseetoo/firmware-image-server:{tag}"
            )
        return self.download_release_firmware(version_id.removeprefix("rel-"))

    # ------------------------------------------------------------------
    def check_updates(self, auto_download: bool = False) -> dict[str, Any]:
        """Compare newest remote versions against the cache; optionally start
        downloads.  Called manually and by the periodic background task."""
        result: dict[str, Any] = {"images": None, "firmware": None, "started_jobs": []}
        images = self.list_images()
        stable = [a for a in images["available"] if a["channel"] == "stable"]
        newest_image = (stable or images["available"] or [None])[0]
        result["images"] = {
            "newest": newest_image,
            "error": images["error"],
            "up_to_date": bool(newest_image and newest_image.get("cached")),
        }

        if auto_download and newest_image and not newest_image.get("cached"):
            try:
                job = self.download_image(newest_image)
                result["started_jobs"].append(job.id)
            except Exception:  # noqa: BLE001
                pass

        # Firmware follows the image: pull the bundle each cached image pins.
        firmware = self.list_firmware(remote=False)
        missing = [
            f for f in firmware["available"]
            if f["source_kind"] == "container" and not f["cached"]
        ]
        result["firmware"] = {
            "matched_bundles": len(firmware["available"]),
            "missing": [f["version_id"] for f in missing],
            "up_to_date": not missing,
        }
        if auto_download:
            for f in missing:
                try:
                    job = self.download_container_firmware(f["container_ref"])
                    result["started_jobs"].append(job.id)
                    break  # one at a time; the next check picks up the rest
                except Exception:  # noqa: BLE001
                    pass
        self.last_check = result
        return result

    def _prune(self, job: Job) -> None:
        keep = self.settings.keep_versions
        if keep <= 0:
            return
        # Never prune a firmware bundle that a kept image still points at.
        protected = set()
        for img in self.cache.list_versions("images")[:keep]:
            match = self.matched_firmware_for(img.meta)
            if match:
                protected.add(match["version_id"])
        for cat, prot in (("images", set()), ("firmware", protected)):
            for vid in self.cache.prune(cat, keep, protect=prot):  # type: ignore[arg-type]
                job.log_line(f"Pruned old {cat} version: {vid}")
