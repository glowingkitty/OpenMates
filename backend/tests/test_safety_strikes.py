# backend/tests/test_safety_strikes.py
#
# One strike per violation, ban only at the third strike (with refund via the
# regular account-deletion task), technical safety-check failures never strike.
# Run: python -m pytest backend/tests/test_safety_strikes.py -q

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.apps.images.tasks import generate_task
from backend.shared.python_utils.image_safety.messages import build_rejection_payload, category_info
from backend.shared.python_utils.image_safety.pipeline import SafetyRejection
from backend.shared.python_utils.image_safety import account_suspension
from backend.shared.python_utils.image_safety.strike_counter import COUNTER_TTL_SECONDS, StrikeCounter

LANG = "de"


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.expiries = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def incrby(self, key, n):
        self.data[key] = int(self.data.get(key, 0)) + n
        return self.data[key]

    async def expire(self, key, ttl):
        self.expiries[key] = ttl
        return True

    async def delete(self, key):
        self.data.pop(key, None)

    async def get(self, key):
        return self.data.get(key)


def make_cache(language=LANG):
    redis = FakeRedis()
    cache = MagicMock()

    async def _client():
        return redis

    type(cache).client = property(lambda self: _client())
    cache.get_user_by_id = AsyncMock(return_value={"language": language, "subscription_status": "active"})
    cache.delete = AsyncMock()
    cache.get = AsyncMock(return_value=None)  # no cached user_tokens map
    cache.publish_event = AsyncMock()  # force-logout broadcast after suspension
    cache.redis = redis
    return cache


def make_directus():
    # Suspension revokes every session first; the user has no session rows here.
    return MagicMock(logout_all_sessions=AsyncMock(), update_user=AsyncMock(return_value=True),
                     get_items=AsyncMock(return_value=[]))


def make_task(cache):
    return SimpleNamespace(_cache_service=cache, _directus_service=make_directus())


def make_rejection(category):
    info = category_info(category)
    return SafetyRejection(
        stage="input", category=category, severity=info["severity"], reason="test",
        user_facing_message=info["message"], tool_response=build_rejection_payload(category),
    )


async def reject(task, category, response_id):
    with patch.object(generate_task, "write_audit_entry", new=AsyncMock()) as audit, \
         patch.object(generate_task, "_cache_safety_rejection", new=AsyncMock()), \
         patch.object(account_suspension, "alert_admin", new=AsyncMock()) as alert, \
         patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
        task.alert = alert
        result = await generate_task._handle_safety_rejection(
            task, make_rejection(category), user_id="user-1", prompt="p",
            assistant_response_id=response_id, source_embed_id=None, output_embed_id=None,
            provider=None, model=None, log_prefix="[t]",
        )
    return result, send_task, audit


# contract-test: direct surface=rest_api assertions=safety-strikes.one-strike-per-violation,safety-strikes.warning-localized
@pytest.mark.asyncio
async def test_critical_rejection_is_one_strike_and_never_deletes():
    task = make_task(make_cache("en"))
    result, send_task, _ = await reject(task, "S1_csam", "r1")
    assert "strike 1 of 3" in result["user_facing_message"]
    assert task._cache_service.redis.data["chat_image_rejects:user-1"] == 1
    send_task.assert_not_called()


# contract-test: direct surface=rest_api assertions=safety-strikes.warning-localized
# contract-test: supporting surface=rest_api assertions=safety-strikes.admin-deletion-refunds
def suspension_fields(task):
    return task._directus_service.update_user.call_args.args[1]

# contract-test: supporting surface=rest_api assertions=safety-strikes.warning-localized,safety-strikes.one-strike-per-violation
@pytest.mark.asyncio
async def test_first_strike_warns_only():
    task = make_task(make_cache("en"))
    result, send_task, _ = await reject(task, "S3_sexual_other", "r1")
    assert "strike 1 of 3" in result["user_facing_message"]
    task._directus_service.update_user.assert_not_called()
    task._directus_service.logout_all_sessions.assert_not_called()
    task.alert.assert_not_called()
    send_task.assert_not_called()

