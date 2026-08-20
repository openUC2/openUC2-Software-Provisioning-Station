"""ImSwitch setup preloading via boot-partition init-root archives.

os-rpi ships a first-boot mechanism: any `/boot/firmware/init-root-*.tar.gz`
is extracted onto `/` (preserving ownership) and then deleted, see
`deployments/provisioning/boot-init-root.pkg`.  That is how we preload a
microscope configuration onto a freshly flashed card without booting it.

The archive we build mirrors the known-good example:

    home/pi/ImSwitchConfig/config/imcontrol_options.json
    home/pi/ImSwitchConfig/imcontrol_setups/<setup>.json

owned by uid/gid 1000 (the `pi` user), because the extractor runs as root
and restores the ownership recorded in the archive.

Setup files come from openUC2/ImSwitchConfig (branch `master`,
`imcontrol_setups/`).  That directory holds ~54 files, most of them
historical, so the station shows a curated subset by default — editable in
Settings — with a "show all" escape hatch.
"""

from __future__ import annotations

import io
import json
import tarfile
import time
from pathlib import Path
from typing import Any

import httpx

REPO_OWNER = "openUC2"
REPO_NAME = "ImSwitchConfig"
REPO_BRANCH = "master"
SETUPS_DIR = "imcontrol_setups"

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"

# Where the config lands on the microscope.
PI_UID = 1000
PI_GID = 1000
PI_CONFIG_ROOT = "home/pi/ImSwitchConfig"
PI_ABS_CONFIG_ROOT = "/home/pi/ImSwitchConfig"

# The archive must match the extractor's glob: init-root-*.tar.gz
ARCHIVE_NAME = "init-root-imswitch-config.tar.gz"


class ConfigError(RuntimeError):
    pass


def build_options(setup_filename: str) -> dict[str, Any]:
    """The `config/imcontrol_options.json` that selects a setup.

    `setupFileName` is written as the absolute on-device path — the copy
    committed upstream points at a developer's laptop
    (`/Users/bene/...`), which is meaningless on a Pi.
    """
    return {
        "setupFileName": f"{PI_ABS_CONFIG_ROOT}/{SETUPS_DIR}/{setup_filename}",
        "recording": {
            "outputFolder": f"{PI_ABS_CONFIG_ROOT}/recordings",
            "includeDateInOutputFolder": True,
        },
        "watcher": {
            "outputFolder": f"{PI_ABS_CONFIG_ROOT}/scripts",
        },
    }


