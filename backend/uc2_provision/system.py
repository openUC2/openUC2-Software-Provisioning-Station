"""Host power control.

The station is a dedicated appliance — the touchscreen is the only input a
technician has, so shutting down the Raspberry Pi cleanly has to be a menu
item rather than "find a keyboard". The backend runs as root (see
scripts/uc2-provision.service), so no sudo prompt is involved.
"""

from __future__ import annotations

import platform
import subprocess


class SystemControlError(RuntimeError):
    pass


def _power_action(verb: str, label: str) -> None:
    if platform.system() != "Linux":
        raise SystemControlError(
            f"{label} is only supported on the station itself (Linux) — "
            f"not available in this {platform.system()} dev environment."
        )
    try:
        # Detached and slightly delayed so the HTTP response reaches the UI
        # before the OS goes down under it.
        subprocess.Popen(
            ["sh", "-c", f"sleep 1; exec systemctl {verb}"], start_new_session=True
        )
    except FileNotFoundError as exc:
        raise SystemControlError(f"Could not run systemctl {verb}: {exc}") from exc


def shutdown_host() -> None:
    _power_action("poweroff", "Shutdown")


def reboot_host() -> None:
    _power_action("reboot", "Reboot")
