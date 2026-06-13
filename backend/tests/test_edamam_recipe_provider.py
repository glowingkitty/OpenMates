# backend/tests/test_edamam_recipe_provider.py
#
# Contract tests for the Edamam-backed Nutrition recipe provider.
# These tests pin the provider behavior before replacing the older REWE search:
# one search request should fetch rich fields, filter missing instructions,
# paginate only when necessary, normalize inconsistent steps, and expose errors.

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.apps.nutrition.providers import edamam_recipe_provider as provider


class FakeSecretsManager:
    async def get_secret(self, secret_path: str, secret_key: str) -> str | None:
        secrets = {
            (provider.EDAMAM_SECRET_PATH, "app_id"): "test-app-id",
            (provider.EDAMAM_SECRET_PATH, "app_key"): "test-app-key",
        }
        return secrets.get((secret_path, secret_key))


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.request = httpx.Request("GET", "https://api.edamam.com/api/recipes/v2")

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


def _hit(label: str, instructions: list[str] | None, url: str | None = None) -> dict[str, Any]:
    return {
        "recipe": {
            "uri": f"http://www.edamam.com/ontologies/edamam.owl#recipe_{label.lower().replace(' ', '-')}",
            "label": label,
            "source": "Example Source",
            "url": url or f"https://example.com/{label.lower().replace(' ', '-')}",
            "image": "https://example.com/image.jpg",
            "images": {"REGULAR": {"url": "https://example.com/image.jpg", "width": 300, "height": 300}},
            "ingredientLines": ["1 cup test ingredient"],
            "ingredients": [{"text": "1 cup test ingredient", "quantity": 1, "measure": "cup", "food": "test ingredient"}],
            "instructionLines": instructions or [],
            "yield": 4,
            "totalTime": 20,
            "calories": 400,
            "dietLabels": ["Low-Sodium"],
            "healthLabels": ["Vegetarian"],
            "cautions": [],
            "cuisineType": ["american"],
            "mealType": ["lunch/dinner"],
            "dishType": ["main course"],
            "totalNutrients": {"PROCNT": {"label": "Protein", "quantity": 20, "unit": "g"}},
        }
    }


@pytest.mark.asyncio
async def test_search_requests_instruction_fields_and_filters_missing_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(
            {
                "count": 3,
                "hits": [
                    _hit("No Steps", []),
                    _hit("Has Steps", ["Step 1: Mix.", "Step 2: Serve."]),
                    _hit("Also Has Steps", ["Bake."]),
                ],
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await provider.search_recipes(
        query="edamame",
        max_results=2,
        secrets_manager=FakeSecretsManager(),
    )

    assert len(calls) == 1
    params = calls[0]["params"]
    assert params["q"] == "edamame"
    assert params["field"].count("instructionLines") == 1
    assert [recipe.title for recipe in result.recipes] == ["Has Steps", "Also Has Steps"]
    assert result.filtered_out_missing_instructions == 1
    assert all(recipe.instructions for recipe in result.recipes)


@pytest.mark.asyncio
async def test_search_paginates_only_when_needed_and_preserves_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        if len(calls) == 1:
            return FakeResponse(
                {
                    "count": 4,
                    "hits": [_hit("Missing", []), _hit("One", ["Cook."])],
                    "_links": {"next": {"href": "https://api.edamam.com/api/recipes/v2?page=2"}},
                }
            )
        return FakeResponse({"count": 4, "hits": [_hit("Two", ["Serve."])]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await provider.search_recipes(
        query="edamame",
        max_results=2,
        secrets_manager=FakeSecretsManager(),
    )

    assert [recipe.title for recipe in result.recipes] == ["One", "Two"]
    assert result.pages_requested == 2
    assert result.raw_hits_seen == 3
    assert calls[1]["params"]["field"].count("instructionLines") == 1


def test_normalize_instruction_lines_splits_combined_step_markers() -> None:
    instructions = provider.normalize_instruction_lines(
        [
            "Step 1: Mix flour. Step 2: Add water. Step 3: Serve immediately.",
            "Enjoy while warm.",
        ]
    )

    assert instructions == [
        {"step": 1, "text": "Mix flour."},
        {"step": 2, "text": "Add water."},
        {"step": 3, "text": "Serve immediately."},
        {"step": 4, "text": "Enjoy while warm."},
    ]


@pytest.mark.asyncio
async def test_search_maps_rate_limit_to_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse({"status": "error", "message": "Limits exceeded"}, status_code=429)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(provider.EdamamProviderError) as excinfo:
        await provider.search_recipes(
            query="edamame",
            max_results=2,
            secrets_manager=FakeSecretsManager(),
        )

    assert excinfo.value.status_code == 429
    assert "rate limit" in str(excinfo.value).lower()
