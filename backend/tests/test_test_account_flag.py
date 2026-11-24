# contract-test-file: tooling
# is_test_account: set only by redeeming a marks_test_account gift card, excluded from server
# stats, and the production batch script (capped credits, marking, single-use).

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("redis.asyncio")

from backend.core.api.app.routes import payments
from backend.core.api.app.services.directus.user.user_lookup import get_total_users_count

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_test_gift_card_batch.py"
_spec = importlib.util.spec_from_file_location("create_test_gift_card_batch", _SCRIPT)
batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(batch)


def _redeem(card):
    directus = MagicMock()
    directus.get_gift_card_by_code = AsyncMock(return_value=card)
    directus.update_user = AsyncMock(return_value=True)
    directus.record_gift_card_redemption = AsyncMock(return_value=True)
    directus.redeem_gift_card = AsyncMock(return_value=True)
    cache = MagicMock()
    cache.get_user_by_id = AsyncMock(return_value={"credits": 0, "vault_key_id": "k"})
    cache.set_user = AsyncMock()
    cache.set = AsyncMock(return_value=True)
    cache.get = AsyncMock(return_value=None)
    cache.update_liability = AsyncMock()
    cache.increment_stat = AsyncMock()
    enc = MagicMock()
    enc.encrypt_with_user_key = AsyncMock(return_value=("enc", 1))
    request = payments.RedeemGiftCardRequest(code="abcd-1234")
    fn = getattr(payments.redeem_gift_card, "__wrapped__", payments.redeem_gift_card)
    response = asyncio.run(fn(MagicMock(), request, None, SimpleNamespace(id="u1"), directus, cache, enc))
    return response, directus, cache


def test_marking_card_sets_flag_on_the_redeemer():
    response, directus, cache = _redeem({"id": "g", "credits_value": 1000, "marks_test_account": True})
    assert response.success
    assert directus.update_user.await_args.args[1]["is_test_account"] is True
    assert cache.set_user.await_args.args[0]["is_test_account"] is True


def test_normal_card_never_touches_flag():
    response, directus, cache = _redeem({"id": "g", "credits_value": 1000})
    assert response.success
    assert "is_test_account" not in directus.update_user.await_args.args[1]
    assert "is_test_account" not in cache.set_user.await_args.args[0]


def test_server_stats_user_count_can_exclude_test_accounts():
    seen = {}

    async def request(method, url, params=None):
        seen.update(params)
        return SimpleNamespace(status_code=200, json=lambda: {"meta": {"filter_count": 7}})

    fake = SimpleNamespace(base_url="http://d", _make_api_request=request)
    assert asyncio.run(get_total_users_count(fake, exclude_test_accounts=True)) == 7
    assert json.loads(seen["filter"]) == {"is_test_account": {"_neq": True}}
    seen.clear()
    asyncio.run(get_total_users_count(fake))
    assert "filter" not in seen


def test_server_stats_task_excludes_test_accounts():
    source = (Path(__file__).resolve().parents[1] / "core/api/app/tasks/server_stats_tasks.py").read_text()
    assert "get_total_users_count(exclude_test_accounts=True)" in source
    assert "'is_test_account': {'_neq': True}" in source


def test_batch_cards_are_marked_single_use_and_credit_capped():
    fields = batch.build_card_fields(1000, "note")
    assert fields["marks_test_account"] is True and fields["is_reusable"] is False
    for bad in (0, 1001, 50000):
        with pytest.raises(ValueError):
            batch.build_card_fields(bad, "note")


def test_create_batch_marks_every_card_and_returns_codes():
    directus = MagicMock()
    directus.get_gift_card_by_code = AsyncMock(return_value=None)
    directus.create_gift_card = AsyncMock(side_effect=lambda **kw: {"id": kw["code"]})
    directus.update_item = AsyncMock()
    codes = asyncio.run(batch.create_batch(directus, 3, 1000, "ai-test-users batch x"))
    assert len(set(codes)) == 3
    assert all(c.kwargs["credits_value"] == 1000 and not c.kwargs.get("is_reusable")
               for c in directus.create_gift_card.await_args_list)
    assert all(c.args[2] == {"marks_test_account": True, "notes": "ai-test-users batch x"}
               for c in directus.update_item.await_args_list)