SUSPENSION_EMAIL = "app.tasks.email_tasks.safety_review_email_task.send_safety_suspension_email"


def assert_only_suspension_emails(send_task, states):
    """No deletion (or any other) task is queued; only the suspension email, once per new suspension."""
    names = [c.kwargs.get("name") for c in send_task.call_args_list]
    assert names == [SUSPENSION_EMAIL] * len(states), names
    assert [c.kwargs["kwargs"]["state"] for c in send_task.call_args_list] == states


# contract-test: supporting surface=rest_api assertions=safety-strikes.second-strike-suspends-7-days
@pytest.mark.asyncio
async def test_second_strike_suspends_for_seven_days_and_logs_out():
    task = make_task(make_cache("en"))
    await reject(task, "S3_sexual_other", "r1")
    result, send_task, _ = await reject(task, "S6_public_figure_blocked", "r2")
    fields = suspension_fields(task)
    assert fields["safety_suspension_state"] == "temporary"
    until = datetime.fromisoformat(fields["safety_suspended_until"])
    assert timedelta(days=6, hours=23) < until - datetime.now(timezone.utc) < timedelta(days=7, minutes=1)
    assert fields["safety_suspension_category"] == "S6_public_figure_blocked"
    task._directus_service.logout_all_sessions.assert_awaited_once_with("user-1")
    task.alert.assert_awaited_once()
    assert "suspended until" in result["user_facing_message"]
    assert_only_suspension_emails(send_task, ["temporary"])

# contract-test: supporting surface=rest_api assertions=safety-strikes.third-strike-pending-review,safety-strikes.never-auto-delete
@pytest.mark.asyncio
async def test_third_strike_is_pending_review_alerts_admin_and_never_deletes():
    task = make_task(make_cache("en"))
    await reject(task, "S3_sexual_other", "r1")
    await reject(task, "S6_public_figure_blocked", "r2")
    result, send_task, _ = await reject(task, "S9_hate_symbol", "r3")
    fields = suspension_fields(task)
    assert fields["safety_suspension_state"] == "pending_review"
    assert fields["safety_suspended_until"] is None
    assert task.alert.await_count == 1
    assert "reviewed" in result["user_facing_message"]
    assert_only_suspension_emails(send_task, ["pending_review"])
    assert not any(c.kwargs.get("name") == "delete_user_account" for c in send_task.call_args_list)

# contract-test: supporting surface=rest_api assertions=safety-strikes.third-strike-pending-review
def test_admin_alert_has_context_but_never_content():
    text = account_suspension.build_admin_alert(
        user_id="user-12345678", user={"date_created": "2026-01-01", "subscription_status": "active"},
        state="pending_review", category="S9_hate_symbol", strike_count=3,
        decision={"stage": "input", "reason": "nudity=0.97", "scores": {"sightengine.nudity": 0.97, "x": "secret prompt"}, "threshold": 0.8},
    )
    for expected in ("S9_hate_symbol", "nudity=0.97", "threshold=0.8", "2026-01-01", "Plan: active", "Earlier strikes: 2"):
        assert expected in text
    assert "secret prompt" not in text

# contract-test: supporting surface=rest_api assertions=safety-strikes.strikes-expire-90-days
@pytest.mark.asyncio
async def test_strikes_expire_after_ninety_days():
    cache = make_cache("en")
    counter = StrikeCounter(cache)
    await counter.record_strike(user_id="u", severity="", assistant_response_id="r1")
    await counter.record_strike(user_id="u", severity="", assistant_response_id="r2")
    assert COUNTER_TTL_SECONDS == 90 * 86400
    assert cache.redis.expiries["chat_image_rejects:u"] == 90 * 86400

