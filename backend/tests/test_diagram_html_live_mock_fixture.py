"""The signed offline diagram replay enters the real Jev and model boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.apps.ai.processing.jev_preprocessing import (
    decide_app_and_project_routing_with_jev,
    decide_preprocessing_with_jev,
)
from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.testing.diagram_html_fixture import (
    GROUP, PROMPT, DISCUSSION_PROMPT, PROSE_PROMPT, PROSE_RESPONSE,
    SOURCE_PROMPT, SOURCE_RESPONSE, MINDMAP_PROMPT, MINDMAP_RESPONSE, MINDMAP_SOURCE, active, llm_fixture,
)
from backend.apps.diagrams.diagram_guidance import diagram_guidance_prompt
from backend.apps.ai.utils.diagram_html_fences import validate_diagram_html_source
from backend.shared.providers.typesafe import budget as jev_budget
from backend.shared.providers.typesafe import client as jev_client_module
from backend.shared.providers.typesafe.batching import question_batches
from backend.shared.providers.typesafe.client import (
    DecisionProviderUnavailable, DecisionRequestTooLarge, JevDecisionClient,
)
from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.mock_context import mock_group_var, mock_mode_var


@pytest.fixture
def diagram_replay(monkeypatch):
    # Worker startup loads these public, hash-checked tokenizer tables before
    # signed LIVE mock mode blocks all unregistered outbound HTTP. Keep the
    # real Jev budget estimator active throughout the replay tests.
    jev_budget._encodings()
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    mode = mock_mode_var.set("mock")
    group = mock_group_var.set(GROUP)
    try:
        yield
    finally:
        mock_group_var.reset(group)
        mock_mode_var.reset(mode)


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", [PROMPT, DISCUSSION_PROMPT, PROSE_PROMPT, SOURCE_PROMPT, MINDMAP_PROMPT])
async def test_diagram_replay_selects_app_and_type_through_real_jev_questions(diagram_replay, prompt) -> None:
    history = [{"role": "user", "content": prompt}]
    routing = await decide_app_and_project_routing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        available_apps=["diagrams", "web"], available_skills=[], available_focus_modes=[],
        topic_areas=["general_misc", "software_development"],
        is_first_message=True,
    )
    assert routing["selected_app_ids"] == ["diagrams"]
    selected = await decide_preprocessing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        topic_areas=["general_misc", "software_development"], available_skills=[],
        available_focus_modes=[], available_settings_and_memories={}, recent_skill_activity=[],
        conversation_summary=None, previous_category=None, is_first_message=True,
        available_apps=["diagrams", "web"],
        selected_app_ids=routing["selected_app_ids"], early_decisions=routing["early_decisions"],
    )
    assert selected["selected_app_ids"] == ["diagrams"]
    assert selected["relevant_diagram_types"] == ["type-architecture"]
    assert selected["relevant_diagram_variant"] == "minimal_dark"


@pytest.mark.parametrize(("prompt", "previous_prompt"), [
    (DISCUSSION_PROMPT, None), (PROSE_PROMPT, None), (SOURCE_PROMPT, None),
    (SOURCE_PROMPT, PROSE_PROMPT), (DISCUSSION_PROMPT, SOURCE_PROMPT), (MINDMAP_PROMPT, None),
])
# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.precedence.obligations
def test_discussion_replay_requires_complete_prompt_before_optional_output(diagram_replay, prompt, previous_prompt) -> None:
    root = Path(__file__).resolve().parents[1] / "apps"
    protocols = [yaml.safe_load((root / app / "app.yml").read_text())["instructions"][0]["instruction"]
                 for app in ("mindmaps", "diagrams")]
    guide = diagram_guidance_prompt(["type-architecture"], variant="minimal_dark")
    history = ([{"role": "user", "content": previous_prompt},
                {"role": "assistant", "content": "Previous answer."}] if previous_prompt else [])
    kwargs = {"model": "fixture-model", "stream": True,
              "messages": [*history, {"role": "user", "content": prompt}], "tools": []}
    with pytest.raises(AssertionError, match="complete native visualization guidance"):
        llm_fixture("llm/fixture-model", kwargs)
    for missing in range(3):
        incomplete = [part for index, part in enumerate([*protocols, guide]) if index != missing]
        with pytest.raises(AssertionError, match="complete native visualization guidance"):
            llm_fixture("llm/fixture-model", {**kwargs, "messages": [
                {"role": "system", "content": "\n".join(incomplete)}, *kwargs["messages"]]})
    replay = llm_fixture("llm/fixture-model", {**kwargs, "messages": [
        {"role": "system", "content": "\n".join([*protocols, guide])}, *kwargs["messages"]]})
    content = "".join(chunk["value"] for chunk in replay["response"]["chunks"])
    if prompt == SOURCE_PROMPT:
        assert content == SOURCE_RESPONSE
    elif prompt == MINDMAP_PROMPT:
        from backend.apps.ai.utils.mindmap_fences import normalize_mindmap_source
        assert content == MINDMAP_RESPONSE
        assert normalize_mindmap_source(MINDMAP_SOURCE).status == "valid"
    elif prompt == PROSE_PROMPT:
        assert "mermaid" not in content.lower()
        assert content == PROSE_RESPONSE
        assert "```" not in content
    else:
        assert "mermaid" not in content.lower()
        assert content.startswith("```openmates_diagram\n")


# contract-test: supporting surface=rest_api assertions=chats.streaming.ordered-final,chats.rendering.assistant-document-convergence
@pytest.mark.asyncio
async def test_diagram_replay_streams_exact_frontend_source_through_model_wrapper(
    diagram_replay, tmp_path: Path,
) -> None:
    async def forbidden_provider(**_kwargs):
        raise AssertionError("offline diagram replay must never call a provider")

    wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))
    stream = await wrapped(
        model="gemini-3.5-flash-lite", stream=True,
        messages=[{"role": "user", "content": PROMPT}], tools=[],
    )
    fenced = "".join([chunk async for chunk in stream if isinstance(chunk, str)])
    source = (Path(__file__).resolve().parents[2]
              / "frontend/packages/ui/src/components/embeds/diagrams/diagramHtmlExampleDark.html").read_text()
    assert (Path(__file__).resolve().parents[1]
            / "apps/ai/testing/fixtures/diagram_html_web.html").read_text() == source
    assert fenced == f"```openmates_diagram\n{source.rstrip()}\n```"
    metadata = validate_diagram_html_source(source)
    assert (metadata.diagram_kind, metadata.render_width, metadata.render_height) == (
        "architecture", 1240, 900,
    )


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
@pytest.mark.asyncio
async def test_diagram_replay_covers_postprocessing_without_a_provider(diagram_replay, tmp_path: Path) -> None:
    async def forbidden_provider(**_kwargs):
        raise AssertionError("offline postprocessing must never call a provider")

    wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))
    result = await wrapped(
        model="gemini-3.5-flash-lite", stream=False, tool_choice="required",
        messages=[{"role": "user", "content": PROMPT}],
        tools=[{"type": "function", "function": {"name": "generate_suggestions_and_metadata"}}],
    )
    assert result.success is True
    assert result.tool_calls_made[0].function_name == "generate_suggestions_and_metadata"
    jev = await JevDecisionClient(secrets_manager=None).evaluate(
        state={"user_message": PROMPT, "assistant_response": "A diagram was generated."},
        questions={
            "harmful_response": {"type": "score", "instructions": "Rate safety",
                                 "criteria": ["Safe", "Harmful"]},
            "app_0": {"type": "noul", "instructions": {"app_id": "diagrams"}},
        },
    )
    assert jev.answers["harmful_response"].score == 0
    assert jev.answers["app_0"].noul == 1


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_diagram_replay_rejects_unknown_turn_and_production_context(
    diagram_replay, monkeypatch,
) -> None:
    client = JevDecisionClient(secrets_manager=None)
    with pytest.raises(DecisionProviderUnavailable, match="no decision fixture"):
        await client.evaluate(
            state={"messages": [{"role": "user", "content": "unrelated request"}]},
            questions={"preview": {"type": "choice", "instructions": "Choose",
                                   "criteria": {"none": "No preview"}}},
        )
    assert llm_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": "unrelated request"}],
    }) is None
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert active() is False


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_diagram_replay_still_enforces_jev_token_budget_before_fixture(diagram_replay, monkeypatch) -> None:
    calls = []

    def over_budget(state, questions):
        calls.append((state, questions))
        return jev_client_module.MAX_ESTIMATED_INPUT_TOKENS + 1

    monkeypatch.setattr(jev_client_module, "estimate_request_tokens", over_budget)
    state = {"user_message": PROMPT}
    questions = {"preview": {"type": "choice", "instructions": "Choose",
                             "criteria": {"none": "No preview"}}}
    with pytest.raises(DecisionRequestTooLarge, match="estimated input tokens"):
        question_batches(state, questions)
    assert calls == [(state, questions)]
