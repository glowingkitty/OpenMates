# backend/tests/test_safety_appeals.py
#
# Appeal token, appeal rules (1,000 chars, consent, window), admin routes (non-admin 403),
# the 48h reminder, the 14-day auto-restore and the retention purge.
# Run: python -m pytest backend/tests/test_safety_appeals.py -q

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.core.api.app.routes import admin_safety_reviews, safety_appeals
from backend.shared.python_utils.image_safety import safety_review
from backend.shared.python_utils.image_safety.account_suspension import AccountSuspendedError, suspend_account_for_strikes

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-secret")


def directus(appeals=None, users=None):
    d = MagicMock()
    d.get_items = AsyncMock(side_effect=lambda collection, **kw: (appeals if collection == "safety_appeals" else users) or [])
    d.create_item = AsyncMock(return_value=(True, {}))
    d.update_item = AsyncMock(return_value=True)
    d.update_user = AsyncMock(return_value=True)
    d.delete_item = AsyncMock(return_value=True)
    return d


def suspended(days_ago=1, state="pending_review"):
    return {"id": "u1", "safety_suspension_state": state,
            "safety_suspension_started_at": (NOW - timedelta(days=days_ago)).isoformat(),
            "safety_suspension_category": "S3_sexual_other"}


# contract-test: supporting surface=rest_api assertions=safety-strikes.appeal-consented-review
def test_token_is_bound_to_one_account_and_expires():
    token = safety_review.create_appeal_token("u1")
    assert safety_review.verify_appeal_token(token) == "u1"
    with pytest.raises(safety_review.AppealError):
        safety_review.verify_appeal_token(token.replace("u1:", "u2:", 1))
    with pytest.raises(safety_review.AppealError):
        safety_review.verify_appeal_token(token, now=NOW.timestamp() + 7200)


# contract-test: supporting surface=rest_api assertions=safety-strikes.appeal-consented-review
def test_suspension_error_detail_carries_appeal_token():
    detail = AccountSuspendedError("pending_review", None, "m", user_id="u1", category="c").detail()
    assert safety_review.verify_appeal_token(detail["appeal_token"]) == "u1"


# contract-test: supporting surface=rest_api assertions=safety-strikes.appeal-consented-review
@pytest.mark.asyncio
async def test_appeal_rules():
    d = directus()
    with pytest.raises(safety_review.AppealError) as e:
        await safety_review.submit_appeal(directus_service=d, user=suspended(), explanation="x" * 1001,
                                          consent_share_requests=True, flagged_requests=None, attachment_data_url=None)
    assert e.value.status_code == 422
    with pytest.raises(safety_review.AppealError):  # request text without consent
        await safety_review.submit_appeal(directus_service=d, user=suspended(), explanation="ok",
                                          consent_share_requests=False, flagged_requests=["a"], attachment_data_url=None)
    with pytest.raises(safety_review.AppealError):  # window over
        await safety_review.submit_appeal(directus_service=d, user=suspended(days_ago=15), explanation="ok",
                                          consent_share_requests=True, flagged_requests=None, attachment_data_url=None)
    result = await safety_review.submit_appeal(directus_service=d, user=suspended(), explanation="ok",
                                               consent_share_requests=True, flagged_requests=["a"], attachment_data_url=None)
    assert result["status"] == "open"
    assert d.create_item.await_args.args[1]["flagged_requests"] == ["a"]


def appeal_client(user):
    app = FastAPI()
    app.include_router(safety_appeals.router)
    d = directus()
    d.get_user_profile = AsyncMock(return_value=(True, user, None))
    app.dependency_overrides[safety_appeals.get_directus_service] = lambda: d
    return TestClient(app), d


# contract-test: supporting surface=rest_api assertions=safety-strikes.appeal-consented-review
def test_appeal_route_auth_and_consent():
    client, _ = appeal_client(suspended())
    assert client.post("/v1/safety/appeal", json={}).status_code == 401
    headers = {"Authorization": f"Bearer {safety_review.create_appeal_token('u1')}"}
    assert client.post("/v1/safety/appeal", headers=headers,
                       json={"explanation": "x" * 1001, "consent_share_requests": True}).status_code == 422
    assert client.post("/v1/safety/appeal", headers=headers,
                       json={"explanation": "ok", "flagged_requests": ["a"], "consent_share_requests": False}).status_code == 422
    assert client.post("/v1/safety/appeal", headers=headers,
                       json={"explanation": "ok", "consent_share_requests": True}).status_code == 200


# contract-test: supporting surface=rest_api assertions=safety-strikes.appeal-consented-review
def test_appeal_token_of_other_account_reads_only_own_case():
    client, _ = appeal_client(suspended())
    headers = {"Authorization": f"Bearer {safety_review.create_appeal_token('u1')}"}
    body = client.get("/v1/safety/appeal", headers=headers).json()
    assert body["suspended"] is True and body["category"] == "S3_sexual_other"


# contract-test: supporting surface=rest_api assertions=safety-strikes.appeal-consented-review
def test_admin_routes_reject_non_admin():
    app = FastAPI()
    app.include_router(admin_safety_reviews.router)
    async def not_admin():
        raise HTTPException(status_code=403, detail="Admin privileges required")
    app.dependency_overrides[admin_safety_reviews.require_admin] = not_admin
    client = TestClient(app)
    assert client.get("/v1/admin/safety-reviews").status_code == 403
    assert client.post("/v1/admin/safety-reviews/u1/ask", json={"question": "q"}).status_code == 403
    assert client.post("/v1/admin/safety-reviews/u1/restore").status_code == 403


