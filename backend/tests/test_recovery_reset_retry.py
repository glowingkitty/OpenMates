import asyncio
from datetime import datetime, timezone

from backend.core.api.app.routes.auth_routes.recovery_reset_state import (
    cancel_pending_reset_if_current,
    parse_recovery_due_at,
    retryable_reset_failure,
)


class FakeDirectus:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def update_item_if_version(self, collection, item_id, data, expected_version, **kwargs):
        self.calls.append((collection, item_id, data, expected_version, kwargs))
        return self.result

    async def get_items(self, collection, params, **kwargs):
        self.calls.append((collection, params, kwargs))
        return self.rows


# contract-test: direct surface=rest_api assertions=auth.recovery.email-delay
def test_directus_zone_less_recovery_deadline_remains_cancellable():
    for stored in ("2026-09-30T09:44:53", "2026-09-30T09:44:53Z", "2026-09-30T11:44:53+02:00"):
        due_at = parse_recovery_due_at(stored)
        assert due_at == datetime(2026, 9, 30, 9, 44, 53, tzinfo=timezone.utc)
        assert datetime(2026, 9, 29, 9, 44, 53, tzinfo=timezone.utc) < due_at


# contract-test: direct surface=rest_api assertions=auth.recovery.email-delay
def test_cancellation_confirms_persisted_state_when_directus_omits_updated_row():
    directus = FakeDirectus(None)
    directus.rows = [{"id": "reset-1", "state": "cancelled", "version": 7,
                     "cancelled_at": "2026-09-29T10:33:49.000"}]
    result = asyncio.run(cancel_pending_reset_if_current(directus, {"id": "reset-1", "version": 6}))
    assert result == directus.rows[0]
    assert directus.calls[0][2]["state"] == "cancelled"
    assert directus.calls[0][3] == 6
    assert directus.calls[0][4] == {"extra_filters": {"state": "pending"}, "admin_required": True}


# contract-test: direct surface=rest_api assertions=auth.recovery.email-delay
def test_cancellation_rejects_an_unconfirmed_state_transition():
    for state, version in (("pending", 6), ("processing", 7), ("cancelled", 8)):
        directus = FakeDirectus(None)
        directus.rows = [{"id": "reset-1", "state": state, "version": version}]
        assert asyncio.run(cancel_pending_reset_if_current(directus, {"id": "reset-1", "version": 6})) is None


# contract-test: direct surface=rest_api assertions=auth.recovery.email-delay
def test_partial_reset_failure_reopens_only_claimed_version_for_new_email_proof():
    directus = FakeDirectus({"id": "reset-1", "state": "pending", "version": 8})
    response = asyncio.run(retryable_reset_failure(
        directus, {"id": "reset-1", "version": 6},
        "Cleanup incomplete", "CLEANUP_INCOMPLETE",
    ))
    assert not response.success
    assert response.error_code == "CLEANUP_INCOMPLETE"
    assert directus.calls == [(
        "account_recovery_resets", "reset-1",
        {"state": "pending", "version": 8}, 7,
        {"extra_filters": {"state": "processing"}, "admin_required": True},
    )]


# contract-test: direct surface=rest_api assertions=auth.recovery.email-delay
def test_failed_state_release_never_reports_retryable_success():
    directus = FakeDirectus(None)
    response = asyncio.run(retryable_reset_failure(
        directus, {"id": "reset-1", "version": 6},
        "Cleanup incomplete", "CLEANUP_INCOMPLETE",
    ))
    assert not response.success
    assert response.error_code == "RECOVERY_RETRY_UNAVAILABLE"
