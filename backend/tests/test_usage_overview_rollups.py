from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.core.api.app.services.usage_overview_service import (
    UsageOverviewService,
    aggregate_landing_daily_items,
    aggregate_usage_entries,
    aggregate_workflow_daily_items,
    period_for_timestamp,
    recent_periods,
)


# contract-test: supporting surface=rest_api assertions=billing.surface.semantic-parity
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


# contract-test: supporting surface=rest_api assertions=billing.surface.semantic-parity
def test_recent_months_cross_year_boundary() -> None:
    periods = recent_periods("monthly", 3, now=datetime(2026, 1, 15, tzinfo=timezone.utc))

    assert [period.period_key for period in periods] == ["2026-01", "2025-12", "2025-11"]


# contract-test: supporting surface=rest_api assertions=billing.surface.semantic-parity
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


# contract-test: supporting surface=rest_api assertions=workflows.billing.skill-usage
def test_workflow_daily_items_use_semantic_sources_and_app_skill_groups() -> None:
    timestamp = int(datetime(2026, 9, 14, 12, tzinfo=timezone.utc).timestamp())

    by_date = aggregate_workflow_daily_items([
        {"source": "workflow", "app_id": "weather", "skill_id": "forecast", "credits": 4, "created_at": timestamp, "updated_at": timestamp},
        {"source": "workflow", "app_id": "weather", "skill_id": "forecast", "credits": 6, "created_at": timestamp + 1, "updated_at": timestamp + 1},
        {"source": "workflow_test", "app_id": "web", "skill_id": "search", "credits": 3, "created_at": timestamp + 2, "updated_at": timestamp + 2},
        {"source": "chat", "app_id": "ai", "skill_id": "ask", "credits": 99, "created_at": timestamp + 3, "updated_at": timestamp + 3},
    ])

    items = by_date["2026-09-14"]
    assert [(item["type"], item["app_id"], item["skill_id"]) for item in items] == [
        ("workflow_test", "web", "search"),
        ("workflow", "weather", "forecast"),
    ]
    assert items[1]["total_credits"] == 10
    assert items[1]["entry_count"] == 2


# contract-test: direct surface=rest_api assertions=billing.usage.landing-complete
def test_landing_daily_items_reconcile_every_usage_context_exactly_once() -> None:
    timestamp = int(datetime(2026, 9, 23, 12, tzinfo=timezone.utc).timestamp())
    entries = [
        {"source": "chat", "chat_id": "chat-1", "app_id": "ai", "skill_id": "ask", "credits": 2, "created_at": timestamp, "updated_at": timestamp},
        {"source": "chat", "chat_id": "incognito", "app_id": "ai", "skill_id": "ask", "credits": 3, "created_at": timestamp + 1, "updated_at": timestamp + 1},
        {"source": "direct", "app_id": "audio", "skill_id": "transcribe", "type": "realtime_transcription_interrupted", "duration_seconds": 11, "credits": 8, "created_at": timestamp + 2, "updated_at": timestamp + 2},
        {"source": "api_key", "api_key_hash": "api-hash", "app_id": "web", "skill_id": "search", "credits": 5, "created_at": timestamp + 3, "updated_at": timestamp + 3},
        {"source": "direct", "device_hash": "device-hash", "app_id": "code", "skill_id": "run", "credits": 7, "created_at": timestamp + 4, "updated_at": timestamp + 4},
        {"source": "workflow", "app_id": "weather", "skill_id": "forecast", "credits": 11, "created_at": timestamp + 5, "updated_at": timestamp + 5},
        {"source": "workflow_test", "app_id": "web", "skill_id": "search", "credits": 13, "created_at": timestamp + 6, "updated_at": timestamp + 6},
        {"source": "benchmark", "app_id": "ai", "skill_id": "ask", "credits": 17, "created_at": timestamp + 7, "updated_at": timestamp + 7},
        {"source": "chat", "app_id": "ai", "skill_id": "ask", "credits": 19, "created_at": timestamp + 8, "updated_at": timestamp + 8},
    ]

    days = aggregate_landing_daily_items(entries, ["2026-09-23"])

    assert len(days) == 1
    items = days[0]["items"]
    assert {item["type"] for item in items} == {
        "chat",
        "incognito",
        "app",
        "api_key",
        "device",
        "workflow",
        "workflow_test",
        "benchmark",
        "unattributed",
    }
    assert sum(item["entry_count"] for item in items) == len(entries)
    assert sum(item["total_credits"] for item in items) == sum(entry["credits"] for entry in entries)
    assert days[0]["total_credits"] == 85
    interrupted = next(item for item in items if item["usage_type"] == "realtime_transcription_interrupted")
    assert interrupted["type"] == "app"
    assert interrupted["started_minutes"] == 1
    assert interrupted["navigation_target"] == "none"
    assert next(item for item in items if item["type"] == "chat")["navigation_target"] == "chat"


