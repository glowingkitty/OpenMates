"""Focused transport tests; paid inference and product behavior are separate."""
# contract-test-file: infrastructure

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from backend.core.api.app.services.workflow_gemini_authoring import (
    WorkflowAuthoringProviderError,
    WorkflowAuthoringStopped,
    WorkflowGeminiAuthor,
    authoring_prompt,
    complete_flat_components,
    complete_plan_components,
    complete_step_components,
    provider_response_schema,
)
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
)


@pytest.fixture(autouse=True)
def filesystem_capabilities(monkeypatch):
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())


def selection(*capabilities: str, operation: str = "create") -> WorkflowPreselection:
    registry = WorkflowCapabilityRegistry()
    return WorkflowPreselection([registry.get_capability(identifier) for identifier in capabilities],
                                operation, "none", True, {}, {})


def test_prompt_examples_are_valid_json_with_real_weather_contract_and_quoted_operators():
    prompt = authoring_prompt(SimpleNamespace(context=lambda: {"capabilities": []}), "UTC")
    example_text = prompt.split("replace example values with user request and selected skill contracts): ", 1)[1]
    examples, _ = json.JSONDecoder().raw_decode(example_text)
    weather, check, yes, no = examples["workflows"][0]["nodes"]
    assert weather["capability"] == "weather.forecast"
    assert json.loads(weather["input_json"])["start_date"] == {"$date": "today", "format": "date"}
    assert json.loads(check["predicate_json"])["op"] == "eq"
    assert yes["parent_check_id"] == no["parent_check_id"] == "rain"
    assert "NOT forecast data" in prompt
    assert "Daily and weekly clock times MUST use time" in prompt
    assert "do not add Ask AI merely" in prompt
    assert "op:'" not in prompt


def test_provider_envelope_is_flat_and_constant_across_selections():
    from jsonschema import Draft202012Validator
    schema = provider_response_schema(selection("weather.forecast", "ai.ask"))
    assert schema == provider_response_schema(selection("web.search"))
    assert len(json.dumps(schema)) < 2500
    assert "minItems" not in json.dumps(schema) and "maxItems" not in json.dumps(schema)
    validator = Draft202012Validator(schema)
    flat = {"workflows": [{"header": {"operation": "create", "schedule": {"type": "daily"}},
                           "nodes": [{"kind": "app", "id": "weather", "capability": "weather.forecast",
                                      "input_json": '{"location":"Berlin","days":1}'}]}]}
    validator.validate(flat)
    assert list(validator.iter_errors({"operation": "create"}))
    flat["workflows"][0]["nodes"][0]["input_json"] = {"location": "Berlin"}
    assert list(validator.iter_errors(flat))


def test_provider_node_grammar_keeps_kind_branch_and_encoded_fields_typed():
    from jsonschema import Draft202012Validator
    schema = provider_response_schema(selection("weather.forecast"))
    Draft202012Validator.check_schema(schema)
    node = schema["properties"]["workflows"]["items"]["properties"]["nodes"]["items"]
    assert node["required"] == ["kind", "id"]
    assert node["properties"]["branch"]["enum"] == ["default", "yes", "no", "unsure"]
    assert node["properties"]["predicate_json"] == {"type": "string"}
    assert "yes" not in node["properties"]


