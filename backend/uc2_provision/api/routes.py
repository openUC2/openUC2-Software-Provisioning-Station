"""REST + WebSocket API consumed by the kiosk frontend."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .. import __version__
from ..cache import safe_id
from ..config import settings
from ..espflash import (
    BAUD_CHOICES,
    CHIP_MAP,
    flash_firmware,
    list_serial_ports,
    send_serial_command,
)
from ..github import GitHubError
from ..hwtest import TEST_GROUPS, HardwareError
from ..imswitchconfig import ARCHIVE_NAME, ConfigError, build_options
from ..jobs import JobState, jobs
from ..oci import OCIError
from ..sdcard import list_block_devices, write_boot_files, write_image
from ..state import (
    cache,
    hardware,
    imswitch_configs,
    save_test_params,
    sync,
    test_params,
)
from ..system import SystemControlError, reboot_host, shutdown_host
from ..testparams import TestParams
from ..updater import UpdateError, repo_status, update

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Status & settings
# ---------------------------------------------------------------------------

@router.get("/status")
def status() -> dict[str, Any]:
    return {
        "app_version": __version__,
        "production_mode": settings.production_mode,
        "image_source": settings.image_source.slug,
        "firmware_source": settings.firmware_source.slug,
        "github_token_set": bool(settings.github_token),
        "baud_choices": BAUD_CHOICES,
        "esp_default_baud": settings.esp_default_baud,
        "last_check": sync.last_check or None,
        **cache.disk_stats(),
    }


@router.get("/github/status")
def github_status() -> dict[str, Any]:
    try:
        return sync.github.check_auth()
    except Exception as exc:  # noqa: BLE001 - network status is best-effort
        return {"authenticated": False, "error": str(exc)}


@router.post("/system/shutdown")
def system_shutdown() -> dict[str, Any]:
    try:
        shutdown_host()
    except SystemControlError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"shutting_down": True}


@router.post("/system/reboot")
def system_reboot() -> dict[str, Any]:
    try:
        reboot_host()
    except SystemControlError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"rebooting": True}


# ---------------------------------------------------------------------------
# Self-update
# ---------------------------------------------------------------------------

@router.get("/system/version")
def system_version(fetch: bool = False) -> dict[str, Any]:
    """Installed commit and, with fetch=true, how far behind origin it is."""
    return repo_status(fetch=fetch)


class UpdateRequest(BaseModel):
    reboot: bool = False


@router.post("/system/update")
def system_update(req: UpdateRequest) -> dict[str, Any]:
    """Pull the latest commit and restart (or reboot) the station."""
    status_info = repo_status()
    if not status_info.get("update_supported"):
        raise HTTPException(
            status_code=501,
            detail=status_info.get("error", "In-place update is not available."),
        )

    def work(job) -> None:  # noqa: ANN001
        update(job, restart=not req.reboot, reboot=req.reboot)

    try:
        job = jobs.submit(
            "update", "Update station software", work, exclusive="update"
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_dict(with_log=False)


# ---------------------------------------------------------------------------
# ImSwitch configuration presets
# ---------------------------------------------------------------------------

@router.get("/configs")
def list_configs() -> dict[str, Any]:
    index = imswitch_configs.index()
    setups = imswitch_configs.list_setups(
        settings.imswitch_setup_allowlist, settings.imswitch_show_all_setups
    )
    return {
        "setups": setups,
        "synced_at": index.get("synced_at"),
        "source": index.get("source"),
        "total_upstream": len(index.get("setups", [])),
        "show_all": settings.imswitch_show_all_setups,
        "allowlist": settings.imswitch_setup_allowlist,
        "archive_name": ARCHIVE_NAME,
    }


@router.post("/configs/sync")
def sync_configs() -> dict[str, Any]:
    try:
        index = imswitch_configs.sync()
    except ConfigError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - network failures reach the UI
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"synced_at": index["synced_at"], "count": len(index["setups"])}


@router.get("/configs/{name}/preview")
def preview_config(name: str) -> dict[str, Any]:
    """What would be written for this setup, without touching a card."""
    try:
        archive = imswitch_configs.build_archive(name)
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "setup": name,
        "archive_name": ARCHIVE_NAME,
        "archive_bytes": len(archive),
        "options": build_options(name),
        "paths": [
            "home/pi/ImSwitchConfig/config/imcontrol_options.json",
            f"home/pi/ImSwitchConfig/imcontrol_setups/{name}",
        ],
    }


class ApplyConfigRequest(BaseModel):
    device: str
    setup: str


@router.post("/configs/apply")
def apply_config(req: ApplyConfigRequest) -> dict[str, Any]:
    """Write the init-root archive onto an already-flashed card."""
    try:
        archive = imswitch_configs.build_archive(req.setup)
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def work(job) -> None:  # noqa: ANN001
        job.set_progress(0.2, "Mounting boot partition")
        write_boot_files(job, req.device, {ARCHIVE_NAME: archive})
        job.set_progress(1.0, "Config written")

    try:
        job = jobs.submit(
            "apply-config",
            f"Preload {req.setup} → {req.device}",
            work,
            meta={"device": req.device, "setup": req.setup},
            exclusive=f"sdcard:{req.device}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_dict(with_log=False)


class SettingsUpdate(BaseModel):
    github_token: str | None = None
    keep_versions: int | None = Field(default=None, ge=1, le=20)
    check_interval_min: int | None = Field(default=None, ge=0)
    production_mode: bool | None = None
    esp_default_baud: int | None = None
    esp_erase_before_flash: bool | None = None
    imswitch_setup_allowlist: list[str] | None = None
    imswitch_show_all_setups: bool | None = None


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    data = settings.persistable()
    # Never leak the token back out; report only that it's set.
    data["github_token"] = "***" if data["github_token"] else ""
    return data


@router.put("/settings")
def put_settings(update: SettingsUpdate) -> dict[str, Any]:
    changed = update.model_dump(exclude_none=True)
    if changed.get("github_token") == "***":
        changed.pop("github_token")
    for key, value in changed.items():
        setattr(settings, key, value)
    settings.save()
    return get_settings()


# ---------------------------------------------------------------------------
# Versions / cache
# ---------------------------------------------------------------------------

@router.get("/versions/images")
def versions_images(remote: bool = True) -> dict[str, Any]:
    return sync.list_images(remote=remote)


@router.get("/versions/firmware")
def versions_firmware(remote: bool = True) -> dict[str, Any]:
    return sync.list_firmware(remote=remote)


@router.get("/versions/firmware/{version_id}/variants")
def firmware_variants(version_id: str) -> list[dict[str, Any]]:
    return sync.firmware_variants(version_id)


@router.post("/versions/images/{version_id}/download")
def download_image(version_id: str) -> dict[str, Any]:
    try:
        job = sync.download_image_by_version(version_id)
    except (GitHubError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.to_dict(with_log=False)


@router.post("/versions/images/{version_id}/download-firmware")
def download_matching_firmware(version_id: str) -> dict[str, Any]:
    """Pull the firmware bundle pinned by this image's deployment files."""
    try:
        job = sync.download_firmware_for_image(version_id)
    except (GitHubError, OCIError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.to_dict(with_log=False)


@router.get("/versions/images/{version_id}/pair")
def image_pair(version_id: str) -> dict[str, Any]:
    """The ImSwitch build + firmware bundle this image pins (works before
    the image itself is downloaded)."""
    try:
        return sync.resolve_pair_for_version(version_id)
    except (GitHubError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/versions/images/{version_id}/firmware")
def matching_firmware(version_id: str) -> dict[str, Any]:
    """The firmware bundle that belongs to this image, and its variants."""
    img = cache.get("images", version_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not cached")
    match = sync.matched_firmware_for(img.meta)
    if not match:
        return {"match": None, "variants": []}
    return {"match": match, "variants": sync.firmware_variants(match["version_id"])}


@router.post("/versions/firmware/{version_id}/download")
def download_firmware(version_id: str) -> dict[str, Any]:
    try:
        job = sync.download_firmware(version_id)
    except (GitHubError, OCIError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.to_dict(with_log=False)


@router.delete("/versions/{category}/{version_id}")
def delete_version(category: Literal["images", "firmware"], version_id: str) -> dict[str, Any]:
    if not cache.delete(category, version_id):
        raise HTTPException(status_code=404, detail="Version not cached")
    return {"deleted": version_id}


@router.post("/versions/check")
def check_updates(auto_download: bool = False) -> dict[str, Any]:
    try:
        return sync.check_updates(auto_download=auto_download)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# SD card
# ---------------------------------------------------------------------------

@router.get("/sdcard/devices")
def sdcard_devices() -> list[dict[str, Any]]:
    return [d.to_dict() for d in list_block_devices()]


class SdFlashRequest(BaseModel):
    device: str
    version_id: str
    # Optional ImSwitch setup to preload via an init-root boot archive.
    setup: str | None = None


@router.post("/sdcard/flash")
def sdcard_flash(req: SdFlashRequest) -> dict[str, Any]:
    version = cache.get("images", req.version_id)
    if not version or not version.meta.get("complete"):
        raise HTTPException(status_code=404, detail="Image not cached — download it first")
    images = sorted(version.path.glob("*.img.xz")) + sorted(version.path.glob("*.img"))
    if not images:
        raise HTTPException(status_code=404, detail="No .img/.img.xz file in cached version")
    image_path = images[0]

    boot_files: dict[str, bytes] | None = None
    if req.setup:
        # Built up front so a bad/unsynced setup fails before the card is wiped.
        try:
            boot_files = {ARCHIVE_NAME: imswitch_configs.build_archive(req.setup)}
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def work(job) -> None:  # noqa: ANN001
        write_image(job, image_path, req.device, boot_files=boot_files)

    try:
        job = jobs.submit(
            "flash-sdcard",
            f"Write {image_path.name} → {req.device}",
            work,
            meta={
                "device": req.device,
                "version_id": version.version_id,
                "setup": req.setup,
            },
            exclusive=f"sdcard:{req.device}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_dict(with_log=False)


# ---------------------------------------------------------------------------
# ESP32
# ---------------------------------------------------------------------------

@router.get("/esp/ports")
def esp_ports() -> list[dict[str, Any]]:
    return [p.to_dict() for p in list_serial_ports()]


class EspFlashRequest(BaseModel):
    port: str
    version_id: str
    variant_id: str
    baud: int | None = None
    erase_first: bool | None = None


@router.post("/esp/flash")
def esp_flash(req: EspFlashRequest) -> dict[str, Any]:
    version = cache.get("firmware", req.version_id)
    if not version or not version.meta.get("complete"):
        raise HTTPException(status_code=404, detail="Firmware not cached — download it first")
    variant = next(
        (v for v in sync.firmware_variants(req.version_id) if v["id"] == req.variant_id),
        None,
    )
    if variant is None:
        raise HTTPException(status_code=404, detail=f"Unknown variant {req.variant_id}")
    firmware_path = version.path / variant["file"]
    baud = req.baud or settings.esp_default_baud
    if baud not in BAUD_CHOICES:
        raise HTTPException(status_code=400, detail=f"Baud must be one of {BAUD_CHOICES}")
    erase = settings.esp_erase_before_flash if req.erase_first is None else req.erase_first
    chip = CHIP_MAP.get(variant.get("chip_family") or "")

    def work(job) -> None:  # noqa: ANN001
        flash_firmware(
            job,
            port=req.port,
            firmware_path=firmware_path,
            chip=chip,
            baud=baud,
            erase_first=erase,
        )

    try:
        job = jobs.submit(
            "flash-esp",
            f"Flash {variant['name']} ({version.version_id}) → {req.port}",
            work,
            meta={
                "port": req.port,
                "variant": variant["id"],
                "version_id": version.version_id,
                "baud": baud,
            },
            exclusive=f"esp:{req.port}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_dict(with_log=False)


class SerialCommand(BaseModel):
    port: str
    payload: str
    baud: int = 115200
    read_seconds: float = Field(default=2.0, ge=0.1, le=30)


@router.post("/esp/serial")
def esp_serial(cmd: SerialCommand) -> dict[str, Any]:
    """Send a raw UC2 JSON command over serial (escape hatch — the test
    endpoints below are the supported path)."""
    try:
        response = send_serial_command(
            cmd.port, cmd.payload, baud=cmd.baud, read_seconds=cmd.read_seconds
        )
    except Exception as exc:  # noqa: BLE001 - surface serial errors to UI
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"response": response}


# ---------------------------------------------------------------------------
# Hardware testing (UC2-REST)
# ---------------------------------------------------------------------------

@router.get("/test/groups")
def test_groups() -> dict[str, Any]:
    """Test catalog + which of them the connected board can actually run."""
    status = hardware.status()
    caps = set(status.get("capabilities") or [])
    groups = []
    for g in TEST_GROUPS:
        entry = dict(g)
        entry["available"] = (
            not g.get("master_only") or "can" in caps
        ) if status.get("connected") else False
        groups.append(entry)
    return {"groups": groups, "connection": status}


@router.get("/test/params")
def get_test_params() -> dict[str, Any]:
    return {"values": test_params.model_dump(), "schema": test_params.schema_for_ui()}


@router.put("/test/params")
def put_test_params(update: dict[str, Any]) -> dict[str, Any]:
    """Replace the test parameter document (partial updates per group)."""
    try:
        merged = test_params.model_dump()
        for group, values in update.items():
            if group in merged and isinstance(merged[group], dict) and isinstance(values, dict):
                merged[group].update(values)
            else:
                merged[group] = values
        new_params = TestParams.model_validate(merged)
    except Exception as exc:  # noqa: BLE001 - validation feedback for the UI
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for field in new_params.model_fields:
        setattr(test_params, field, getattr(new_params, field))
    save_test_params()
    return {"values": test_params.model_dump(), "schema": test_params.schema_for_ui()}


class ConnectRequest(BaseModel):
    port: str
    baud: int | None = None


@router.post("/test/connect")
def test_connect(req: ConnectRequest) -> dict[str, Any]:
    try:
        return hardware.connect(req.port, req.baud)
    except HardwareError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/test/disconnect")
def test_disconnect() -> dict[str, Any]:
    return hardware.disconnect()


@router.get("/test/status")
def test_status() -> dict[str, Any]:
    return hardware.status()


class RunTestRequest(BaseModel):
    group: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/test/run")
def test_run(req: RunTestRequest) -> dict[str, Any]:
    try:
        return hardware.run(req.group, req.action, req.args)
    except HardwareError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - a failing command is a test result
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# Production mode helper: everything needed for one-button flashing
# ---------------------------------------------------------------------------

@router.get("/production")
def production_info() -> dict[str, Any]:
    """What the locked production screen flashes: the newest cached stable
    image, plus the firmware bundle that image pins (not merely the newest
    firmware on disk — production must ship a matching pair)."""
    complete_images = [v for v in cache.list_versions("images") if v.meta.get("complete")]
    image_v = next(
        (v for v in complete_images if v.meta.get("channel") in (None, "stable")),
        next(iter(complete_images), None),
    )

    firmware_v = None
    if image_v:
        match = sync.matched_firmware_for(image_v.meta)
        if match:
            candidate = cache.get("firmware", match["version_id"])
            if candidate and candidate.meta.get("complete"):
                firmware_v = candidate
    if firmware_v is None:
        # No image, or its bundle isn't cached — fall back to the newest
        # bundle that belongs to a microscope (ODMR is a separate product).
        firmware_v = next(
            (
                v
                for v in cache.list_versions("firmware")
                if v.meta.get("complete") and v.meta.get("source_kind") != "odmr"
            ),
            None,
        )

    return {
        "image": image_v.to_dict() if image_v else None,
        "firmware": firmware_v.to_dict() if firmware_v else None,
        "firmware_variants": (
            sync.firmware_variants(firmware_v.version_id) if firmware_v else []
        ),
        "paired": bool(
            image_v
            and firmware_v
            and (sync.matched_firmware_for(image_v.meta) or {}).get("version_id")
            == firmware_v.version_id
        ),
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@router.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [j.to_dict(with_log=False) for j in jobs.list()]


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    if not jobs.cancel(job_id):
        raise HTTPException(status_code=409, detail="Job not running")
    return {"cancelled": job_id}


@router.websocket("/jobs/{job_id}/ws")
async def job_ws(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    try:
        sent_log = 0
        while True:
            job = jobs.get(job_id)
            if job is None:
                await websocket.send_json({"error": "not found"})
                break
            payload = job.to_dict(with_log=False)
            log = list(job.log)
            payload["log_delta"] = log[sent_log:]
            sent_log = len(log)
            await websocket.send_json(payload)
            if job.state in (JobState.success, JobState.failed, JobState.cancelled):
                break
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001 - already closed
            pass
