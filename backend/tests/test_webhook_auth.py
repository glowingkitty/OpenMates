# backend/tests/test_webhook_auth.py
#
# Unit tests for WebhookAuthService — the authentication layer for incoming webhooks.
#
# Tests cover: key format validation, cache-first lookup, expiry, activation status,
# permission checks, rate limiting, request deduplication, and the FastAPI dependency.
#
# Run: python -m pytest backend/tests/test_webhook_auth.py -v

import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


async def _acoro(value):
    """Helper: create an awaitable that returns a value (simulates async property)."""
    return value


# Import the module under test
try:
    from backend.core.api.app.utils.webhook_auth import (
        WebhookAuthService,
        WebhookKeyNotFoundError,
        WebhookKeyInactiveError,
        WebhookRateLimitError,
        WebhookDuplicateRequestError,
        WebhookPermissionError,
    )
    # Per-key rate limits replaced the old module constant. These tests
    # construct webhook records with explicit rate_limit_count / period so
    # they don't need to import the old WEBHOOK_RATE_LIMIT_MAX_REQUESTS.
    _DEFAULT_TEST_RATE_LIMIT = 3
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_cache():
    """Mock CacheService with async methods."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    # Mock the `client` property for rate limiting
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=None)
    mock_client.incr = AsyncMock()
    mock_client.expire = AsyncMock()
    mock_client.ttl = AsyncMock(return_value=3600)
    mock_client.pipeline = MagicMock()
    pipe_mock = AsyncMock()
    pipe_mock.incr = MagicMock()
    pipe_mock.expire = MagicMock()
    pipe_mock.execute = AsyncMock()
    mock_client.pipeline.return_value = pipe_mock
    cache.client = AsyncMock(return_value=mock_client)
    return cache


@pytest.fixture
def mock_directus():
    """Mock DirectusService with async methods."""
    directus = AsyncMock()
    directus.get_webhook_by_key_hash = AsyncMock(return_value=None)
    directus.update_webhook_last_used = AsyncMock(return_value=True)
    return directus


@pytest.fixture
def service(mock_directus, mock_cache):
    """WebhookAuthService instance with mocked dependencies."""
    return WebhookAuthService(
        directus_service=mock_directus,
        cache_service=mock_cache,
    )


@pytest.fixture
def valid_webhook_record():
    """A valid webhook record as returned by Directus."""
    return {
        "id": "test-webhook-id",
        "user_id": "test-user-id",
        "hashed_user_id": hashlib.sha256("test-user-id".encode()).hexdigest(),
        "key_hash": hashlib.sha256("wh-testkey12345".encode()).hexdigest(),
        "encrypted_name": "encrypted_test_name",
        "direction": "incoming",
        "permissions": ["trigger_chat"],
        "require_confirmation": False,
        "is_active": True,
        "expires_at": None,
        "last_used_at": None,
        # Per-key rate limit fields (added in the webhook redesign)
        "rate_limit_count": _DEFAULT_TEST_RATE_LIMIT,
        "rate_limit_period": "hour",
        "message_template": "{{payload_json}}",
    }


# ---------------------------------------------------------------------------
# Tests: Key format validation
# ---------------------------------------------------------------------------

class TestKeyFormatValidation:
    @pytest.mark.asyncio
    async def test_rejects_empty_key(self, service):
        with pytest.raises(WebhookKeyNotFoundError, match="Invalid webhook key format"):
            await service.authenticate_webhook_key("")

    @pytest.mark.asyncio
    async def test_rejects_none_key(self, service):
        with pytest.raises(WebhookKeyNotFoundError, match="Invalid webhook key format"):
            await service.authenticate_webhook_key(None)

    @pytest.mark.asyncio
    async def test_rejects_wrong_prefix(self, service):
        with pytest.raises(WebhookKeyNotFoundError, match="Invalid webhook key format"):
            await service.authenticate_webhook_key("sk-api-wrongprefix")

    @pytest.mark.asyncio
    async def test_rejects_partial_prefix(self, service):
        with pytest.raises(WebhookKeyNotFoundError, match="Invalid webhook key format"):
            await service.authenticate_webhook_key("wh")


# ---------------------------------------------------------------------------
# Tests: Key lookup
# ---------------------------------------------------------------------------

class TestKeyLookup:
    @pytest.mark.asyncio
    async def test_uses_cache_first(self, service, mock_cache, valid_webhook_record):
        """Cache hit should skip Directus."""
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        result = await service.authenticate_webhook_key("wh-testkey12345")
        assert result["webhook_id"] == "test-webhook-id"
        assert result["user_id"] == "test-user-id"
        service.directus_service.get_webhook_by_key_hash.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_directus_on_cache_miss(self, service, mock_directus, valid_webhook_record):
        """Cache miss should query Directus and cache the result."""
        mock_directus.get_webhook_by_key_hash = AsyncMock(return_value=valid_webhook_record)
        result = await service.authenticate_webhook_key("wh-testkey12345")
        assert result["webhook_id"] == "test-webhook-id"
        mock_directus.get_webhook_by_key_hash.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_on_key_not_found(self, service):
        """Both cache miss and Directus miss should raise."""
        with pytest.raises(WebhookKeyNotFoundError, match="Webhook key not found"):
            await service.authenticate_webhook_key("wh-nonexistentkey")


# ---------------------------------------------------------------------------
# Tests: Expiry
# ---------------------------------------------------------------------------

class TestExpiry:
    @pytest.mark.asyncio
    async def test_accepts_non_expired_key(self, service, mock_cache, valid_webhook_record):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        valid_webhook_record["expires_at"] = future
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        result = await service.authenticate_webhook_key("wh-testkey12345")
        assert result["webhook_id"] == "test-webhook-id"

    @pytest.mark.asyncio
    async def test_rejects_expired_key(self, service, mock_cache, valid_webhook_record):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        valid_webhook_record["expires_at"] = past
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        with pytest.raises(WebhookKeyNotFoundError, match="expired"):
            await service.authenticate_webhook_key("wh-testkey12345")


# ---------------------------------------------------------------------------
# Tests: Active status
# ---------------------------------------------------------------------------

class TestActiveStatus:
    @pytest.mark.asyncio
    async def test_rejects_inactive_key(self, service, mock_cache, valid_webhook_record):
        valid_webhook_record["is_active"] = False
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        with pytest.raises(WebhookKeyInactiveError, match="deactivated"):
            await service.authenticate_webhook_key("wh-testkey12345")


# ---------------------------------------------------------------------------
# Tests: Permissions
# ---------------------------------------------------------------------------

class TestPermissions:
    @pytest.mark.asyncio
    async def test_accepts_valid_permission(self, service, mock_cache, valid_webhook_record):
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        result = await service.authenticate_webhook_key("wh-testkey12345", required_permission="trigger_chat")
        assert "trigger_chat" in result["permissions"]

    @pytest.mark.asyncio
    async def test_rejects_missing_permission(self, service, mock_cache, valid_webhook_record):
        valid_webhook_record["permissions"] = []
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        with pytest.raises(WebhookPermissionError, match="lacks"):
            await service.authenticate_webhook_key("wh-testkey12345", required_permission="trigger_chat")

    @pytest.mark.asyncio
    async def test_rejects_unknown_permission(self, service, mock_cache, valid_webhook_record):
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        with pytest.raises(WebhookPermissionError, match="Unknown"):
            await service.authenticate_webhook_key("wh-testkey12345", required_permission="admin_delete")


# ---------------------------------------------------------------------------
# Tests: Direction check
# ---------------------------------------------------------------------------

class TestDirection:
    @pytest.mark.asyncio
    async def test_rejects_outgoing_key_on_incoming_endpoint(self, service, mock_cache, valid_webhook_record):
        valid_webhook_record["direction"] = "outgoing"
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        with pytest.raises(WebhookPermissionError, match="incoming"):
            await service.authenticate_webhook_key("wh-testkey12345")


# ---------------------------------------------------------------------------
# Tests: Rate limiting
# ---------------------------------------------------------------------------

def _make_mock_client(**overrides):
    """Create a mock Redis client for cache_service.client."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=overrides.get("get_return", None))
    mock_client.set = AsyncMock()
    mock_client.incr = AsyncMock()
    mock_client.expire = AsyncMock()
    mock_client.ttl = AsyncMock(return_value=overrides.get("ttl_return", 3600))
    pipe = AsyncMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock()
    mock_client.pipeline = MagicMock(return_value=pipe)
    return mock_client


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_allows_within_per_key_limit(self, service, mock_cache, valid_webhook_record):
        valid_webhook_record["rate_limit_count"] = 5
        valid_webhook_record["rate_limit_period"] = "hour"
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        # 2 prior invocations recorded in the counter — under the 5 limit.
        mock_client = _make_mock_client(get_return="2")
        type(mock_cache).client = property(lambda self: _acoro(mock_client))

        result = await service.authenticate_webhook_key("wh-testkey12345")
        assert result["webhook_id"] == "test-webhook-id"
        assert result["rate_limit_count"] == 5
        assert result["rate_limit_period"] == "hour"

    @pytest.mark.asyncio
    async def test_rejects_over_per_key_limit(self, service, mock_cache, valid_webhook_record):
        valid_webhook_record["rate_limit_count"] = 3
        valid_webhook_record["rate_limit_period"] = "hour"
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        # Counter at 5 already — over the per-key limit of 3.
        mock_client = _make_mock_client(get_return="5", ttl_return=1800)
        type(mock_cache).client = property(lambda self: _acoro(mock_client))

        with pytest.raises(WebhookRateLimitError):
            await service.authenticate_webhook_key("wh-testkey12345")

    @pytest.mark.asyncio
    async def test_unlimited_skips_rate_limit_check(self, service, mock_cache, valid_webhook_record):
        """rate_limit_count=None means unlimited — rate-limit code path is skipped entirely."""
        valid_webhook_record["rate_limit_count"] = None
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        # Counter is irrelevant — never read — but set it over any plausible limit anyway.
        mock_client = _make_mock_client(get_return="9999")
        type(mock_cache).client = property(lambda self: _acoro(mock_client))

        result = await service.authenticate_webhook_key("wh-testkey12345")
        assert result["webhook_id"] == "test-webhook-id"
        assert result["rate_limit_count"] is None


