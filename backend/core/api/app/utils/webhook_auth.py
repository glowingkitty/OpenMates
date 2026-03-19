# backend/core/api/app/utils/webhook_auth.py
#
# Webhook key authentication for incoming webhook requests.
#
# Simpler than API key auth (no device approval workflow) but with additional
# security layers: per-key rate limiting (cache-based sliding window) and
# request deduplication (idempotency keys).
#
# Architecture: docs/architecture/webhooks.md
# Pattern mirrors: api_key_auth.py (cache-first lookup, Directus fallback)

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import Request, HTTPException, status, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

# --- Constants ---

# Webhook key prefix — distinguishes webhook keys from API keys ("sk-api-")
WEBHOOK_KEY_PREFIX = "wh-"

# Per-key rate limit: max requests within the sliding window
WEBHOOK_RATE_LIMIT_MAX_REQUESTS = 30
WEBHOOK_RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour

# Request deduplication window (seconds) — rejects replayed request IDs
WEBHOOK_IDEMPOTENCY_WINDOW_SECONDS = 300  # 5 minutes

# Cache TTL for webhook key records (seconds)
WEBHOOK_KEY_CACHE_TTL = 300  # 5 minutes (matches api_key pattern)

# Allowed permissions for incoming webhooks
ALLOWED_PERMISSIONS = {"trigger_chat"}


# --- Exceptions ---

class WebhookKeyNotFoundError(Exception):
    """Raised when webhook key is not found, invalid, or expired."""
    pass


class WebhookKeyInactiveError(Exception):
    """Raised when webhook key exists but is deactivated."""
    pass


class WebhookRateLimitError(Exception):
    """Raised when per-key rate limit is exceeded."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")


class WebhookDuplicateRequestError(Exception):
    """Raised when a duplicate request_id is detected within the idempotency window."""
    pass


class WebhookPermissionError(Exception):
    """Raised when the webhook key lacks the required permission."""
    pass


# --- Service ---

class WebhookAuthService:
    """
    Service for webhook key authentication and request validation.

    Security layers:
    1. Key format validation (wh- prefix)
    2. Key lookup: cache-first → Directus fallback (never treat cache miss as error)
    3. Expiry check
    4. Active status check
    5. Permission check (requested action must be in key's permissions list)
    6. Per-key sliding-window rate limiting (cache counter)
    7. Request deduplication (optional idempotency key)
    """

    def __init__(
        self,
        directus_service: DirectusService,
        cache_service: CacheService,
    ):
        self.directus_service = directus_service
        self.cache_service = cache_service

    @staticmethod
    def hash_webhook_key(webhook_key: str) -> str:
        """Hash a webhook key using SHA-256."""
        return hashlib.sha256(webhook_key.encode()).hexdigest()

    async def authenticate_webhook_key(
        self,
        webhook_key: str,
        required_permission: str = "trigger_chat",
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Authenticate a webhook key and return webhook metadata + user info.

        Args:
            webhook_key: The raw webhook key (starts with "wh-")
            required_permission: The permission needed for the requested action
            request_id: Optional idempotency key for deduplication

        Returns:
            Dict with: webhook_id, user_id, hashed_user_id, require_confirmation,
                       permissions, key_hash

        Raises:
            WebhookKeyNotFoundError: Key is invalid, missing, or expired
            WebhookKeyInactiveError: Key is deactivated
            WebhookRateLimitError: Per-key rate limit exceeded
            WebhookDuplicateRequestError: Duplicate request_id within window
            WebhookPermissionError: Key lacks the required permission
        """
        # --- 1. Format validation ---
        if not webhook_key or not webhook_key.startswith(WEBHOOK_KEY_PREFIX):
            raise WebhookKeyNotFoundError("Invalid webhook key format")

        # --- 2. Hash and lookup ---
        key_hash = self.hash_webhook_key(webhook_key)
        webhook_record = await self._get_webhook_record(key_hash)

        if not webhook_record:
            raise WebhookKeyNotFoundError("Webhook key not found")

        # --- 3. Active check ---
        if not webhook_record.get("is_active", True):
            raise WebhookKeyInactiveError("Webhook key is deactivated")

        # --- 4. Expiry check ---
        expires_at = webhook_record.get("expires_at")
        if expires_at:
            self._check_expiry(expires_at)

        # --- 5. Direction check (only incoming keys accepted here) ---
        direction = webhook_record.get("direction", "incoming")
        if direction != "incoming":
            raise WebhookPermissionError(
                f"Webhook key direction is '{direction}', but only 'incoming' keys are accepted"
            )

        # --- 6. Permission check ---
        permissions = webhook_record.get("permissions") or []
        if required_permission not in ALLOWED_PERMISSIONS:
            raise WebhookPermissionError(f"Unknown permission: {required_permission}")
        if required_permission not in permissions:
            raise WebhookPermissionError(
                f"Webhook key lacks the '{required_permission}' permission"
            )

        # --- 7. Per-key rate limiting ---
        await self._check_rate_limit(key_hash)

        # --- 8. Request deduplication ---
        if request_id:
            await self._check_idempotency(key_hash, request_id)

        # --- 9. Update last_used_at (fire-and-forget) ---
        await self._update_last_used(key_hash, webhook_record)

        return {
            "webhook_id": webhook_record.get("id"),
            "user_id": webhook_record.get("user_id"),
            "hashed_user_id": webhook_record.get("hashed_user_id"),
            "require_confirmation": bool(webhook_record.get("require_confirmation", False)),
            "permissions": permissions,
            "key_hash": key_hash,
        }

    # --- Internal helpers ---

    async def _get_webhook_record(self, key_hash: str) -> Optional[Dict[str, Any]]:
        """
        Look up a webhook record by key hash. Cache-first with Directus fallback.
        Never treats a cache miss as a terminal error.
        """
        cache_key = f"webhook_key_record:{key_hash}"

        # Try cache
        cached = await self.cache_service.get(cache_key)
        if cached:
            return cached

        # Directus fallback
        try:
            record = await self.directus_service.get_webhook_by_key_hash(key_hash)
            if record:
                await self.cache_service.set(cache_key, record, ttl=WEBHOOK_KEY_CACHE_TTL)
            return record
        except Exception as e:
            logger.error(f"Directus lookup failed for webhook key {key_hash[:12]}...: {e}", exc_info=True)
            return None

    def _check_expiry(self, expires_at: Any) -> None:
        """Raise WebhookKeyNotFoundError if the key has expired."""
        try:
            if isinstance(expires_at, str):
                expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            else:
                expires_dt = expires_at

            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)

            if expires_dt < datetime.now(timezone.utc):
                raise WebhookKeyNotFoundError("Webhook key has expired")
        except WebhookKeyNotFoundError:
            raise
        except Exception as e:
            logger.warning(f"Error parsing webhook key expiry: {e}")
            # Don't fail on unparseable dates — log and continue

    async def _check_rate_limit(self, key_hash: str) -> None:
        """
        Sliding-window rate limit per webhook key using cache counters.
        Raises WebhookRateLimitError if exceeded.
        """
        rate_key = f"webhook_rate:{key_hash}"
        try:
            client = await self.cache_service.client
            if not client:
                return  # If cache is down, don't block — fail open for availability

            current = await client.get(rate_key)
            count = int(current) if current else 0

            if count >= WEBHOOK_RATE_LIMIT_MAX_REQUESTS:
                ttl = await client.ttl(rate_key)
                retry_after = max(ttl, 60)
                raise WebhookRateLimitError(retry_after=retry_after)

            pipe = client.pipeline()
            pipe.incr(rate_key)
            # Set TTL only if key is new (INCR creates it with no TTL)
            if count == 0:
                pipe.expire(rate_key, WEBHOOK_RATE_LIMIT_WINDOW_SECONDS)
            await pipe.execute()
        except WebhookRateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Rate limit check failed for webhook {key_hash[:12]}...: {e}")
            # Fail open — don't block requests if cache is broken

    async def _check_idempotency(self, key_hash: str, request_id: str) -> None:
        """
        Reject duplicate request_ids within the idempotency window.
        Raises WebhookDuplicateRequestError if the same request_id was seen recently.
        """
        idem_key = f"webhook_idem:{key_hash}:{request_id}"
        try:
            client = await self.cache_service.client
            if not client:
                return  # Fail open

            existing = await client.get(idem_key)
            if existing:
                raise WebhookDuplicateRequestError()

            await client.set(idem_key, "1", ex=WEBHOOK_IDEMPOTENCY_WINDOW_SECONDS)
        except WebhookDuplicateRequestError:
            raise
        except Exception as e:
            logger.warning(f"Idempotency check failed for webhook {key_hash[:12]}...: {e}")

    async def _update_last_used(self, key_hash: str, webhook_record: Dict[str, Any]) -> None:
        """Update last_used_at timestamp (best-effort, non-blocking)."""
        try:
            last_used_at = datetime.now(timezone.utc).isoformat()
            updated = await self.directus_service.update_webhook_last_used(
                key_hash, last_used_at=last_used_at
            )
            if updated:
                webhook_record["last_used_at"] = last_used_at
                cache_key = f"webhook_key_record:{key_hash}"
                await self.cache_service.set(cache_key, webhook_record, ttl=WEBHOOK_KEY_CACHE_TTL)
        except Exception as e:
            logger.warning(f"Failed to update webhook last_used timestamp: {e}")


