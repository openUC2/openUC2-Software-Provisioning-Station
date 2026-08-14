"""Shared singletons wired together at import time."""

from __future__ import annotations

from .cache import ArtifactCache
from .config import settings
from .jobs import jobs
from .sync import SyncService

cache = ArtifactCache(settings.cache_dir)
sync = SyncService(settings, cache, jobs)
