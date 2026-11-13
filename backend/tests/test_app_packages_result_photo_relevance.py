"""Photo ranking of installed-provider results: bounded input, truthful fallback."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from backend.shared.app_packages import result_photo_relevance as relevance
from backend.shared.providers.typesafe.client import DecisionProviderUnavailable
from backend.shared.providers.typesafe.models import ScoreAnswer

PHOTO = b"prepared-jpeg"


def _result(title: str, **extra: Any) -> Dict[str, Any]:
    return {"title": title, "provider": "My Provider", "provider_id": "my_provider",
            "image_url": f"https://example.org/{title}.jpg", "purchase_url": f"https://example.org/{title}",
            "product_id": f"id-{title}", **extra}


def _answer(score: float) -> ScoreAnswer:
    return ScoreAnswer.model_construct(type="score", score=score)


class _FakeClient:
    """Scores each candidate by the ``fit`` fact of its projection."""

    calls: List[Dict[str, Any]] = []
    failure: Exception | None = None

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def evaluate_with_images(self, *, state: Any, questions: Any, images: Any) -> Any:
        type(self).calls.append({"state": state, "questions": questions, "images": images})
        if type(self).failure is not None:
            raise type(self).failure
        return SimpleNamespace(answers={
            row["candidate_id"]: _answer(row["data"]["fit"]) for row in state["candidates"]
        })


@pytest.fixture
def fake_decisions(monkeypatch):
    _FakeClient.calls, _FakeClient.failure = [], None

    async def fake_download(url: str) -> bytes:
        if "broken" in url:
            raise ValueError("unreadable")
        return PHOTO

    monkeypatch.setattr("backend.apps.ai.utils.internal_decisions.JevDecisionClient", _FakeClient)
    monkeypatch.setattr(relevance, "download_public_image", fake_download)
    return _FakeClient


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_only_listed_skills_with_criteria_are_ranked_and_ask_for_a_larger_pool():
    item = {"query": "lamp", "relevance_criteria": "brass, art deco", "max_results": 3}
    assert relevance.wants_photo_ranking("shopping", "search_products", item)
    assert relevance.wants_photo_ranking("travel", "search_stays", item)
    assert not relevance.wants_photo_ranking("events", "search", item)
    assert not relevance.wants_photo_ranking("shopping", "search_products", {**item, "relevance_criteria": "  "})
    assert relevance.widen_candidate_pool(item)["max_results"] == relevance.CANDIDATE_POOL
    assert item["max_results"] == 3 and relevance.requested_limit(item) == 3
    assert relevance.widen_candidate_pool({"query": "lamp"}) == {"query": "lamp"}


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
def test_photo_urls_and_projection_hide_links_and_identifiers():
    stay = {"name": "Example Hotel", "images": [{"thumbnail": "https://example.org/t1.jpg",
                                                 "original_image": "https://example.org/o1.jpg"},
                                                {"original_image": "https://example.org/o2.jpg"}, "https://example.org/3.jpg"],
            "property_token": "secret-token", "booking_url": "https://example.org/book", "rating": 4.5}
    assert relevance.photo_urls(stay) == ["https://example.org/t1.jpg", "https://example.org/o2.jpg"]
    assert dict(relevance.result_projection(stay)) == {"name": "Example Hotel", "rating": 4.5}
    assert dict(relevance.result_projection(_result("lamp", fit=3))) == {"title": "lamp", "fit": 3}


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_results_are_ordered_by_score_and_clear_conflicts_are_dropped(fake_decisions):
    results = [_result("conflict", fit=0), _result("plausible", fit=2), _result("best", fit=4),
               _result("broken", fit=4), {"title": "no photo", "provider_id": "my_provider", "fit": 4}]
    ranking = await relevance.rank_results_by_photos(
        results, relevance_criteria=" brass ", searched="lamp", secrets_manager=None)
    assert ranking.applied
    assert [r["title"] for r in ranking.results] == ["best", "plausible", "broken", "no photo"]
    assert ranking.results[0]["visual_match"] == {"status": "evaluated", "score": 4, "score_min": 0, "score_max": 4}
    assert ranking.results[-1]["visual_match"] == {"status": "unavailable"}
    state = fake_decisions.calls[0]["state"]
    assert state["relevance_criteria"] == "brass" and state["searched_for"] == "lamp"
    serialized = str(state) + str(fake_decisions.calls[0]["questions"])
    assert "example.org" not in serialized and "id-best" not in serialized
    assert set(fake_decisions.calls[0]["images"].values()) == {PHOTO}


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_failed_decision_or_missing_photos_keep_provider_order(fake_decisions):
    results = [_result("first", fit=1), _result("second", fit=4)]
    fake_decisions.failure = DecisionProviderUnavailable("down")
    failed = await relevance.rank_results_by_photos(
        results, relevance_criteria="brass", searched="lamp", secrets_manager=None)
    assert not failed.applied and failed.results == results
    fake_decisions.calls.clear()
    without = [{"title": "plain", "provider_id": "my_provider"}]
    unranked = await relevance.rank_results_by_photos(
        without, relevance_criteria="brass", searched="lamp", secrets_manager=None)
    assert not unranked.applied and unranked.results == without and not fake_decisions.calls


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_batches_stay_within_the_image_limit(fake_decisions):
    results = [_result(f"item{n}", fit=2, image_urls=[f"https://example.org/item{n}-b.jpg"]) for n in range(12)]
    ranking = await relevance.rank_results_by_photos(
        results, relevance_criteria="brass", searched="lamp", secrets_manager=None)
    assert ranking.applied and len(ranking.results) == 12
    assert [len(call["state"]["candidates"]) for call in fake_decisions.calls] == [5, 5, 2]
    assert all(len(call["images"]) <= 18 for call in fake_decisions.calls)
