"""Celery prefork pool start-up guard.

Celery's parent process SIGKILLs a pool child that does not report WORKER_UP
within ``worker_proc_alive_timeout`` (Celery default: 4 s). Our children run
``worker_process_init`` (skill registry, memories, AI client pre-warm) before
they report up, and on a busy host that takes far longer than 4 s. On
2026-11-14 every child of app-ai-worker, core-worker and task-worker was killed
before it took a task; the respawns kept the CPU saturated, so the loop fed
itself and no AI chat ran for ~20 h (TASK-832). This module:

- sets a start-up allowance that fits our init (default 60 s, env override
  ``CELERY_WORKER_PROC_ALIVE_TIMEOUT``),
- keeps Celery's own "Timed out waiting for UP message" error visible, which
  was silently lost, so a kill always carries its reason,
- logs how long a child's init took against that allowance, so a slow start is
  visible before it turns into a kill loop.

Tests: backend/tests/test_celery_pool_startup.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

DEFAULT_PROC_ALIVE_TIMEOUT_SECONDS = 60.0
PROC_ALIVE_TIMEOUT_ENV = "CELERY_WORKER_PROC_ALIVE_TIMEOUT"
# A child whose init uses more than this share of the allowance is logged as a
# warning: it is close to being killed.
SLOW_INIT_WARNING_FRACTION = 0.5
POOL_LOGGER_NAME = "celery.concurrency.asynpool"

logger = logging.getLogger(__name__)


def proc_alive_timeout_seconds(environ: dict[str, str] | None = None) -> float:
    """Return the pool child start-up allowance in seconds.

    Raises ValueError for a non-numeric or non-positive override, so a bad
    setting fails the worker start instead of silently re-enabling 4 s.
    """
    env = os.environ if environ is None else environ
    raw = env.get(PROC_ALIVE_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_PROC_ALIVE_TIMEOUT_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{PROC_ALIVE_TIMEOUT_ENV} must be positive, got {raw!r}")
    return value


def apply_pool_startup_settings(app: Any, environ: dict[str, str] | None = None) -> float:
    """Set ``worker_proc_alive_timeout`` on the Celery app and return it."""
    timeout = proc_alive_timeout_seconds(environ)
    app.conf.worker_proc_alive_timeout = timeout
    return timeout


def surface_pool_kill_reasons(**_kwargs: Any) -> None:
    """Keep Celery's pool errors (e.g. 'Timed out waiting for UP message') visible.

    Connected to ``worker_init`` and ``after_setup_logger``: Celery's logging
    set-up runs after our module-level logging config, and on production the
    asynpool error never reached the logs while its SIGKILL did.
    """
    pool_logger = logging.getLogger(POOL_LOGGER_NAME)
    pool_logger.disabled = False
    pool_logger.propagate = True
    if pool_logger.level == logging.NOTSET or pool_logger.level > logging.INFO:
        pool_logger.setLevel(logging.INFO)


def report_child_init_duration(elapsed_seconds: float, timeout_seconds: float) -> None:
    """Log a pool child's init time; warn when it nears the start-up allowance."""
    message = (
        f"[POOL] Worker child init took {elapsed_seconds:.1f}s "
        f"(start-up allowance {timeout_seconds:.0f}s)"
    )
    if elapsed_seconds >= timeout_seconds * SLOW_INIT_WARNING_FRACTION:
        logger.warning(message + " - close to the allowance; a busy host may get children killed")
    else:
        logger.info(message)