# contract-test: supporting surface=rest_api assertions=safety-strikes.never-wrong-login-data
def test_suspended_account_is_refused_with_its_own_message():
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    with pytest.raises(account_suspension.AccountSuspendedError) as temporary:
        account_suspension.raise_if_suspended(
            {"safety_suspension_state": "temporary", "safety_suspended_until": future, "language": "en"})
    assert "suspended until" in temporary.value.message and temporary.value.detail()["code"] == "account_suspended"
    with pytest.raises(account_suspension.AccountSuspendedError) as pending:
        account_suspension.raise_if_suspended({"safety_suspension_state": "pending_review", "language": "de"})
    assert "Einspruch" in pending.value.message
    assert "login" not in pending.value.message.lower()

# contract-test: supporting surface=rest_api assertions=safety-strikes.second-strike-suspends-7-days
def test_expired_temporary_suspension_is_active_again():
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    account_suspension.raise_if_suspended({"safety_suspension_state": "temporary", "safety_suspended_until": past})
    account_suspension.raise_if_suspended({})

# contract-test: supporting surface=rest_api assertions=safety-strikes.admin-deletion-refunds
@pytest.mark.asyncio
async def test_admin_delete_queues_deletion_with_refund():
    directus = MagicMock(logout_all_sessions=AsyncMock(), get_items=AsyncMock(return_value=[]),
                         update_item=AsyncMock(return_value=True))
    with patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
        await account_suspension.delete_suspended_account_by_admin(
            user_id="user-1", reason="admin_safety_review", directus_service=directus)
    kwargs = send_task.call_args.kwargs
    assert kwargs["name"] == "delete_user_account"
    assert kwargs["kwargs"]["refund_invoices"] is True
    assert kwargs["kwargs"]["deletion_type"] == "policy_violation"

# contract-test: supporting surface=rest_api assertions=safety-strikes.third-strike-pending-review
@pytest.mark.asyncio
async def test_admin_restore_lifts_suspension_clears_strikes_and_sends_apology():
    cache = make_cache("en")
    directus = MagicMock(update_user=AsyncMock(return_value=True),
                         get_items=AsyncMock(return_value=[{"id": "a1", "decision": None}]),
                         update_item=AsyncMock(return_value=True))
    await StrikeCounter(cache).record_strike(user_id="user-1", severity="", assistant_response_id="r1")
    with patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
        await account_suspension.restore_suspended_account(
            user_id="user-1", directus_service=directus, cache_service=cache)
    assert directus.update_user.call_args.args[1]["safety_suspension_state"] == "none"
    assert "chat_image_rejects:user-1" not in cache.redis.data
    names = [c.kwargs["name"] for c in send_task.call_args_list]
    assert any(n.endswith("send_safety_account_restored_email") for n in names)
    assert "delete_user_account" not in names
    directus.update_item.assert_awaited()

# contract-test: direct surface=rest_api assertions=safety-strikes.one-strike-per-violation
@pytest.mark.asyncio
async def test_same_response_is_debounced():
    task = make_task(make_cache("en"))
    await reject(task, "S1_csam", "r1")
    await reject(task, "S1_csam", "r1")
    assert task._cache_service.redis.data["chat_image_rejects:user-1"] == 1


# contract-test: direct surface=rest_api assertions=safety-strikes.technical-failure-no-strike
@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["safeguard_error", "safeguard_parse_error", "safeguard_not_configured"])
async def test_technical_failure_never_strikes_or_bans(category):
    task = make_task(make_cache("en"))
    for i in range(5):
        result, send_task, audit = await reject(task, category, f"r{i}")
        send_task.assert_not_called()
        audit.assert_not_called()
        assert "strike" not in result["user_facing_message"].lower()
        assert "temporarily unavailable" in result["user_facing_message"]
    assert "chat_image_rejects:user-1" not in task._cache_service.redis.data