# contract-test: supporting surface=rest_api assertions=safety-strikes.review-deadlines-retention
@pytest.mark.asyncio
async def test_reminder_after_48_hours_once():
    d = directus(users=[suspended(days_ago=3)])
    alert = AsyncMock()
    with patch("backend.shared.python_utils.image_safety.account_suspension.list_pending_reviews", AsyncMock(return_value=[{**suspended(3), "id": "u1"}])):
        assert await safety_review.remind_stale_reviews(d, alert) == 1
        fresh = {**suspended(3), "safety_review_reminded_at": NOW.isoformat()}
        with patch("backend.shared.python_utils.image_safety.account_suspension.list_pending_reviews", AsyncMock(return_value=[{**fresh, "id": "u1"}])):
            assert await safety_review.remind_stale_reviews(d, alert) == 0


# contract-test: supporting surface=rest_api assertions=safety-strikes.review-deadlines-retention
@pytest.mark.asyncio
async def test_auto_restore_after_14_days_without_appeal():
    restore = AsyncMock()
    old, recent = {**suspended(15), "id": "old"}, {**suspended(5), "id": "recent"}
    with patch("backend.shared.python_utils.image_safety.account_suspension.list_pending_reviews", AsyncMock(return_value=[old, recent])), \
         patch("backend.shared.python_utils.image_safety.account_suspension.restore_suspended_account", restore):
        assert await safety_review.auto_restore_unappealed(directus(), MagicMock()) == 1
    assert restore.await_args.kwargs["user_id"] == "old"
    appealed = directus(appeals=[{"id": "a", "status": "open"}])
    with patch("backend.shared.python_utils.image_safety.account_suspension.list_pending_reviews", AsyncMock(return_value=[old])), \
         patch("backend.shared.python_utils.image_safety.account_suspension.restore_suspended_account", restore):
        assert await safety_review.auto_restore_unappealed(appealed, MagicMock()) == 0


# contract-test: supporting surface=rest_api assertions=safety-strikes.review-deadlines-retention
@pytest.mark.asyncio
async def test_retention_purge_clears_closed_records():
    d = directus(appeals=[{"id": "a1"}], users=[{"id": "u1"}])
    assert await safety_review.purge_closed_cases(d) == {"appeals": 1, "cases": 1}
    d.delete_item.assert_awaited_once()
    assert d.update_user.await_args.args[1]["safety_decision"] is None


# contract-test: supporting surface=rest_api assertions=safety-strikes.review-deadlines-retention
@pytest.mark.asyncio
async def test_suspension_queues_email_and_stores_flagged_ids():
    d = directus()
    d.logout_all_sessions = AsyncMock()
    cache = MagicMock()
    cache.delete = AsyncMock()
    cache.get_user_by_id = AsyncMock(return_value={})
    celery = MagicMock()
    with patch("backend.core.api.app.tasks.celery_config.app", celery), \
         patch("backend.shared.python_utils.image_safety.account_suspension.end_all_sessions", AsyncMock()), \
         patch("backend.shared.python_utils.image_safety.account_suspension.alert_admin", AsyncMock()):
        await suspend_account_for_strikes(user_id="u1", strike_count=3, category="c", directus_service=d,
                                          cache_service=cache, flagged_message_ids=["m1"])
    assert d.update_user.await_args.args[1]["safety_flagged_message_ids"] == ["m1"]
    assert any("send_safety_suspension_email" in c.kwargs["name"] for c in celery.send_task.call_args_list)


# contract-test: supporting surface=rest_api assertions=safety-strikes.second-strike-suspends-7-days
@pytest.mark.asyncio
async def test_suspension_signs_the_account_out_everywhere():
    """Strike 2 revokes OpenMates sessions and pushes force_logout to open clients."""
    d = directus()
    d.logout_all_sessions = AsyncMock(return_value=(True, ""))
    cache = MagicMock()
    cache.delete = AsyncMock()
    cache.get_user_by_id = AsyncMock(return_value={})
    revoke = AsyncMock(return_value=2)
    broadcast = AsyncMock()
    with patch("backend.core.api.app.tasks.celery_config.app", MagicMock()), \
         patch("backend.core.api.app.services.session_security_state.revoke_all_user_sessions", revoke), \
         patch("backend.core.api.app.routes.auth_routes.auth_sessions._broadcast_force_logout", broadcast), \
         patch("backend.shared.python_utils.image_safety.account_suspension.alert_admin", AsyncMock()):
        result = await suspend_account_for_strikes(user_id="u1", strike_count=2, category="disinformation",
                                                   directus_service=d, cache_service=cache)
    assert result["state"] == "temporary"
    revoke.assert_awaited_once_with(d, cache, "u1")
    d.logout_all_sessions.assert_awaited_once_with("u1")
    broadcast.assert_awaited_once_with(cache, "u1", "account_suspended")


# contract-test: supporting surface=rest_api assertions=safety-strikes.review-deadlines-retention
def test_pending_review_listing_requests_only_service_readable_user_fields():
    """The service role gets a Directus 403 for directus_users.date_created; the
    reminder/auto-restore beat and the admin list must not request it."""
    import asyncio
    from backend.shared.python_utils.image_safety.account_suspension import list_pending_reviews

    d = directus(users=[{"id": "u1", "signup_started_at": "2026-01-02T00:00:00+00:00"}])
    asyncio.run(list_pending_reviews(d))
    fields = d.get_items.await_args.kwargs["params"]["fields"].split(",")
    assert "date_created" not in fields and "signup_started_at" in fields