class ImSwitchConfigStore:
    """Local mirror of the selectable ImSwitch setups.

    Setup files are a few kB each, so unlike images and firmware they are
    mirrored wholesale rather than version-pruned; the station keeps working
    offline once synced.
    """

    def __init__(self, root: Path, token_provider=lambda: "") -> None:
        self.root = root
        self.setups_dir = root / "setups"
        self.index_file = root / "index.json"
        self.setups_dir.mkdir(parents=True, exist_ok=True)
        self._token = token_provider

    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "uc2-provision-station",
        }
        token = self._token()
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def sync(self) -> dict[str, Any]:
        """Fetch the setup list and download every setup file."""
        with httpx.Client(headers=self._headers(), timeout=60, follow_redirects=True) as c:
            r = c.get(
                f"{API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{SETUPS_DIR}",
                params={"ref": REPO_BRANCH},
            )
            if r.status_code == 403 and "rate limit" in r.text.lower():
                raise ConfigError(
                    "GitHub rate limit hit — add a token in Settings to sync configs."
                )
            if r.status_code != 200:
                raise ConfigError(
                    f"Could not list {SETUPS_DIR} ({r.status_code}) — check network access."
                )
            entries = [
                e
                for e in r.json()
                if e.get("type") == "file" and e.get("name", "").endswith(".json")
            ]
            if not entries:
                raise ConfigError(f"No setup files found in {SETUPS_DIR}")

            downloaded: list[dict[str, Any]] = []
            for entry in entries:
                name = entry["name"]
                dest = self.setups_dir / name
                # Skip unchanged files: GitHub's blob sha is stable per content.
                existing = self._index_entry(name)
                if existing and existing.get("sha") == entry.get("sha") and dest.exists():
                    downloaded.append(existing)
                    continue
                raw = c.get(f"{RAW}/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}/{SETUPS_DIR}/{name}")
                if raw.status_code != 200:
                    continue
                dest.write_bytes(raw.content)
                downloaded.append(
                    {
                        "name": name,
                        "sha": entry.get("sha"),
                        "size": entry.get("size"),
                        "summary": _summarize(raw.content),
                    }
                )

        index = {
            "synced_at": time.time(),
            "source": f"{REPO_OWNER}/{REPO_NAME}@{REPO_BRANCH}",
            "setups": sorted(downloaded, key=lambda s: s["name"].lower()),
        }
        self.index_file.write_text(json.dumps(index, indent=2))
        return index

    def _index_entry(self, name: str) -> dict[str, Any] | None:
        for s in self.index().get("setups", []):
            if s["name"] == name:
                return s
        return None

    def index(self) -> dict[str, Any]:
        if not self.index_file.exists():
            return {"setups": [], "synced_at": None}
        try:
            return json.loads(self.index_file.read_text())
        except (OSError, json.JSONDecodeError):
            return {"setups": [], "synced_at": None}

    def list_setups(self, allowlist: list[str] | None, show_all: bool) -> list[dict[str, Any]]:
        setups = self.index().get("setups", [])
        for s in setups:
            s["available"] = (self.setups_dir / s["name"]).exists()
            s["curated"] = not allowlist or s["name"] in allowlist
        if show_all or not allowlist:
            return setups
        return [s for s in setups if s["curated"]]

    def read_setup(self, name: str) -> bytes:
        path = self.setups_dir / Path(name).name  # never escape the mirror
        if not path.exists():
            raise ConfigError(f"Setup {name} is not synced — run a config sync first.")
        return path.read_bytes()

    # ------------------------------------------------------------------
    def build_archive(self, setup_name: str) -> bytes:
        """Build the init-root tar.gz that preloads `setup_name`."""
        setup_name = Path(setup_name).name
        setup_bytes = self.read_setup(setup_name)
        try:
            json.loads(setup_bytes)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{setup_name} is not valid JSON: {exc}") from exc

        options = json.dumps(build_options(setup_name), indent=4).encode() + b"\n"

        buf = io.BytesIO()
        now = int(time.time())

        def _dir(tf: tarfile.TarFile, name: str) -> None:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = info.gid = PI_UID
            info.uname = info.gname = "pi"
            info.mtime = now
            tf.addfile(info)

        def _file(tf: tarfile.TarFile, name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = PI_UID
            info.uname = info.gname = "pi"
            info.mtime = now
            tf.addfile(info, io.BytesIO(data))

        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            # Parent directories are listed explicitly so ownership is applied
            # to them too, matching the reference archive.
            for d in (
                "home",
                "home/pi",
                PI_CONFIG_ROOT,
                f"{PI_CONFIG_ROOT}/config",
                f"{PI_CONFIG_ROOT}/{SETUPS_DIR}",
            ):
                _dir(tf, d)
            _file(tf, f"{PI_CONFIG_ROOT}/config/imcontrol_options.json", options)
            _file(tf, f"{PI_CONFIG_ROOT}/{SETUPS_DIR}/{setup_name}", setup_bytes)

        return buf.getvalue()


def _summarize(raw: bytes) -> dict[str, Any]:
    """Pull a few human-meaningful facts out of a setup file for the UI."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}

    def names(key: str) -> list[str]:
        section = data.get(key)
        return list(section.keys()) if isinstance(section, dict) else []

    detectors = names("detectors")
    managers = []
    for det in (data.get("detectors") or {}).values():
        if isinstance(det, dict) and det.get("managerName"):
            managers.append(det["managerName"])
    return {
        "detectors": detectors,
        "cameras": sorted(set(managers)),
        "lasers": names("lasers"),
        "positioners": names("positioners"),
        "led_matrix": bool(data.get("LEDMatrixs")),
    }
