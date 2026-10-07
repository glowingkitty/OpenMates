"""Regression coverage for ranking provider outages and queued refreshes."""
# contract-test-file: infrastructure

# contract-test-file: infrastructure

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from backend.scripts import aggregate_leaderboards
from backend.scripts.fetch_lmarena_rankings import parse_lmarena_markdown, validate_rankings


@pytest.fixture
def leaderboard_tasks():
    pytest.importorskip("celery")
    from backend.core.api.app.tasks import leaderboard_tasks as module
    return module


VALID_DATA = {"metadata": {"generated_at": "earlier"}, "rankings": [
    {"model_id": "working-model", "composite_score": 90},
]}
EMPTY_DATA = {"metadata": {"generated_at": "failed"}, "rankings": [], "unranked": [
    {"model_id": "working-model"},
]}


def _current_lmarena_markdown(count=30):
    """Small public, synthetic table matching the current seven-column page."""
    families = (
        ("gemini", "Google"), ("claude", "Anthropic"),
        ("gpt", "OpenAI"), ("grok", "xAI"),
    )
    rows = [
        "| Rank | Rank Spread | Model | Score | Votes | Price $/M | Context |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rank in range(1, count + 1):
        family, organization = families[(rank - 1) % len(families)]
        model = f"{family}-fixture-{rank}"
        prefix = "Anthropic<br>![Icon](https://example.invalid/icon.png)<br>" if rank == 2 else ""
        score = f"{1500 - 6 * rank}±{3 + rank % 5}"
        if rank == 1:
            score += "Preliminary"
        rows.append(
            f"| {rank} | {rank} {rank + 2} | {prefix}[{model}](https://example.invalid/{model})"
            f"<br>{organization} · Proprietary | {score} | {50_000 - rank * 100:,} | $2 / $10 | 1M |"
        )
    return "\n".join(rows)


def test_current_lmarena_score_ci_and_model_suffix_validate():
    markdown = _current_lmarena_markdown()
    rankings = parse_lmarena_markdown(markdown, "text")

    assert len(rankings) == 30
    assert rankings[0] == {
        "rank": 1, "model": "gemini-fixture-1", "score": 1494,
        "votes": 49_900, "organization": "Google",
    }
    assert rankings[1]["model"] == "claude-fixture-2"  # Last link, after an icon.
    assert rankings[1]["organization"] == "Anthropic"
    assert {entry["organization"] for entry in rankings} == {"Google", "Anthropic", "OpenAI", "xAI"}
    assert validate_rankings(rankings, "text", markdown)["valid"] is True

    # Extra modern columns cannot turn a plain-text Price into an organization.
    no_suffix = "\n".join([
        "| Rank | Rank Spread | Model | Score | Votes | Price $/M | Context | Release |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        "| 1 | 1 3 | [unnamed-fixture](https://example.invalid/unnamed) |"
        " 1450±4 | 12,345 | Free | 1M | Preview |",
    ])
    assert "organization" not in parse_lmarena_markdown(no_suffix, "text")[0]


def test_legacy_lmarena_columns_and_invalid_current_ci():
    legacy = "\n".join([
        "| Rank | Rank Spread | Model | Score | 95% CI (±) | Votes | Organization | License |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        "| 1 | 1◄─►1 | [legacy-model](https://example.invalid/legacy) | 1489 Preliminary | ±5 | 26,385 | Google | Proprietary |",
    ])
    assert parse_lmarena_markdown(legacy, "text") == [{
        "rank": 1, "model": "legacy-model", "score": 1489,
        "votes": 26_385, "organization": "Google",
    }]

    insufficient = _current_lmarena_markdown(9).replace("1494±4Preliminary", "1494±bad")
    rankings = parse_lmarena_markdown(insufficient, "text")
    assert len(rankings) == 8
    assert validate_rankings(rankings, "text", insufficient)["valid"] is False


def test_provider_outage_preserves_last_good_file(tmp_path, monkeypatch):
    output_file = tmp_path / "models_leaderboard.yml"
    output_file.write_text(yaml.safe_dump(VALID_DATA))

    provider_models = {"working-model": {
        "name": "Working Model", "provider_id": "example", "country_origin": "US",
    }}
    monkeypatch.setattr(aggregate_leaderboards, "load_provider_models", lambda: provider_models)
    monkeypatch.setattr(aggregate_leaderboards, "build_external_id_index", lambda _models: {})

    async def failed_lmarena(*, category):
        return {"rankings": [], "validation": {"valid": False}}

    async def failed_openrouter():
        return {"leaderboard": [], "validation": {"valid": False}}

    monkeypatch.setattr(aggregate_leaderboards, "fetch_lmarena_data", failed_lmarena)
    monkeypatch.setattr(aggregate_leaderboards, "fetch_openrouter_data", failed_openrouter)

    with pytest.raises(ValueError, match="LMArena ranking source failed validation"):
        asyncio.run(aggregate_leaderboards.aggregate_leaderboards(output_path=output_file))

    assert yaml.safe_load(output_file.read_text()) == VALID_DATA


def test_partial_provider_outage_preserves_last_good_file(tmp_path, monkeypatch):
    output_file = tmp_path / "models_leaderboard.yml"
    output_file.write_text(yaml.safe_dump(VALID_DATA))

    async def working_lmarena(*, category):
        return {"rankings": [{"model": "working-model", "score": 1450}], "validation": {"valid": True}}

    async def failed_openrouter():
        return {"leaderboard": [], "validation": {"valid": False}}

    monkeypatch.setattr(aggregate_leaderboards, "fetch_lmarena_data", working_lmarena)
    monkeypatch.setattr(aggregate_leaderboards, "fetch_openrouter_data", failed_openrouter)

    with pytest.raises(ValueError, match="OpenRouter ranking source failed validation"):
        asyncio.run(aggregate_leaderboards.aggregate_leaderboards(output_path=output_file))

    assert yaml.safe_load(output_file.read_text()) == VALID_DATA


def test_zero_ranked_models_preserves_last_good_file(tmp_path, monkeypatch):
    output_file = tmp_path / "models_leaderboard.yml"
    output_file.write_text(yaml.safe_dump(VALID_DATA))

    async def empty_lmarena(*, category):
        return {"rankings": [], "validation": {"valid": True}}

    async def empty_openrouter():
        return {"leaderboard": [], "validation": {"valid": True}}

    monkeypatch.setattr(aggregate_leaderboards, "load_provider_models", lambda: {})
    monkeypatch.setattr(aggregate_leaderboards, "fetch_lmarena_data", empty_lmarena)
    monkeypatch.setattr(aggregate_leaderboards, "fetch_openrouter_data", empty_openrouter)

    with pytest.raises(ValueError, match="no ranked models"):
        asyncio.run(aggregate_leaderboards.aggregate_leaderboards(output_path=output_file))

    assert yaml.safe_load(output_file.read_text()) == VALID_DATA


def test_invalid_cache_falls_back_to_valid_file_and_repairs_cache(tmp_path, monkeypatch, leaderboard_tasks):
    output_file = tmp_path / "models_leaderboard.yml"
    output_file.write_text(yaml.safe_dump(VALID_DATA))
    monkeypatch.setattr(leaderboard_tasks, "Path", lambda _path: output_file)
    stored = {leaderboard_tasks.LEADERBOARD_CACHE_KEY: EMPTY_DATA}

    class FakeCacheService:
        async def get(self, key):
            return stored.get(key)

        async def set(self, key, value, ttl):
            stored[key] = value
            return True

        async def close(self):
            pass

    monkeypatch.setattr(leaderboard_tasks, "CacheService", FakeCacheService)

    assert asyncio.run(leaderboard_tasks.get_leaderboard_data()) == VALID_DATA
    assert yaml.safe_load(output_file.read_text()) == VALID_DATA
    assert asyncio.run(leaderboard_tasks.get_leaderboard_data()) == VALID_DATA


def test_empty_refresh_cannot_replace_cache_or_provider_ranking(tmp_path, monkeypatch, leaderboard_tasks):
    output_file = tmp_path / "models_leaderboard.yml"
    output_file.write_text(yaml.safe_dump(EMPTY_DATA))
    monkeypatch.setattr(leaderboard_tasks, "Path", lambda _path: output_file)
    stored = {leaderboard_tasks.LEADERBOARD_CACHE_KEY: VALID_DATA}

    class FakeCacheService:
        async def get(self, key):
            return stored.get(key)

        async def set(self, key, value, ttl):
            stored[key] = value
            return True

        async def close(self):
            pass

    monkeypatch.setattr(leaderboard_tasks, "CacheService", FakeCacheService)

    assert asyncio.run(leaderboard_tasks._update_cache_async(EMPTY_DATA)) is False
    assert leaderboard_tasks.refresh_leaderboard_cache.run()["success"] is False
    assert stored[leaderboard_tasks.LEADERBOARD_CACHE_KEY] == VALID_DATA


def test_queued_refreshes_share_one_provider_slot(monkeypatch, leaderboard_tasks):
    owners = {}
    provider_calls = []

    class FakeClient:
        async def set(self, key, value, *, ex, nx):
            assert ex == leaderboard_tasks.LEADERBOARD_REFRESH_COOLDOWN
            assert nx is True
            if key in owners:
                return False
            owners[key] = value
            return True

        async def get(self, key):
            return owners.get(key)

    class FakeCacheService:
        @property
        async def client(self):
            return FakeClient()

        async def close(self):
            pass

    async def aggregate(_category):
        provider_calls.append(1)
        return VALID_DATA

    async def update_cache(_data):
        return True

    monkeypatch.setattr(leaderboard_tasks, "CacheService", FakeCacheService)
    monkeypatch.setattr(leaderboard_tasks, "_aggregate_leaderboard_async", aggregate)
    monkeypatch.setattr(leaderboard_tasks, "_update_cache_async", update_cache)

    results = [leaderboard_tasks.update_leaderboard_daily.run() for _ in range(12)]
    assert results[0]["success"] is True
    assert all(result.get("skipped") for result in results[1:])
    assert len(provider_calls) == 1


def test_failed_refresh_owner_can_retry_but_backlog_cannot(monkeypatch, leaderboard_tasks):
    owners = {}

    class FakeClient:
        async def set(self, key, value, *, ex, nx):
            if key in owners:
                return False
            owners[key] = value
            return True

        async def get(self, key):
            return owners.get(key, "").encode()

    class FakeCacheService:
        @property
        async def client(self):
            return FakeClient()

        async def close(self):
            pass

    monkeypatch.setattr(leaderboard_tasks, "CacheService", FakeCacheService)
    claim = leaderboard_tasks._claim_refresh_slot_async

    assert asyncio.run(claim("text", "failed-owner", 0)) is True
    assert asyncio.run(claim("text", "queued-other", 0)) is False
    assert asyncio.run(claim("text", "failed-owner", 1)) is True
    assert asyncio.run(claim("text", "queued-other", 1)) is False
    assert asyncio.run(claim("text", "failed-owner", 4)) is False


def test_failed_scrape_keeps_real_model_selection_available(tmp_path, monkeypatch, leaderboard_tasks):
    """The preserved YAML reaches Auto selection through the real cache reader."""
    from backend.apps.ai.utils import model_selector

    backend_dir = Path(__file__).resolve().parents[1]
    original = yaml.safe_load((backend_dir / "data/models_leaderboard.yml").read_text())
    assert original["rankings"][0]["model_id"] == "gemini-3.7-flash"
    output_file = tmp_path / "models_leaderboard.yml"
    output_file.write_text(yaml.safe_dump(original))

    async def failed_lmarena(*, category):
        return {"rankings": [], "validation": {"valid": False}}

    async def failed_openrouter():
        return {"leaderboard": [], "validation": {"valid": False}}

    monkeypatch.setattr(aggregate_leaderboards, "fetch_lmarena_data", failed_lmarena)
    monkeypatch.setattr(aggregate_leaderboards, "fetch_openrouter_data", failed_openrouter)
    monkeypatch.setattr(aggregate_leaderboards, "PROVIDERS_DIR", backend_dir / "providers")
    monkeypatch.setattr(leaderboard_tasks, "Path", lambda _path: output_file)
    monkeypatch.setattr(model_selector, "PROVIDERS_DIR", backend_dir / "providers")
    monkeypatch.setattr(model_selector, "_auto_select_cache", None)

    cache = {leaderboard_tasks.LEADERBOARD_CACHE_KEY: EMPTY_DATA}

    class FakeCacheService:
        async def get(self, key):
            return cache.get(key)

        async def set(self, key, value, ttl):
            cache[key] = value
            return True

        async def close(self):
            pass

    monkeypatch.setattr(leaderboard_tasks, "CacheService", FakeCacheService)

    with pytest.raises(ValueError, match="LMArena ranking source failed validation"):
        asyncio.run(aggregate_leaderboards.aggregate_leaderboards(output_path=output_file))

    selector = asyncio.run(model_selector.get_model_selector())
    selection = selector.select_models(
        task_area="general",
        complexity="complex",
        available_model_ids=["gemini-3.7-flash", "google/gemini-3.7-flash"],
    )

    assert yaml.safe_load(output_file.read_text()) == original
    assert json.loads(cache[leaderboard_tasks.LEADERBOARD_CACHE_KEY]) == original
    assert selection.primary_model_id == "google/gemini-3.7-flash"
