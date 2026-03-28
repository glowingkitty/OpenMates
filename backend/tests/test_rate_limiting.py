# backend/tests/test_rate_limiting.py
#
# Unit tests for the rate limiting module that enforces provider API rate limits
# using Dragonfly cache-based sliding window counters.
#
# Tests cover: provider config loading, rate limit checking (allowed/exceeded/no-config),
# the wait-for-rate-limit loop, and the RateLimitScheduledException.
#
# Architecture: docs/architecture/app_skills.md (rate limiting section)
# Run: python -m pytest backend/tests/test_rate_limiting.py -v

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from backend.apps.ai.processing.rate_limiting import (
        _get_provider_rate_limit,
        check_rate_limit,
        wait_for_rate_limit,
        RateLimitScheduledException,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_cache_service():
    """Mock CacheService with async client property."""
    mock_client = AsyncMock()
    mock_client.incr = AsyncMock(return_value=1)
    mock_client.expire = AsyncMock()

    cache = MagicMock()
    # Production code does: client = await cache_service.client
    # So .client must be an awaitable that resolves to mock_client
    cache.client = AsyncMock(return_value=mock_client)
    # Stash the client for assertion access in tests
    cache._mock_client = mock_client
    return cache


@pytest.fixture
def mock_cache_exceeded():
    """Mock CacheService where rate limit is exceeded (count > limit)."""
    mock_client = AsyncMock()
    mock_client.incr = AsyncMock(return_value=999)  # way over any limit
    mock_client.expire = AsyncMock()

    cache = MagicMock()
    cache.client = AsyncMock(return_value=mock_client)
    cache._mock_client = mock_client
    return cache


# ===========================================================================
# _get_provider_rate_limit
# ===========================================================================

class TestGetProviderRateLimit:
    def test_returns_none_when_no_config(self, monkeypatch):
        """Should return None when provider config doesn't exist."""
        mock_cm = MagicMock()
        mock_cm.get_provider_config.return_value = None
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.ConfigManager",
            lambda: mock_cm,
        )
        result = _get_provider_rate_limit("nonexistent_provider")
        assert result is None

    def test_returns_none_when_no_rate_limits_section(self, monkeypatch):
        """Should return None when provider config has no rate_limits key."""
        mock_cm = MagicMock()
        mock_cm.get_provider_config.return_value = {"name": "test", "base_url": "..."}
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.ConfigManager",
            lambda: mock_cm,
        )
        result = _get_provider_rate_limit("test_provider")
        assert result is None

    def test_returns_plan_specific_limits(self, monkeypatch):
        """Should return rate limits for the correct plan."""
        mock_cm = MagicMock()
        mock_cm.get_provider_config.return_value = {
            "rate_limits": {
                "free": {"requests_per_second": 1, "requests_per_month": 1000},
                "pro": {"requests_per_second": 15, "requests_per_month": 100000},
            }
        }
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.ConfigManager",
            lambda: mock_cm,
        )
        # Set the plan env var
        monkeypatch.setenv("TEST_PROVIDER_PLAN", "pro")
        result = _get_provider_rate_limit("test_provider")
        assert result == {"requests_per_second": 15, "requests_per_month": 100000}

    def test_defaults_to_free_plan_for_brave(self, monkeypatch):
        """Brave should default to 'free' plan when env var is not set."""
        mock_cm = MagicMock()
        mock_cm.get_provider_config.return_value = {
            "rate_limits": {
                "free": {"requests_per_second": 1},
                "pro": {"requests_per_second": 15},
            }
        }
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.ConfigManager",
            lambda: mock_cm,
        )
        monkeypatch.delenv("BRAVE_PLAN", raising=False)
        result = _get_provider_rate_limit("brave")
        assert result == {"requests_per_second": 1}

    def test_falls_back_to_direct_format(self, monkeypatch):
        """Should handle old format where rate_limits has direct keys."""
        mock_cm = MagicMock()
        mock_cm.get_provider_config.return_value = {
            "rate_limits": {"requests_per_second": 5}
        }
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.ConfigManager",
            lambda: mock_cm,
        )
        monkeypatch.delenv("TEST_PROVIDER_PLAN", raising=False)
        result = _get_provider_rate_limit("test_provider")
        assert result == {"requests_per_second": 5}

    def test_returns_none_on_exception(self, monkeypatch):
        """Should return None and not crash on ConfigManager errors."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.ConfigManager",
            lambda: (_ for _ in ()).throw(RuntimeError("Config error")),
        )
        result = _get_provider_rate_limit("broken_provider")
        assert result is None


# ===========================================================================
# check_rate_limit
# ===========================================================================

class TestCheckRateLimit:
    @pytest.mark.asyncio
    async def test_allowed_when_no_config(self, monkeypatch):
        """Should allow request when no rate limit config exists (fail open)."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting._get_provider_rate_limit",
            lambda provider_id: None,
        )
        is_allowed, retry_after = await check_rate_limit("unknown", "search")
        assert is_allowed is True
        assert retry_after is None

    @pytest.mark.asyncio
    async def test_allowed_when_unlimited(self, monkeypatch, mock_cache_service):
        """Should allow request when requests_per_second is None (unlimited)."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting._get_provider_rate_limit",
            lambda provider_id: {"requests_per_second": None},
        )
        is_allowed, retry_after = await check_rate_limit(
            "test", "search", cache_service=mock_cache_service
        )
        assert is_allowed is True
        assert retry_after is None

    @pytest.mark.asyncio
    async def test_allowed_under_limit(self, monkeypatch, mock_cache_service):
        """Should allow request when count is under the limit."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting._get_provider_rate_limit",
            lambda provider_id: {"requests_per_second": 10},
        )
        # mock_cache_service returns incr=1, which is under limit of 10
        is_allowed, retry_after = await check_rate_limit(
            "test", "search", cache_service=mock_cache_service
        )
        assert is_allowed is True
        assert retry_after is None

    @pytest.mark.asyncio
    async def test_blocked_over_limit(self, monkeypatch, mock_cache_exceeded):
        """Should block request when count exceeds the limit."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting._get_provider_rate_limit",
            lambda provider_id: {"requests_per_second": 5},
        )
        is_allowed, retry_after = await check_rate_limit(
            "test", "search", cache_service=mock_cache_exceeded
        )
        assert is_allowed is False
        assert retry_after is not None
        assert retry_after > 0

    @pytest.mark.asyncio
    async def test_cache_key_includes_model_id(self, monkeypatch, mock_cache_service):
        """Cache key should include model_id when provided."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting._get_provider_rate_limit",
            lambda provider_id: {"requests_per_second": 10},
        )
        await check_rate_limit(
            "test", "search", model_id="gpt-4", cache_service=mock_cache_service
        )
        # Verify incr was called (the key includes model_id)
        mock_cache_service._mock_client.incr.assert_called_once()
        call_args = mock_cache_service._mock_client.incr.call_args[0][0]
        assert "gpt-4" in call_args

    @pytest.mark.asyncio
    async def test_fail_open_on_exception(self, monkeypatch):
        """Should allow request on cache errors (fail open)."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting._get_provider_rate_limit",
            lambda provider_id: {"requests_per_second": 5},
        )
        # Cache service that raises
        broken_cache = AsyncMock()
        broken_cache.client = AsyncMock(side_effect=ConnectionError("Cache down"))

        is_allowed, retry_after = await check_rate_limit(
            "test", "search", cache_service=broken_cache
        )
        assert is_allowed is True
        assert retry_after is None

    @pytest.mark.asyncio
    async def test_allows_when_cache_client_is_none(self, monkeypatch):
        """Should allow request when cache client is None."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting._get_provider_rate_limit",
            lambda provider_id: {"requests_per_second": 5},
        )
        cache = AsyncMock()
        cache.client = None

        is_allowed, retry_after = await check_rate_limit(
            "test", "search", cache_service=cache
        )
        assert is_allowed is True


