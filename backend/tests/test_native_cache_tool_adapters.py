"""Native append-only tool loading at the provider request boundary."""

# contract-test-file: infrastructure
# contract-test: supporting surface=cli assertions=ai-model-routing.catalog.capability-recommendation-variants

import asyncio
import logging
import sys
from types import SimpleNamespace

import pytest

from backend.apps.ai.llm_providers.anthropic_shared import _prepare_messages_for_anthropic
from backend.apps.ai.llm_providers.native_cache_context import (
    NativeCacheProviderOutput, NativeCacheSchemaChanged,
    validate_native_cache_context,
)
from backend.apps.ai.llm_providers.openai_responses import invoke_responses, responses_input


def tool(name: str, *, version: int = 1) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": f"Version {version}",
        "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
    }}


def test_timeline_rejects_event_inside_parallel_tool_results() -> None:
    messages = [
        {"role": "system", "content": "Stable"},
        {"role": "user", "content": "Run"},
        {"role": "assistant", "tool_calls": []},
        {"role": "tool", "tool_call_id": "a", "content": "one"},
        {"role": "tool", "tool_call_id": "b", "content": "two"},
    ]
    context = {"baseline_tools": [tool("base")], "events": [
        {"after_message_index": 3, "add_tools": [tool("selected")]},
    ]}
    with pytest.raises(ValueError, match="parallel tool results"):
        validate_native_cache_context(context, messages)


def test_openai_same_name_schema_change_requires_segment_reset() -> None:
    async def create(**_kwargs):
        raise AssertionError("schema change must be rejected before API request")

    async def invoke():
        await invoke_responses(
            client=SimpleNamespace(responses=SimpleNamespace(create=create)),
            task_id="test", model_id="gpt-6-astra",
            messages=[{"role": "user", "content": "next"}],
            reasoning_effort="medium", native_cache_context={
                "baseline_tools": [tool("base")], "events": [
                    {"after_message_index": 0, "add_tools": [tool("base", version=2)]},
                ],
            },
        )

    with pytest.raises(NativeCacheSchemaChanged, match="new cache segment"):
        asyncio.run(invoke())


