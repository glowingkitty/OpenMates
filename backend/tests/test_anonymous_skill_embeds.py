"""Transient anonymous app-skill embeds for composite and non-composite skills.

Regression: production 2026-11-15 logged "No child_type defined for app_id='math',
skill_id='calculate'" from the anonymous embed builder, so signed-out users got
no calculation embed. Non-composite skills must stream one finished
``app_skill_use`` embed with inline results, the shape the authenticated path
creates and ``MathCalculateEmbedPreview`` reads.

Code: backend/apps/ai/processing/anonymous_skill_embeds.py
"""

from __future__ import annotations

import json

import pytest
from toon_format import decode

from backend.apps.ai.processing.anonymous_skill_embeds import build_anonymous_skill_embeds
from backend.core.api.app.services.embed_service import EmbedService, _flatten_for_toon_tabular


class _EmptyAppsMetadataCache:
    async def get_discovered_apps_metadata(self) -> dict:
        return {}


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=apps.anonymous.local-results-and-promotion
async def test_math_calculate_has_no_composite_child_type() -> None:
    child_type = await EmbedService.get_composite_child_embed_type(
        "math", "calculate", cache_service=_EmptyAppsMetadataCache()
    )
    assert child_type is None


# contract-test: supporting surface=rest_api assertions=apps.anonymous.local-results-and-promotion
def test_non_composite_skill_yields_one_embed_with_inline_results() -> None:
    results = [{"expression": "2+2", "result": "4", "embed_ref": "calc-ref"}]
    embeds = build_anonymous_skill_embeds(
        app_id="math",
        skill_id="calculate",
        results=results,
        preview_data={"result_count": 1, "results_toon": "ignored"},
        child_type=None,
        flatten=_flatten_for_toon_tabular,
    )

    assert len(embeds.payloads) == 1
    embed = embeds.payloads[0]
    assert embed["type"] == "app_skill_use"
    assert embed["status"] == "finished"
    assert embed["embed_ids"] is None
    assert "parent_embed_id" not in embed
    content = decode(embed["content"])
    assert content["app_id"] == "math"
    assert content["skill_id"] == "calculate"
    assert content["result_count"] == 1
    assert content["results"][0]["expression"] == "2+2"
    assert content["results"][0]["result"] == "4"
    assert "results_toon" not in content
    assert content["embed_ref"] == embed["embed_ref"]
    assert json.loads(embeds.reference) == {
        "type": "app_skill_use",
        "embed_id": embed["embed_id"],
        "app_id": "math",
        "skill_id": "calculate",
    }


# contract-test: supporting surface=rest_api assertions=apps.anonymous.local-results-and-promotion
def test_composite_skill_keeps_parent_and_child_graph() -> None:
    results = [
        {"title": "First", "url": "https://example.org/1", "embed_ref": "first-ref"},
        {"title": "Second", "url": "https://example.org/2", "embed_ref": "second-ref"},
    ]
    embeds = build_anonymous_skill_embeds(
        app_id="news",
        skill_id="search",
        results=results,
        preview_data={"query": "example", "result_count": 2},
        child_type="news_result",
        flatten=_flatten_for_toon_tabular,
    )

    parent, *children = embeds.payloads
    assert parent["type"] == "app_skill_use"
    assert parent["embed_ids"] == [child["embed_id"] for child in children]
    assert [child["type"] for child in children] == ["news_result", "news_result"]
    assert all(child["parent_embed_id"] == parent["embed_id"] for child in children)
    parent_content = decode(parent["content"])
    assert parent_content["query"] == "example"
    assert "results" not in parent_content
    assert [decode(child["content"])["embed_ref"] for child in children] == ["first-ref", "second-ref"]
    assert json.loads(embeds.reference)["embed_id"] == parent["embed_id"]