# ===========================================================================
# wait_for_rate_limit
# ===========================================================================

class TestWaitForRateLimit:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_allowed(self, monkeypatch):
        """Should return immediately when the first check allows the request."""
        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.check_rate_limit",
            AsyncMock(return_value=(True, None)),
        )
        # Should complete without hanging
        await asyncio.wait_for(
            wait_for_rate_limit("test", "search"),
            timeout=1.0,
        )

    @pytest.mark.asyncio
    async def test_waits_and_retries_on_short_rate_limit(self, monkeypatch):
        """Should sleep and retry when rate limited with short wait."""
        call_count = 0

        async def mock_check(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (False, 0.05)  # short wait
            return (True, None)  # allowed on retry

        monkeypatch.setattr(
            "backend.apps.ai.processing.rate_limiting.check_rate_limit",
            mock_check,
        )

        await asyncio.wait_for(
            wait_for_rate_limit("test", "search"),
            timeout=2.0,
        )
        assert call_count == 2


# ===========================================================================
# RateLimitScheduledException
# ===========================================================================

class TestRateLimitScheduledException:
    def test_attributes(self):
        exc = RateLimitScheduledException(
            task_id="task-123",
            wait_time=5.0,
            message="Scheduled via Celery",
        )
        assert exc.task_id == "task-123"
        assert exc.wait_time == 5.0
        assert str(exc) == "Scheduled via Celery"

    def test_is_exception(self):
        exc = RateLimitScheduledException(
            task_id="t", wait_time=1.0, message="test"
        )
        assert isinstance(exc, Exception)
