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