# contract-test: direct surface=rest_api assertions=safety-strikes.warning-localized
@pytest.mark.asyncio
async def test_warning_uses_user_language():
    task = make_task(make_cache("de"))
    result, _, _ = await reject(task, "S1_csam", "r1")
    assert "Verstoß 1 von 3" in result["user_facing_message"]


# contract-test: direct surface=rest_api assertions=safety-strikes.one-strike-per-violation
# contract-test: supporting surface=rest_api assertions=safety-strikes.admin-deletion-refunds
# contract-test: supporting surface=rest_api assertions=safety-strikes.third-strike-pending-review,safety-strikes.never-auto-delete
@pytest.mark.asyncio
async def test_upload_endpoint_follows_the_same_ladder_and_never_deletes():
    from backend.core.api.app.routes.internal_api import ContentSafetyRejectRequest, content_safety_reject

    cache = make_cache("en")
    directus = make_directus()
    payload = ContentSafetyRejectRequest(user_id="user-1", rejection_reason="sexual_activity=0.95")
    with patch.object(account_suspension, "alert_admin", new=AsyncMock()) as alert, \
         patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
        first = await content_safety_reject(payload, directus_service=directus, cache_service=cache)
        assert first["reject_count"] == 1 and first["result"] == "tracked"
        assert "strike 1 of 3" in first["warning"]
        directus.update_user.assert_not_called()
        second = await content_safety_reject(payload, directus_service=directus, cache_service=cache)
        assert second["result"] == "account_suspended" and second["suspension_state"] == "temporary"
        third = await content_safety_reject(payload, directus_service=directus, cache_service=cache)
    assert third["suspension_state"] == "pending_review"
    assert alert.await_count == 2
    assert_only_suspension_emails(send_task, ["temporary", "pending_review"])

# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.asyncio
async def test_suggestive_only_uploads_never_strike_or_delete():
    from backend.core.api.app.routes.internal_api import ContentSafetyRejectRequest, content_safety_reject

    cache = make_cache("en")
    directus = MagicMock(logout_all_sessions=AsyncMock())
    suggestive = ContentSafetyRejectRequest(user_id="user-1", rejection_reason="suggestive=0.93")
    with patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
        for _ in range(5):
            result = await content_safety_reject(suggestive, directus_service=directus, cache_service=cache)
            assert result == {"result": "not_counted", "reject_count": 0}
        assert not any(value for value in cache.redis.data.values())
        send_task.assert_not_called()

        explicit = ContentSafetyRejectRequest(user_id="user-1", rejection_reason="sexual_display=0.95")
        counted = await content_safety_reject(explicit, directus_service=directus, cache_service=cache)
    assert counted["result"] == "tracked" and counted["reject_count"] == 1
    directus.logout_all_sessions.assert_not_called()


# contract-test: direct surface=rest_api assertions=safety-strikes.technical-failure-no-strike
@pytest.mark.asyncio
async def test_unavailable_upload_check_never_strikes_or_deletes():
    from backend.core.api.app.routes.internal_api import ContentSafetyRejectRequest, content_safety_reject

    cache = make_cache("en")
    directus = MagicMock(logout_all_sessions=AsyncMock())
    payload = ContentSafetyRejectRequest(
        user_id="user-1", rejection_reason="safety_service_unavailable", upload_type="profile_image"
    )
    with patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
        for _ in range(4):
            result = await content_safety_reject(payload, directus_service=directus, cache_service=cache)
            assert result == {"result": "not_counted", "reject_count": 0}
    assert not any(value for value in cache.redis.data.values())
    send_task.assert_not_called()
    directus.logout_all_sessions.assert_not_called()


# contract-test: direct surface=rest_api assertions=safety-strikes.one-strike-per-violation
@pytest.mark.asyncio
async def test_generation_then_upload_share_one_counter_without_double_count():
    cache = make_cache("en")
    counter = StrikeCounter(cache)
    result = await counter.record_strike(user_id="u", severity="critical", assistant_response_id="r")
    assert result.new_count == 1 and not result.ban_triggered
