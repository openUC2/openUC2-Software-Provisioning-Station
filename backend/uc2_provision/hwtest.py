"""Hardware testing over UC2-REST.

After flashing, a technician verifies the board actually works.  Every test
is a small, named action ("move X forward", "laser 1 on", "home Z") that the
station runs on the connected board and then asks the technician to confirm
physically ("did the stage move right?").

Communication goes through the UC2-REST client (`uc2rest.UC2Client`) rather
than raw serial writes, so we inherit its command encoding, axis mapping and
firmware handshake.  Note UC2-REST is serial-only — the WiFi/HTTP transport
was removed upstream.

**The CAN master (HAT) is special**: motor/laser/LED commands sent to it are
routed transparently to the corresponding CAN slave, so the same test
actions work whether they are aimed at a standalone board or at a whole
microscope hanging off a master.  Direct node addressing (bus scan, node-id
assignment) is available on masters only.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .testparams import TestParams

# Axis names → UC2 stepper ids (A=0, X=1, Y=2, Z=3).
AXES = ["X", "Y", "Z", "A"]

# CAN node ids used by the openUC2 bus, for display during a bus scan.
CAN_NODE_HINTS = {
    1: "master (HAT)",
    11: "motor X", 12: "motor Y", 13: "motor Z",
    20: "laser 0", 21: "laser 1", 22: "laser 2", 23: "laser 3",
    30: "LED matrix",
    60: "GPIO / collision",
    61: "PTZ bridge",
}


class HardwareError(RuntimeError):
    pass


def _import_uc2rest():
    try:
        import uc2rest  # noqa: PLC0415 - optional dependency, imported on demand
    except ImportError as exc:  # pragma: no cover - depends on install
        raise HardwareError(
            "UC2-REST is not installed — run `pip install UC2-REST` in the "
            "station's virtualenv to enable hardware testing."
        ) from exc
    return uc2rest


@dataclass
class Connection:
    port: str
    baud: int
    client: Any
    info: dict[str, Any]
    opened_at: float


class HardwareManager:
    """Owns the (single) live board connection.

    Only one board is talked to at a time — the station has one test bay —
    which also keeps us from holding a serial port that the flasher needs.
    """

    def __init__(self, params_provider: Callable[[], TestParams]) -> None:
        self._params = params_provider
        self._conn: Connection | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    @property
    def connection(self) -> Connection | None:
        return self._conn

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._conn is None:
                return {"connected": False}
            return {
                "connected": True,
                "port": self._conn.port,
                "baud": self._conn.baud,
                "connected_for_s": round(time.time() - self._conn.opened_at, 1),
                **self._conn.info,
            }

    def connect(self, port: str, baud: int | None = None) -> dict[str, Any]:
        uc2rest = _import_uc2rest()
        params = self._params()
        baud = baud or params.baud
        with self._lock:
            self.disconnect()
            client = uc2rest.UC2Client(serialport=port, baudrate=baud, DEBUG=False)
            serial = getattr(client, "serial", None)
            if serial is None or not getattr(serial, "is_connected", False):
                # UC2Client silently falls back to a mock serial device.
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass
                raise HardwareError(
                    f"No UC2 board answered on {port} at {baud} baud. "
                    "Check the cable, the baud rate, and that the board is flashed."
                )
            info = self._identify(client)
            self._conn = Connection(
                port=port, baud=baud, client=client, info=info, opened_at=time.time()
            )
            return {"connected": True, "port": port, "baud": baud, **info}

    def _identify(self, client: Any) -> dict[str, Any]:
        info: dict[str, Any] = {"firmware": None, "is_master": False, "capabilities": []}
        try:
            fw = client.state.get_firmware_info(timeout=3)
            if isinstance(fw, dict):
                info["firmware"] = fw
                pindef = str(fw.get("pindef", "")).lower()
                info["is_master"] = bool(fw.get("isMaster")) or "master" in pindef
                info["board_hint"] = fw.get("pindef") or fw.get("name")
        except Exception as exc:  # noqa: BLE001 - identification is best-effort
            info["identify_error"] = str(exc)

        # A master fronts every subsystem; a slave only its own. We can't
        # reliably introspect a slave's type, so offer everything and let a
        # failed command report the truth.
        info["capabilities"] = ["motor", "laser", "led", "galvo"]
        if info["is_master"]:
            info["capabilities"].append("can")
        return info

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.client.close()
                except Exception:  # noqa: BLE001 - closing a dead port
                    pass
                self._conn = None
            return {"connected": False}

    def _client(self) -> Any:
        with self._lock:
            if self._conn is None:
                raise HardwareError("No board connected — connect one first.")
            return self._conn.client

    # ------------------------------------------------------------------
    # Test actions
    # ------------------------------------------------------------------
    def run(self, group: str, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        handler = getattr(self, f"_run_{group}", None)
        if handler is None:
            raise HardwareError(f"Unknown test group: {group}")
        started = time.time()
        with self._lock:
            result = handler(action, args)
        return {
            "group": group,
            "action": action,
            "args": args,
            "duration_s": round(time.time() - started, 2),
            "result": _jsonable(result),
        }

    # -- motor ----------------------------------------------------------
    def _run_motor(self, action: str, args: dict[str, Any]) -> Any:
        c = self._client()
        p = self._params().motor
        axis = str(args.get("axis", "X")).upper()
        if axis not in AXES:
            raise HardwareError(f"Unknown axis {axis}")
        steps = int(args.get("steps", p.steps))
        speed = int(args.get("speed", p.speed))

        if action == "enable":
            return c.motor.set_motor_enable(enable=True)
        if action == "disable":
            return c.motor.set_motor_enable(enable=False)
        if action in ("move_forward", "move_backward"):
            if p.enable_before_move:
                c.motor.set_motor_enable(enable=True)
            signed = steps if action == "move_forward" else -steps
            return c.motor.move_axis_by_name(
                axis=axis,
                steps=signed,
                speed=speed,
                acceleration=p.acceleration,
                is_blocking=p.is_blocking,
                is_absolute=False,
            )
        if action == "home":
            return c.home.home(
                axis=axis,
                speed=int(args.get("home_speed", p.home_speed)),
                direction=int(args.get("direction", p.home_direction)),
                endstoppolarity=int(args.get("endstop_polarity", p.home_endstop_polarity)),
                timeout=int(args.get("timeout", p.home_timeout_s)),
                isBlocking=True,
            )
        if action == "stop":
            return c.motor.stop()
        if action == "position":
            return c.motor.get_position(timeout=2)
        raise HardwareError(f"Unknown motor action: {action}")

    # -- laser ----------------------------------------------------------
    def _run_laser(self, action: str, args: dict[str, Any]) -> Any:
        c = self._client()
        p = self._params().laser
        channel = int(args.get("channel", 1))

        if action == "on":
            return c.laser.set_laser(
                channel=channel, value=int(args.get("value", p.value_on))
            )
        if action == "off":
            return c.laser.set_laser(channel=channel, value=p.value_off)
        if action == "blink":
            c.laser.set_laser(channel=channel, value=int(args.get("value", p.value_on)))
            time.sleep(float(args.get("dwell_s", p.dwell_s)))
            return c.laser.set_laser(channel=channel, value=p.value_off)
        if action == "all_off":
            return [c.laser.set_laser(channel=ch, value=p.value_off) for ch in p.channels]
        raise HardwareError(f"Unknown laser action: {action}")

    # -- LED ------------------------------------------------------------
    def _run_led(self, action: str, args: dict[str, Any]) -> Any:
        c = self._client()
        p = self._params().led
        intensity = tuple(args.get("intensity", p.intensity))

        if action == "all_on":
            return c.led.send_LEDMatrix_full(intensity=intensity)
        if action == "off":
            return c.led.send_LEDMatrix_off()
        if action == "single":
            return c.led.send_LEDMatrix_single(
                indexled=int(args.get("index", p.single_index)), intensity=intensity
            )
        if action == "status":
            return c.led.send_LEDMatrix_status(status=str(args.get("status", "success")))
        if action in ("left", "right", "top", "bottom"):
            return c.led.send_LEDMatrix_halves(region=action, intensity=intensity)
        raise HardwareError(f"Unknown LED action: {action}")

    # -- galvo -----------------------------------------------------------
    def _run_galvo(self, action: str, args: dict[str, Any]) -> Any:
        c = self._client()
        p = self._params().galvo

        if action == "start":
            return c.galvo.set_galvo_scan(
                nx=int(args.get("nx", p.nx)), ny=int(args.get("ny", p.ny)),
                x_min=p.x_min, x_max=p.x_max, y_min=p.y_min, y_max=p.y_max,
                sample_period_us=p.sample_period_us, frame_count=0,
            )
        if action == "stop":
            return c.galvo.stop_galvo_scan()
        if action in ("sweep_x", "sweep_y"):
            # A slow, large-amplitude waveform makes mirror motion visible.
            channel = 1 if action == "sweep_x" else 2
            return c.galvo.set_dac(
                channel=channel,
                frequency=int(args.get("frequency", p.dac_frequency)),
                amplitude=int(args.get("amplitude", p.dac_amplitude)),
                offset=int(args.get("offset", p.park_x if channel == 1 else p.park_y)),
            )
        if action == "park":
            # Zero frequency and amplitude hold the mirror at a fixed offset.
            return [
                c.galvo.set_dac(channel=1, frequency=0, amplitude=0,
                                offset=int(args.get("x", p.park_x))),
                c.galvo.set_dac(channel=2, frequency=0, amplitude=0,
                                offset=int(args.get("y", p.park_y))),
            ]
        if action == "status":
            return c.galvo.get_galvo_status(timeout=2)
        raise HardwareError(f"Unknown galvo action: {action}")

    # -- CAN bus (master only) -------------------------------------------
    def _run_can(self, action: str, args: dict[str, Any]) -> Any:
        c = self._client()
        if action == "scan":
            result = c.can.scan(timeout=int(args.get("timeout", 5)))
            return _annotate_can(result)
        if action == "discover":
            return _annotate_can(c.can.discover(timeout=int(args.get("timeout", 8))))
        if action == "devices":
            return c.can.get_available_devices(timeout=2)
        if action == "assign_id":
            mac = args.get("mac")
            new_id = args.get("new_id")
            if not mac or new_id is None:
                raise HardwareError("assign_id needs 'mac' and 'new_id'")
            return c.can.assign_node_id_by_mac(mac, int(new_id))
        if action == "reboot_node":
            return c.can.reboot_remote(can_address=int(args.get("node", 0)))
        raise HardwareError(f"Unknown CAN action: {action}")

    # -- board state ------------------------------------------------------
    def _run_state(self, action: str, args: dict[str, Any]) -> Any:
        c = self._client()
        if action == "firmware":
            return c.state.get_firmware_info(timeout=3)
        if action == "state":
            return c.state.get_state(timeout=3)
        if action == "restart":
            return c.state.espRestart(timeout=2)
        raise HardwareError(f"Unknown state action: {action}")


def _annotate_can(result: Any) -> Any:
    """Label scan results with what each node id normally is."""
    if isinstance(result, dict):
        for entry in result.get("scan", []) or []:
            if isinstance(entry, dict) and "canId" in entry:
                entry["expected_role"] = CAN_NODE_HINTS.get(entry["canId"], "unknown")
    return result


def _jsonable(value: Any) -> Any:
    """UC2-REST returns numpy arrays for positions; make them serializable."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


