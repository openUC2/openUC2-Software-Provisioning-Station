"""Board catalog — maps firmware binaries to human-meaningful boards.

Two naming schemes exist for the same builds:

* **container / build-frame**: `esp32_<PIO_ENV>[_mot<AXIS>][_merged].bin`
  (what the firmware-image-server image ships under /srv)
* **release / build-and-release**: `<board-id>.bin` friendly names
  (what the GitHub release and the web flasher use)

Both ship *app-only* and *merged* variants of most builds.  Only the merged
image may be written at offset 0x0 — an app-only binary belongs at 0x10000
and flashing it at 0 produces a board that never boots.  `resolve_variants`
therefore only ever selects merged images.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Categories drive the UI grouping and which hardware tests are offered.
CAT_STANDALONE = "standalone"
CAT_MASTER = "can-master"
CAT_SLAVE = "can-slave"
CAT_BRIDGE = "bridge"
CAT_ODMR = "odmr"
CAT_OTHER = "other"


@dataclass
class Board:
    id: str
    name: str
    chip: str | None          # ESP32 / ESP32-S3 / ESP32-C3; None = auto-detect
    category: str
    # Which hardware-test groups apply once this board is flashed.
    tests: list[str] = field(default_factory=list)
    # Filenames that provide this board, best first.
    filenames: tuple[str, ...] = ()
    description: str = ""
    # CAN node this firmware becomes, when applicable (used by the HAT to
    # address it during testing).
    can_axis: str | None = None

    def to_dict(self, file: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "chip_family": self.chip,
            "category": self.category,
            "tests": self.tests,
            "file": file,
            "description": self.description,
            "can_axis": self.can_axis,
        }


def _b(
    id: str,
    name: str,
    chip: str | None,
    category: str,
    filenames: Iterable[str],
    tests: Iterable[str] = (),
    description: str = "",
    can_axis: str | None = None,
) -> Board:
    return Board(
        id=id,
        name=name,
        chip=chip,
        category=category,
        tests=list(tests),
        filenames=tuple(filenames),
        description=description,
        can_axis=can_axis,
    )


# Chip families come from the release pipeline's explicit board map
# (firmware-index.json), which is authoritative — the PlatformIO env name
# alone is not (e.g. the PS4 USB-host bridge needs S3 for USB OTG).
CATALOG: list[Board] = [
    # -- standalone all-in-one controllers -------------------------------
    _b("esp32-uc2-standalone-2", "UC2 Standalone V2", "ESP32", CAT_STANDALONE,
       ["esp32-uc2-standalone-2.bin", "esp32_UC2_2_merged.bin"],
       ["motor", "laser", "led"], "All-in-one controller, UC2 board v2"),
    _b("esp32-uc2-standalone-3", "UC2 Standalone V3", "ESP32", CAT_STANDALONE,
       ["esp32-uc2-standalone-3.bin", "esp32_UC2_3_merged.bin"],
       ["motor", "laser", "led"], "All-in-one controller, UC2 board v3"),
    _b("esp32-uc2-standalone-4", "UC2 Standalone V4", "ESP32", CAT_STANDALONE,
       ["esp32-uc2-standalone-4.bin", "esp32_UC2_4_merged.bin"],
       ["motor", "laser", "led"], "All-in-one controller, UC2 board v4"),
    _b("uc2-can-standalone-v4", "UC2 CAN Standalone V4", "ESP32", CAT_STANDALONE,
       ["uc2-can-standalone-v4.bin", "esp32_UC2_canopen_standalone_v4_release_merged.bin"],
       ["motor", "laser", "led"], "Standalone v4 with CAN bus support"),
    _b("esp32-uc2-wemos", "UC2 WEMOS D1 R32", "ESP32", CAT_STANDALONE,
       ["esp32-uc2-wemos.bin", "esp32_UC2_WEMOS_merged.bin"],
       ["motor", "laser", "led"], "Wemos D1 R32 based controller"),

    # -- CAN master (the HAT) --------------------------------------------
    _b("uc2-can-master", "UC2 CAN Master (HAT)", "ESP32", CAT_MASTER,
       ["uc2-can-master.bin", "esp32_UC2_canopen_master_release_merged.bin"],
       ["motor", "laser", "led", "galvo", "can"],
       "HAT / bus master — forwards commands to every CAN module"),

    # -- CAN slave modules ------------------------------------------------
    _b("uc2-can-slave-motor", "CAN Motor (generic)", "ESP32-S3", CAT_SLAVE,
       ["uc2-can-slave-motor.bin", "esp32_UC2_canopen_slave_motor_release_merged.bin"],
       ["motor"], "Motor module without a preset axis id"),
    _b("uc2-can-slave-motor-x", "CAN Motor X", "ESP32-S3", CAT_SLAVE,
       ["esp32_UC2_canopen_slave_motor_release_motX_merged.bin"],
       ["motor"], "Motor module pre-assigned to axis X", can_axis="X"),
    _b("uc2-can-slave-motor-y", "CAN Motor Y", "ESP32-S3", CAT_SLAVE,
       ["esp32_UC2_canopen_slave_motor_release_motY_merged.bin"],
       ["motor"], "Motor module pre-assigned to axis Y", can_axis="Y"),
    _b("uc2-can-slave-motor-z", "CAN Motor Z", "ESP32-S3", CAT_SLAVE,
       ["esp32_UC2_canopen_slave_motor_release_motZ_merged.bin"],
       ["motor"], "Motor module pre-assigned to axis Z", can_axis="Z"),
    _b("uc2-can-slave-motor-a", "CAN Motor A", "ESP32-S3", CAT_SLAVE,
       ["esp32_UC2_canopen_slave_motor_release_motA_merged.bin"],
       ["motor"], "Motor module pre-assigned to axis A", can_axis="A"),
    _b("uc2-can-slave-accelmotor", "CAN Motor (accel)", "ESP32-S3", CAT_SLAVE,
       ["uc2-can-slave-accelmotor.bin",
        "esp32_UC2_canopen_slave_accelmotor_release_merged.bin"],
       ["motor"], "Motor module with acceleration profiles"),
    _b("uc2-can-slave-laser", "CAN Laser", "ESP32-S3", CAT_SLAVE,
       ["uc2-can-slave-laser.bin", "esp32_UC2_canopen_slave_laser_release_merged.bin"],
       ["laser"], "Laser / illumination driver module"),
    _b("uc2-can-slave-led", "CAN LED Matrix", "ESP32-S3", CAT_SLAVE,
       ["uc2-can-slave-led.bin", "esp32_UC2_canopen_slave_led_release_merged.bin"],
       ["led"], "LED matrix / ring illumination module"),
    _b("uc2-can-slave-galvo", "CAN Galvo", "ESP32-S3", CAT_SLAVE,
       ["uc2-can-slave-galvo.bin", "esp32_UC2_canopen_slave_galvo_release_merged.bin"],
       ["galvo"], "Galvanometer scanner module"),
    _b("uc2-can-slave-gpio", "CAN GPIO", "ESP32-S3", CAT_SLAVE,
       ["uc2-can-slave-gpio.bin", "esp32_UC2_canopen_slave_gpio_release_merged.bin"],
       ["gpio"], "General purpose IO module"),

    # -- bridges ----------------------------------------------------------
    _b("uc2-can-bridge-ps4-usbhost", "PS4 Controller Bridge", "ESP32-S3", CAT_BRIDGE,
       ["uc2-can-bridge-ps4-usbhost.bin",
        "esp32_UC2_canopen_bridge_ps4_usbhost_release_merged.bin"],
       [], "USB host bridge for PS4 gamepad control"),
    _b("uc2-can-bridge-ptz", "PTZ Bridge", None, CAT_BRIDGE,
       ["esp32_UC2_canopen_bridge_ptz_release_merged.bin"],
       [], "Pan/tilt/zoom camera bridge"),

    # -- Xiao / Waveshare boards -----------------------------------------
    _b("seeed_xiao_esp32s3", "Xiao ESP32S3", "ESP32-S3", CAT_OTHER,
       ["seeed_xiao_esp32s3.bin", "esp32_seeed_xiao_esp32s3_merged.bin"],
       ["motor", "laser"], "Seeed Xiao ESP32-S3 board"),
    _b("seeed_xiao_esp32s3_ledring", "Xiao LED Ring", "ESP32-S3", CAT_OTHER,
       ["seeed_xiao_esp32s3_ledring.bin",
        "esp32_seeed_xiao_esp32s3_ledring_merged.bin"],
       ["led"], "Xiao ESP32-S3 driving an LED ring"),
    _b("seeed_xiao_esp32s3_ledservo", "Xiao LED + Servo", "ESP32-S3", CAT_OTHER,
       ["seeed_xiao_esp32s3_ledservo.bin",
        "esp32_seeed_xiao_esp32s3_ledservo_merged.bin"],
       ["led"], "Xiao ESP32-S3 with LED and servo control"),
    _b("waveshare_esp32s3_ledarray", "Waveshare LED Array", "ESP32-S3", CAT_OTHER,
       ["waveshare_esp32s3_ledarray.bin",
        "esp32_waveshare_esp32s3_ledarray_merged.bin"],
       ["led"], "Waveshare ESP32-S3 LED array"),

    # -- ODMR --------------------------------------------------------------
    _b("odmr-xiao-esp32s3", "ODMR Xiao ESP32-S3", "ESP32-S3", CAT_ODMR,
       ["odmr-xiao-esp32s3.bin"],
       [], "ODMR quantum sensing board (Xiao ESP32-S3)"),
    _b("odmr-xiao-esp32c3", "ODMR Xiao ESP32-C3", "ESP32-C3", CAT_ODMR,
       ["odmr-xiao-esp32c3.bin"],
       [], "ODMR quantum sensing board (Xiao ESP32-C3)"),
]

BY_ID = {b.id: b for b in CATALOG}
# filename -> (board, rank) where rank is the board's preference order.
_BY_FILE: dict[str, tuple[Board, int]] = {}
for _b_ in CATALOG:
    for _rank, _fn in enumerate(_b_.filenames):
        _BY_FILE[_fn] = (_b_, _rank)


def _is_flashable_at_zero(filename: str) -> bool:
    """Only merged images (or friendly release names, which are merged) may
    be written at offset 0."""
    if not filename.endswith(".bin"):
        return False
    if filename.endswith("_merged.bin"):
        return True
    # Env-named builds without the _merged suffix are app-only images.
    return not filename.startswith("esp32_")


def resolve_variants(filenames: Iterable[str]) -> list[dict[str, Any]]:
    """Map the files present in a bundle onto catalog boards.

    Unknown-but-flashable binaries are still offered (so a new board added
    upstream is usable before this table catches up), just without curated
    metadata.
    """
    available = [f for f in filenames if _is_flashable_at_zero(f)]
    chosen: dict[str, tuple[int, str]] = {}  # board id -> (rank, filename)
    unknown: list[str] = []

    for fn in available:
        hit = _BY_FILE.get(fn)
        if hit is None:
            unknown.append(fn)
            continue
        board, rank = hit
        prev = chosen.get(board.id)
        if prev is None or rank < prev[0]:
            chosen[board.id] = (rank, fn)

    variants = [BY_ID[bid].to_dict(fn) for bid, (_, fn) in chosen.items()]

    for fn in unknown:
        stem = fn.removesuffix("_merged.bin").removesuffix(".bin")
        stem = re.sub(r"^esp32_", "", stem)
        variants.append(
            {
                "id": stem,
                "name": stem.replace("_", " "),
                "chip_family": _guess_chip(fn),
                "category": CAT_OTHER,
                "tests": [],
                "file": fn,
                "description": "Not in the board catalog — chip auto-detected",
                "can_axis": None,
            }
        )

    order = {
        CAT_STANDALONE: 0, CAT_MASTER: 1, CAT_SLAVE: 2,
        CAT_BRIDGE: 3, CAT_ODMR: 4, CAT_OTHER: 5,
    }
    variants.sort(key=lambda v: (order.get(v["category"], 9), v["name"]))
    return variants


def _guess_chip(filename: str) -> str | None:
    low = filename.lower()
    if "esp32c3" in low or "esp32-c3" in low:
        return "ESP32-C3"
    if "esp32s3" in low or "esp32-s3" in low or "xiao" in low or "canopen_slave" in low:
        return "ESP32-S3"
    return None  # let esptool auto-detect rather than risk a wrong --chip
