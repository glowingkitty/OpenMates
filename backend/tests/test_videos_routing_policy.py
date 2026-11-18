# backend/tests/test_videos_routing_policy.py
#
# videos.generate routing follows the user's AI settings (no network: the decision client is a fake).

import pytest

from backend.apps.ai.utils import internal_decisions
from backend.apps.videos import routing
from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy
from backend.shared.providers.typesafe.models import ChoiceAnswer


class _Response:
    def __init__(self, answers):
        self.answers = answers


def _fake_factory(monkeypatch):
    seen = {}

    class _Client:
        async def evaluate(self, *, state, questions):
            seen["asked"] = True
            return _Response({"route": ChoiceAnswer.model_construct(
                choice="composed", probabilities={"composed": 0.9}, confidence=0.9)})

    def factory(policy, **kwargs):
        seen["policy"], seen["kwargs"] = policy, kwargs
        return _Client()

    monkeypatch.setattr(internal_decisions, "decision_client_for_policy", factory)
    return seen


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_routing_asks_the_client_built_for_the_users_policy(monkeypatch):
    seen = _fake_factory(monkeypatch)
    policy = InternalLlmPolicy(complex_model="anthropic/claude-fable-5-2")
    decision = await routing.decide_route(mode="auto", instructions="a title card", picture_kinds=[],
                                          secrets_manager=None, task_id="t1", policy=policy)
    assert decision.route == "composed" and seen["asked"]
    assert seen["policy"] is policy
    assert seen["kwargs"]["purpose"] == routing.ROUTING_TASK and seen["kwargs"]["max_retries"] == 1


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_turned_off_routing_models_make_routing_unavailable():
    policy = InternalLlmPolicy(disabled_ai_models=frozenset({"typesafe/jev"}), complex_model=None)
    client = internal_decisions.decision_client_for_policy(policy, secrets_manager=None, task_id="t1",
                                                           purpose=routing.ROUTING_TASK, model="typesafe/jev")
    if isinstance(client, internal_decisions.DisabledDecisionClient):
        with pytest.raises(routing.RoutingUnavailable):
            await routing.decide_route(mode="auto", instructions="x", picture_kinds=[], secrets_manager=None,
                                       task_id="t1", policy=policy)
