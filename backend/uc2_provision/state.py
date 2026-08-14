"""Shared singletons wired together at import time."""

from __future__ import annotations

from .cache import ArtifactCache
from .config import settings
from .hwtest import HardwareManager
from .jobs import jobs
from .sync import SyncService
from .testparams import TestParams

cache = ArtifactCache(settings.cache_dir)
sync = SyncService(settings, cache, jobs)

test_params_file = settings.data_dir / "test_params.json"
test_params = TestParams.load(test_params_file)


def save_test_params() -> None:
    test_params.save(test_params_file)


hardware = HardwareManager(lambda: test_params)
