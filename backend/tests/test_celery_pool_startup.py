"""Pool start-up guard for Celery prefork workers (prod outage 2026-11-14, TASK-832).

Celery SIGKILLs a pool child that does not report WORKER_UP within
``worker_proc_alive_timeout``. With Celery's 4 s default, every child of the
production AI worker was killed during its ~6-30 s init and no chat ran.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from celery import Celery
from celery.concurrency.prefork import TaskPool

from backend.core.api.app.tasks import celery_pool_startup as pool_startup

CELERY_CONFIG = Path(__file__).resolve().parents[1] / "core/api/app/tasks/celery_config.py"


def test_default_allowance_is_far_above_celery_four_second_default():
    assert Celery().conf.worker_proc_alive_timeout == 4.0
    assert pool_startup.proc_alive_timeout_seconds({}) == 60.0


def test_env_override_is_used_and_bad_values_fail_loudly():
    env = pool_startup.PROC_ALIVE_TIMEOUT_ENV
    assert pool_startup.proc_alive_timeout_seconds({env: "90"}) == 90.0
    assert pool_startup.proc_alive_timeout_seconds({env: "  "}) == 60.0
    with pytest.raises(ValueError):
        pool_startup.proc_alive_timeout_seconds({env: "0"})
    with pytest.raises(ValueError):
        pool_startup.proc_alive_timeout_seconds({env: "soon"})


def test_prefork_pool_receives_the_raised_allowance():
    """The value must reach the pool Celery actually builds, not only app.conf."""
    app = Celery("pool-startup-test")
    assert pool_startup.apply_pool_startup_settings(app, {}) == 60.0
    captured = {}

    class RecordingPool:
        """Stands in for billiard's pool; records what Celery passes to it."""

        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def apply_async(self, *args, **kwargs):
            raise AssertionError("not used")

        maintain_pool = terminate_job = grow = shrink = apply_async

    pool = TaskPool(limit=1, app=app)
    pool.Pool = RecordingPool
    pool.BlockingPool = RecordingPool
    pool.on_start()
    assert captured["proc_alive_timeout"] == 60.0


def test_pool_kill_reasons_stay_visible_after_logging_reconfiguration():
    pool_logger = logging.getLogger(pool_startup.POOL_LOGGER_NAME)
    saved = (pool_logger.disabled, pool_logger.propagate, pool_logger.level)
    try:
        pool_logger.disabled = True
        pool_logger.propagate = False
        pool_logger.setLevel(logging.CRITICAL)
        pool_startup.surface_pool_kill_reasons()
        assert pool_logger.disabled is False
        assert pool_logger.propagate is True
        assert pool_logger.isEnabledFor(logging.ERROR)
    finally:
        pool_logger.disabled, pool_logger.propagate = saved[0], saved[1]
        pool_logger.setLevel(saved[2])


def test_slow_child_init_is_reported_as_warning(caplog):
    with caplog.at_level(logging.INFO, logger=pool_startup.__name__):
        pool_startup.report_child_init_duration(2.0, 60.0)
        pool_startup.report_child_init_duration(31.0, 60.0)
    levels = [(r.levelno, "31.0s" in r.getMessage()) for r in caplog.records]
    assert (logging.INFO, False) in levels
    assert (logging.WARNING, True) in levels


def test_celery_config_wires_the_guard_into_every_worker():
    source = CELERY_CONFIG.read_text()
    assert "_pool_startup.apply_pool_startup_settings(app)" in source
    assert "signals.worker_init.connect(_pool_startup.surface_pool_kill_reasons" in source
    assert "signals.after_setup_logger.connect(_pool_startup.surface_pool_kill_reasons" in source
    assert "_pool_startup.report_child_init_duration(" in source