def test_active_users_and_completed_signups_exclude_test_accounts():
    from backend.core.api.app.services.directus.user.user_lookup import (
        get_active_users_since, get_completed_signups_count)
    seen = {}
    chat = "/chat/0b1c2d3e-0000-4000-8000-000000000001"

    async def request(method, url, params=None):
        seen.update(params)
        rows = [{"id": "a", "last_opened": chat}, {"id": "b", "last_opened": chat, "is_test_account": True}]
        return SimpleNamespace(status_code=200, json=lambda: {"data": rows, "meta": {"filter_count": 1}})

    fake = SimpleNamespace(base_url="http://d", _make_api_request=request)
    asyncio.run(get_active_users_since(fake, 1_700_000_000))
    assert {"is_test_account": {"_neq": True}} in json.loads(seen["filter"])["_and"]
    assert asyncio.run(get_completed_signups_count(fake)) == 1


def test_metric_gauges_exclude_test_accounts():
    root = Path(__file__).resolve().parents[1] / "core/api/app"
    for name in ("services/metrics.py", "tasks/user_metrics.py"):
        assert "get_total_users_count(exclude_test_accounts=True)" in (root / name).read_text()


def test_post_update_account_script_refuses_non_test_emails():
    script = Path(__file__).resolve().parents[1] / "scripts" / "post_update_test_account.py"
    spec = importlib.util.spec_from_file_location("post_update_test_account", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.require_test_email("OMTestUser-0123456789abcdef@example.org").startswith("omtestuser-")
    for bad in ("person@example.org", "omtestuser-xyz@example.org", "omtestuser-0123456789abcdef"):
        with pytest.raises(module.RefusedError):
            module.require_test_email(bad)


class _MemoCache:
    """Minimal cache: user lookup, memo get/set and stat counters."""

    def __init__(self, user=None):
        self.user, self.memo, self.stats = user, {}, {}

    async def get_user_by_id(self, user_id):
        return self.user

    async def get(self, key):
        return self.memo.get(key)

    async def set(self, key, value, ttl=None):
        self.memo[key] = value

    async def increment_stat(self, field, amount=1, day=None):
        self.stats[field] = self.stats.get(field, 0) + amount


def test_is_test_account_user_cached_label_and_directus_fallback():
    from backend.core.api.app.services.stats_account_label import is_test_account_user
    directus = MagicMock()
    directus.get_user_fields_direct = AsyncMock(return_value={"is_test_account": True})
    flagged = _MemoCache({"is_test_account": True})
    assert asyncio.run(is_test_account_user(flagged, directus, "u1")) is True
    regular = _MemoCache({"is_test_account": False})
    assert asyncio.run(is_test_account_user(regular, directus, "u1")) is False
    directus.get_user_fields_direct.assert_not_awaited()
    # cache miss on the field: Directus is read once, then memoized
    miss = _MemoCache({"credits": 5})
    assert asyncio.run(is_test_account_user(miss, directus, "u1")) is True
    assert asyncio.run(is_test_account_user(miss, directus, "u1")) is True
    assert directus.get_user_fields_direct.await_count == 1
    directus.get_user_fields_direct = AsyncMock(return_value=None)
    assert asyncio.run(is_test_account_user(_MemoCache(None), directus, "u2")) is False


def _create_message(cache, hashed):
    from backend.core.api.app.services.directus.chat_methods import ChatMethods
    directus = MagicMock()
    directus.create_item = AsyncMock(return_value=(True, {"id": "m"}))
    directus.cache = cache
    cache.delete = AsyncMock()
    methods = ChatMethods.__new__(ChatMethods)
    methods.directus_service = directus
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "backend.core.api.app.services.directus.chat_methods._validate_client_encrypted_message_content",
            lambda *a, **k: None,
        )
        asyncio.run(methods.create_message_in_directus(
            {"id": "m1", "chat_id": "c", "hashed_user_id": hashed, "role": "user", "encrypted_content": "x"}))


def test_messages_sent_skips_test_accounts_only():
    import hashlib
    from backend.core.api.app.services.stats_account_label import remember_test_account
    cache = _MemoCache()
    asyncio.run(remember_test_account(cache, "tester", True))
    _create_message(cache, hashlib.sha256(b"tester").hexdigest())
    assert "messages_sent" not in cache.stats
    _create_message(cache, hashlib.sha256(b"someone").hexdigest())
    assert cache.stats["messages_sent"] == 1


def test_billing_usage_stats_skip_test_accounts():
    from backend.core.api.app.services import billing_service
    source = Path(billing_service.__file__).read_text()
    assert source.count("is_test_account_user(") >= 2
    assert "not _is_test_charge" in source
