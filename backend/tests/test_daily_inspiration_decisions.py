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


@pytest.fixture(autouse=True)
def source_only_tests(monkeypatch):
    # Pixel transport/abstention have separate thumbnail integration coverage.
    async def visual(rows, _client):
        return rows
    monkeypatch.setattr(decisions, "review_thumbnails", visual)
    # The real semantic-review model boundary has its own focused offline suite.
    async def semantic(rows, *_args, **_kwargs):
        return rows
    monkeypatch.setattr(decisions, "review_copy_candidates", semantic)


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
        elif key.endswith("_language"):
            answers[key] = {"type": "choice", "choice": "correct",
                            "probabilities": {"correct": 1.0}, "confidence": 1.0}
        elif key.endswith(("_coherence", "_relevance")):
            choice = "coherent" if key.endswith("_coherence") else "relevant"
            answers[key] = {"type": "choice", "choice": choice,
                            "probabilities": {choice: 1.0}, "confidence": 1.0}
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
        answers["candidate_000_assistant_response_grounding"] = {"type": "choice", "choice": "unsupported",
            "probabilities": {"unsupported": 1.0}, "confidence": 1.0}
        assert "outside knowledge" in body["state"]["grounding_rubric"]
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


@pytest.mark.parametrize("model", [config.MERCURY_WRITER])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_writer_selection_is_scoped_and_allowlisted(monkeypatch, model):
    monkeypatch.setenv("DAILY_INSPIRATION_WRITER_MODEL", model)
    assert config.writer_model() == model
    monkeypatch.setenv("DAILY_INSPIRATION_WRITER_MODEL", config.MISTRAL_WRITER)
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
    from backend.apps.ai.daily_inspiration.media_coherence import (
        canonical_wiki_review_source, editorial_review_digest, is_inspiration_media_coherent,
    )
    scope = {"json": json, "review_candidates": review,
             "canonical_wiki_review_source": canonical_wiki_review_source,
             "editorial_review_digest": editorial_review_digest}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)
    record = {"id": "legacy", "content_type": content_type, "title": "Generated title",
              "language": "en", "phrase": "How do clouds form?",
              "assistant_response": "Vapor condenses into droplets."}
    if content_type == "wiki":
        record["wiki_metadata"] = {"wiki_title": "Cloud", "source_language": "en",
            "title": "Cloud formation", "extract": "Vapor condenses into droplets."}
    reviewed = await scope["_review_pool_entries"]([record], Secrets(), "test")
    assert len(reviewed) == 1
    assert reviewed[0]["editorial_review"] == editorial_review_digest(reviewed[0])
    if content_type == "wiki":
        assert is_inspiration_media_coherent(reviewed[0])
        assert captured[0]["title"] == record["wiki_metadata"]["title"]
        assert captured[0]["extract"] == record["wiki_metadata"]["extract"]
    assert captured[0]["channel_name"] == expected_channel
    assert captured[0]["content_type"] == content_type


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_decision", [None, "coherence", "follow_up_0_relevance"])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_japanese_paraphrase_and_source_followups_use_separate_semantic_decisions(failed_decision):
    async def handler(request):
        body = json.loads(request.content)
        assert "never require word overlap" in body["questions"]["candidate_000_coherence"]["instructions"]
        assert "wind" in body["questions"]["candidate_000_follow_up_0_relevance"]["instructions"]
        answers = native_answers(body["questions"])
        if failed_decision:
            choice = "mismatch" if failed_decision == "coherence" else "drift"
            answers[f"candidate_000_{failed_decision}"] = {"type": "choice", "choice": choice,
                "probabilities": {choice: 1.0}, "confidence": 1.0}
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": answers})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rows = await decisions.review_candidates([{"title": "雪の結晶ができる仕組み",
            "description": "雲の水蒸気が氷になり、六角形の結晶に成長します。",
            "card_title": "空から届く六角形", "assistant_response": "雲の中で水分が凍ります。",
            "follow_up_suggestions": ["六角形になる理由は？"]}], Secrets(),
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0))
    assert bool(rows) == (failed_decision is None)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_field,verdict", [
    ("phrase_grounding", "unsupported"),
    ("card_title_language", "wrong"),
    ("assistant_response_grounding", "uncertain"),
    ("follow_up_1_relevance", "drift"),
    ("follow_up_2_language", "wrong"),
])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_one_failed_field_withholds_card_and_returns_source_bound_repair_code(failed_field, verdict):
    feedback = {}
    async def handler(request):
        body = json.loads(request.content)
        assert "_review_identity" not in json.dumps(body["state"])
        answers = native_answers(body["questions"])
        key = "candidate_000_" + failed_field
        assert key in answers
        answers[key] = {"type": "choice", "choice": verdict,
                        "probabilities": {verdict: 1.0}, "confidence": .95}
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": answers})
    candidate = {"title": "Pollination", "description": "Pollen moves between different plants.",
                 "card_title": "Pollen transfer", "phrase": "Pollen moves between plants.",
                 "assistant_response": "Pollen moves between plants. What is pollination?",
                 "follow_up_suggestions": ["What is pollen?", "How does pollen move?", "Which plants?"],
                 "language": "fr", "_review_identity": "server-source"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await decisions.review_candidates([candidate], Secrets(), rejection_feedback=feedback,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0))
    assert result == []
    assert list(feedback) == ["server-source"]
    assert len(feedback["server-source"]) == 1
    assert feedback["server-source"][0].endswith(":" + verdict)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_copy_partitions_keep_each_field_question_with_its_source():
    candidates = [{"title": f"Source {index}", "description": "Water evaporates and vapor condenses.",
                   "card_title": "Water cycle", "phrase": "Water evaporates.",
                   "assistant_response": "Vapor condenses. How does water evaporate?",
                   "follow_up_suggestions": ["What is vapor?", "How does water evaporate?", "What condenses?"],
                   "language": "fr"} for index in range(10)]
    calls = []
    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        ids = {row["candidate_id"] for row in body["state"]["candidates"]}
        for key in body["questions"]:
            assert any(key.startswith(identity + "_") for identity in ids)
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": native_answers(body["questions"])})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await decisions.review_candidates(candidates, Secrets(), rank=True,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0))
    assert len(result) == 10 and len(calls) > 1
    assert sum(len(call["state"]["candidates"]) for call in calls) == 10


