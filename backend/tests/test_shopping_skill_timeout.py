"""Shopping comparison gets a bounded assistant envelope; other tools stay unchanged."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.skill_executor import (
    DEFAULT_SKILL_TIMEOUT, execute_skill_with_multiple_requests, get_skill_timeout,
)


@pytest.mark.parametrize("arguments", [
    {"reference_images": ["photo.png"]},
    {"relevance_criteria": "blue floral"},
    {"requests": [{"query": "plain"}, {"reference_images": ["photo.png"]}]},
    {"requests": [{"relevance_criteria": "blue floral"}, {"query": "plain"}]},
])
def test_shopping_reference_or_relevance_gets_thirty_seconds(arguments):
    assert get_skill_timeout("shopping", "search_products", arguments) == 30.0


@pytest.mark.parametrize("arguments", [
    {}, {"query": "plain"}, {"reference_images": []}, {"reference_images": None},
    {"relevance_criteria": "  "}, {"relevance_criteria": None},
    {"requests": []}, {"requests": [{"reference_images": []}, {"query": "plain"}]},
    {"requests": [None, {"reference_images": [None, "  "]}]},
    {"requests": "invalid"},
])
def test_neutral_shopping_search_keeps_default(arguments):
    assert get_skill_timeout("shopping", "search_products", arguments) == DEFAULT_SKILL_TIMEOUT == 20.0


@pytest.mark.parametrize("app_id,skill_id", [("web", "search"), ("shopping", "other"), ("ai", "decide")])
def test_other_skills_keep_default(app_id, skill_id):
    assert get_skill_timeout(app_id, skill_id, {"requests": [{"reference_images": ["photo.png"], "relevance_criteria": "fit"}]}) == 20.0


@pytest.mark.asyncio
@pytest.mark.parametrize("requests", [[{"reference_images": ["photo.png"]}], [
    {"relevance_criteria": "blue floral"}, {"query": "plain"},
]])
async def test_selection_does_not_replace_explicit_executor_timeouts(monkeypatch, requests):
    from backend.apps.ai.processing import skill_executor
    dispatch = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(skill_executor, "execute_skill", dispatch)
    result = await execute_skill_with_multiple_requests(
        "shopping", "search_products", {"requests": requests}, timeout=.5)
    assert result == [{"results": []}]
    assert dispatch.await_args.args[3] == .5
