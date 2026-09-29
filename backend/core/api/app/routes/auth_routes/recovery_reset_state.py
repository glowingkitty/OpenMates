"""Durable state helpers for delayed destructive account recovery."""

from datetime import datetime, timezone

from backend.core.api.app.schemas.auth_recovery import RecoveryCompleteResponse

RECOVERY_COLLECTION = "account_recovery_resets"


def parse_recovery_due_at(value: str) -> datetime:
    """Interpret Directus ``dateTime`` values as UTC, including zone-less rows.

    The schema stores these deadlines in a PostgreSQL timestamp column without
    timezone information, while all recovery deadlines are created in UTC.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


async def cancel_pending_reset_if_current(directus_service, pending: dict):
    """Confirm the state transition from durable fields after Directus writes it.

    Directus may return an empty bulk-PATCH result and reformat ``cancelled_at``
    on readback. Its generic conditional-update helper then reports no matching
    row even when the cancellation was persisted.
    """
    next_version = int(pending["version"]) + 1
    await directus_service.update_item_if_version(
        RECOVERY_COLLECTION, pending["id"],
        {"state": "cancelled", "version": next_version,
         "cancelled_at": datetime.now(timezone.utc).isoformat()},
        int(pending["version"]), extra_filters={"state": "pending"}, admin_required=True,
    )
    rows = await directus_service.get_items(
        RECOVERY_COLLECTION,
        params={"filter": {"id": {"_eq": pending["id"]}}, "limit": 1},
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    current = rows[0] if rows else None
    if current and current.get("state") == "cancelled" and int(current.get("version", -1)) == next_version:
        return current
    return None


async def retryable_reset_failure(directus_service, pending: dict, message: str, error_code: str):
    """Release a failed post-deadline attempt for a fresh verified retry."""
    version = int(pending["version"]) + 1
    reopened = await directus_service.update_item_if_version(
        RECOVERY_COLLECTION, pending["id"],
        {"state": "pending", "version": version + 1},
        version, extra_filters={"state": "processing"}, admin_required=True,
    )
    if not reopened:
        return RecoveryCompleteResponse(success=False, message="Recovery needs support to resume safely.", error_code="RECOVERY_RETRY_UNAVAILABLE")
    return RecoveryCompleteResponse(success=False, message=message, error_code=error_code)
