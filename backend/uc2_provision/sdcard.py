"""SD card detection and image writing.

Detection is deliberately conservative: only removable / hotplug / USB / MMC
disks are offered, and any disk holding the running system is filtered out.
Writing streams the .img.xz through an in-process LZMA decompressor straight
onto the block device — no temp file, progress tracked via compressed bytes
consumed (accurate because xz input size is known).

Supports Linux (the actual station) and macOS (development).
"""

from __future__ import annotations

import json
import lzma
import os
import platform
import plistlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jobs import Job

WRITE_CHUNK = 4 << 20  # 4 MiB


@dataclass
class BlockDevice:
    device: str          # /dev/sda, /dev/mmcblk0, /dev/disk4
    size_bytes: int
    model: str
    removable: bool
    transport: str       # usb, mmc, ...
    mountpoints: list[str]
    is_system: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "size_bytes": self.size_bytes,
            "model": self.model,
            "removable": self.removable,
            "transport": self.transport,
            "mountpoints": self.mountpoints,
            "is_system": self.is_system,
            "writable_target": self.removable and not self.is_system,
        }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def list_block_devices() -> list[BlockDevice]:
    if platform.system() == "Darwin":
        return _list_macos()
    return _list_linux()


def _list_linux() -> list[BlockDevice]:
    try:
        raw = subprocess.run(
            ["lsblk", "-J", "-b", "-o",
             "NAME,PATH,SIZE,TYPE,RM,HOTPLUG,MODEL,TRAN,MOUNTPOINTS"],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(raw)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return []

    devices: list[BlockDevice] = []
    for d in data.get("blockdevices", []):
        if d.get("type") != "disk":
            continue
        mounts: list[str] = []

        def collect(node: dict[str, Any]) -> None:
            for mp in node.get("mountpoints") or []:
                if mp:
                    mounts.append(mp)
            for child in node.get("children") or []:
                collect(child)

        collect(d)
        is_system = any(mp in ("/", "/boot", "/boot/firmware") or mp.startswith("/usr")
                        for mp in mounts)
        removable = bool(d.get("rm")) or bool(d.get("hotplug"))
        tran = (d.get("tran") or "").lower()
        # SD readers on USB report tran=usb; Pi's built-in slot exposes mmcblk.
        if tran in ("usb", "mmc"):
            removable = True
        devices.append(
            BlockDevice(
                device=d.get("path") or f"/dev/{d['name']}",
                size_bytes=int(d.get("size") or 0),
                model=(d.get("model") or "").strip(),
                removable=removable,
                transport=tran,
                mountpoints=mounts,
                is_system=is_system,
            )
        )
    return devices


def _list_macos() -> list[BlockDevice]:
    try:
        raw = subprocess.run(
            ["diskutil", "list", "-plist", "external", "physical"],
            capture_output=True, check=True,
        ).stdout
        listing = plistlib.loads(raw)
    except (subprocess.CalledProcessError, FileNotFoundError, plistlib.InvalidFileException):
        return []

    devices: list[BlockDevice] = []
    for name in listing.get("WholeDisks", []):
        try:
            info_raw = subprocess.run(
                ["diskutil", "info", "-plist", name],
                capture_output=True, check=True,
            ).stdout
            info = plistlib.loads(info_raw)
        except (subprocess.CalledProcessError, plistlib.InvalidFileException):
            continue
        mounts = []
        for disk in listing.get("AllDisksAndPartitions", []):
            if disk.get("DeviceIdentifier") == name:
                for part in disk.get("Partitions", []):
                    if part.get("MountPoint"):
                        mounts.append(part["MountPoint"])
        devices.append(
            BlockDevice(
                device=f"/dev/{name}",
                size_bytes=int(info.get("TotalSize") or 0),
                model=(info.get("MediaName") or "").strip(),
                removable=bool(info.get("RemovableMediaOrExternalDevice", True)),
                transport=(info.get("BusProtocol") or "").lower(),
                mountpoints=mounts,
                is_system=False,  # already filtered to external
            )
        )
    return devices


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

class _CountingReader:
    """Wraps a file object, counting bytes read — lets us report progress on
    the compressed stream while LZMAFile consumes it."""

    def __init__(self, path: Path) -> None:
        self._f = open(path, "rb")
        self.bytes_read = 0

    def read(self, n: int = -1) -> bytes:
        data = self._f.read(n)
        self.bytes_read += len(data)
        return data

    def close(self) -> None:
        self._f.close()


def _unmount_all(device: str, job: Job) -> None:
    system = platform.system()
    if system == "Darwin":
        job.log_line(f"Unmounting {device} ...")
        subprocess.run(["diskutil", "unmountDisk", "force", device],
                       capture_output=True, text=True)
        return
    # Linux: unmount every mounted partition of this disk.
    try:
        raw = subprocess.run(
            ["lsblk", "-J", "-o", "PATH,MOUNTPOINTS", device],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return

    def walk(node: dict[str, Any]) -> None:
        for mp in node.get("mountpoints") or []:
            if mp:
                job.log_line(f"Unmounting {node['path']} ({mp}) ...")
                subprocess.run(["umount", node["path"]], capture_output=True)
        for child in node.get("children") or []:
            walk(child)

    for d in data.get("blockdevices", []):
        walk(d)


def _validate_target(device: str) -> BlockDevice:
    for dev in list_block_devices():
        if dev.device == device:
            if dev.is_system:
                raise RuntimeError(f"{device} holds the running system — refusing to write")
            if not dev.removable:
                raise RuntimeError(f"{device} is not a removable device — refusing to write")
            return dev
    raise RuntimeError(f"{device} not found or not a removable disk")


def write_image(job: Job, image_path: Path, device: str) -> None:
    """Stream-decompress image_path (.img.xz or plain .img) onto `device`."""
    if not image_path.exists():
        raise FileNotFoundError(f"Image missing: {image_path}")
    target = _validate_target(device)
    job.log_line(f"Target: {target.device} ({target.model}, "
                 f"{target.size_bytes / 1e9:.1f} GB, {target.transport})")

    _unmount_all(device, job)

    # On macOS the raw device node is dramatically faster.
    write_dev = device
    if platform.system() == "Darwin" and device.startswith("/dev/disk"):
        write_dev = device.replace("/dev/disk", "/dev/rdisk")

    total_compressed = image_path.stat().st_size
    counting = _CountingReader(image_path)
    is_xz = image_path.suffix == ".xz"
    stream = lzma.LZMAFile(counting) if is_xz else counting  # type: ignore[arg-type]

    job.set_progress(0.0, f"Writing {image_path.name}")
    written = 0
    started = time.time()
    fd = os.open(write_dev, os.O_WRONLY)
    try:
        last_report = 0.0
        while True:
            job.check_cancelled()
            chunk = stream.read(WRITE_CHUNK)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                n = os.write(fd, view)
                view = view[n:]
            written += len(chunk)
            frac = counting.bytes_read / total_compressed if total_compressed else 0
            # Reserve the last 5% for fsync, which can take a while.
            job.set_progress(frac * 0.95)
            now = time.time()
            if now - last_report > 5:
                mbps = written / max(now - started, 0.001) / 1e6
                job.set_progress(frac * 0.95,
                                 f"Writing {image_path.name} — {written / 1e9:.2f} GB "
                                 f"({mbps:.0f} MB/s)")
                last_report = now
        job.set_progress(0.95, "Flushing buffers (this can take a minute)")
        job.log_line(f"Wrote {written / 1e9:.2f} GB, syncing ...")
        os.fsync(fd)
    finally:
        os.close(fd)
        if is_xz:
            stream.close()
        counting.close()

    if platform.system() == "Darwin":
        subprocess.run(["diskutil", "eject", device], capture_output=True)
        job.log_line("Ejected — safe to remove the card.")
    else:
        subprocess.run(["sync"], capture_output=True)
        # Re-read the partition table so a subsequent detect shows the new layout.
        subprocess.run(["partprobe", device], capture_output=True)
        job.log_line("Sync complete — safe to remove the card.")
    elapsed = time.time() - started
    job.set_progress(1.0, f"Done in {elapsed / 60:.1f} min")
