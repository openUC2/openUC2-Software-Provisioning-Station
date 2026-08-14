"""Runtime configuration.

Settings are loaded from (highest precedence first):
  1. environment variables prefixed with UC2_ (e.g. UC2_GITHUB_TOKEN)
  2. a JSON settings file in the data directory (editable from the UI)
  3. defaults below

The data directory defaults to /var/lib/uc2-provision on Linux and
~/uc2-provision elsewhere so the app is developable on a laptop.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    if platform.system() == "Linux":
        return Path("/var/lib/uc2-provision")
    return Path.home() / "uc2-provision"


class SourceRepo(BaseModel):
    """A GitHub repository we pull artifacts from."""

    owner: str
    repo: str
    # Which release assets to pick up, as glob patterns.
    asset_patterns: list[str] = Field(default_factory=lambda: ["*"])
    # Include GitHub pre-releases in listings.
    include_prereleases: bool = False

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UC2_", env_file=None)

    data_dir: Path = Field(default_factory=default_data_dir)
    github_token: str = ""

    # Artifact sources. os-rpi provides SD card images, uc2-esp32 the firmware.
    image_source: SourceRepo = SourceRepo(
        owner="openUC2",
        repo="os-rpi",
        asset_patterns=["*.img.xz", "*.img.zip", "*.sha256"],
    )
    # uc2-esp32 publishes nearly everything as GitHub "pre-releases" (beta.N
    # tags are what os-rpi stable pins), so include them by default.
    firmware_source: SourceRepo = SourceRepo(
        owner="youseetoo",
        repo="uc2-esp32",
        asset_patterns=["*.bin", "firmware-index.json"],
        include_prereleases=True,
    )

    # How many past versions to keep per source when auto-pruning.
    keep_versions: int = 3
    # Periodic release check interval in minutes (0 disables).
    check_interval_min: int = 60

    # Production mode: locked UI, only latest stable, no dropdowns.
    production_mode: bool = False

    # ESP32 flashing defaults.
    esp_default_baud: int = 460800
    esp_erase_before_flash: bool = True

    host: str = "0.0.0.0"
    port: int = 8000

    # ------------------------------------------------------------------
    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def persistable(self) -> dict[str, Any]:
        """Subset of settings the UI may change and we persist to disk."""
        return {
            "github_token": self.github_token,
            "keep_versions": self.keep_versions,
            "check_interval_min": self.check_interval_min,
            "production_mode": self.production_mode,
            "esp_default_baud": self.esp_default_baud,
            "esp_erase_before_flash": self.esp_erase_before_flash,
        }

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps(self.persistable(), indent=2))


def load_settings() -> Settings:
    settings = Settings()
    persisted_file = settings.settings_file
    if persisted_file.exists():
        try:
            persisted = json.loads(persisted_file.read_text())
        except (OSError, json.JSONDecodeError):
            persisted = {}
        allowed = set(settings.persistable())
        # Env vars win: only apply persisted values for fields env didn't set.
        overrides = {
            k: v
            for k, v in persisted.items()
            if k in allowed and k not in settings.model_fields_set
        }
        if overrides:
            settings = Settings(**overrides)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = load_settings()
