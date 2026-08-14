"""Editable hardware-test parameters.

These are the knobs a technician tunes per production batch (step counts,
speeds, homing direction, endstop polarity, laser power …).  They live in a
JSON file next to the settings so they can be edited from the UI exactly
like the GitHub token, without touching code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class MotorParams(BaseModel):
    steps: int = Field(default=1000, description="Steps per test move")
    speed: int = Field(default=10000, description="Move speed (steps/s)")
    acceleration: int | None = Field(default=None, description="Optional acceleration")
    is_blocking: bool = Field(default=True, description="Wait for the move to finish")
    home_speed: int = Field(default=15000, description="Homing speed")
    home_direction: int = Field(default=-1, description="Homing direction (-1 or 1)")
    home_endstop_polarity: int = Field(default=1, description="Endstop polarity (-1 or 1)")
    home_timeout_s: int = Field(default=20, description="Homing timeout (seconds)")
    enable_before_move: bool = Field(default=True, description="Energise motors first")


class LaserParams(BaseModel):
    value_on: int = Field(default=1023, description="Laser value when ON (0-1023)")
    value_off: int = Field(default=0, description="Laser value when OFF")
    channels: list[int] = Field(default=[1, 2, 3], description="Channels to expose (1=R,2=G,3=B)")
    dwell_s: float = Field(default=1.0, description="How long the blink test stays on")


class LedParams(BaseModel):
    intensity: list[int] = Field(default=[128, 128, 128], description="RGB 0-255")
    n_leds: int = Field(default=64, description="LEDs on the matrix")
    single_index: int = Field(default=0, description="Index used by the single-LED test")


class GalvoParams(BaseModel):
    nx: int = Field(default=256, description="Scan points in X")
    ny: int = Field(default=256, description="Scan points in Y")
    x_min: int = Field(default=500, description="DAC min X (0-4095)")
    x_max: int = Field(default=3500, description="DAC max X (0-4095)")
    y_min: int = Field(default=500, description="DAC min Y (0-4095)")
    y_max: int = Field(default=3500, description="DAC max Y (0-4095)")
    sample_period_us: int = Field(default=1, description="Sample period (µs)")
    park_x: int = Field(default=2048, description="Park position X (DAC counts)")
    park_y: int = Field(default=2048, description="Park position Y (DAC counts)")
    dac_frequency: int = Field(default=2, description="Sweep frequency (Hz)")
    dac_amplitude: int = Field(default=1000, description="Sweep amplitude (DAC counts)")


class TestParams(BaseModel):
    """Everything the hardware tests need, in one editable document."""

    motor: MotorParams = MotorParams()
    laser: LaserParams = LaserParams()
    led: LedParams = LedParams()
    galvo: GalvoParams = GalvoParams()
    # Serial baud used to talk to boards. UC2 firmware runs the console at
    # 115200; 921600 exists for boards configured for the fast console.
    baud: int = Field(default=115200, description="Serial baud for test commands")
    connect_timeout_s: float = Field(default=8.0, description="Connection timeout")

    @classmethod
    def load(cls, path: Path) -> "TestParams":
        if path.exists():
            try:
                return cls.model_validate_json(path.read_text())
            except Exception:  # noqa: BLE001 - fall back to defaults on corruption
                pass
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2))

    def schema_for_ui(self) -> dict[str, Any]:
        """Field metadata so the UI can render an editor without hardcoding."""
        out: dict[str, Any] = {}
        for group, model in (
            ("motor", MotorParams), ("laser", LaserParams),
            ("led", LedParams), ("galvo", GalvoParams),
        ):
            out[group] = {
                name: {
                    "description": f.description or "",
                    "type": "list" if str(f.annotation).startswith("list")
                    else ("bool" if f.annotation is bool else "number"),
                }
                for name, f in model.model_fields.items()
            }
        return out