def completed_card(language, identity):
    return {"title": "Cloud formation", "description": "Water evaporates and condenses.",
            "card_title": "Water cycle", "phrase": "Water evaporates. What condenses?",
            "assistant_response": "Water evaporates. Vapor condenses. What happens next?",
            "follow_up_suggestions": ["What evaporates?", "What is vapor?", "What condenses?"],
            "language": language, "_review_identity": identity, "record": object()}


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_focus_review_routes_only_completed_english_german_and_preserves_other_jev_gates(monkeypatch):
    rows = [completed_card('en', 'english'), completed_card('de-DE', 'german'),
            completed_card('ja', 'japanese'), {'title': 'Public source', 'language': 'en'}]
    seen = []

    async def semantic(candidates, *_args, **_kwargs):
        seen.extend(candidates)
        return candidates

    async def handler(request):
        body = json.loads(request.content)
        questions = body['questions']
        for index in (0, 1):
            prefix = f'candidate_{index:03d}_'
            assert prefix + 'policy' in questions and prefix + 'coherence' in questions
            assert not any(key.startswith(prefix) and key.endswith(('_grounding', '_language', '_relevance'))
                           for key in questions)
        assert 'candidate_002_card_title_language' in questions
        assert 'candidate_002_follow_up_2_relevance' in questions
        assert 'candidate_003_policy' in questions
        assert 'candidate_003_coherence' not in questions
        return httpx.Response(200, json={'model': 'jev-1.14.0', 'answers': native_answers(questions)})

    monkeypatch.setattr(decisions, 'review_copy_candidates', semantic)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        admitted = await decisions.review_candidates(rows, Secrets(), client=JevDecisionClient(
            secrets_manager=Secrets(), http_client=http, provider='typesafe', max_retries=0))
    assert len(admitted) == 4
    assert [row['_review_identity'] for row in seen] == ['english', 'german']
    assert admitted[0] is seen[0] and admitted[1] is seen[1]
    assert admitted[0]['record'] is rows[0]['record']


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_gate', ['policy', 'coherence', 'thumbnail'])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_gemini_never_overrides_failed_jev_policy_coherence_or_pixels(monkeypatch, failed_gate):
    calls = []
    row = completed_card('en', 'server-only')
    row.update(youtube_id='DOH-HNotTaE', content_type='video')

    async def semantic(candidates, *_args, **_kwargs):
        calls.append(candidates)
        return candidates

    async def visual(candidates, _client):
        return [] if failed_gate == 'thumbnail' else candidates

    async def handler(request):
        body = json.loads(request.content)
        answers = native_answers(body['questions'])
        if failed_gate != 'thumbnail':
            choice = 'reject' if failed_gate == 'policy' else 'mismatch'
            answers['candidate_000_' + failed_gate] = {'type': 'choice', 'choice': choice,
                'probabilities': {choice: 1.0}, 'confidence': 1.0}
        return httpx.Response(200, json={'model': 'jev-1.14.0', 'answers': answers})

    monkeypatch.setattr(decisions, 'review_copy_candidates', semantic)
    monkeypatch.setattr(decisions, 'review_thumbnails', visual)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await decisions.review_candidates([row], Secrets(), client=JevDecisionClient(
            secrets_manager=Secrets(), http_client=http, provider='typesafe', max_retries=0)) == []
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('result', ['outage', 'negative', 'forged'])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_focus_failure_withholds_only_focus_rows_and_never_accepts_forged_objects(monkeypatch, result):
    rows = [completed_card('en', 'focus'), completed_card('fr', 'nonfocus')]
    feedback = {}

    async def semantic(candidates, *_args, **kwargs):
        if result == 'outage':
            raise ConnectionError('must not leak public copy')
        if result == 'negative':
            kwargs['rejection_feedback']['focus'] = ['phrase.grounding:causal_role']
            return []
        return [dict(candidates[0])]

    async def handler(request):
        questions = json.loads(request.content)['questions']
        return httpx.Response(200, json={'model': 'jev-1.14.0', 'answers': native_answers(questions)})

    monkeypatch.setattr(decisions, 'review_copy_candidates', semantic)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        admitted = await decisions.review_candidates(rows, Secrets(), rejection_feedback=feedback,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider='typesafe', max_retries=0))
    assert len(admitted) == 1 and admitted[0]['_review_identity'] == 'nonfocus'
    if result == 'outage':
        assert feedback == {'focus': ['review:unavailable']}
    elif result == 'negative':
        assert feedback == {'focus': ['phrase.grounding:causal_role']}


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_source_only_discovery_never_calls_semantic_reviewer(monkeypatch):
    calls = []

    async def semantic(*_args, **_kwargs):
        calls.append(True)
        return []

    async def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={'model': 'jev-1.14.0', 'answers': native_answers(body['questions'])})

    monkeypatch.setattr(decisions, 'review_copy_candidates', semantic)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        admitted = await decisions.review_candidates([{'title': 'Cloud', 'language': 'en'},
            {'title': 'Wolke', 'language': 'de'}], Secrets(), rank=True,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider='typesafe', max_retries=0))
    assert len(admitted) == 2 and calls == []
