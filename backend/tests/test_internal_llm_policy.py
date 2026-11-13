"""Skill-internal LLM steps follow the user's AI settings (internal_llm_policy + internal_decisions).

Covers the policy parsing, author route selection, restriction filtering, the
decision adapter that lets the user's model answer Jev-shaped questions, and
the images authors that use them. Fakes only; no provider is called.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.apps.ai.utils import internal_decisions
from backend.apps.ai.utils.internal_decisions import (
    DisabledDecisionClient,
    UserModelDecisionClient,
    answers_from_model_json,
    decision_client_for_policy,
)
from backend.apps.images.vector_author import VECTOR_AUTHOR_MODELS, VECTOR_REVIEW_MODEL, author_svg, review_with_jev
from backend.shared.providers.typesafe.client import DecisionProviderUnavailable, JevDecisionClient
from backend.shared.providers.typesafe.models import ChoiceAnswer, NoulAnswer, ScoreAnswer
from backend.shared.python_utils.internal_llm_policy import (
    DEFAULT_POLICY,
    InternalLlmPolicy,
    policy_from_skill_kwargs,
)

from backend.tests.provider_catalogue_support import repo_provider_catalogue  # noqa: F401 - pytest fixture

pytestmark = pytest.mark.usefixtures("repo_provider_catalogue")

USER_IMAGE_MODEL = "mistral/mistral-medium-latest"
USER_TEXT_ONLY_MODEL = "deepseek/deepseek-v4-pro"
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def _policy(**prefs: Any) -> InternalLlmPolicy:
    return InternalLlmPolicy.from_user_preferences(prefs)


# --- policy ------------------------------------------------------------------------------


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_no_settings_keep_the_default_models_and_add_nothing_to_the_skill_call():
    policy = _policy(timezone="Europe/Berlin", default_ai_model_simple="inception/mercury-3")
    assert policy.is_default and policy.to_payload() is None
    routes = policy.author_routes(VECTOR_AUTHOR_MODELS)
    assert [r.model_id for r in routes] == list(VECTOR_AUTHOR_MODELS)
    assert all(policy.stream_options(r) == {} for r in routes)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_payload_round_trip_and_malformed_fields_are_dropped():
    policy = _policy(default_ai_model_complex=USER_IMAGE_MODEL, disabled_ai_models=["gpt-6.1-sol", 3],
                     disabled_ai_servers={"gemini-3.8-flash": ["google"], "bad": "x"},
                     server_region_preference="global")
    again = policy_from_skill_kwargs({"internal_llm_policy": policy.to_payload()})
    assert again == policy
    assert again.disabled_ai_models == frozenset({"gpt-6.1-sol"})
    assert dict(again.disabled_ai_servers) == {"gemini-3.8-flash": frozenset({"google"})}
    assert InternalLlmPolicy.from_payload({"complex_model": "not a model", "server_region_preference": "mars"}) \
        == DEFAULT_POLICY
    assert policy_from_skill_kwargs({}) == DEFAULT_POLICY


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_saved_complex_model_alone_answers_when_it_takes_the_inputs():
    policy = _policy(default_ai_model_complex=USER_IMAGE_MODEL)
    routes = policy.author_routes(VECTOR_AUTHOR_MODELS, required_inputs=("text", "image"))
    assert [(r.model_id, r.user_selected) for r in routes] == [(USER_IMAGE_MODEL, True)]
    assert policy.stream_options(routes[0]) == {"server_region_preference": "eu"}


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_text_only_complex_model_falls_back_to_permitted_defaults_for_picture_steps():
    policy = _policy(default_ai_model_complex=USER_TEXT_ONLY_MODEL)
    assert [r.model_id for r in policy.author_routes(VECTOR_AUTHOR_MODELS)] == [USER_TEXT_ONLY_MODEL]
    picture_routes = policy.author_routes(VECTOR_AUTHOR_MODELS, required_inputs=("text", "image"))
    assert [r.model_id for r in picture_routes] == list(VECTOR_AUTHOR_MODELS)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_turned_off_models_and_servers_are_never_used():
    policy = _policy(disabled_ai_models=["gemini-3.8-flash"], disabled_ai_servers={"gpt-6.1-sol": ["openai"]})
    assert [r.model_id for r in policy.author_routes(VECTOR_AUTHOR_MODELS)] == ["anthropic/claude-haiku-5-5"]
    turned_off_choice = _policy(default_ai_model_complex=USER_IMAGE_MODEL, disabled_ai_models=["mistral-medium-latest"])
    assert USER_IMAGE_MODEL not in [r.model_id for r in turned_off_choice.author_routes(VECTOR_AUTHOR_MODELS)]
    partly = _policy(disabled_ai_servers={"gemini-3.8-flash": ["google"]})
    lead = partly.author_routes(VECTOR_AUTHOR_MODELS)[0]
    assert lead.model_id == "google/gemini-3.8-flash"
    assert partly.stream_options(lead)["allowed_server_ids"] == {"google_ai_studio"}


# --- decision adapter --------------------------------------------------------------------


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_default_policy_keeps_the_plain_jev_client():
    client = decision_client_for_policy(None, secrets_manager=None, task_id="t", purpose="p")
    assert type(client) is JevDecisionClient
    assert type(decision_client_for_policy(DEFAULT_POLICY, secrets_manager=None)) is JevDecisionClient


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_complex_model_answers_decisions_and_jev_restrictions_apply_otherwise():
    user = decision_client_for_policy(_policy(default_ai_model_complex=USER_IMAGE_MODEL), secrets_manager=None,
                                      needs_images=True)
    assert isinstance(user, UserModelDecisionClient) and user.model == USER_IMAGE_MODEL
    # A text-only choice cannot judge pictures: Jev answers the picture review instead.
    assert type(decision_client_for_policy(_policy(default_ai_model_complex=USER_TEXT_ONLY_MODEL),
                                           secrets_manager=None, needs_images=True)) is JevDecisionClient
    direct_only = decision_client_for_policy(_policy(disabled_ai_servers={"jev-1.14": ["openrouter"]}),
                                             secrets_manager=None)
    assert direct_only._providers == ("typesafe",)
    off = decision_client_for_policy(_policy(disabled_ai_models=["jev-1.14"]), secrets_manager=None)
    assert isinstance(off, DisabledDecisionClient)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_turned_off_decisions_report_unavailable():
    with pytest.raises(DecisionProviderUnavailable):
        await DisabledDecisionClient("off").evaluate(state={}, questions={})


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_model_json_becomes_typed_answers():
    questions = {
        "fit": {"type": "noul", "instructions": "?"},
        "route": {"type": "choice", "instructions": "?", "criteria": {"composed": "a", "generative": "b"}},
        "level": {"type": "score", "instructions": "?", "criteria": ["Low", "Mid", "High"]},
        "missing": {"type": "noul", "instructions": "?"},
    }
    text = ('Sure: {"fit": {"yes": 0.9}, "route": {"probabilities": {"composed": 3, "generative": 1}},'
            ' "level": {"probabilities": {"0": 0, "1": 0.5, "2": 0.5}}}')
    answers = answers_from_model_json(text, questions)
    assert answers["fit"] == {"type": "noul", "noul": 0.9}
    assert answers["route"]["choice"] == "composed" and answers["route"]["probabilities"]["composed"] == 0.75
    assert answers["level"]["score"] == pytest.approx(1.5)
    assert "missing" not in answers
    ChoiceAnswer.model_validate(answers["route"])
    ScoreAnswer.model_validate(answers["level"])


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_user_model_client_streams_with_the_users_restrictions():
    calls: list[dict[str, Any]] = []

    async def stream(**kwargs: Any):
        calls.append(kwargs)
        yield '{"ok": {"yes": 0.2}}'

    policy = _policy(default_ai_model_complex=USER_IMAGE_MODEL, server_region_preference="global")
    client = decision_client_for_policy(policy, secrets_manager=None, needs_images=True, task_id="t",
                                        stream_fn=stream)
    response = await client.evaluate_with_images(
        state={"picture": "ref"}, questions={"ok": {"type": "noul", "instructions": "Is it red?"}},
        images={"ref": b"\xff\xd8jpeg"},
    )
    assert isinstance(response.answers["ok"], NoulAnswer) and response.answers["ok"].noul == 0.2
    assert response.model == USER_IMAGE_MODEL
    assert calls[0]["model_id"] == USER_IMAGE_MODEL and calls[0]["server_region_preference"] == "global"
    assert any(block.get("type") == "image_url" for block in calls[0]["message_history"][0]["content"])


# --- images authors ----------------------------------------------------------------------


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_drawing_author_and_review_use_the_users_model(monkeypatch):
    authored_with: list[str] = []

    async def stream(**kwargs: Any):
        authored_with.append(kwargs["model_id"])
        if kwargs["system_prompt"] == internal_decisions.DECISION_SYSTEM_PROMPT:
            yield '{"requirement_1": {"yes": 0.95}}'
            yield SimpleNamespace(input_tokens=321, output_tokens=12)
        else:
            yield SVG

    original = internal_decisions.decision_client_for_policy

    def with_fake_stream(*args: Any, **kwargs: Any):
        return original(*args, stream_fn=stream, **kwargs)

    monkeypatch.setattr(internal_decisions, "decision_client_for_policy", with_fake_stream)
    monkeypatch.setattr("backend.apps.images.vector_author.render_review_jpeg", lambda svg: b"jpeg")
    policy = _policy(default_ai_model_complex=USER_IMAGE_MODEL)
    result = await author_svg(task_id="t", prompt="a black square", requirements=["it is black"],
                              stream_fn=stream, policy=policy)
    assert result.model_id == USER_IMAGE_MODEL
    assert authored_with == [USER_IMAGE_MODEL, USER_IMAGE_MODEL]
    assert ("review", USER_IMAGE_MODEL, 321, 12) in {(u.step, u.model_id, u.input_tokens, u.output_tokens) for u in result.usage}


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_drawing_review_without_settings_still_uses_jev(monkeypatch):
    seen: list[Any] = []

    class FakeJev:
        def __init__(self, **kwargs: Any) -> None:
            seen.append(kwargs)

        async def evaluate_with_images(self, **_: Any):
            from backend.shared.providers.typesafe.models import DecisionResponse

            return DecisionResponse.model_validate({"model": "jev-1.14.0", "answers": {
                "requirement_1": {"type": "noul", "noul": 0.9}}, "usage": {"input_tokens": 12}})

    monkeypatch.setattr(internal_decisions, "JevDecisionClient", FakeJev)
    monkeypatch.setattr("backend.apps.images.vector_author.render_review_jpeg", lambda svg: b"jpeg")
    review = await review_with_jev(svg=SVG, prompt="p", requirements=["it is black"], is_modification=False,
                                   secrets_manager=None, task_id="t")
    assert review.accepted and review.model_id == VECTOR_REVIEW_MODEL and review.input_tokens == 12
    assert seen[0]["telemetry_purpose"] == "vector_graphic_review" and "provider" not in seen[0]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_every_drawing_model_turned_off_is_a_clear_error():
    from backend.apps.images.vector_author import VectorAuthorError

    async def stream(**_: Any):
        raise AssertionError("no model may be called")
        yield  # pragma: no cover

    policy = _policy(disabled_ai_models=[m.split("/", 1)[1] for m in VECTOR_AUTHOR_MODELS])
    with pytest.raises(VectorAuthorError, match="turned off in the user's AI settings"):
        await author_svg(task_id="t", prompt="a square", stream_fn=stream, policy=policy)
