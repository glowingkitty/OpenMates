# backend/tests/test_safety_strikes.py
#
# One strike per violation, ban only at the third strike (with refund via the
# regular account-deletion task), technical safety-check failures never strike.
# Run: python -m pytest backend/tests/test_safety_strikes.py -q

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.apps.images.tasks import generate_task
from backend.shared.python_utils.image_safety.messages import build_rejection_payload, category_info
from backend.shared.python_utils.image_safety.pipeline import SafetyRejection
from backend.shared.python_utils.image_safety.strike_counter import StrikeCounter

LANG = "de"


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def incrby(self, key, n):
        self.data[key] = int(self.data.get(key, 0)) + n
        return self.data[key]

    async def expire(self, key, ttl):
        return True

    async def get(self, key):
        return self.data.get(key)


def make_cache(language=LANG):
    redis = FakeRedis()
    cache = MagicMock()

    async def _client():
        return redis

    type(cache).client = property(lambda self: _client())
    cache.get_user_by_id = AsyncMock(return_value={"language": language})
    cache.redis = redis
    return cache


def make_task(cache):
    return SimpleNamespace(_cache_service=cache, _directus_service=MagicMock(logout_all_sessions=AsyncMock()))


def make_rejection(category):
    info = category_info(category)
    return SafetyRejection(
        stage="input", category=category, severity=info["severity"], reason="test",
        user_facing_message=info["message"], tool_response=build_rejection_payload(category),
    )


async def reject(task, category, response_id):
    with patch.object(generate_task, "write_audit_entry", new=AsyncMock()) as audit, \
         patch.object(generate_task, "_cache_safety_rejection", new=AsyncMock()), \
         patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
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
# contract-test: supporting surface=rest_api assertions=safety-strikes.deletion-after-suspension-refunds
@pytest.mark.asyncio
async def test_second_strike_warns_third_deletes_once_with_refund():
    task = make_task(make_cache("en"))
    await reject(task, "S3_sexual_other", "r1")
    result, send_task, _ = await reject(task, "S6_public_figure_blocked", "r2")
    assert "strike 2 of 3" in result["user_facing_message"]
    send_task.assert_not_called()

    result, send_task, _ = await reject(task, "S9_hate_symbol", "r3")
    send_task.assert_called_once()
    kwargs = send_task.call_args.kwargs
    assert kwargs["name"] == "delete_user_account"
    assert kwargs["kwargs"]["refund_invoices"] is True
    assert kwargs["kwargs"]["deletion_type"] == "policy_violation"


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
# contract-test: supporting surface=rest_api assertions=safety-strikes.deletion-after-suspension-refunds
@pytest.mark.asyncio
async def test_upload_endpoint_counts_one_strike_and_third_deletes():
    from backend.core.api.app.routes.internal_api import ContentSafetyRejectRequest, content_safety_reject

    cache = make_cache("en")
    directus = MagicMock(logout_all_sessions=AsyncMock())
    payload = ContentSafetyRejectRequest(user_id="user-1", rejection_reason="sexual_activity=0.95")
    with patch("backend.core.api.app.tasks.celery_config.app.send_task") as send_task:
        first = await content_safety_reject(payload, directus_service=directus, cache_service=cache)
        assert first["reject_count"] == 1 and first["result"] == "tracked"
        assert "strike 1 of 3" in first["warning"]
        await content_safety_reject(payload, directus_service=directus, cache_service=cache)
        send_task.assert_not_called()
        third = await content_safety_reject(payload, directus_service=directus, cache_service=cache)
    assert third["result"] == "account_deleted"
    send_task.assert_called_once()
    assert send_task.call_args.kwargs["kwargs"]["refund_invoices"] is True


# contract-test: direct surface=rest_api assertions=safety-strikes.one-strike-per-violation
@pytest.mark.asyncio
async def test_generation_then_upload_share_one_counter_without_double_count():
    cache = make_cache("en")
    counter = StrikeCounter(cache)
    result = await counter.record_strike(user_id="u", severity="critical", assistant_response_id="r")
    assert result.new_count == 1 and not result.ban_triggered