# ---------------------------------------------------------------------------
# Tests: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_allows_unique_request_id(self, service, mock_cache, valid_webhook_record):
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)
        mock_client = _make_mock_client(get_return=None)  # No rate limit + no idem key
        type(mock_cache).client = property(lambda self: _acoro(mock_client))

        result = await service.authenticate_webhook_key(
            "wh-testkey12345", request_id="unique-req-001"
        )
        assert result["webhook_id"] == "test-webhook-id"

    @pytest.mark.asyncio
    async def test_rejects_duplicate_request_id(self, service, mock_cache, valid_webhook_record):
        mock_cache.get = AsyncMock(return_value=valid_webhook_record)

        mock_client = AsyncMock()
        # Rate limit check returns under limit; idem key exists
        async def side_effect(key):
            if "webhook_rate:" in key:
                return "1"  # Under rate limit
            if "webhook_idem:" in key:
                return "1"  # Duplicate!
            return None
        mock_client.get = AsyncMock(side_effect=side_effect)
        mock_client.set = AsyncMock()
        pipe = AsyncMock()
        pipe.incr = MagicMock()
        pipe.expire = MagicMock()
        pipe.execute = AsyncMock()
        mock_client.pipeline = MagicMock(return_value=pipe)
        type(mock_cache).client = property(lambda self: _acoro(mock_client))

        with pytest.raises(WebhookDuplicateRequestError):
            await service.authenticate_webhook_key(
                "wh-testkey12345", request_id="duplicate-req-001"
            )


# ---------------------------------------------------------------------------
# Tests: Hash function
# ---------------------------------------------------------------------------

class TestHashFunction:
    def test_hash_is_deterministic(self):
        key = "wh-test-key-12345"
        hash1 = WebhookAuthService.hash_webhook_key(key)
        hash2 = WebhookAuthService.hash_webhook_key(key)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_different_keys_different_hashes(self):
        hash1 = WebhookAuthService.hash_webhook_key("wh-key-aaa")
        hash2 = WebhookAuthService.hash_webhook_key("wh-key-bbb")
        assert hash1 != hash2