def test_openai_adds_selected_tools_in_order_and_restricts_removed_names() -> None:
    messages = [
        {"role": "system", "content": "Stable"},
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Answer"},
        {"role": "user", "content": "Second"},
    ]
    context = {"baseline_tools": [tool("base")], "events": [
        {"after_message_index": 1, "system_suffix": "Current time: noon", "add_tools": [tool("selected")]},
        {"after_message_index": 3, "remove_tools": ["selected"], "add_tools": [tool("new")]},
    ]}
    response = {"status": "completed", "output": [
        {"type": "reasoning", "encrypted_content": "opaque"},
        {"type": "message", "content": [{"type": "output_text", "text": "Done"}]},
    ], "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        async def events():
            yield {"type": "response.completed", "response": response}
        return events()

    async def collect():
        stream = await invoke_responses(
            client=SimpleNamespace(responses=SimpleNamespace(create=create)),
            task_id="test", model_id="gpt-6-astra", messages=messages,
            reasoning_effort="medium", native_cache_context=context, stream=True,
        )
        return [item async for item in stream]

    chunks = asyncio.run(collect())
    assert captured["store"] is False
    assert "previous_response_id" not in captured
    assert [entry["name"] for entry in captured["tools"]] == ["base"]
    assert captured["input"][2] == {"role": "developer", "content": "Current time: noon"}
    assert captured["input"][3]["type"] == "additional_tools"
    assert [entry["name"] for entry in captured["input"][3]["tools"]] == ["selected"]
    assert captured["input"][-1]["tools"][0]["name"] == "new"
    assert captured["tool_choice"] == {"type": "allowed_tools", "mode": "auto", "tools": [
        {"type": "function", "name": "base"}, {"type": "function", "name": "new"},
    ]}
    output = next(item for item in chunks if isinstance(item, NativeCacheProviderOutput))
    assert output.output == response["output"]
    assert "opaque" not in repr(output)
    assert "output" not in output.model_dump()
    assert responses_input([{"role": "assistant", "provider_transport_state": output.output}]) == response["output"]


@pytest.mark.parametrize("model_id", ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-5.6-terra"])
def test_openai_catalog_models_route_native_context_to_responses(model_id, monkeypatch) -> None:
    from backend.apps.ai.llm_providers import openai_client

    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "output": []}

    monkeypatch.setattr(openai_client, "_openai_direct_client", SimpleNamespace(
        responses=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda *_: {
        "reasoning_effort": "medium",
    })
    result = asyncio.run(openai_client._invoke_openai_direct_api(
        task_id="test", model_id=model_id,
        messages=[{"role": "system", "content": "Stable"}, {"role": "user", "content": "Hello"}],
        native_cache_context={"baseline_tools": [tool("base")], "events": []},
    ))
    assert result.success
    assert captured["model"] == model_id
    assert captured["store"] is False
    assert captured["tools"][0]["name"] == "base"


def test_openai_native_request_keeps_frozen_prefix_without_legacy_breakpoint(monkeypatch) -> None:
    from backend.apps.ai.llm_providers import openai_client

    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return {"status": "completed", "output": []}

    monkeypatch.setattr(openai_client, "_openai_direct_client", SimpleNamespace(
        responses=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda *_: {
        "reasoning_effort": "medium",
    })
    stable = "Stable instruction. " * 300
    first_messages = [
        {"role": "system", "content": stable},
        {"role": "user", "content": "First"},
    ]
    first_event = {"after_message_index": 1, "add_tools": [tool("selected")]}
    second_messages = first_messages + [
        {"role": "assistant", "content": "Answer"},
        {"role": "user", "content": "Second"},
    ]
    second_event = {"after_message_index": 3, "add_tools": [tool("next")]}

    async def run():
        for messages, events in (
            (first_messages, [first_event]),
            (second_messages, [first_event, second_event]),
        ):
            result = await openai_client._invoke_openai_direct_api(
                task_id="test", model_id="gpt-6-astra", messages=messages,
                cacheable_system_prefix=stable,
                native_cache_context={"baseline_tools": [tool("base")], "events": events},
            )
            assert result.success

    asyncio.run(run())
    first, second = requests
    assert first["input"][0] == {"role": "system", "content": stable}
    assert second["input"][:len(first["input"])] == first["input"]
    assert first["tools"] == second["tools"]
    assert first["store"] is False and second["store"] is False
    assert "prompt_cache_breakpoint" not in repr(requests)


def test_openai_tool_free_history_adds_then_disables_tools_without_rewriting_prefix() -> None:
    messages = [
        {"role": "system", "content": "Stable"},
        {"role": "user", "content": "First"},
        {"role": "assistant", "provider_transport_state": [
            {"type": "message", "content": [{"type": "output_text", "text": "One"}]},
        ]},
        {"role": "user", "content": "Second"},
        {"role": "assistant", "provider_transport_state": [
            {"type": "message", "content": [{"type": "output_text", "text": "Two"}]},
        ]},
        {"role": "user", "content": "Third"},
    ]
    additions = {"after_message_index": 3, "add_tools": [tool("selected")]}
    removal = {"after_message_index": 5, "remove_tools": ["selected"]}
    captured = []

    async def create(**kwargs):
        captured.append(kwargs)
        return {"status": "completed", "output": []}

    async def run():
        for count, events, choice in ((2, [], "auto"), (4, [additions], "auto"),
                                      (6, [additions, removal], "none")):
            await invoke_responses(
                client=SimpleNamespace(responses=SimpleNamespace(create=create)),
                task_id="test", model_id="gpt-6-astra", messages=messages[:count],
                reasoning_effort="medium", native_cache_context={
                    "baseline_tools": [], "events": events,
                }, tool_choice=choice,
            )

    asyncio.run(run())
    first, second, third = captured
    assert all("tools" not in request for request in captured)
    assert second["input"][:len(first["input"])] == first["input"]
    assert third["input"][:len(second["input"])] == second["input"]
    assert second["input"][-1]["tools"][0]["name"] == "selected"
    assert third["tool_choice"] == "none"
    assert first["store"] is second["store"] is third["store"] is False


def test_anthropic_tool_free_history_uses_empty_baseline_and_inline_changes(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=object))
    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace())
    from backend.apps.ai.llm_providers.anthropic_direct_api import invoke_direct_api

    messages = [
        {"role": "system", "content": "Stable"},
        {"role": "user", "content": "First"},
        {"role": "assistant", "provider_transport_state": [{"type": "text", "text": "One"}]},
        {"role": "user", "content": "Second"},
        {"role": "assistant", "provider_transport_state": [{"type": "text", "text": "Two"}]},
        {"role": "user", "content": "Third"},
    ]
    additions = {"after_message_index": 3, "add_tools": [tool("selected")]}
    removal = {"after_message_index": 5, "remove_tools": ["selected"]}
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return [SimpleNamespace(
            type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"),
            usage=SimpleNamespace(input_tokens=10, output_tokens=1,
                                  cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0),
        )]

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))

    async def run():
        for count, events, choice in ((2, [], "auto"), (4, [additions], "auto"),
                                      (6, [additions, removal], "none")):
            stream = await invoke_direct_api(
                "test", "claude-sonnet-5-5", messages[:count], client, stream=True,
                native_cache_context={"baseline_tools": [], "events": events},
                tool_choice=choice,
            )
            await anext(stream.__aiter__(), None)

    asyncio.run(run())
    first, second, third = requests
    assert all(request["tools"] == [] for request in requests)
    assert second["messages"][:len(first["messages"])] == first["messages"]
    assert third["messages"][:len(second["messages"])] == second["messages"]
    assert second["messages"][-1]["content"][0]["type"] == "tool_addition"
    assert third["messages"][-1]["content"][0]["type"] == "tool_removal"
    assert all(request["extra_body"] == {"cache_control": {"type": "ephemeral"}}
               for request in requests)
    assert all("tool_choice" not in request for request in requests)


