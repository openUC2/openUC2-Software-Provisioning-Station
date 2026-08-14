"""ESP32 firmware flashing via esptool (fully local, no WebSerial).

The uc2-esp32 release pipeline publishes *merged* binaries (bootloader +
partition table + boot_app0 + app in one file), so every variant is written
as a single image at offset 0x0.  The flash sequence is:

    1. esptool erase_flash        (at a conservative 115200 baud)
    2. esptool write_flash 0x0    (at the user-selected baud, default 460800)
    3. optional: open the serial port and capture boot output

esptool is invoked as a subprocess (`python -m esptool`) so a crash or a
wedged serial port can never take down the backend, and so we can stream its
stdout into the job log line by line.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import serial as pyserial
from serial.tools import list_ports

from .jobs import Job

BAUD_CHOICES = [115200, 230400, 460800, 921600]
ERASE_BAUD = 115200

# chipFamily strings used in the esp-web-tools manifests / firmware-index.json
CHIP_MAP = {
    "ESP32": "esp32",
    "ESP32-S2": "esp32s2",
    "ESP32-S3": "esp32s3",
    "ESP32-C3": "esp32c3",
}

# USB VID:PID pairs of adapters used on UC2 boards (CP210x, CH340/CH341,
# FTDI, Espressif native USB).  Anything else is still listed, just unmarked.
KNOWN_ADAPTERS = {
    (0x10C4, 0xEA60): "CP210x",
    (0x1A86, 0x7523): "CH340",
    (0x1A86, 0x55D4): "CH9102",
    (0x0403, 0x6001): "FTDI",
    (0x303A, 0x1001): "ESP32-S3 USB",
    (0x303A, 0x0002): "ESP32 USB",
}


@dataclass
class SerialPortInfo:
    device: str
    description: str
    adapter: str | None
    vid: int | None
    pid: int | None
    serial_number: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "description": self.description,
            "adapter": self.adapter,
            "vid": f"{self.vid:04x}" if self.vid is not None else None,
            "pid": f"{self.pid:04x}" if self.pid is not None else None,
            "serial_number": self.serial_number,
        }


def list_serial_ports() -> list[SerialPortInfo]:
    out: list[SerialPortInfo] = []
    for p in list_ports.comports():
        # ESP32 boards always enumerate as USB serial (CP210x/CH340/FTDI or
        # native USB), which carries a VID/PID — anything without one is a
        # Bluetooth pseudo-port or an on-board UART; hide it from the UI.
        if p.vid is None:
            continue
        adapter = None
        if p.vid is not None and p.pid is not None:
            adapter = KNOWN_ADAPTERS.get((p.vid, p.pid))
        out.append(
            SerialPortInfo(
                device=p.device,
                description=p.description or "",
                adapter=adapter,
                vid=p.vid,
                pid=p.pid,
                serial_number=p.serial_number,
            )
        )
    # Likely ESP adapters first.
    out.sort(key=lambda s: (s.adapter is None, s.device))
    return out


PROGRESS_RE = re.compile(r"\((?P<pct>\d{1,3})\s*%\)")


def _run_esptool(job: Job, args: list[str], progress_span: tuple[float, float]) -> None:
    """Run esptool as a subprocess, streaming output into the job log and
    mapping its percentage output onto [progress_span]."""
    cmd = [sys.executable, "-m", "esptool", *args]
    job.log_line("$ " + " ".join(cmd[2:]))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lo, hi = progress_span
    assert proc.stdout is not None
    last_line = ""
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        m = PROGRESS_RE.search(line)
        if m:
            pct = int(m.group("pct")) / 100.0
            job.set_progress(lo + (hi - lo) * pct)
            # esptool prints one line per block; don't flood the log.
            if pct in (0.0, 1.0) or int(m.group("pct")) % 10 == 0:
                job.log_line(line)
        else:
            job.log_line(line)
        last_line = line
        if job.cancel_requested:
            proc.terminate()
            proc.wait(timeout=10)
            job.check_cancelled()
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"esptool exited with code {code}: {last_line}")


def flash_firmware(
    job: Job,
    port: str,
    firmware_path: Path,
    chip: str | None = None,
    baud: int = 460800,
    erase_first: bool = True,
    offset: int = 0x0,
) -> None:
    """Erase (optionally) and write a merged firmware binary."""
    if not firmware_path.exists():
        raise FileNotFoundError(f"Firmware file missing: {firmware_path}")
    chip_args = ["--chip", chip] if chip else []

    if erase_first:
        job.set_progress(0.02, "Erasing flash")
        job.log_line(f"Erasing flash on {port} at {ERASE_BAUD} baud ...")
        _run_esptool(
            job,
            [*chip_args, "--port", port, "--baud", str(ERASE_BAUD), "erase_flash"],
            (0.02, 0.25),
        )
        job.set_progress(0.25, "Erase complete")
        # Give the chip a moment to reset before reconnecting.
        time.sleep(1.0)

    job.set_progress(0.28, f"Writing {firmware_path.name}")
    job.log_line(f"Writing {firmware_path.name} at offset {offset:#x}, {baud} baud ...")
    _run_esptool(
        job,
        [
            *chip_args,
            "--port", port,
            "--baud", str(baud),
            "write_flash",
            # Merged images embed the correct flash mode/size; keep them.
            "--flash_mode", "keep",
            "--flash_freq", "keep",
            "--flash_size", "keep",
            f"{offset:#x}",
            str(firmware_path),
        ],
        (0.28, 0.95),
    )
    job.set_progress(0.97, "Verifying boot")
    boot = read_boot_banner(port)
    if boot:
        for line in boot.splitlines()[:15]:
            job.log_line(f"boot: {line}")
    job.set_progress(1.0, "Done")


def read_boot_banner(port: str, baud: int = 115200, seconds: float = 3.0) -> str:
    """Reset the board via DTR/RTS and capture the first boot output."""
    try:
        with pyserial.Serial(port, baud, timeout=0.5) as ser:
            # Classic auto-reset dance: EN low via RTS pulse.
            ser.dtr = False
            ser.rts = True
            time.sleep(0.1)
            ser.rts = False
            end = time.time() + seconds
            chunks: list[bytes] = []
            while time.time() < end:
                data = ser.read(4096)
                if data:
                    chunks.append(data)
            return b"".join(chunks).decode("utf-8", errors="replace")
    except (OSError, pyserial.SerialException):
        return ""


def send_serial_command(
    port: str,
    payload: str,
    baud: int = 115200,
    read_seconds: float = 2.0,
) -> str:
    """Send one line (UC2 JSON command) and return the response text.

    Used by the hardware-test scaffolding: UC2 firmware speaks JSON over
    serial, e.g. {"task": "/motor_act", ...}.
    """
    with pyserial.Serial(port, baud, timeout=0.5) as ser:
        ser.reset_input_buffer()
        ser.write(payload.strip().encode() + b"\n")
        ser.flush()
        end = time.time() + read_seconds
        chunks: list[bytes] = []
        while time.time() < end:
            data = ser.read(4096)
            if data:
                chunks.append(data)
        return b"".join(chunks).decode("utf-8", errors="replace")
