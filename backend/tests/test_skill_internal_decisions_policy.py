"""Skill-internal decision steps follow the user's AI settings (no network, fakes only)."""

from __future__ import annotations

import pytest

from backend.apps.ai.utils import internal_decisions
from backend.apps.code.skills import get_docs_skill
from backend.apps.shopping import visual_ranking as visual
from backend.shared.providers.typesafe.client import DecisionProviderUnavailable
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_utils import search_relevance
from backend.shared.python_utils.internal_llm_policy import (
    InternalLlmPolicy,
    InternalModelRoute,
    policy_from_skill_kwargs,
)

from backend.tests.provider_catalogue_support import repo_provider_catalogue  # noqa: F401 - pytest fixture

pytestmark = pytest.mark.usefixtures("repo_provider_catalogue")

JEV_OFF = InternalLlmPolicy(disabled_ai_models=frozenset({"jev-1.14"}))
USER_MODEL = InternalLlmPolicy(complex_model="example/big-model")


def _score(value: float) -> dict:
    return {"type": "score", "score": value, "legend": {"0": "no", "4": "yes"},
            "probabilities": {"0": 0.1, "4": 0.9}, "confidence": 0.8}


class JevFake:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        JevFake.instances.append(self)

    async def evaluate(self, *, state, questions, assets=None):
        return DecisionResponse(model="jev", answers={key: _score(4.0) for key in questions})

    async def evaluate_with_images(self, *, state, questions, images):
        return DecisionResponse(model="jev", answers={key: _score(4.0) for key in questions})


@pytest.fixture(autouse=True)
def _jev(monkeypatch):
    JevFake.instances = []
    monkeypatch.setattr(internal_decisions, "JevDecisionClient", JevFake)
    monkeypatch.setattr(InternalLlmPolicy, "allowed_servers",
                        lambda self, ref, cfg=None: frozenset() if self.disabled_ai_models else frozenset({"typesafe", "mistral", "cerebras"}))


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_skill_kwargs_parse_policy():
    assert policy_from_skill_kwargs({}).is_default
    assert not policy_from_skill_kwargs({"internal_llm_policy": USER_MODEL.to_payload()}).is_default


# --- search relevance --------------------------------------------------------------------

async def _rank(policy):
    return await search_relevance.rank_search_candidates(
        candidates=[{"id": "a"}, {"id": "b"}], candidate_projections=[{"title": "A"}, {"title": "B"}],
        relevance_criteria="fits", search_parameters={"query": "q"}, profile="events",
        secrets_manager=object(), policy=policy)


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_search_relevance_default_policy_uses_jev():
    result = await _rank(None)
    assert result.applied and len(JevFake.instances) == 1


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_search_relevance_complex_model_routes_to_user_model(monkeypatch):
    seen = {}

    class UserClient:
        async def evaluate(self, *, state, questions, assets=None):
            seen["asked"] = True
            return DecisionResponse(model="example/big-model", answers={k: _score(4.0) for k in questions})

    def factory(policy, **kwargs):
        seen["policy"] = policy
        return UserClient()

    monkeypatch.setattr(search_relevance, "decision_client_for_policy", factory)
    result = await _rank(USER_MODEL)
    assert result.applied and seen["policy"] is USER_MODEL and seen["asked"]
    assert JevFake.instances == []


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_search_relevance_jev_off_keeps_original_order_unranked():
    result = await _rank(JEV_OFF)
    assert not result.applied and [c["id"] for c in result.candidates] == ["a", "b"]
    assert JevFake.instances == []


# --- shopping visual ranking -------------------------------------------------------------

async def _visual(monkeypatch, policy):
    prepared = visual.prepare_image(_png())

    async def download(url):
        return prepared

    monkeypatch.setattr(visual, "download_public_product_image", download)
    return await visual.rank_products_visually(
        candidates=[{"product_id": "1", "title": "Fabric", "image_url": "https://cdn.example/1.jpg"}],
        reference_images=[prepared], relevance_criteria="blue", query="fabric", secrets_manager=None,
        policy=policy)


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (600, 300), "red").save(out, format="PNG")
    return out.getvalue()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_visual_ranking_default_policy_uses_jev(monkeypatch):
    result = await _visual(monkeypatch, None)
    assert result.candidates[0]["visual_match"]["status"] == "evaluated"
    assert len(JevFake.instances) == 1 and JevFake.instances[0].kwargs["max_retries"] == 0


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_visual_ranking_complex_model_routes_to_user_model(monkeypatch):
    seen = {}

    class UserClient:
        async def evaluate_with_images(self, *, state, questions, images):
            seen["images"] = len(images)
            return DecisionResponse(model="example/big-model", answers={k: _score(4.0) for k in questions})

    def factory(policy, **kwargs):
        seen["policy"], seen["needs_images"] = policy, kwargs["needs_images"]
        return UserClient()

    monkeypatch.setattr(visual, "decision_client_for_policy", factory)
    result = await _visual(monkeypatch, USER_MODEL)
    assert result.candidates[0]["visual_match"]["status"] == "evaluated"
    assert seen["policy"] is USER_MODEL and seen["needs_images"] and seen["images"] >= 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_visual_ranking_jev_off_reports_unavailable(monkeypatch):
    result = await _visual(monkeypatch, JEV_OFF)
    assert result.candidates[0]["visual_match"]["status"] == "unavailable"
    assert JevFake.instances == []


