"""Editorial admission and ranking contracts at the native decision boundary."""
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
import json
import ast
from pathlib import Path

import httpx
import pytest

from backend.apps.ai.daily_inspiration import decisions, validator
from backend.shared.providers.typesafe.client import JevDecisionClient
from backend.apps.ai.daily_inspiration import config


class Secrets:
    async def get_secret(self, **_kwargs):
        return "test-key"


def native_answers(questions, policy=None):
    answers = {}
    for key, question in questions.items():
        if key.endswith("_policy"):
            choice = (policy or {}).get(key, "allow")
            answers[key] = {"type": "choice", "choice": choice,
                            "probabilities": {choice: 1.0}, "confidence": 1.0}
        elif key.endswith("_grounding"):
            answers[key] = {"type": "choice", "choice": "supported",
                            "probabilities": {"supported": 1.0}, "confidence": 1.0}
        elif key.endswith("_category"):
            answers[key] = {"type": "choice", "choice": "science",
                            "probabilities": {"science": 1.0}, "confidence": 1.0}
        else:
            levels = {str(i): label for i, label in enumerate(question["criteria"])}
            answers[key] = {"type": "score", "score": 4 if "001" in key else 2,
                            "legend": levels, "probabilities": {i: .2 for i in levels},
                            "confidence": .8}
    return answers


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_native_policy_precedes_fit_and_never_invents_candidates():
    original = [
        {"youtube_id": "clickbait", "title": "Secret world rulers", "description": "A conspiracy promoted as fact."},
        {"youtube_id": "useful", "title": "Cloud formation", "description": "Condensation explained."},
        {"youtube_id": "unknown", "title": "The truth"},
    ]

    async def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "jev-1.14.0"
        assert "clickbait" in body["state"]["policy"]
        assert "conspiracy" in body["state"]["policy"]
        assert "youtube_id" not in json.dumps(body["state"])
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": native_answers(
            body["questions"], {"candidate_000_policy": "reject", "candidate_002_policy": "unknown"}),
            "usage": {"input_tokens": 100}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await decisions.review_candidates(original, Secrets(), rank=True,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0))
    assert [row["youtube_id"] for row in result] == ["useful"]
    assert result[0]["editorial_category"] == "science"
    assert "editorial_category" not in original[1]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_educational_rank_is_independent_of_view_count():
    async def handler(request):
        body = json.loads(request.content)
        assert "view_count" not in json.dumps(body["state"])
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": native_answers(body["questions"])})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await decisions.review_candidates([
            {"title": "General science", "youtube_id": "popular", "view_count": 9000000},
            {"title": "Cloud formation", "youtube_id": "relevant", "view_count": 10},
        ], Secrets(), topic="cloud formation", rank=True,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0))
    assert [row["youtube_id"] for row in result] == ["relevant", "popular"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_pool_retains_public_video_description_for_later_review():
    from backend.core.api.app.services.directus.daily_inspiration_pool_methods import DailyInspirationPoolMethods
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    service = SimpleNamespace(get_items=AsyncMock(return_value=[]),
                              create_item=AsyncMock(return_value=(True, {"id": "new-row"})))
    pool = DailyInspirationPoolMethods(service)
    result = await pool.add_to_pool("fixture-id", "en", "How do clouds form?", "Cloud Formation",
        "Cooling vapor forms droplets.", "science", "video",
        video_description="Public source: cooling water vapor condenses into droplets.")
    assert result == {"id": "new-row"}
    assert service.create_item.call_args.args[1]["video_description"] == "Public source: cooling water vapor condenses into droplets."


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["outage", "missing", "low_confidence", "nonfinite"])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_outages_and_unreliable_decisions_withhold_new_content(failure):
    async def handler(request):
        if failure == "outage":
            return httpx.Response(503)
        body = json.loads(request.content)
        answers = native_answers(body["questions"])
        if failure == "missing":
            answers.pop(next(iter(answers)))
        elif failure == "low_confidence":
            answers["candidate_000_policy"]["confidence"] = .1
        else:
            answers["candidate_000_fit"]["score"] = float("nan")
            # Native invalid numeric payload, without httpx's strict JSON encoder.
            return httpx.Response(200, content=json.dumps({"model": "jev-1.14.0", "answers": answers}))
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": answers})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await decisions.review_candidates([{"title": "Cloud formation"}], Secrets(), rank=True,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0)) == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_final_review_includes_every_copy_field_and_source_evidence(monkeypatch):
    async def review(candidates, *_args, **_kwargs):
        assert candidates == [{"title": "Cloud formation", "channel_name": "Independent teacher",
            "description": "Water vapor condenses into droplets.", "card_title": "Clouds",
            "phrase": "How do clouds form?", "assistant_response": "Condensation produces droplets.",
            "follow_up_suggestions": ["Explain condensation", "What is humidity?", "Why do clouds float?"]}]
        return []
    monkeypatch.setattr(validator, "review_candidates", review)
    assert not await validator.validate_inspiration(
        "How do clouds form?", "Clouds", "Condensation produces droplets.", "Cloud formation",
        "Independent teacher", Secrets(), source_description="Water vapor condenses into droplets.",
        follow_up_suggestions=["Explain condensation", "What is humidity?", "Why do clouds float?"])


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_unsupported_claim_is_withheld_even_with_high_policy_and_fit_scores():
    async def handler(request):
        body = json.loads(request.content)
        answers = native_answers(body["questions"])
        answers["candidate_000_grounding"] = {"type": "choice", "choice": "unsupported",
            "probabilities": {"unsupported": 1.0}, "confidence": 1.0}
        assert "outside knowledge" in body["questions"]["candidate_000_grounding"]["instructions"]
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": answers})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await decisions.review_candidates([{"title": "Cloud formation",
            "description": "Water vapor condenses into droplets.",
            "assistant_response": "Every cloud weighs precisely 100 million tonnes."}], Secrets(), rank=True,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0)) == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_oversized_evidence_never_reaches_inference():
    class NoInference:
        async def evaluate(self, **_kwargs):
            pytest.fail("Oversized evidence reached inference")
    assert await decisions.review_candidates([{"title": "x" * 6001}], Secrets(), client=NoInference()) == []


@pytest.mark.parametrize("model", [config.MISTRAL_WRITER, config.MERCURY_WRITER])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_writer_selection_is_scoped_and_allowlisted(monkeypatch, model):
    monkeypatch.setenv("DAILY_INSPIRATION_WRITER_MODEL", model)
    assert config.writer_model() == model
    monkeypatch.setenv("DAILY_INSPIRATION_WRITER_MODEL", "unreviewed/arbitrary-model")
    with pytest.raises(ValueError):
        config.writer_model()


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type,expected_channel", [("video", ""), ("wiki", "Wikipedia")])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_legacy_pool_review_does_not_invent_a_source_identity(content_type, expected_channel):
    source = Path(__file__).resolve().parents[1] / "core/api/app/tasks/default_inspiration_tasks.py"
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "_review_pool_entries")
    captured = []
    async def review(rows, *_args, **_kwargs):
        captured.extend(rows)
        return rows
    scope = {"json": json, "review_candidates": review}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)
    record = {"id": "legacy", "content_type": content_type, "title": "Cloud formation",
              "phrase": "How do clouds form?", "assistant_response": "Vapor condenses into droplets."}
    assert await scope["_review_pool_entries"]([record], Secrets(), "test") == [record]
    assert captured[0]["channel_name"] == expected_channel
    assert captured[0]["content_type"] == content_type
