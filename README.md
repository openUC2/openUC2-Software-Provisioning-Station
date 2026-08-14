# openUC2 Software Provisioning Station

A standalone flashing station for openUC2 microscope production: a Raspberry
Pi with a touchscreen where a technician plugs in SD cards and ESP32 boards
and flashes the correct, matching software versions — no PC, no browser
WebSerial, no internet dependency once versions are cached.

**What it does**

- ⬇ **Pre-downloads** the latest `os-rpi` SD card images (GitHub Actions
  artifacts) and `uc2-esp32` firmware releases, periodically or on demand
- 💾 **Flashes SD cards** — streams the `.img.xz` straight onto the card
  with progress, checksum verification and safe device detection
- 🔌 **Flashes ESP32 boards** — full `esptool` **erase** then **write** of
  merged binaries at offset `0x0`, selectable baud rate, per-module variants
  (standalone v2/v3/v4, CAN master, motor X/Y/Z/A, laser, LED, …)
- 🔗 Shows the **matching pair** per image: which `ghcr.io/openuc2/imswitch`
  build and which firmware-server version are baked into it
- 📚 **Version library** with disk management: keep N versions, delete old
  ones, all cached locally for offline flashing
- 🏭 **Production mode**: locked one-button screen — flashes the latest
  cached stable version, shows the version number, nothing else to get wrong
- 🧪 Hardware-test scaffolding: JSON-over-serial command endpoint
  (`/motor_act`, `/laser_act`, …) for the upcoming test-checklist feature

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for diagrams of where every
artifact comes from (ImSwitch → docker → os-rpi image; uc2-esp32 → merged
binaries → release) and how the station is put together.

## Quick start (development, macOS/Linux)

Backend:

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/uc2-provision          # serves http://localhost:8000
```

Frontend (dev server with hot reload, proxies /api to :8000):

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

Or build it once and let the backend serve it: `npm run build`, then open
http://localhost:8000.

> SD card writing needs permission to open block devices — run the backend
> with `sudo` when testing that locally.

## Station install (Raspberry Pi)

```bash
git clone https://github.com/openUC2/openUC2-Software-Provisioning-Station
cd openUC2-Software-Provisioning-Station
sudo bash scripts/install.sh --kiosk    # omit --kiosk for headless/API-only
sudo reboot
```

Then on the touchscreen: **Settings → paste a GitHub token** (fine-grained,
`actions:read` on `openUC2/os-rpi` is enough; classic `repo` scope also
works). This is required because os-rpi images are published as **CI
artifacts**, which GitHub only serves to authenticated users — firmware
releases are public and work without a token.

## Configuration

Settings live in `/var/lib/uc2-provision/settings.json` (Linux) or
`~/uc2-provision/settings.json` (dev) and are editable in the UI. Env vars
(`UC2_*`) override everything, e.g. `UC2_GITHUB_TOKEN`, `UC2_PORT`,
`UC2_PRODUCTION_MODE=1`.

| Setting | Default | Meaning |
|---|---|---|
| `github_token` | — | needed for image downloads + higher rate limits |
| `keep_versions` | 3 | versions kept per source before pruning |
| `check_interval_min` | 60 | periodic GitHub check + auto-download (0 = off) |
| `esp_default_baud` | 460800 | write baud (erase always runs at 115200) |
| `esp_erase_before_flash` | true | full chip erase before writing |
| `production_mode` | false | locked one-button UI |

## API

The UI is a thin client over a REST API — everything is scriptable:

```
GET  /api/status                     station status + disk usage
GET  /api/versions/images            available (GitHub) + cached images
GET  /api/versions/firmware          available + cached firmware releases
POST /api/versions/<cat>/<id>/download
POST /api/versions/check?auto_download=true
GET  /api/versions/firmware/<id>/variants
GET  /api/sdcard/devices             removable drives (system disks filtered)
POST /api/sdcard/flash               {device, version_id}
GET  /api/esp/ports                  USB serial ports (CP210x/CH340/… tagged)
POST /api/esp/flash                  {port, version_id, variant_id, baud, erase_first}
POST /api/esp/serial                 {port, payload} — UC2 JSON test commands
GET  /api/jobs/<id>                  progress + log (also WS /api/jobs/<id>/ws)
```

## Roadmap

- [ ] Hardware test checklists after flashing (homing, laser channels,
      "is the motor moving right?" pass/fail per unit)
- [ ] Import images from USB stick / Google Drive archive (offline seeding)
- [ ] Ship the station itself as a flashable SD image via CI (like the
      solar microscope build)

## Repo layout

```
backend/    FastAPI app (uc2_provision package)
frontend/   React + Vite touch kiosk UI
docs/       architecture + provenance diagrams
scripts/    Pi installer, systemd unit, kiosk setup
```
