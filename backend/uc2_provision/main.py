"""FastAPI application entrypoint.

Serves the REST/WebSocket API and, when a built frontend exists
(frontend/dist), the kiosk UI itself.  A background task periodically checks
GitHub for new image/firmware versions and pre-downloads them.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import settings

log = logging.getLogger("uc2-provision")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


async def periodic_check() -> None:
    from .state import sync

    # Give the server a moment to come up before the first check.
    await asyncio.sleep(15)
    while True:
        interval = settings.check_interval_min
        if interval <= 0:
            await asyncio.sleep(60)
            continue
        try:
            result = await asyncio.to_thread(sync.check_updates, True)
            log.info("Periodic update check: image up-to-date=%s firmware up-to-date=%s",
                     (result.get("images") or {}).get("up_to_date"),
                     (result.get("firmware") or {}).get("up_to_date"))
        except Exception as exc:  # noqa: BLE001 - never kill the loop
            log.warning("Periodic update check failed: %s", exc)
        await asyncio.sleep(interval * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(periodic_check())
    yield
    task.cancel()


app = FastAPI(title="openUC2 Provisioning Station", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # kiosk-local usage; dev server runs on another port
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "uc2_provision.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
