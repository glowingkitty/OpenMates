"""Test-account label lookups for aggregate statistics.

Temporary test accounts (users.is_test_account: AI test users, post-update check
accounts) never count in usage or growth statistics. This module has no service
imports so Directus mixins and billing can both use it without import cycles.
"""
import hashlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TEST_ACCOUNT_MEMO_PREFIX = "stats:test_account:"  # + sha256(user_id); "1" test account, "0" regular
TEST_ACCOUNT_MEMO_TTL_TRUE = 30 * 86400
TEST_ACCOUNT_MEMO_TTL_FALSE = 3600


def _test_account_memo_key(hashed_user_id: str) -> str:
    return f"{TEST_ACCOUNT_MEMO_PREFIX}{hashed_user_id}"


async def remember_test_account(cache: Any, user_id: str, is_test: bool) -> None:
    """Memoize the test-account label by hashed user id (messages only carry the hash)."""
    hashed = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    await cache.set(
        _test_account_memo_key(hashed),
        "1" if is_test else "0",
        ttl=TEST_ACCOUNT_MEMO_TTL_TRUE if is_test else TEST_ACCOUNT_MEMO_TTL_FALSE,
    )


async def is_test_account_hash(cache: Any, hashed_user_id: Optional[str]) -> bool:
    """True when a memo marks this hashed user id as test account (unknown counts as regular)."""
    if not hashed_user_id:
        return False
    return await cache.get(_test_account_memo_key(hashed_user_id)) in ("1", 1, b"1", True)


async def is_test_account_user(
    cache: Any, directus: Any, user_id: Optional[str], cached_user: Optional[Dict[str, Any]] = None
) -> bool:
    """True for temporary test accounts (users.is_test_account), which never count in usage stats.

    Order: given/cached user dict with the field, short Redis memo, then Directus. An unreadable
    label counts as a regular user (stats stay as before, nothing is hidden).
    """
    if not user_id:
        return False
    user = cached_user if cached_user is not None else await cache.get_user_by_id(user_id)
    if user and "is_test_account" in user:
        return user.get("is_test_account") is True
    hashed = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    memo = await cache.get(_test_account_memo_key(hashed))
    if memo in ("1", 1, b"1", True):
        return True
    if memo in ("0", 0, b"0", False):
        return False
    fields = await directus.get_user_fields_direct(user_id, ["is_test_account"])
    if fields is None:
        logger.warning("Test-account label unreadable for user %s; counting stats", user_id[:8])
        return False
    is_test = fields.get("is_test_account") is True
    await remember_test_account(cache, user_id, is_test)
    return is_test
