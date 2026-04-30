# backend/tests/test_celery_dedup.py
"""
Unit tests for the Celery task dedup lock mechanism.

Tests the acquire/release lifecycle, verifying that:
- First execution acquires the lock (returns True)
- Duplicate execution is blocked (returns False)
- Releasing the lock allows re-acquisition (the retry fix for OPE-482)
- Empty task_id is handled gracefully
- Redis failures are surfaced as RuntimeError (fail-closed)
- DedupedTask.on_retry() releases the lock before the retry is scheduled
"""

import os
from unittest.mock import MagicMock, patch

import pytest

# These tests use a real Redis/Dragonfly connection on the dev server.
# They are safe to run in CI because they use unique key prefixes.
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://default:@cache:6379/0")


def _redis_available() -> bool:
    """Check if Redis is reachable (skips tests when running outside Docker)."""
    try:
        import redis
        client = redis.Redis.from_url(BROKER_URL, socket_timeout=2, socket_connect_timeout=2)
        client.ping()
        client.close()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_available(), reason="Redis not reachable (run inside Docker/CI)"
)

try:
    import celery as _celery_mod  # noqa: F401
    _has_celery = True
except ImportError:
    _has_celery = False

requires_celery = pytest.mark.skipif(
    not _has_celery, reason="celery not installed (run inside Docker/CI)"
)


@requires_redis
class TestAcquireReleaseCycle:
    """Test the acquire -> release -> re-acquire lifecycle (OPE-482 fix)."""

    def test_first_acquire_succeeds(self):
        """First call with a unique task_id should return True."""
        from backend.shared.python_utils.celery_dedup import (
            acquire_celery_task_dedup_lock,
            release_celery_task_dedup_lock,
        )

        task_id = "test-dedup-acquire-001"
        try:
            result = acquire_celery_task_dedup_lock(
                task_id, broker_url=BROKER_URL, ttl_seconds=10
            )
            assert result is True
        finally:
            release_celery_task_dedup_lock(task_id, broker_url=BROKER_URL)

    def test_duplicate_acquire_blocked(self):
        """Second call with the same task_id should return False (deduped)."""
        from backend.shared.python_utils.celery_dedup import (
            acquire_celery_task_dedup_lock,
            release_celery_task_dedup_lock,
        )

        task_id = "test-dedup-blocked-002"
        try:
            first = acquire_celery_task_dedup_lock(
                task_id, broker_url=BROKER_URL, ttl_seconds=10
            )
            second = acquire_celery_task_dedup_lock(
                task_id, broker_url=BROKER_URL, ttl_seconds=10
            )
            assert first is True
            assert second is False
        finally:
            release_celery_task_dedup_lock(task_id, broker_url=BROKER_URL)

    def test_release_then_reacquire(self):
        """After release, a retry should be able to acquire the lock again.

        This is the core fix for OPE-482: when a task fails and retries,
        on_retry() calls release_celery_task_dedup_lock() so the retry
        can re-acquire the lock instead of being silently skipped.
        """
        from backend.shared.python_utils.celery_dedup import (
            acquire_celery_task_dedup_lock,
            release_celery_task_dedup_lock,
        )

        task_id = "test-dedup-retry-003"
        try:
            # Simulate first execution
            first = acquire_celery_task_dedup_lock(
                task_id, broker_url=BROKER_URL, ttl_seconds=10
            )
            assert first is True

            # Simulate task failure -> on_retry releases the lock
            released = release_celery_task_dedup_lock(
                task_id, broker_url=BROKER_URL
            )
            assert released is True

            # Simulate retry execution — should succeed now
            retry = acquire_celery_task_dedup_lock(
                task_id, broker_url=BROKER_URL, ttl_seconds=10
            )
            assert retry is True
        finally:
            release_celery_task_dedup_lock(task_id, broker_url=BROKER_URL)

    def test_release_nonexistent_key(self):
        """Releasing a key that doesn't exist should return False, not raise."""
        from backend.shared.python_utils.celery_dedup import (
            release_celery_task_dedup_lock,
        )

        result = release_celery_task_dedup_lock(
            "test-dedup-nonexistent-004", broker_url=BROKER_URL
        )
        assert result is False


class TestDedupEdgeCases:
    """Edge case tests that don't require Redis or Celery."""

    def test_empty_task_id_acquire(self):
        """Empty task_id should return True (allow execution, can't dedup)."""
        from backend.shared.python_utils.celery_dedup import (
            acquire_celery_task_dedup_lock,
        )

        assert acquire_celery_task_dedup_lock("", broker_url=BROKER_URL) is True

    def test_empty_task_id_release(self):
        """Empty task_id should return False (nothing to release)."""
        from backend.shared.python_utils.celery_dedup import (
            release_celery_task_dedup_lock,
        )

        assert release_celery_task_dedup_lock("", broker_url=BROKER_URL) is False

    def test_acquire_no_broker_url_raises(self):
        """Missing broker URL should raise RuntimeError (fail-closed)."""
        from backend.shared.python_utils.celery_dedup import (
            acquire_celery_task_dedup_lock,
        )

        env = {k: v for k, v in os.environ.items() if k != "CELERY_BROKER_URL"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="broker URL"):
                acquire_celery_task_dedup_lock("test-no-url", broker_url=None)


@requires_celery
class TestDedupedTaskOnRetry:
    """Test that DedupedTask.on_retry() releases the dedup lock."""

    def test_on_retry_calls_release(self):
        """on_retry should call release_celery_task_dedup_lock with the task_id."""
        from backend.core.api.app.tasks.base_task import DedupedTask

        task = DedupedTask()
        task.name = "test.task"
        task.request = MagicMock()
        task.request.retries = 1

        with patch(
            "backend.core.api.app.tasks.base_task.release_celery_task_dedup_lock"
        ) as mock_release:
            task.on_retry(
                exc=RuntimeError("test"),
                task_id="retry-test-id-005",
                args=[],
                kwargs={},
                einfo=None,
            )
            mock_release.assert_called_once_with(
                "retry-test-id-005", broker_url=None
            )

    def test_on_retry_skipped_when_dedup_disabled(self):
        """on_retry should NOT release lock when dedup_enabled=False."""
        from backend.core.api.app.tasks.base_task import DedupedTask

        task = DedupedTask()
        task.name = "test.task"
        task.dedup_enabled = False
        task.request = MagicMock()
        task.request.retries = 0

        with patch(
            "backend.core.api.app.tasks.base_task.release_celery_task_dedup_lock"
        ) as mock_release:
            task.on_retry(
                exc=RuntimeError("test"),
                task_id="retry-disabled-006",
                args=[],
                kwargs={},
                einfo=None,
            )
            mock_release.assert_not_called()

    def test_on_retry_skipped_when_no_task_id(self):
        """on_retry should NOT release lock when task_id is None."""
        from backend.core.api.app.tasks.base_task import DedupedTask

        task = DedupedTask()
        task.name = "test.task"
        task.request = MagicMock()
        task.request.retries = 0

        with patch(
            "backend.core.api.app.tasks.base_task.release_celery_task_dedup_lock"
        ) as mock_release:
            task.on_retry(
                exc=RuntimeError("test"),
                task_id=None,
                args=[],
                kwargs={},
                einfo=None,
            )
            mock_release.assert_not_called()
