"""Purpose-based chat request safety: decline, strike and batching."""


from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml


from backend.apps.ai.processing import jev_preprocessing
from backend.apps.ai.processing import request_purpose_policy
from backend.apps.ai.processing.request_purpose_policy import (
    QUESTION_IDS, evaluate_request_purpose, record_request_strike, request_purpose_questions,
)
from backend.shared.providers.typesafe.batching import question_batches
from backend.shared.providers.typesafe.client import DecisionProviderUnavailable, MAX_QUESTIONS


def decisions(**changes):
    base = {"harmful_purpose": "none", "illegal_category": "none",
            "live_site_abuse": 0.0, "live_site_abuse_repeated_across_sites": 0.0}
    return {**base, **changes}


# contract-test: direct surface=rest_api assertions=safety-strikes.harmful-purpose-strikes
@pytest.mark.parametrize("purpose", ["propaganda", "hate", "disinformation", "manipulative_tabloid"])
def test_harmful_purpose_declines_with_one_strike(purpose):
    outcome = evaluate_request_purpose(decisions(harmful_purpose=purpose))
    assert outcome.strike and outcome.category == purpose and outcome.message_key == "harmful_purpose"


@pytest.mark.parametrize("category", [
    "minor_sexual_content", "non_consensual_intimate_image", "sexual_deepfake", "mass_harm_weapon"])
# contract-test: direct surface=rest_api assertions=safety-strikes.harmful-purpose-strikes
def test_illegal_categories_strike(category):
    outcome = evaluate_request_purpose(decisions(illegal_category=category))
    assert outcome.strike and outcome.message_key == "illegal_category"


# contract-test: direct surface=rest_api assertions=safety-strikes.harmful-purpose-strikes
def test_analysis_requests_are_allowed_without_strike():
    # "How does propaganda work?", fact-checking, history and labelled satire score none.
    assert evaluate_request_purpose(decisions()).action == "allow"
    assert evaluate_request_purpose(None).action == "allow"
    assert evaluate_request_purpose({"harmful_purpose": "propaganda"}).action == "allow"  # malformed


# contract-test: supporting surface=rest_api assertions=safety-strikes.harmful-purpose-strikes
def test_questions_are_listed_and_explanations_score_none():
    questions = request_purpose_questions()
    assert set(questions) == set(QUESTION_IDS)
    assert "none" in questions["harmful_purpose"]["criteria"]
    assert "Explaining, analysing" in questions["harmful_purpose"]["instructions"]


# contract-test: supporting surface=rest_api assertions=safety-strikes.harmful-purpose-strikes
def test_questions_join_public_decisions_without_a_new_batch():
    public = jev_preprocessing._public_decision_questions(True)
    assert set(QUESTION_IDS) <= set(public)
    without = {key: value for key, value in public.items() if key not in QUESTION_IDS}
    state = {"messages": ["Hello"]}
    try:
        assert len(question_batches(state, without)) == len(question_batches(state, public)) == 1
    except DecisionProviderUnavailable:
        pytest.skip("Jev input tokenizer is not installed in this environment")
    assert len(public) < MAX_QUESTIONS


class FakeCounter:
    def __init__(self):
        self.count, self.seen = 0, set()

    async def record_strike(self, *, user_id, severity, assistant_response_id):
        if assistant_response_id in self.seen:
            return SimpleNamespace(recorded=False, debounced=True, new_count=self.count, error=None)
        self.seen.add(assistant_response_id)
        self.count += 1
        return SimpleNamespace(recorded=True, debounced=False, new_count=self.count, error=None)


SOURCE = yaml.safe_load(
    (Path(__file__).parents[2] / "frontend/packages/ui/src/i18n/sources/request_purpose.yml").read_text(encoding="utf-8"))
LANGUAGES = "en de zh es fr pt ru ja ko it tr vi id pl nl ar hi th cs sv he".split()


def fake_translate(key, language):
    return SOURCE[key][language]


# contract-test: direct surface=rest_api assertions=safety-strikes.harmful-purpose-strikes
@pytest.mark.asyncio
async def test_strike_is_recorded_once_per_turn_and_second_strike_suspends():
    counter = FakeCounter()
    outcome = evaluate_request_purpose(decisions(harmful_purpose="hate"))
    suspend = AsyncMock()
    package = "backend.shared.python_utils.image_safety"
    policy = SimpleNamespace(strike_warning=lambda *args: "Suspended.")
    modules = {
        package: SimpleNamespace(strike_policy=policy),
        f"{package}.strike_policy": policy,
        f"{package}.account_suspension": SimpleNamespace(suspend_account_for_strikes=suspend),
        f"{package}.strike_counter": SimpleNamespace(BAN_THRESHOLD=3, get_strike_counter=lambda cache: counter),
    }
    with patch.dict(sys.modules, modules), patch.object(request_purpose_policy, "_translate", fake_translate):
        first = await record_request_strike(outcome, user_id="u", assistant_response_id="m1", language="en",
                                            cache_service=object(), directus_service=object())
        await record_request_strike(outcome, user_id="u", assistant_response_id="m1", language="en",
                                    cache_service=object(), directus_service=object())
        assert counter.count == 1
        assert "strike 1 of 3" in first and "propaganda" in first
        suspend.assert_not_awaited()
        await record_request_strike(outcome, user_id="u", assistant_response_id="m2", language="en",
                                    cache_service=object(), directus_service=object())
        assert counter.count == 2
        suspend.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=safety-strikes.harmful-purpose-strikes
def test_every_message_exists_in_all_languages_and_explains_local_alternative():
    for key in ("harmful_purpose", "illegal_category", "live_site_abuse", "strike_notice"):
        assert all(SOURCE[key][language] for language in LANGUAGES), key
    assert "localhost" in SOURCE["live_site_abuse"]["en"] and "localhost" in SOURCE["live_site_abuse"]["de"]
    assert "{strike}" in SOURCE["strike_notice"]["ja"]
