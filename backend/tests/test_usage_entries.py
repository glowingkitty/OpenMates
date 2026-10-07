# backend/tests/test_usage_entries.py
#
# Regression tests for billing usage history retrieval.
# The user-facing billing page and CLI depend on this query returning the newest
# usage rows first; otherwise successful charges can be hidden behind older rows.
# These tests keep the Directus query contract deterministic without needing a
# live Directus instance or real encryption keys.

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest

from backend.core.api.app.services.llm_usage_receipt import (
    settle_public_llm_usage_receipt,
    validate_public_llm_usage_receipt,
)


def _load_usage_methods_class():
    module_path = Path(__file__).resolve().parents[1] / "core/api/app/services/directus/usage.py"
    spec = importlib.util.spec_from_file_location("usage_methods_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.UsageMethods


UsageMethods = _load_usage_methods_class()


class FakeDirectusSDK:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def get_items(self, collection: str, params: dict[str, Any], no_cache: bool = False):
        self.calls.append({"collection": collection, "params": params, "no_cache": no_cache})
        return self.rows

    async def create_item(self, collection: str, payload: dict[str, Any]):
        self.calls.append({"collection": collection, "payload": payload})
        return True, {"id": "usage-created"}


class FakeEncryption:
    async def encrypt_with_user_key(self, key_id: str, plaintext: str):
        return f"enc:{key_id}:{plaintext}", None

    async def decrypt_with_user_key(self, ciphertext: str, _key_id: str):
        return ciphertext


def _llm_receipt() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "input_tokens": 12,
        "uncached_input_tokens": 7,
        "cache_read_input_tokens": 5,
        "cache_creation_input_tokens": 0,
        "output_tokens": 3,
        "usage_source": "provider_reported",
        "entries": [{
            "model_id": "model-public", "inference_host": "host-public", "pricing_version": "tariff-v1",
            "input_tokens": 12, "uncached_input_tokens": 7, "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 0, "cache_creation_5m_input_tokens": 0,
            "cache_creation_1h_input_tokens": 0, "output_tokens": 3,
            "rates": {"input": "100", "cache_read": "200", "cache_write": None,
                      "cache_write_1h": None, "output": "50"},
            "write_billing": "included_in_input",
            "category_credits": {"input": "0.07", "cache_read": "0.025", "cache_write": "0",
                                 "cache_write_1h": "0", "output": "0.06"},
            "raw_credits": "0.155",
        }],
        "raw_credits": "0.155", "rounding_adjustment": "0.845",
        "credits_charged": 1, "settlement_state": "settled",
    }


class RoundTripEncryption(FakeEncryption):
    async def decrypt_with_user_key(self, ciphertext: str, key_id: str):
        prefix = f"enc:{key_id}:"
        assert ciphertext.startswith(prefix)
        return ciphertext[len(prefix):]


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge
def test_settled_llm_receipt_reconciles_a_clamped_debit_without_changing_pricing_snapshot() -> None:
    original = _llm_receipt()
    original["credits_charged"] = 9
    original["settlement_state"] = "pending"
    settled = settle_public_llm_usage_receipt(original, 2)
    assert settled["credits_charged"] == 2
    assert settled["rounding_adjustment"] == "1.845"
    assert settled["settlement_state"] == "settled"
    assert settled["requested_credits"] == 9
    assert settled["entries"] == original["entries"]
    assert original["credits_charged"] == 9


# contract-test: direct surface=rest_api assertions=billing.usage.receipt-token-breakdown
def test_repeating_fraction_receipt_settles_without_decimal_context_rounding() -> None:
    original = _llm_receipt()
    original["raw_credits"] = "0." + "3" * 60
    original["credits_charged"] = 3
    original["requested_credits"] = 7  # Earlier workflow cap already recorded.
    settled = settle_public_llm_usage_receipt(original, 2)
    assert settled["requested_credits"] == 7
    assert settled["rounding_adjustment"] == "1." + "6" * 59 + "7"
    with localcontext() as context:
        context.prec = 100
        assert Decimal(settled["raw_credits"]) + Decimal(settled["rounding_adjustment"]) == 2
    assert "requested_credits" in original
    assert original["credits_charged"] == 3