# ---------------------------------------------------------------------------
# Declarative catalog the UI renders test buttons from
# ---------------------------------------------------------------------------

TEST_GROUPS: list[dict[str, Any]] = [
    {
        "id": "motor",
        "name": "Motor",
        "icon": "motor",
        "prompt": "Watch the stage while each move runs.",
        "axes": AXES,
        "actions": [
            {"id": "move_forward", "name": "Move +", "per_axis": True,
             "confirm": "Did the axis move in the positive direction?"},
            {"id": "move_backward", "name": "Move −", "per_axis": True,
             "confirm": "Did the axis move back to where it started?"},
            {"id": "home", "name": "Home", "per_axis": True,
             "confirm": "Did the axis reach the endstop and stop cleanly?"},
            {"id": "position", "name": "Read position", "per_axis": False},
            {"id": "enable", "name": "Enable motors", "per_axis": False},
            {"id": "stop", "name": "Stop", "per_axis": False, "danger": True},
        ],
    },
    {
        "id": "laser",
        "name": "Laser",
        "icon": "laser",
        "prompt": "Check each illumination channel lights up.",
        "channels": [1, 2, 3],
        "actions": [
            {"id": "on", "name": "On", "per_channel": True,
             "confirm": "Is this channel emitting?"},
            {"id": "off", "name": "Off", "per_channel": True},
            {"id": "blink", "name": "Blink", "per_channel": True,
             "confirm": "Did the channel blink once?"},
            {"id": "all_off", "name": "All off", "per_channel": False, "danger": True},
        ],
    },
    {
        "id": "led",
        "name": "LED matrix",
        "icon": "led",
        "prompt": "Verify the illumination matrix.",
        "actions": [
            {"id": "all_on", "name": "All on", "confirm": "Are all LEDs lit evenly?"},
            {"id": "single", "name": "Single LED", "confirm": "Is exactly one LED lit?"},
            {"id": "left", "name": "Left half"},
            {"id": "right", "name": "Right half"},
            {"id": "off", "name": "Off"},
        ],
    },
    {
        "id": "galvo",
        "name": "Galvo",
        "icon": "galvo",
        "prompt": "Check the scanner mirrors move.",
        "actions": [
            {"id": "start", "name": "Start scan", "confirm": "Is the beam scanning?"},
            {"id": "sweep_x", "name": "Sweep X", "confirm": "Did the X mirror move?"},
            {"id": "sweep_y", "name": "Sweep Y", "confirm": "Did the Y mirror move?"},
            {"id": "stop", "name": "Stop scan"},
            {"id": "park", "name": "Park centre"},
            {"id": "status", "name": "Read status"},
        ],
    },
    {
        "id": "can",
        "name": "CAN bus",
        "icon": "can",
        "master_only": True,
        "prompt": "Only available on a CAN master (HAT).",
        "actions": [
            {"id": "scan", "name": "Scan bus",
             "confirm": "Are all expected modules listed?"},
            {"id": "discover", "name": "Deep discover"},
            {"id": "devices", "name": "List devices"},
        ],
    },
    {
        "id": "state",
        "name": "Board",
        "icon": "board",
        "prompt": "Identify the connected board.",
        "actions": [
            {"id": "firmware", "name": "Firmware info"},
            {"id": "state", "name": "Full state"},
            {"id": "restart", "name": "Restart board", "danger": True},
        ],
    },
]
