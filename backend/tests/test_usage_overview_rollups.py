from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.core.api.app.services.usage_overview_service import aggregate_usage_entries, period_for_timestamp, recent_periods


def test_usage_overview_period_keys_are_stable() -> None:
    timestamp = int(datetime(2026, 7, 20, 12, 30, tzinfo=timezone.utc).timestamp())

    daily = period_for_timestamp(timestamp, "daily")
    weekly = period_for_timestamp(timestamp, "weekly")
    monthly = period_for_timestamp(timestamp, "monthly")

    assert daily.period_key == "2026-07-20"
    assert weekly.period_key == "2026-W30"
    assert monthly.period_key == "2026-07"
    assert daily.period_start < timestamp < daily.period_end
    assert weekly.period_start < timestamp < weekly.period_end
    assert monthly.period_start < timestamp < monthly.period_end


def test_recent_months_cross_year_boundary() -> None:
    periods = recent_periods("monthly", 3, now=datetime(2026, 1, 15, tzinfo=timezone.utc))

    assert [period.period_key for period in periods] == ["2026-01", "2025-12", "2025-11"]


def test_aggregate_usage_entries_groups_tokens_and_credits_without_double_counting() -> None:
    period = period_for_timestamp(int(datetime(2026, 7, 20, 12, tzinfo=timezone.utc).timestamp()), "daily")
    entries = [
        {
            "created_at": period.period_start + 10,
            "credits": 7,
            "input_tokens": 100,
            "output_tokens": 25,
            "user_input_tokens": 10,
            "system_prompt_tokens": 80,
            "tool_inference_iterations": 1,
            "app_id": "ai",
            "skill_id": "ask",
            "source": "chat",
            "model_used": "openai/gpt-5.1",
            "server_provider": "OpenAI API",
            "server_region": "US",
        },
        {
            "created_at": period.period_start + 20,
            "credits": 3,
            "input_tokens": 50,
            "output_tokens": 10,
            "app_id": "ai",
            "skill_id": "ask",
            "source": "api_key",
            "model_used": "openai/gpt-5.1",
            "server_provider": "OpenAI API",
            "server_region": "US",
        },
        {
            "created_at": period.period_start + 30,
            "credits": 5,
            "app_id": "web",
            "skill_id": "search",
            "source": "chat",
        },
    ]

    rollup = aggregate_usage_entries(entries, period)

    assert rollup["totals"]["credits"] == 15
    assert rollup["totals"]["entries"] == 3
    assert rollup["totals"]["input_tokens"] == 150
    assert rollup["totals"]["output_tokens"] == 35
    assert rollup["totals"]["total_tokens"] == 185
    assert rollup["totals"]["entries_without_token_data"] == 1
    assert rollup["token_coverage"]["entries_with_token_data"] == 2
    assert rollup["by_model"][0]["model_used"] == "openai/gpt-5.1"
    assert rollup["by_model"][0]["total_tokens"] == 185
    assert {item["source"]: item["credits"] for item in rollup["by_source"]} == {"chat": 12, "api_key": 3}
    assert {f"{item['app_id']}/{item['skill_id']}": item["credits"] for item in rollup["by_skill"]} == {"ai/ask": 10, "web/search": 5}


@pytest.mark.asyncio
async def test_usage_overview_rebuilds_missing_periods_with_one_raw_usage_read() -> None:
    class FakeUsage:
        async def _decrypt_usage_entries(self, entries, user_vault_key_id):
            assert user_vault_key_id == "vault-key"
            return entries

    class FakeDirectus:
        def __init__(self):
            self.usage = FakeUsage()
            self.reads: list[str] = []
            self.created: list[dict] = []

        async def get_items(self, collection, params=None, **kwargs):
            self.reads.append(collection)
            if collection == "usage_period_rollups":
                return []
            if collection == "usage":
                start = params["filter"]["created_at"]["_gte"]
                return [{"created_at": start + 60, "credits": 5, "source": "chat"}]
            return []

        async def create_item(self, collection, payload, **kwargs):
            assert collection == "usage_period_rollups"
            self.created.append(payload)

        async def update_item(self, collection, item_id, payload, **kwargs):
            raise AssertionError("missing rollups should create, not update")

    class FakeEncryption:
        async def encrypt_with_user_key(self, key_id, plaintext):
            assert key_id == "vault-key"
            return f"cipher:{plaintext}", {}

        async def decrypt_with_user_key(self, encrypted, key_id):
            raise AssertionError("cached rollups should not be decrypted when none exist")

    from backend.core.api.app.services.usage_overview_service import UsageOverviewService

    directus = FakeDirectus()
    service = UsageOverviewService(directus, FakeEncryption())

    overview = await service.get_overview(
        user_id_hash="hash",
        user_vault_key_id="vault-key",
        granularity="daily",
        count=3,
    )

    assert directus.reads.count("usage") == 1
    assert overview["totals"]["entries"] == 1
    assert len(overview["periods"]) == 3
    assert len(directus.created) == 1
