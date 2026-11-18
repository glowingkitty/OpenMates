"""Tests for status-monitor traffic exemption (token, account list, billing, anonymous admission)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.shared.python_utils import monitor_traffic as mt
from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService
from backend.core.api.app.services.billing_service import BillingService


def _secrets(values):
    async def get_secret(path, key, log_missing=True):
        assert path == mt.MONITOR_VAULT_PATH
        return values.get(key)
    return SimpleNamespace(get_secret=get_secret)


@pytest.fixture(autouse=True)
def _clear():
    mt.clear_monitor_cache()
    yield
    mt.clear_monitor_cache()


# contract-test: direct surface=rest_api assertions=external-status-monitoring.probes.no-billing
@pytest.mark.asyncio
async def test_probe_token_valid_invalid_missing():
    sm = _secrets({"probe_token": "s3cret"})
    assert await mt.is_monitor_probe(sm, "s3cret")
    assert not await mt.is_monitor_probe(sm, "wrong")
    assert not await mt.is_monitor_probe(sm, None)
    mt.clear_monitor_cache()
    assert not await mt.is_monitor_probe(_secrets({}), "s3cret")


# contract-test: direct surface=rest_api assertions=external-status-monitoring.probes.no-billing
def test_parse_user_ids():
    assert mt.parse_user_ids(" a, b ,,c") == frozenset({"a", "b", "c"})
    assert mt.parse_user_ids(None) == frozenset()


# contract-test: direct surface=rest_api assertions=external-status-monitoring.probes.no-billing
@pytest.mark.asyncio
async def test_account_membership():
    sm = _secrets({"account_user_ids": "u1, u2"})
    assert await mt.is_monitor_account(sm, "u2")
    assert not await mt.is_monitor_account(sm, "u3")
    assert not await mt.is_monitor_account(sm, None)


# contract-test: direct surface=rest_api assertions=external-status-monitoring.probes.no-billing
@pytest.mark.asyncio
async def test_billing_skips_monitoring_account_only():
    service = BillingService(MagicMock(), MagicMock(), MagicMock())
    service._monitor_secrets_manager = _secrets({"account_user_ids": "mon"})
    result = await service.charge_user_credits(
        user_id="mon", credits_to_deduct=7, user_id_hash="h", app_id="ai", skill_id="ask", idempotency_key="k1",
    )
    assert result["charged_credits"] == 0 and result["requested_credits"] == 7
    service.cache_service.get_user_by_id.assert_not_called()
    assert not await service._is_monitoring_account("normal")


# contract-test: direct surface=rest_api assertions=external-status-monitoring.probes.no-billing
@pytest.mark.asyncio
async def test_anonymous_admission_bypass_for_monitor_ids():
    directus = MagicMock()
    directus.create_item = AsyncMock()
    cache = MagicMock()
    store = {}
    cache.set = AsyncMock(side_effect=lambda k, v, ttl=None: store.__setitem__(k, v))
    cache.get = AsyncMock(side_effect=lambda k: store.get(k))
    service = AnonymousFreeUsageService(directus_service=directus, cache_service=cache, require_distributed_lock=True)
    rid = f"{mt.MONITOR_REQUEST_PREFIX}abc"
    assert (await service.open_request(request_id=rid, anonymous_id=None, ip_address="1.2.3.4")).accepted
    assert (await service.reserve_operation(parent_request_id=rid, operation_id="op", charge_id="ch", quoted_credits=50)).accepted
    await service.finalize_charge("ch", actual_credits=5)
    await service.release_reservation("op", reason="x")
    assert (await service.checkpoint_operation("op", checkpoint_credits=3)).status == "monitor_probe"
    assert await service.get_request_budget(rid) > 0
    directus.create_item.assert_not_called()