def test_flat_components_emit_header_then_only_complete_nodes():
    source = '{"workflows":[{"header":{"operation":"create","title":"A"},"nodes":['
    assert complete_flat_components(source) == [{"type": "header", "workflow_index": 0,
                                                  "header": {"operation": "create", "title": "A"}}]
    first = {"kind": "check", "id": "c", "mode": "exact", "predicate_json": '{"op":"exists","left":true}'}
    source += json.dumps(first) + ',{"kind":"send","id":"incomplete","message_json":'
    assert complete_flat_components(source)[-1] == {"type": "node", "workflow_index": 0,
                                                     "index": 0, "node": first}


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
async def test_stream_filters_thoughts_and_validates_header_and_each_complete_node():
    header = {"operation": "create", "title": "Forecast", "description": "Send a forecast",
              "icon": "cloud-rain", "schedule": {"type": "daily"}}
    app = {"kind": "app", "id": "weather", "capability": "weather.forecast",
           "input_json": '{"location":"Berlin","days":1}'}
    send = {"kind": "send", "id": "reply", "title": "Forecast",
            "message_json": '[{"ref":{"step":"weather","field":"summary"}}]'}
    fragments = ['{"workflows":[{"header":' + json.dumps(header) + ',"nodes":[',
                 json.dumps(app) + ',', json.dumps(send) + ']}]}']
    events = [{"candidates": [{"content": {"parts": [{"text": "private thought", "thought": True}]}}]}]
    events.extend({"candidates": [{"content": {"parts": [{"text": fragment}]}}]} for fragment in fragments)
    events.append({"candidates": [{"finishReason": "STOP"}], "usageMetadata": {
        "promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 10,
    }})

    def handle(request):
        body = json.loads(request.content)
        assert body["generationConfig"]["thinkingConfig"]["includeThoughts"] is False
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["type"] == "object"
        assert "responseFormat" not in body["generationConfig"]
        assert request.headers["x-goog-api-key"] == "synthetic-key"
        return httpx.Response(200, text=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    components, checkpoints = [], []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        raw, metrics = await WorkflowGeminiAuthor(Secrets(), client).generate(
            text="forecast", selection=selection("weather.forecast"), timezone="UTC",
            on_component=components.append, on_plan_component=checkpoints.append)
    assert raw["steps"] == [{"kind": "app", "id": "weather", "capability": "weather.forecast",
                              "input": {"location": "Berlin", "days": 1}},
                             {"kind": "send", "id": "reply", "title": "Forecast",
                              "message": [{"ref": {"step": "weather", "field": "summary"}}]}]
    assert components == [{"index": 0, "step": app}, {"index": 1, "step": send}]
    assert [item["type"] for item in checkpoints] == ["header", "node", "node"]
    assert metrics["component_count"] == 2
    assert metrics["output_tokens"] == 30
    assert metrics["estimated_cost_usd"] == pytest.approx(0.0001875)


@pytest.mark.asyncio
async def test_provider_rejection_does_not_expose_body():
    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429, text="private request"))) as client:
        with pytest.raises(WorkflowAuthoringProviderError, match="HTTP 429") as error:
            await WorkflowGeminiAuthor(Secrets(), client).generate(
                text="private input", selection=SimpleNamespace(context=lambda: {}), timezone="UTC")
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_provider_rejects_empty_batch_even_without_transport_array_bounds():
    event = {"candidates": [{"content": {"parts": [{"text": '{"workflows":[]}'}]},
                               "finishReason": "STOP"}]}

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text='data: ' + json.dumps(event) + '\n\n'))) as client:
        with pytest.raises(WorkflowAuthoringProviderError, match="plan limits"):
            await WorkflowGeminiAuthor(Secrets(), client).generate(
                text="forecast", selection=selection("weather.forecast"), timezone="UTC")


@pytest.mark.asyncio
async def test_provider_rejects_41_nodes_after_stream_parser_keeps_first_40():
    header = {"operation": "create", "title": "Notices", "description": "Send notices",
              "icon": "help-circle", "schedule": {"type": "daily"}}
    nodes = [{"kind": "send", "id": f"notice_{index}", "title": "Notice",
              "message_json": '[{"text":"Hello"}]'} for index in range(41)]
    source = json.dumps({"workflows": [{"header": header, "nodes": nodes}]})
    assert len(complete_flat_components(source)) == 41  # Header plus only the first 40 nodes.
    event = {"candidates": [{"content": {"parts": [{"text": source}]}, "finishReason": "STOP"}]}

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text='data: ' + json.dumps(event) + '\n\n'))) as client:
        with pytest.raises(WorkflowAuthoringProviderError, match="plan limits") as error:
            await WorkflowGeminiAuthor(Secrets(), client).generate(
                text="notices", selection=selection(), timezone="UTC")
    assert len(error.value.accepted_prefixes[0]["nodes"]) == 40