# contract-test: direct surface=rest_api assertions=billing.self-host.cloud-guard
def test_payment_disabled_receipt_reports_zero_wallet_debit_and_nominal_request() -> None:
    original = _llm_receipt()
    original["credits_charged"] = 12
    settled = settle_public_llm_usage_receipt(original, 0)
    assert settled["credits_charged"] == 0
    assert settled["requested_credits"] == 12
    assert settled["rounding_adjustment"] == "-0.155"
    assert settled["settlement_state"] == "settled"
    assert original["credits_charged"] == 12


# contract-test: direct surface=rest_api assertions=billing.usage.receipt-token-breakdown
def test_optional_billing_mode_and_billed_input_tokens_are_public_and_independent() -> None:
    receipt = _llm_receipt()
    entry = receipt["entries"][0]
    entry["billing_mode"] = "ordinary_input"
    assert validate_public_llm_usage_receipt(receipt) is receipt
    entry.pop("billing_mode")
    entry["billed_input_tokens"] = 12
    assert validate_public_llm_usage_receipt(receipt) is receipt
    entry["billing_mode"] = "cache_aware"
    assert validate_public_llm_usage_receipt(receipt) is receipt

    entry["billed_input_tokens"] = -1
    with pytest.raises(ValueError, match="billed input"):
        validate_public_llm_usage_receipt(receipt)
    entry["billed_input_tokens"] = 12
    entry["billing_mode"] = "supplier_cost"
    with pytest.raises(ValueError, match="billing mode"):
        validate_public_llm_usage_receipt(receipt)


# contract-test: supporting surface=rest_api assertions=billing.surface.semantic-parity
@pytest.mark.anyio
async def test_user_usage_entries_query_requests_newest_first_page() -> None:
    sdk = FakeDirectusSDK([
        {
            "id": "usage-1",
            "type": "skill_execution",
            "source": "chat",
            "created_at": 200,
            "updated_at": 200,
            "app_id": "code",
            "skill_id": "run",
            "encrypted_credits_costs_total": "5",
        }
    ])
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    entries = await usage.get_user_usage_entries(
        user_id_hash="user-hash",
        user_vault_key_id="vault-key",
        limit=10,
        offset=0,
        sort="-created_at",
    )

    assert entries[0]["app_id"] == "code"
    params = sdk.calls[0]["params"]
    assert params["sort"] == ["-created_at"]
    assert params["limit"] == 10
    assert params["offset"] == 0


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
@pytest.mark.anyio
async def test_create_usage_entry_allows_benchmark_source() -> None:
    sdk = FakeDirectusSDK([])
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    async def noop_summary(**_kwargs: Any) -> None:
        return None

    usage._update_monthly_summaries = noop_summary
    usage._update_daily_summaries = noop_summary

    entry_id = await usage.create_usage_entry(
        user_id_hash="user-hash",
        app_id="ai",
        skill_id="ask",
        usage_type="skill_execution",
        timestamp=1780000000,
        credits_charged=1,
        user_vault_key_id="vault-key",
        source="benchmark",
        chat_id="chat-1",
    )

    assert entry_id == "usage-created"
    created = sdk.calls[0]["payload"]
    assert created["source"] == "benchmark"
    assert created["chat_id"] == "chat-1"


