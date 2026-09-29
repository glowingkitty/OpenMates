"""Remove a signup account when its first key or passkey cannot be installed."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def rollback_incomplete_signup(directus, user_id: str) -> bool:
    """Delete an account that has never completed usable credential setup."""
    if not user_id:
        return False
    try:
        deleted = await directus.delete_user(
            user_id, deletion_type="signup_rollback",
            reason="initial_credential_setup_failed",
        )
        if deleted:
            return True
    except Exception:
        logger.exception("Could not roll back incomplete signup account")
    try:
        # Fail closed if storage cannot delete the partial account immediately.
        await directus.update_user(user_id, {"status": "suspended"})
    except Exception:
        logger.exception("Could not suspend incomplete signup account")
    return False