@pytest.mark.asyncio
async def test_retry_keeps_frozen_prefix_and_emits_only_new_valid_node():
    header = {"operation": "create", "title": "Forecast", "description": "Send forecast",
              "icon": "cloud-rain", "schedule": {"type": "daily"}}
    app = {"kind": "app", "id": "forecast", "capability": "weather.forecast",
           "input_json": '{"location":"Berlin","days":1}'}
    send = {"kind": "send", "id": "reply", "title": "Forecast",
            "message_json": '[{"ref":{"step":"forecast","field":"summary"}}]'}
    frozen = [{"header": header, "nodes": [app]}]
    output = {"workflows": [{"header": header, "nodes": [app, send]}]}

    def handle(_):
        event = {"candidates": [{"content": {"parts": [{"text": json.dumps(output)}]},
                                   "finishReason": "STOP"}]}
        return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\n')

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    checkpoints = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        compact, _ = await WorkflowGeminiAuthor(Secrets(), client).generate(
            text="forecast", selection=selection("weather.forecast"), timezone="UTC",
            accepted_prefixes=frozen, correction="Add the send node", on_plan_component=checkpoints.append)
    assert [event["type"] for event in checkpoints] == ["node"]
    assert checkpoints[0]["node"] == send
    assert [step["id"] for step in compact["steps"]] == ["forecast", "reply"]


@pytest.mark.asyncio
async def test_stop_carries_only_valid_accepted_prefix():
    header = {"operation": "create", "title": "Forecast", "description": "Send forecast",
              "icon": "cloud-rain", "schedule": {"type": "daily"}}
    app = {"kind": "app", "id": "forecast", "capability": "weather.forecast",
           "input_json": '{"location":"Berlin","days":1}'}
    chunks = ['{"workflows":[{"header":' + json.dumps(header) + ',"nodes":[', json.dumps(app) + ',']
    events = [{"candidates": [{"content": {"parts": [{"text": chunk}]}}]} for chunk in chunks]
    events.append({"candidates": [{"content": {"parts": [{"text": '{}'}]}}]})

    def handle(_):
        return httpx.Response(200, text=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    stopped = False

    def checkpoint(event):
        nonlocal stopped
        if event["type"] == "node":
            stopped = True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(WorkflowAuthoringStopped) as error:
            await WorkflowGeminiAuthor(Secrets(), client).generate(
                text="forecast", selection=selection("weather.forecast"), timezone="UTC",
                on_plan_component=checkpoint, should_stop=lambda: stopped)
    assert error.value.accepted_prefixes == [{"header": header, "nodes": [app]}]


@pytest.mark.asyncio
async def test_stop_interrupts_stalled_sse_read_and_closes_response():
    header = {"operation": "create", "title": "Forecast", "description": "Send forecast",
              "icon": "cloud-rain", "schedule": {"type": "daily"}}
    app = {"kind": "app", "id": "forecast", "capability": "weather.forecast",
           "input_json": '{"location":"Berlin","days":1}'}
    fragments = ['{"workflows":[{"header":' + json.dumps(header) + ',"nodes":[', json.dumps(app) + ',']
    stop = asyncio.Event()

    class StalledStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            for fragment in fragments:
                event = {"candidates": [{"content": {"parts": [{"text": fragment}]}}]}
                yield ('data: ' + json.dumps(event) + '\n\n').encode()
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = StalledStream()

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    def checkpoint(event):
        if event["type"] == "node":
            async def stop_after_read_stalls():
                await asyncio.sleep(0.05)
                stop.set()
            asyncio.create_task(stop_after_read_stalls())

    started = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=stream))) as client:
        with pytest.raises(WorkflowAuthoringStopped) as error:
            await asyncio.wait_for(WorkflowGeminiAuthor(Secrets(), client).generate(
                text="forecast", selection=selection("weather.forecast"), timezone="UTC",
                on_plan_component=checkpoint, should_stop=stop.is_set), timeout=1.0)
    assert time.monotonic() - started < 1.0
    assert stream.closed
    assert error.value.accepted_prefixes == [{"header": header, "nodes": [app]}]