@pytest.mark.parametrize("source", ["workflow", "workflow_test"])
# contract-test: supporting surface=rest_api assertions=workflows.billing.skill-usage
@pytest.mark.anyio
async def test_create_usage_entry_preserves_workflow_source(source: str) -> None:
    sdk = FakeDirectusSDK([])
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    async def noop_summary(**_kwargs: Any) -> None:
        return None

    usage._update_monthly_summaries = noop_summary
    usage._update_daily_summaries = noop_summary

    await usage.create_usage_entry(
        user_id_hash="user-hash",
        app_id="weather",
        skill_id="forecast",
        usage_type="skill_execution",
        timestamp=1780000000,
        credits_charged=1,
        user_vault_key_id="vault-key",
        source=source,
    )

    assert sdk.calls[0]["payload"]["source"] == source


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.anyio
async def test_create_usage_entry_saves_image_to_html_tokens_and_duration_second() -> None:
    sdk = FakeDirectusSDK([])
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    async def noop_summary(**_kwargs: Any) -> None:
        return None

    usage._update_monthly_summaries = noop_summary
    usage._update_daily_summaries = noop_summary

    entry_id = await usage.create_usage_entry(
        user_id_hash="user-hash",
        app_id="code",
        skill_id="image_to_html",
        usage_type="skill_execution",
        timestamp=1780000000,
        credits_charged=123,
        user_vault_key_id="vault-key",
        model_used="google/gemini-3.7-flash",
        actual_input_tokens=1000,
        actual_output_tokens=500,
        duration_second=61.25,
    )

    assert entry_id == "usage-created"
    created = sdk.calls[0]["payload"]
    assert created["encrypted_input_tokens"] == "enc:vault-key:1000"
    assert created["encrypted_output_tokens"] == "enc:vault-key:500"
    assert created["encrypted_code_run_duration_seconds"] == "enc:vault-key:61.25"


# contract-test: direct surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("context_band", [None, "standard", "over_272k"])
@pytest.mark.parametrize("purpose", [None, "summary"])
@pytest.mark.anyio
async def test_llm_receipt_is_encrypted_and_available_through_both_owner_scoped_readers(context_band: str | None, purpose: str | None) -> None:
    sdk = FakeDirectusSDK([])
    usage = UsageMethods(sdk=sdk, encryption_service=RoundTripEncryption())
    async def noop_summary(**_kwargs: Any) -> None:
        return None
    usage._update_monthly_summaries = noop_summary
    usage._update_daily_summaries = noop_summary
    receipt = _llm_receipt()
    if context_band is not None:
        receipt["entries"][0]["context_band"] = context_band
    if purpose is not None:
        receipt["entries"][0]["purpose"] = purpose

    await usage.create_usage_entry(
        user_id_hash="owner-hash", app_id="ai", skill_id="ask", usage_type="skill_execution",
        timestamp=1780000000, credits_charged=1, user_vault_key_id="owner-key",
        llm_usage_breakdown=receipt,
    )
    row = sdk.calls[0]["payload"]
    assert "llm_usage_breakdown" not in row
    assert json.loads(row["encrypted_llm_usage_breakdown"].removeprefix("enc:owner-key:")) == receipt
    sdk.rows = [row]
    live = await usage.get_user_usage_entries("owner-hash", "owner-key")
    archived = await usage._decrypt_usage_entries([row], "owner-key")
    assert live[0]["llm_usage_breakdown"] == receipt
    assert archived[0]["llm_usage_breakdown"] == receipt
    assert "llm_usage_breakdown" not in (await usage._decrypt_usage_entries([{"encrypted_credits_costs_total": "enc:owner-key:1"}], "owner-key"))[0]


@pytest.mark.parametrize("field,value", [
    ("supplier_cost_usd", "0.001"),
    ("context_band", "unverified-tier"),
    ("context_band", {"supplier_cost_usd": "0.001"}),
    ("context_band", True),
    ("purpose", "private_supplier_summary"),
    ("purpose", {"supplier_cost_usd": "0.001"}),
    ("purpose", True),
])
@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_llm_receipt_rejects_private_or_invalid_metadata_before_usage_write(field: str, value: Any) -> None:
    sdk = FakeDirectusSDK([])
    usage = UsageMethods(sdk=sdk, encryption_service=RoundTripEncryption())
    receipt = _llm_receipt()
    receipt["entries"][0][field] = value
    result = await usage.create_usage_entry(
        user_id_hash="owner-hash", app_id="ai", skill_id="ask", usage_type="skill_execution",
        timestamp=1780000000, credits_charged=1, user_vault_key_id="owner-key",
        llm_usage_breakdown=receipt, build_only=True,
    )
    assert result is None
    assert sdk.calls == []