def test_anthropic_native_request_uses_only_automatic_moving_cache(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=object))
    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace())
    from backend.apps.ai.llm_providers.anthropic_direct_api import invoke_direct_api

    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return [SimpleNamespace(
            type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"),
            usage=SimpleNamespace(input_tokens=10, output_tokens=1,
                                  cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0),
        )]

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    stable = "Stable instruction. " * 300
    first_messages = [
        {"role": "system", "content": stable},
        {"role": "user", "content": "First"},
    ]
    first_event = {"after_message_index": 1, "add_tools": [tool("selected")]}
    second_messages = first_messages + [
        {"role": "assistant", "content": "Answer"},
        {"role": "user", "content": "Second"},
    ]
    second_event = {"after_message_index": 3, "add_tools": [tool("next")]}

    async def run():
        for messages, events in (
            (first_messages, [first_event]),
            (second_messages, [first_event, second_event]),
        ):
            stream = await invoke_direct_api(
                "test", "claude-sonnet-5-5", messages, client, stream=True,
                cacheable_system_prefix=stable,
                native_cache_context={"baseline_tools": [tool("base")], "events": events},
            )
            await anext(stream.__aiter__(), None)

    asyncio.run(run())
    first, second = requests
    assert first["system"] == second["system"]
    assert first["messages"] == second["messages"][:len(first["messages"])]
    assert first["tools"] == second["tools"]
    assert first["extra_body"] == second["extra_body"] == {
        "cache_control": {"type": "ephemeral"},
    }
    assert first["betas"] == second["betas"] == ["inline-tools-2026-09-15"]
    assert "cache_control" not in repr(first["system"])
    assert "cache_control" not in repr(first["messages"])


def test_anthropic_replays_selected_definition_changes_and_private_output() -> None:
    messages = [
        {"role": "system", "content": "Stable"},
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Shown", "provider_transport_state": [
            {"type": "thinking", "thinking": "private", "signature": "signed"},
            {"type": "text", "text": "Shown"},
        ]},
        {"role": "user", "content": "Second"},
    ]
    context = {"baseline_tools": [tool("base")], "events": [
        {"after_message_index": 1, "system_suffix": "Use brief answers", "add_tools": [tool("selected")]},
        {"after_message_index": 3, "remove_tools": ["selected"], "add_tools": [tool("selected", version=2)]},
    ]}
    baseline, indexed_events, active = validate_native_cache_context(context, messages)
    assert [entry["function"]["name"] for entry in baseline] == ["base"]
    assert active == ["base", "selected"]
    system, converted = _prepare_messages_for_anthropic(messages, native_events=indexed_events)
    assert system == "Stable"
    assert [entry["role"] for entry in converted] == ["user", "system", "assistant", "user", "system"]
    assert converted[1]["content"][1]["tool"]["definition"]["name"] == "selected"
    assert converted[2]["content"] == messages[2]["provider_transport_state"]
    assert converted[4]["content"][0] == {
        "type": "tool_removal", "tool": {"type": "tool_reference", "name": "selected"},
    }
    assert converted[4]["content"][1]["tool"]["definition"]["description"] == "Version 2"


