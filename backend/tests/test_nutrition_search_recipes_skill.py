# backend/tests/test_nutrition_search_recipes_skill.py
#
# Contract tests for the Nutrition search_recipes skill after the Edamam
# provider replacement. These tests verify the LLM-facing request shape and the
# skill/provider boundary, not live Edamam network behavior.

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

celery_stub = ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)


class FakeSecretsManager:
    async def get_secret(self, secret_path: str, secret_key: str) -> str | None:
        return "test-secret"


def _skill() -> Any:
    from backend.apps.nutrition.skills.search_recipes import SearchRecipesSkill

    return SearchRecipesSkill(
        app=None,
        app_id="nutrition",
        skill_id="search_recipes",
        skill_name="Search Recipes",
        skill_description="Search recipes",
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_search_recipes_requires_query_not_legacy_filters() -> None:
    response = await _skill().execute(
        requests=[{"filters": ["vegan", "pasta"], "max_results": 3}],
        secrets_manager=FakeSecretsManager(),
    )

    assert response.provider == "Edamam"
    assert response.results
    assert response.results[0]["error"]
    assert "query" in response.results[0]["error"].lower()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_search_recipes_calls_edamam_provider_with_query_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_search_recipes(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return {
            "recipes": [
                {
                    "type": "recipe",
                    "provider": "Edamam",
                    "uid": "recipe-1",
                    "title": "Vegan Pasta",
                    "recipe_url": "https://example.com/vegan-pasta",
                    "image_url": "https://example.com/vegan-pasta.jpg",
                    "ingredients": [{"text": "1 cup pasta"}],
                    "instructions": [{"step": 1, "text": "Cook pasta."}],
                }
            ],
            "total_available": 20,
            "raw_hits_seen": 20,
            "filtered_out_missing_instructions": 0,
        }

    monkeypatch.setattr(
        "backend.apps.nutrition.skills.search_recipes.search_recipes",
        fake_search_recipes,
    )
    async def passthrough_sanitize(**kwargs: Any) -> Any:
        return kwargs["payload"]

    monkeypatch.setattr(
        "backend.apps.nutrition.skills.search_recipes.sanitize_long_text_fields_in_payload",
        passthrough_sanitize,
    )

    response = await _skill().execute(
        requests=[
            {
                "query": "pasta",
                "health": ["vegan"],
                "time": "1-30",
                "max_results": 99,
            }
        ],
        secrets_manager=FakeSecretsManager(),
    )

    assert response.provider == "Edamam"
    assert response.total_available == 20
    assert response.results[0]["results"][0]["provider"] == "Edamam"
    assert calls[0]["query"] == "pasta"
    assert calls[0]["health"] == ["vegan"]
    assert calls[0]["time"] == "1-30"
    assert calls[0]["max_results"] == 10


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_search_recipes_module_exports_typed_skill_contract() -> None:
    import backend.apps.nutrition.skills.search_recipes as module

    request = module.SearchRecipesRequest(requests=[{"query": "vegetable soup"}])
    assert request.requests[0].query == "vegetable soup"
    assert module.SearchRecipesSkill.__module__ == module.__name__
    assert module.SearchRecipesResponse(results=[]).results == []
