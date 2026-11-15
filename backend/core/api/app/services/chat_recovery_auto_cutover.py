"""Activate chat-recovery protocol epoch 1 on production servers after an update.

A production server still at epoch 0 never enqueues recovery-backed inference,
so it has no early (initial) chat title and no sealed completion jobs. After a
release the API runs this once in the background:

- epoch already 1: nothing to do (an operator pause stays untouched);
- epoch 0: wait until no legacy turn is running, pause sends only for the
  activation itself, activate through the reviewed cutover controller (drain
  gate, old-socket closure, roll-forward only) and resume sends.

Sends are never left paused by this task, and it never lowers the epoch. If
legacy work does not drain within the bound, it logs an error and the next
start retries. Development and isolated CI stacks (SERVER_ENVIRONMENT
"development") manage their epoch explicitly and are skipped.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable

from backend.core.api.app.services.chat_recovery_cutover import (
    ChatRecoveryCutoverController,
    CutoverBlockedError,
)

logger = logging.getLogger(__name__)

POLL_SECONDS = 15.0
# Running legacy records expire after 15 minutes; allow two expiry windows.
MAX_WAIT_SECONDS = 30 * 60


def auto_cutover_enabled(environment: str | None = None) -> bool:
    """Production (also the default for self-hosted servers) runs the cutover."""
    value = os.getenv("SERVER_ENVIRONMENT", "production") if environment is None else environment
    return value.strip().lower() in ("production", "prod")


async def ensure_recovery_epoch_one(
    controller: ChatRecoveryCutoverController,
    connection_manager: Any,
    *,
    poll_seconds: float = POLL_SECONDS,
    max_wait_seconds: float = MAX_WAIT_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Bring the server to epoch 1. Returns already_active, activated or timed_out."""
    deadline = clock() + max_wait_seconds
    while True:
        state = await controller.get_state(authoritative=True)
        if int(state.get("protocol_epoch", 0)) >= ChatRecoveryCutoverController.EPOCH_ONE:
            logger.info("[RecoveryCutover] protocol epoch 1 already active")
            return "already_active"
        in_flight = int(state.get("legacy_in_flight", 0))
        if in_flight == 0:
            paused_here = not state.get("sends_paused")
            if paused_here:
                await controller.set_sends_paused(True)
            try:
                await controller.activate_epoch_one(connection_manager)
                logger.info("[RecoveryCutover] activated protocol epoch 1")
                return "activated"
            except CutoverBlockedError as exc:
                logger.info("[RecoveryCutover] activation not yet possible: %s", exc)
            finally:
                if paused_here:
                    await controller.set_sends_paused(False)
        else:
            logger.info("[RecoveryCutover] waiting for %d legacy turn(s) to finish", in_flight)
        if clock() >= deadline:
            logger.error(
                "[RecoveryCutover] protocol epoch 1 not activated within %ds; "
                "early chat titles stay off until the next start",
                int(max_wait_seconds),
            )
            return "timed_out"
        await sleep(poll_seconds)


async def run_auto_cutover(cache_service: Any, directus_service: Any, connection_manager: Any) -> None:
    """Startup entry point; failures are logged, never raised into the API."""
    if not auto_cutover_enabled():
        logger.info("[RecoveryCutover] skipped outside production")
        return
    controller = ChatRecoveryCutoverController(cache_service, directus_service)
    try:
        await ensure_recovery_epoch_one(controller, connection_manager)
    except asyncio.CancelledError:
        raise
    except Exception:  # Startup task boundary: report and let the next start retry.
        logger.exception("[RecoveryCutover] automatic protocol epoch activation failed")