def test_anthropic_native_stream_keeps_thinking_signature_and_tool_json(monkeypatch) -> None:
    # The request adapter uses these only for SDK typing and usage estimation.
    # This fixture supplies provider events without installing either SDK.
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=object))
    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace())
    from backend.apps.ai.llm_providers.anthropic_direct_api import invoke_direct_api
    captured = {}
    events = [
        SimpleNamespace(type="content_block_start", index=0, content_block=SimpleNamespace(type="thinking", thinking="", signature="")),
        SimpleNamespace(type="content_block_delta", index=0, delta=SimpleNamespace(type="thinking_delta", thinking="secret")),
        SimpleNamespace(type="content_block_delta", index=0, delta=SimpleNamespace(type="signature_delta", signature="sig")),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(type="content_block_start", index=1, content_block=SimpleNamespace(type="tool_use", id="call1", name="base", input={})),
        SimpleNamespace(type="content_block_delta", index=1, delta=SimpleNamespace(type="input_json_delta", partial_json='{"value":"x"}')),
        SimpleNamespace(type="content_block_stop", index=1),
        SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="tool_use"), usage=SimpleNamespace(
            input_tokens=10, output_tokens=3, cache_creation_input_tokens=7, cache_read_input_tokens=0,
        )),
    ]

    def create(**kwargs):
        captured.update(kwargs)
        return events

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))

    async def collect():
        stream = await invoke_direct_api(
            "test", "claude-sonnet-5-5", [
                {"role": "system", "content": "Stable"}, {"role": "user", "content": "Run"},
            ], client, stream=True, native_cache_context={
                "baseline_tools": [tool("base")], "events": [],
            },
        )
        return [item async for item in stream]

    chunks = asyncio.run(collect())
    assert captured["betas"] == ["inline-tools-2026-09-15"]
    assert captured["extra_body"] == {"cache_control": {"type": "ephemeral"}}
    assert [entry["name"] for entry in captured["tools"]] == ["base"]
    output = next(item for item in chunks if isinstance(item, NativeCacheProviderOutput))
    assert output.output == [
        {"type": "thinking", "thinking": "secret", "signature": "sig"},
        {"type": "tool_use", "id": "call1", "name": "base", "input": {"value": "x"}},
    ]
    assert "secret" not in repr(output)


@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_native_provider_error_redacts_body_and_preserves_status(monkeypatch, caplog, stream) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=object))
    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace())
    from backend.apps.ai.llm_providers.anthropic_direct_api import invoke_direct_api

    class SecretProviderError(Exception):
        status_code = 429

    def create(**_kwargs):
        raise SecretProviderError("PRIVATE_SIGNED_REASONING in request body")

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))

    async def run():
        response = await invoke_direct_api(
            "test", "claude-sonnet-5-5", [{"role": "user", "content": "hello"}],
            client, stream=stream,
            native_cache_context={"baseline_tools": [tool("base")], "events": []},
        )
        if stream:
            return [chunk async for chunk in response]
        return response

    with caplog.at_level(logging.DEBUG):
        if stream:
            with pytest.raises(IOError, match="status=429") as error:
                asyncio.run(run())
            assert error.value.__cause__ is None
            assert "PRIVATE_SIGNED_REASONING" not in str(error.value)
        else:
            response = asyncio.run(run())
            assert response.success is False
            assert "status=429" in response.error_message
            assert "PRIVATE_SIGNED_REASONING" not in response.error_message
    assert "PRIVATE_SIGNED_REASONING" not in caplog.text


@pytest.mark.parametrize("stream", [False, True])
def test_openai_native_provider_error_redacts_body_and_preserves_status(monkeypatch, caplog, stream) -> None:
    from backend.apps.ai.llm_providers import openai_client

    class SecretProviderError(Exception):
        status_code = 503

    async def create(**_kwargs):
        if not stream:
            raise SecretProviderError("PRIVATE_ENCRYPTED_REASONING in request body")
        async def events():
            yield {"type": "response.created"}
            raise SecretProviderError("PRIVATE_ENCRYPTED_REASONING in stream body")
        return events()

    monkeypatch.setattr(openai_client, "_openai_direct_client", SimpleNamespace(
        responses=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda *_: {
        "reasoning_effort": "medium",
    })

    async def run():
        response = await openai_client._invoke_openai_direct_api(
            task_id="test", model_id="gpt-6-astra",
            messages=[{"role": "user", "content": "hello"}],
            native_cache_context={"baseline_tools": [tool("base")], "events": []},
            stream=stream,
        )
        return [chunk async for chunk in response] if stream else response

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError, match="status=503") as error:
            asyncio.run(run())
    assert error.value.__cause__ is None
    assert "PRIVATE_ENCRYPTED_REASONING" not in str(error.value)
    assert "PRIVATE_ENCRYPTED_REASONING" not in caplog.text
