"""
Background scheduler for periodic status checks and data retention cleanup.
Architecture: Single-process async loop keeps status service lightweight.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status service tests not added yet)
"""

from __future__ import annotations

import asyncio
import logging

from .checker import run_health_checks_once
from .config import get_check_interval_seconds
from .database import cleanup_old_data

logger = logging.getLogger(__name__)


async def run_scheduler(db_path: str, stop_event: asyncio.Event) -> None:
    interval_seconds = get_check_interval_seconds()
    logger.info("status scheduler started (interval=%s seconds)", interval_seconds)

    while not stop_event.is_set():
        try:
            await run_health_checks_once(db_path)
            await cleanup_old_data(db_path)
        except Exception:
            logger.exception("status scheduler iteration failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue

    logger.info("status scheduler stopped")