# contract-test: direct surface=rest_api assertions=billing.usage.landing-complete
@pytest.mark.asyncio
async def test_landing_daily_items_read_all_owner_scoped_pages_without_content() -> None:
    class FakeDirectus:
        def __init__(self):
            self.params: list[dict] = []

        async def get_items(self, collection, params=None, **kwargs):
            assert collection == "usage"
            self.params.append(params)
            offset = params["offset"]
            count = 100 if offset == 0 else 1
            return [
                {
                    "id": f"usage-{offset + index}",
                    "source": "direct",
                    "app_id": "audio",
                    "skill_id": "transcribe",
                    "type": "realtime_transcription_interrupted",
                    "created_at": 1_758_600_000 + index,
                    "updated_at": 1_758_600_000 + index,
                    "encrypted_credits_costs_total": "cipher:8",
                    "encrypted_code_run_duration_seconds": "cipher:11",
                }
                for index in range(count)
            ]

    class FakeEncryption:
        async def decrypt_many_with_user_key(self, values, key_id):
            assert key_id == "vault-key"
            return [value.removeprefix("cipher:") for value in values]

    directus = FakeDirectus()
    service = UsageOverviewService(directus, FakeEncryption())

    days = await service.get_landing_daily_items(
        user_id_hash="owner-hash",
        user_vault_key_id="vault-key",
        period_start=1_758_600_000,
        dates=["2025-09-23"],
    )

    assert [params["offset"] for params in directus.params] == [0, 100]
    assert all(params["filter"]["user_id_hash"] == {"_eq": "owner-hash"} for params in directus.params)
    assert all("content" not in params["fields"] for params in directus.params)
    assert sum(item["entry_count"] for day in days for item in day["items"]) == 101
    assert sum(item["total_credits"] for day in days for item in day["items"]) == 808


# contract-test: supporting surface=rest_api assertions=billing.usage.landing-complete
@pytest.mark.asyncio
async def test_landing_pagination_detects_usage_before_a_gap() -> None:
    class FakeDirectus:
        async def get_items(self, collection, params=None, **kwargs):
            assert collection == "usage"
            assert params["filter"] == {
                "user_id_hash": {"_eq": "owner-hash"},
                "created_at": {"_lt": 1234},
            }
            assert params["fields"] == "id"
            assert params["limit"] == 1
            return [{"id": "older-charge"}]

    service = UsageOverviewService(FakeDirectus(), object())

    assert await service.has_landing_usage_before("owner-hash", 1234) is True


# contract-test: direct surface=rest_api assertions=workflows.billing.skill-usage
@pytest.mark.asyncio
async def test_workflow_daily_items_page_contentless_owner_scoped_usage_rows() -> None:
    class FakeDirectus:
        def __init__(self):
            self.params: list[dict] = []

        async def get_items(self, collection, params=None, **kwargs):
            assert collection == "usage"
            self.params.append(params)
            offset = params["offset"]
            count = 100 if offset == 0 else 1
            return [
                {
                    "id": f"usage-{offset + index}",
                    "source": "workflow" if offset == 0 else "workflow_test",
                    "app_id": "weather",
                    "skill_id": "forecast",
                    "created_at": 1_757_851_200 + index,
                    "updated_at": 1_757_851_200 + index,
                    "encrypted_credits_costs_total": "cipher:1",
                }
                for index in range(count)
            ]

    class FakeEncryption:
        async def decrypt_many_with_user_key(self, values, key_id):
            assert key_id == "vault-key"
            return [value.removeprefix("cipher:") for value in values]

    directus = FakeDirectus()
    service = UsageOverviewService(directus, FakeEncryption())

    items = await service.get_workflow_daily_items(
        user_id_hash="owner-hash",
        user_vault_key_id="vault-key",
        period_start=1_757_851_200,
    )

    assert [params["offset"] for params in directus.params] == [0, 100]
    assert all(params["filter"]["user_id_hash"] == {"_eq": "owner-hash"} for params in directus.params)
    assert all(params["filter"]["source"] == {"_in": ["workflow", "workflow_test"]} for params in directus.params)
    assert all("content" not in params["fields"] and "workflow_id" not in params["fields"] for params in directus.params)
    assert sum(item["total_credits"] for day_items in items.values() for item in day_items) == 101


# contract-test: supporting surface=rest_api assertions=billing.surface.semantic-parity
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
