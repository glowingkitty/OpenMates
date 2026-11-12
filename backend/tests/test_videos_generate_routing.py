# backend/tests/test_videos_generate_routing.py
#
# Routing of videos.generate requests (no network: the decision client is stubbed).

import pytest

from backend.apps.videos import routing
from backend.shared.providers.typesafe import client as typesafe_client
from backend.shared.providers.typesafe.models import ChoiceAnswer


class _Response:
    def __init__(self, answers):
        self.answers = answers


def _stub_client(monkeypatch, *, answer=None, error=None):
    seen = {}

    class _Client:
        def __init__(self, **kwargs):
            seen["init"] = kwargs

        async def evaluate(self, *, state, questions):
            seen["state"], seen["questions"] = state, questions
            if error:
                raise error
            return _Response({"route": answer})

    monkeypatch.setattr(typesafe_client, "JevDecisionClient", _Client)
    return seen


def _choice(value):
    return ChoiceAnswer.model_construct(choice=value, probabilities={value: 0.9}, confidence=0.9)


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_explicit_mode_wins_without_asking(monkeypatch):
    seen = _stub_client(monkeypatch, error=AssertionError("must not be asked"))
    decision = await routing.decide_route(mode="composed", instructions="x", picture_kinds=[],
                                          secrets_manager=None, task_id="t")
    assert decision == routing.RouteDecision("composed", routing.DECIDED_BY_REQUEST)
    assert "state" not in seen


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_auto_asks_with_count_and_kinds_only(monkeypatch):
    seen = _stub_client(monkeypatch, answer=_choice("composed"))
    decision = await routing.decide_route(
        mode="auto", instructions="A recap of these news", picture_kinds=["search_result", "search_result", "image"],
        secrets_manager=None, task_id="t",
    )
    assert decision == routing.RouteDecision("composed", routing.DECIDED_BY_MODEL)
    assert seen["state"]["given_pictures"] == "3 pictures: 1 image, 2 search_result"
    assert set(seen["questions"]["route"]["criteria"]) == {"composed", "generative"}


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_unreachable_routing_model_is_explicit(monkeypatch):
    _stub_client(monkeypatch, error=typesafe_client.DecisionProviderError("down"))
    with pytest.raises(routing.RoutingUnavailable):
        await routing.decide_route(mode="auto", instructions="x", picture_kinds=[], secrets_manager=None,
                                   task_id="t")


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_invalid_routing_answer_is_explicit(monkeypatch):
    _stub_client(monkeypatch, answer=None)
    with pytest.raises(routing.RoutingUnavailable):
        await routing.decide_route(mode="auto", instructions="x", picture_kinds=[], secrets_manager=None,
                                   task_id="t")


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_generative_answer_for_two_pictures_is_made_composed(monkeypatch):
    seen = _stub_client(monkeypatch, answer=_choice("generative"))
    decision = await routing.decide_route(
        mode="auto", instructions="Animate these two photos", picture_kinds=["image", "image"],
        secrets_manager=None, task_id="t",
    )
    assert decision == routing.RouteDecision("composed", routing.DECIDED_BY_MODEL)
    assert "at most one picture" in seen["questions"]["route"]["instructions"]


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_generative_answer_for_one_picture_stays_generative(monkeypatch):
    _stub_client(monkeypatch, answer=_choice("generative"))
    decision = await routing.decide_route(mode="auto", instructions="Animate this photo", picture_kinds=["image"],
                                          secrets_manager=None, task_id="t")
    assert decision == routing.RouteDecision("generative", routing.DECIDED_BY_MODEL)


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_text_only_results_are_counted_and_a_result_is_never_generative(monkeypatch):
    seen = _stub_client(monkeypatch, answer=_choice("generative"))
    decision = await routing.decide_route(
        mode="auto", instructions="A short video about this article", picture_kinds=["search_result_text"],
        secrets_manager=None, task_id="t",
    )
    assert decision == routing.RouteDecision("composed", routing.DECIDED_BY_MODEL)
    assert seen["state"]["given_pictures"] == "no pictures; 1 search result without a picture (text only)"
    assert routing.describe_pictures(["search_result", "search_result_text", "search_result_text"]) == (
        "1 picture: 1 search_result; 2 search results without a picture (text only)")


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed,videos-generate.composed.sound
@pytest.mark.asyncio
async def test_sound_requests_are_routed_as_composed(monkeypatch):
    """Generative clips are silent: the routing question says a voice-over, sound effects or music means composed."""
    seen = _stub_client(monkeypatch, answer=_choice("composed"))
    decision = await routing.decide_route(
        mode="auto", instructions="Three scenes about bees with a voice-over, whooshes and calm music",
        picture_kinds=[], secrets_manager=None, task_id="t",
    )
    assert decision == routing.RouteDecision("composed", routing.DECIDED_BY_MODEL)
    question = seen["questions"]["route"]
    for word in ("voice-over", "sound effects", "music", "generative clips are silent"):
        assert word in question["instructions"]
    assert "voice-over" in question["criteria"]["composed"]
    assert "silent" in question["criteria"]["generative"]


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
def test_skill_hint_keeps_sound_inside_the_video_request():
    """The assistant passes the wanted sound in instructions instead of calling audio or music skills."""
    from pathlib import Path

    import yaml

    app = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/videos/app.yml").read_text())
    hint = next(skill for skill in app["skills"] if skill["id"] == "generate")["preprocessor_hint"]
    assert "makes the video's sound itself" in hint
    assert "do not call audio or music skills" in hint


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
def test_assistant_tool_schema_does_not_offer_mode():
    """The assistant cannot name a mode in chat: the routing model decides from the request."""
    from pathlib import Path

    import yaml

    from backend.apps.ai.processing.tool_generator import _drop_assistant_hidden_properties

    app = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/videos/app.yml").read_text())
    schema = next(skill for skill in app["skills"] if skill["id"] == "generate")["tool_schema"]
    assert "mode" in schema["properties"]["requests"]["items"]["properties"]
    _drop_assistant_hidden_properties(schema)
    offered = schema["properties"]["requests"]["items"]["properties"]
    assert "mode" not in offered
    assert {"instructions", "images"} <= set(offered)


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
def test_assistant_tool_schema_offers_nothing_that_implies_a_route():
    """A named model or a legacy first frame would force the generative route, so neither is offered."""
    from pathlib import Path

    import yaml

    from backend.apps.ai.processing.tool_generator import _drop_assistant_hidden_properties

    app = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/videos/app.yml").read_text())
    schema = next(skill for skill in app["skills"] if skill["id"] == "generate")["tool_schema"]
    _drop_assistant_hidden_properties(schema)
    offered = set(schema["properties"]["requests"]["items"]["properties"])
    assert not offered & {"mode", "model", "input_embed_ids"}
