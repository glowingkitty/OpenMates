import httpx
import logging
import asyncio
import time
import uuid

logger = logging.getLogger(__name__)

# Connection-level errors that indicate CMS is temporarily unreachable.
_CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, OSError)
_ADMIN_TOKEN_CACHE_KEY = "directus_admin_token"
_ADMIN_TOKEN_LOCK_KEY = "directus_admin_token_refresh_lock"
_ADMIN_TOKEN_LOCK_TTL_SECONDS = 30
_ADMIN_TOKEN_LOCK_WAIT_SECONDS = 10
_ADMIN_TOKEN_LOCK_POLL_SECONDS = 0.25


async def _get_cached_admin_token(self):
    token = await self.cache.get(_ADMIN_TOKEN_CACHE_KEY)
    if token:
        self.admin_token = token
        self.auth_token = token
        logger.debug("Using cached admin token")
        return token
    return None


async def _acquire_admin_token_lock(self):
    client = await self.cache.client
    if not client:
        return None

    lock_value = uuid.uuid4().hex
    acquired = await client.set(
        _ADMIN_TOKEN_LOCK_KEY,
        lock_value,
        nx=True,
        ex=_ADMIN_TOKEN_LOCK_TTL_SECONDS,
    )
    return lock_value if acquired else None


async def _release_admin_token_lock(self, lock_value):
    if not lock_value:
        return

    try:
        client = await self.cache.client
        if not client:
            return
        current_value = await client.get(_ADMIN_TOKEN_LOCK_KEY)
        if isinstance(current_value, bytes):
            current_value = current_value.decode("utf-8")
        if current_value == lock_value:
            await client.delete(_ADMIN_TOKEN_LOCK_KEY)
    except Exception as exc:
        logger.warning("Failed to release Directus admin token refresh lock: %s", exc)


async def _wait_for_admin_token_refresh(self):
    deadline = time.monotonic() + _ADMIN_TOKEN_LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(_ADMIN_TOKEN_LOCK_POLL_SECONDS)
        token = await _get_cached_admin_token(self)
        if token:
            return token
    return None

async def get_auth_lock(self):
    if self._auth_lock is None:
        self._auth_lock = asyncio.Lock()
    return self._auth_lock

async def clear_tokens(self):
    self.auth_token = None
    self.admin_token = None
    await self.cache.delete(_ADMIN_TOKEN_CACHE_KEY)
    logger.info("Cleared Directus tokens from memory and cache")

async def validate_token(self, token):
    """
    Check if the token is still valid and return user data.

    Retries connection-level failures with exponential backoff so that
    a CMS restart doesn't cause all active sessions to appear invalid.

    Returns:
        Tuple[bool, Optional[Dict]]: (is_valid, user_data)
        - is_valid: True if token is valid, False otherwise
        - user_data: User data from /users/me endpoint if valid, None otherwise
    """
    if not token:
        return False, None

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/users/me",
                    headers={"Authorization": f"Bearer {token}"}
                )

                if response.status_code == 200:
                    logger.debug("Token is valid")
                    user_data = response.json().get("data", {})
                    return True, user_data
                elif response.status_code == 401:
                    logger.debug("Token is invalid or expired")
                    return False, None
                else:
                    logger.warning(f"Unexpected response checking token: {response.status_code}")
                    return False, None
        except _CONNECTION_ERRORS as e:
            if attempt < max_retries - 1:
                backoff = min(2 ** (attempt + 1), 8)
                logger.warning(f"CMS connection failed during token validation ({type(e).__name__}). "
                               f"Retrying in {backoff}s ({attempt + 1}/{max_retries})...")
                await asyncio.sleep(backoff)
            else:
                logger.error(f"Token validation failed after {max_retries} connection retries: {e}")
                return False, None
        except Exception as e:
            logger.error(f"Error validating token: {str(e)}")
            return False, None
    return False, None

async def login_admin(self):
    """Get a fresh admin token by logging in.

    Retries up to 5 times with exponential backoff for connection-level
    failures (DNS resolution, connect timeout, refused). This prevents
    transient CMS unavailability during container restarts from leaving
    the API without an auth token.
    """
    if not (self.admin_email and self.admin_password):
        logger.error("Cannot login: Admin credentials not available")
        return None

    max_retries = 5
    for attempt in range(max_retries):
        try:
            logger.debug("Logging in to Directus as admin")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/auth/login",
                    json={
                        "email": self.admin_email,
                        "password": self.admin_password
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    if 'data' in data and 'access_token' in data['data']:
                        new_token = data['data']['access_token']
                        self.admin_token = new_token
                        self.auth_token = new_token
                        await self.cache.set(_ADMIN_TOKEN_CACHE_KEY, new_token, ttl=self.token_ttl)
                        logger.debug("Successfully obtained fresh ADMIN token via login")
                        return new_token
                else:
                    logger.error(f"Admin login failed with status {response.status_code}: {response.text}")
                    return None
        except _CONNECTION_ERRORS as e:
            if attempt < max_retries - 1:
                backoff = min(2 ** (attempt + 1), 16)
                logger.warning(f"CMS connection failed during admin login ({type(e).__name__}). "
                               f"Retrying in {backoff}s ({attempt + 1}/{max_retries})...")
                await asyncio.sleep(backoff)
            else:
                logger.error(f"Admin login failed after {max_retries} connection retries: {e}")
                return None
        except Exception as e:
            logger.error(f"Admin login failed: {str(e)}")
            return None
    return None

async def ensure_auth_token(self, admin_required=False, force_refresh=False):
    """Get a valid authentication token, refreshing if necessary"""
    # Always use admin token regardless of admin_required parameter

    # Use Redis as the source of truth for token freshness. A process-local token
    # can outlive Directus' access-token TTL and trigger a refresh stampede.
    cached_token = await _get_cached_admin_token(self)
    if cached_token and not force_refresh:
        return cached_token

    # If we reach here, we need a new token
    auth_lock = await self.get_auth_lock()
    async with auth_lock:
        # Double check if another coroutine in this process got the token.
        cached_token = await _get_cached_admin_token(self)
        if cached_token:
            return cached_token

        lock_value = None
        try:
            lock_value = await _acquire_admin_token_lock(self)
            if not lock_value:
                refreshed_token = await _wait_for_admin_token_refresh(self)
                if refreshed_token:
                    return refreshed_token
                logger.warning("Timed out waiting for Directus admin token refresh lock; refreshing locally")

            # Login to get a fresh token. The distributed lock prevents all API
            # and worker processes from hitting Directus /auth/login together.
            new_token = await self.login_admin()
            if new_token:
                return new_token
        finally:
            await _release_admin_token_lock(self, lock_value)
        
        logger.error("Admin authentication failed!")
        return None
