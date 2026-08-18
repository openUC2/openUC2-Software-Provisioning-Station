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


def shutdown_host() -> None:
    if platform.system() != "Linux":
        raise SystemControlError(
            "Shutdown is only supported on the station itself (Linux) — "
            f"not available in this {platform.system()} dev environment."
        )
    try:
        # Detached Popen: the response reaches the UI before the OS goes down.
        subprocess.Popen(["systemctl", "poweroff"])
    except FileNotFoundError as exc:
        raise SystemControlError(f"Could not run systemctl poweroff: {exc}") from exc
