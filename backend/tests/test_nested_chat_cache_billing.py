"""Cache tariffs, accounting and opaque affinity cover the complete chat tree."""

# contract-test-file: infrastructure
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import main_processor
from backend.apps.ai.processing.model_usage_tracker import (
    ModelUsageTracker,
    build_model_usage_breakdown,
)
from backend.apps.ai.utils.llm_utils import _snapshot_for_customer_scope
from backend.shared.python_schemas.llm_usage import normalize_provider_usage
from backend.core.api.app.services.directus.usage import aggregate_usage_rows_by_root


def request(depth=0, **kwargs):
    values = dict(
        is_anonymous=False,
        is_external=False,
        is_sub_chat=depth > 0,
        is_sub_chat_continuation=False,
        sub_chat_depth=depth,
        user_preferences={},
        user_id_hash="owner-hash",
        team_id="team-a",
        chat_id=f"chat-{depth}",
        root_chat_id="chat-0",
        parent_id=f"chat-{depth - 1}" if depth else None,
        orchestration_id="tree",
    )
    return SimpleNamespace(**{**values, **kwargs})


def tariff():
    return {
        "default_server": "baseten",
        "pricing": {
            "tokens": {
                "input": {"per_credit_unit": 10},
                "cache_read": {"per_credit_unit": 100},
                "output": {"per_credit_unit": 5},
            }
        },
        "cache_pricing": {
            "enabled": True,
            "eligible_hosts": ["baseten", "openrouter"],
            "status": "verified_for_activation",
            "write_billing": "included_in_input",
            "source_url": "https://www.baseten.co/pricing/",
            "reviewed_on": "2026-10-25",
            "expires_on": "2099-01-01",
        },
    }


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("depth", [0, 1, 2])
@pytest.mark.parametrize("continuation", [False, True])
def test_parent_child_grandchild_cache_tariff_eligibility(depth, continuation):
    req = request(depth, is_sub_chat_continuation=continuation)
    assert main_processor._customer_cache_pricing_scope(req)
    assert not main_processor._normal_chat_cache_pricing_scope(req)
    assert main_processor._normal_chat_cache_pricing_scope(
        request(0, orchestration_id=None)
    )


@pytest.mark.parametrize(
    "excluded",
    [
        {"is_anonymous": True},
        {"is_external": True},
        {"user_preferences": {"workflow_ai": True}},
        {"user_preferences": {"workflow_budget": {}}},
        {"user_preferences": {"workflow_credit_allowance": 10}},
    ],
)
def test_excluded_scheduling_and_billing_contracts_stay_separate(excluded):
    assert not main_processor._customer_cache_pricing_scope(request(2, **excluded))


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown,billing.credits.idempotent-charge
def test_tree_cache_receipts_replace_cumulative_events_and_sum_once_under_root():
    rows = []
    for depth in (0, 1, 2):
        req = request(depth)
        frozen = _snapshot_for_customer_scope(
            tariff(),
            cache_pricing_enabled=main_processor._customer_cache_pricing_scope(req),
        )
        tracker = ModelUsageTracker()
        for output in (10, 20, 20):
            usage = normalize_provider_usage(
                {
                    "input_tokens": 100,
                    "output_tokens": output,
                    "cache_read_input_tokens": 80,
                    "cache_creation_input_tokens": 0,
                    "reasoning_tokens": 7,
                },
                model_id="deepseek/deepseek-v4.1-flash",
                provider_kind="openai",
                inference_host="baseten",
                tariff_snapshot=frozen,
                attempt_id=f"attempt-{depth}",
            )
            tracker.record_reported_usage(
                model_id=usage.model_id, normalized_usage=usage
            )
        # 20 ordinary / 10 + 80 cached / 100 + 20 output / 5 = 6.8 -> floor 6.
        buckets = list(tracker._usage_by_attempt.values())
        receipt = build_model_usage_breakdown(buckets, lambda *_: tariff())
        assert receipt["credits_charged"] == 6
        assert receipt["cache_read_input_tokens"] == 80
        assert receipt["output_tokens"] == 20  # Reasoning is already included.
        assert len(receipt["entries"]) == 1
        assert receipt["entries"][0]["billing_mode"] == "cache_aware"
        rows.append(
            {
                "id": f"usage-{depth}",
                "chat_id": req.chat_id,
                "actual_chat_id": req.chat_id,
                "root_chat_id": req.root_chat_id,
                "depth": depth,
                "charge_id": f"charge-{depth}",
                "credits": receipt["credits_charged"],
            }
        )
    grouped = aggregate_usage_rows_by_root(rows)
    assert list(grouped) == ["chat-0"]
    assert grouped["chat-0"]["total_credits"] == 18
    assert [r["depth"] for r in grouped["chat-0"]["entries"]] == [0, 1, 2]


def test_descendants_share_affinity_but_other_owners_teams_roots_do_not(monkeypatch):
    monkeypatch.setattr(
        main_processor, "INTERNAL_API_SHARED_TOKEN", "test-only-affinity-secret"
    )
    keys = [
        main_processor._mistral_prompt_cache_key(request(depth)) for depth in (0, 1, 2)
    ]
    assert keys[0] == keys[1] == keys[2]
    for changed in [
        {"user_id_hash": "other"},
        {"team_id": "other"},
        {"root_chat_id": "other"},
    ]:
        assert (
            main_processor._mistral_prompt_cache_key(request(2, **changed)) != keys[0]
        )
    assert "chat" not in keys[0] and "owner" not in keys[0]
