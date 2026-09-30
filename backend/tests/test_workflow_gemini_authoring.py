"""Focused transport tests; paid inference and product behavior are separate."""
# contract-test-file: infrastructure

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.core.api.app.services.workflow_gemini_authoring import (
    WorkflowAuthoringProviderError,
    WorkflowGeminiAuthor,
    complete_step_components,
)


def test_components_never_emit_incomplete_nested_steps_or_quoted_key():
    prefix = '{"title":"\\\"steps\\\":[fake]","steps":['
    first = {"kind": "app", "id": "weather", "input": {"location": "Lisbon"}}
    check = {"kind": "check", "yes": [{"kind": "send", "message": "bring umbrella"}]}
    source = prefix + json.dumps(first) + ',' + json.dumps(check)
    assert complete_step_components(source[:-2]) == [first]
    assert complete_step_components(source) == [first, check]


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
