"""Versioned artifact cache.

Layout on disk:

    <data_dir>/cache/
        images/<version_id>/
            meta.json
            os-rpi-....img.xz
        firmware/<version_id>/
            meta.json
            <variant>.bin ...

`version_id` is a filesystem-safe identifier (release tag, or e.g.
"pr-285-6d00c59" for CI artifacts).  meta.json stores provenance: source repo,
commit sha, download URL, sizes, sha256 digests, and for images the resolved
"matching pair" (pinned imswitch / firmware-server container refs).
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Category = Literal["images", "firmware"]


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "unknown"


@dataclass
class CachedVersion:
    category: Category
    version_id: str
    path: Path
    meta: dict[str, Any]
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "version_id": self.version_id,
            "size_bytes": self.size_bytes,
            "files": sorted(
                p.name for p in self.path.iterdir() if p.name != "meta.json"
            )
            if self.path.exists()
            else [],
            **self.meta,
        }


class ArtifactCache:
    def __init__(self, cache_dir: Path) -> None:
        self.root = cache_dir
        for cat in ("images", "firmware"):
            (self.root / cat).mkdir(parents=True, exist_ok=True)

    # -- paths -----------------------------------------------------------
    def version_dir(self, category: Category, version_id: str) -> Path:
        return self.root / category / safe_id(version_id)

    # -- queries ---------------------------------------------------------
    def list_versions(self, category: Category) -> list[CachedVersion]:
        out: list[CachedVersion] = []
        base = self.root / category
        for d in sorted(base.iterdir()) if base.exists() else []:
            if not d.is_dir():
                continue
            meta_file = d / "meta.json"
            meta: dict[str, Any] = {}
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                except (OSError, json.JSONDecodeError):
                    meta = {"corrupt_meta": True}
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            out.append(
                CachedVersion(
                    category=category,
                    version_id=d.name,
                    path=d,
                    meta=meta,
                    size_bytes=size,
                )
            )
        # Newest first by download time, then name.
        out.sort(key=lambda v: (v.meta.get("downloaded_at") or 0, v.version_id), reverse=True)
        return out

    def get(self, category: Category, version_id: str) -> CachedVersion | None:
        d = self.version_dir(category, version_id)
        if not d.is_dir():
            return None
        for v in self.list_versions(category):
            if v.version_id == safe_id(version_id):
                return v
        return None

    def is_complete(self, category: Category, version_id: str) -> bool:
        v = self.get(category, version_id)
        return bool(v and v.meta.get("complete"))

    # -- mutation --------------------------------------------------------
    def begin(self, category: Category, version_id: str, meta: dict[str, Any]) -> Path:
        d = self.version_dir(category, version_id)
        d.mkdir(parents=True, exist_ok=True)
        meta = {**meta, "complete": False, "downloaded_at": time.time()}
        (d / "meta.json").write_text(json.dumps(meta, indent=2))
        return d

    def finalize(self, category: Category, version_id: str, extra: dict[str, Any] | None = None) -> None:
        d = self.version_dir(category, version_id)
        meta_file = d / "meta.json"
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        meta.update(extra or {})
        meta["complete"] = True
        meta_file.write_text(json.dumps(meta, indent=2))

    def delete(self, category: Category, version_id: str) -> bool:
        d = self.version_dir(category, version_id)
        if d.is_dir():
            shutil.rmtree(d)
            return True
        return False

    def prune(self, category: Category, keep: int, protect: set[str] | None = None) -> list[str]:
        """Delete oldest complete versions beyond `keep`. Returns deleted ids."""
        protect = protect or set()
        versions = [v for v in self.list_versions(category) if v.meta.get("complete")]
        deleted: list[str] = []
        for v in versions[keep:]:
            if v.version_id in protect:
                continue
            self.delete(category, v.version_id)
            deleted.append(v.version_id)
        return deleted

    # -- disk usage ------------------------------------------------------
    def disk_stats(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.root)
        cache_size = sum(
            f.stat().st_size for f in self.root.rglob("*") if f.is_file()
        )
        return {
            "disk_total_bytes": usage.total,
            "disk_free_bytes": usage.free,
            "cache_bytes": cache_size,
        }