# --- get_docs library selection ----------------------------------------------------------

LIBS = [{"id": "/a/one", "title": "One", "description": "first"}, {"id": "/b/two", "title": "Two", "description": "second"}]


class _Result:
    def __init__(self, library_id):
        self.success = True
        self.tool_calls_made = [object()]
        self.library_id = library_id


@pytest.fixture
def providers(monkeypatch):
    calls = []

    def fake(name, library_id):
        async def invoke(**kwargs):
            calls.append(name)
            return _Result(library_id)
        return invoke

    import backend.apps.ai.llm_providers.cerebras_wrapper as cerebras
    import backend.apps.ai.llm_providers.groq_client as groq
    import backend.apps.ai.llm_providers.mistral_client as mistral

    monkeypatch.setattr(groq, "invoke_groq_chat_completions", fake("groq", "/b/two"))
    monkeypatch.setattr(cerebras, "invoke_cerebras_chat_completions", fake("cerebras", "/b/two"))
    monkeypatch.setattr(mistral, "invoke_mistral_chat_completions", fake("mistral", "/b/two"))
    monkeypatch.setattr(get_docs_skill, "_extract_library_id_from_response",
                        lambda result, valid_ids, task_id="", provider="": result.library_id)
    return calls


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_get_docs_default_policy_asks_groq_first(providers):
    assert await get_docs_skill.select_library_with_llm(LIBS, "q", object()) == "/b/two"
    assert providers == ["groq"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_get_docs_user_model_picks_library(providers, monkeypatch):
    route = InternalModelRoute(model_id="example/big-model", user_selected=True)
    monkeypatch.setattr(InternalLlmPolicy, "author_routes", lambda self, *a, **k: [route])
    seen = {}

    class UserClient:
        async def evaluate(self, *, state, questions, assets=None):
            seen["criteria"] = questions["library"]["criteria"]
            return DecisionResponse(model="example/big-model", answers={"library": {
                "type": "choice", "choice": "/a/one", "probabilities": {"/a/one": 0.9, "/b/two": 0.1},
                "confidence": 0.9}})

    monkeypatch.setattr(get_docs_skill, "decision_client_for_policy", lambda policy, **kw: UserClient())
    assert await get_docs_skill.select_library_with_llm(LIBS, "q", object(), policy=USER_MODEL) == "/a/one"
    assert set(seen["criteria"]) == {"/a/one", "/b/two"} and providers == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_get_docs_turned_off_models_fall_back_to_first_result(providers):
    # The user turned off every library selection model.
    policy = InternalLlmPolicy(disabled_ai_models=frozenset(
        {"jev-1.14", "openai/gpt-oss-20b", "gpt-oss-120b", "mistral-small-latest"}))
    assert await get_docs_skill.select_library_with_llm(LIBS, "q", object(), policy=policy) == "/a/one"
    assert providers == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
async def test_get_docs_skips_only_the_turned_off_model(providers, monkeypatch):
    policy = InternalLlmPolicy(disabled_ai_models=frozenset({"openai/gpt-oss-20b"}))
    monkeypatch.setattr(InternalLlmPolicy, "allowed_servers",
                        lambda self, ref, cfg=None: frozenset({"cerebras", "mistral"}) if "gpt-oss-120b" in ref or "mistral" in ref else frozenset())
    assert await get_docs_skill.select_library_with_llm(LIBS, "q", object(), policy=policy) == "/b/two"
    assert providers == ["cerebras"]


# contract-test: supporting surface=rest_api assertions=ai-model-routing.skills.internal-llm-follows-settings
def test_disabled_jev_client_reports_unavailable():
    client = internal_decisions.decision_client_for_policy(JEV_OFF, secrets_manager=None)
    with pytest.raises(DecisionProviderUnavailable):
        import asyncio

        asyncio.run(client.evaluate(state={}, questions={}))
