"""Focused transport tests; paid inference and product behavior are separate."""
# contract-test-file: infrastructure

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.core.api.app.services.workflow_gemini_authoring import (
    WorkflowAuthoringProviderError,
    WorkflowGeminiAuthor,
    authoring_prompt,
    complete_plan_components,
    complete_step_components,
)


def test_prompt_examples_are_valid_json_with_real_weather_contract_and_quoted_operators():
    prompt = authoring_prompt(SimpleNamespace(context=lambda: {"capabilities": []}), "UTC")
    example_text = prompt.split("not example placeholders): ", 1)[1]
    examples, _ = json.JSONDecoder().raw_decode(example_text)
    weather, check = examples["create"]["steps"]
    assert weather["capability"] == "weather.forecast"
    assert check["predicate"]["op"] == "eq"
    assert examples["ask_ai"]["prompt"][1]["ref"]["field"] == "results"
    assert "NOT forecast data" in prompt
    assert "op:'" not in prompt


def test_components_never_emit_incomplete_nested_steps_or_quoted_key():
    prefix = '{"title":"\\\"steps\\\":[fake]","steps":['
    first = {"kind": "app", "id": "weather", "input": {"location": "Lisbon"}}
    check = {"kind": "check", "yes": [{"kind": "send", "message": "bring umbrella"}]}
    source = prefix + json.dumps(first) + ',' + json.dumps(check)
    assert complete_step_components(source[:-2]) == [first]
    assert complete_step_components(source) == [first, check]


def test_batch_components_keep_header_and_only_complete_steps():
    first = {"operation": "create", "title": "First", "schedule": {"type": "weekly"},
             "steps": [{"kind": "end", "id": "done"}]}
    source = '{"operations":[' + json.dumps(first) + ',{"operation":"create","title":"Second","steps":['
    components = complete_plan_components(source)
    assert len(components) == 1
    assert components[0] == {"workflow_index": 0, "index": 0, "plan": first}
    source += '{"kind":"app","id":"partial","input":'
    assert complete_plan_components(source) == components


def test_duplicate_properties_do_not_create_provisional_steps():
    assert complete_plan_components('{"operation":"create","operation":"update","steps":[{"kind":"end","id":"x"}]}') == []


@pytest.mark.asyncio
async def test_stream_filters_thoughts_emits_complete_steps_and_counts_reasoning(monkeypatch):
    from backend.core.api.app.services import workflow_authoring_compiler

    monkeypatch.setattr(workflow_authoring_compiler, "build_authoring_schema", lambda _: {"type": "object"})
    fragments = ['{"steps":[', '{"id":"a","kind":"end"}', ']}']
    events = [{"candidates": [{"content": {"parts": [{"text": "private thought", "thought": True}]}}]}]
    events.extend({"candidates": [{"content": {"parts": [{"text": fragment}]}}]} for fragment in fragments)
    events.append({"candidates": [{"finishReason": "STOP"}], "usageMetadata": {
        "promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 10,
    }})

    def handle(request):
        body = json.loads(request.content)
        assert body["generationConfig"]["thinkingConfig"]["includeThoughts"] is False
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseFormat" not in body["generationConfig"]
        assert request.headers["x-goog-api-key"] == "synthetic-key"
        return httpx.Response(200, text=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    selection = SimpleNamespace(context=lambda: {"capabilities": []})
    components = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        raw, metrics = await WorkflowGeminiAuthor(Secrets(), client).generate(
            text="end", selection=selection, timezone="UTC", on_component=components.append)
    assert raw == {"steps": [{"id": "a", "kind": "end"}]}
    assert components == [{"index": 0, "step": raw["steps"][0]}]
    assert metrics["component_count"] == 1
    assert metrics["output_tokens"] == 30
    assert metrics["estimated_cost_usd"] == pytest.approx(0.0001875)


@pytest.mark.asyncio
async def test_provider_rejection_does_not_expose_body(monkeypatch):
    from backend.core.api.app.services import workflow_authoring_compiler

    monkeypatch.setattr(workflow_authoring_compiler, "build_authoring_schema", lambda _: {"type": "object"})

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429, text="private request"))) as client:
        with pytest.raises(WorkflowAuthoringProviderError, match="HTTP 429") as error:
            await WorkflowGeminiAuthor(Secrets(), client).generate(
                text="private input", selection=SimpleNamespace(context=lambda: {}), timezone="UTC")
    assert "private" not in str(error.value)