# --- FastAPI dependencies ---

def get_webhook_auth_service(request: Request) -> WebhookAuthService:
    """Get webhook authentication service from app state."""
    return WebhookAuthService(
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
    )


# Security scheme for OpenAPI documentation (Swagger UI)
webhook_key_scheme = HTTPBearer(
    scheme_name="Webhook Key",
    description="Enter your webhook key. Webhook keys start with 'wh-'. Use format: Bearer wh-..."
)


async def verify_webhook_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(webhook_key_scheme),
    required_permission: str = "trigger_chat",
) -> Dict[str, Any]:
    """
    FastAPI dependency to verify webhook key authentication.

    Returns webhook metadata if key is valid and authorized.
    Raises HTTPException with appropriate status code on failure.
    """
    webhook_auth_service = get_webhook_auth_service(request)
    webhook_key = credentials.credentials

    # Extract optional request_id from header (for idempotency)
    request_id = request.headers.get("X-Request-Id") or request.headers.get("Idempotency-Key")

    try:
        return await webhook_auth_service.authenticate_webhook_key(
            webhook_key=webhook_key,
            required_permission=required_permission,
            request_id=request_id,
        )
    except WebhookKeyNotFoundError as e:
        logger.warning(f"Webhook key authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired webhook key",
        )
    except WebhookKeyInactiveError as e:
        logger.warning(f"Webhook key inactive: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook key is deactivated",
        )
    except WebhookRateLimitError as e:
        logger.warning(f"Webhook rate limit exceeded: {e}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
            headers={"Retry-After": str(e.retry_after)},
        )
    except WebhookDuplicateRequestError:
        logger.info("Duplicate webhook request rejected")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate request. This request_id was already processed.",
        )
    except WebhookPermissionError as e:
        logger.warning(f"Webhook permission denied: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


# Convenience dependency for use in routes
WebhookKeyAuth = Depends(verify_webhook_key)
