# backend/tests/test_openai_compatible_tools_contract.py
#
# Contract tests for OpenAI-compatible client-supplied function tools.
# `/v1/chat/completions` must treat these tools as external client tools only:
# it may return tool calls, but it must not execute OpenMates app skills or
# reinterpret colliding names as internal OpenMates capabilities.

from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.routes import openai_compat


class FakeConfigManager:
    def get_provider_configs(self) -> Dict[str, Dict[str, Any]]:
        return {
            "openai": {
                "provider_id": "openai",
                "no_api_key": True,
                "models": [
                    {
                        "id": "gpt-4o-mini",
                        "for_app_skill": "ai.ask",
                        "release_date": "2024-07-18",
                        "output_types": ["text"],
                        "features": {"tool_use": True, "streaming": True},
                    }
                ],
            }
        }

    def get_provider_config(self, provider_id: str) -> Dict[str, Any] | None:
        return self.get_provider_configs().get(provider_id)


def _client() -> TestClient:
    app = FastAPI()
    app.state.config_manager = FakeConfigManager()
    app.state.secrets_manager = object()
    app.state.directus_service = object()
    app.dependency_overrides[openai_compat.get_session_or_api_key_info] = lambda: {
        "user_id": "user-1",
        "api_key_encrypted_name": "test-key",
        "api_key_hash": "hash-1",
        "device_hash": None,
    }
    app.dependency_overrides[openai_compat.get_directus_service] = lambda: app.state.directus_service
    app.include_router(openai_compat.router)
    return TestClient(app)


def _weather_tool(name: str = "get_weather") -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Get weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }


def test_function_tools_use_direct_client_tool_dispatch(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_ai_ask(**kwargs: Any) -> Dict[str, Any]:
        captured["ai_ask_called"] = kwargs
        return {}

    async def fake_client_tools(
        *,
        request_body: Dict[str, Any],
        user_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        captured["client_tools_request"] = request_body
        captured["user_info"] = user_info
        return {
            "id": "chatcmpl-tool-test",
            "object": "chat.completion",
            "created": 1,
            "model": request_body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"Berlin"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

    monkeypatch.setattr(openai_compat, "_dispatch_ai_ask_chat_completion", fake_ai_ask)
    monkeypatch.setattr(openai_compat, "_dispatch_client_tool_chat_completion", fake_client_tools)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Weather?"}],
            "tools": [_weather_tool()],
            "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    assert body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert captured["client_tools_request"]["tools"][0]["function"]["name"] == "get_weather"
    assert captured["client_tools_request"]["tool_choice"] == {"type": "function", "function": {"name": "get_weather"}}
    assert "ai_ask_called" not in captured


def test_tool_result_followup_messages_are_accepted_by_client_tool_path(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_client_tools(
        *,
        request_body: Dict[str, Any],
        user_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        del user_info
        captured["messages"] = request_body["messages"]
        return {
            "id": "chatcmpl-tool-followup",
            "object": "chat.completion",
            "created": 1,
            "model": request_body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "It is sunny."},
                    "finish_reason": "stop",
                }
            ],
        }

    monkeypatch.setattr(openai_compat, "_dispatch_client_tool_chat_completion", fake_client_tools)

    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": "Weather?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city":"Berlin"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"weather":"sunny"}'},
        {"role": "user", "content": "Summarize it."},
    ]

    response = _client().post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o-mini", "messages": messages, "tools": [_weather_tool()]},
    )

    assert response.status_code == 200
    assert captured["messages"][2]["role"] == "tool"
    assert captured["messages"][2]["tool_call_id"] == "call_1"


def test_collision_like_tool_names_stay_external_client_tools(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_ai_ask(**kwargs: Any) -> Dict[str, Any]:
        captured["ai_ask_called"] = kwargs
        return {}

    async def fake_client_tools(
        *,
        request_body: Dict[str, Any],
        user_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        del user_info
        captured["tool_name"] = request_body["tools"][0]["function"]["name"]
        return {
            "id": "chatcmpl-collision-test",
            "object": "chat.completion",
            "created": 1,
            "model": request_body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "web-search", "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

    monkeypatch.setattr(openai_compat, "_dispatch_ai_ask_chat_completion", fake_ai_ask)
    monkeypatch.setattr(openai_compat, "_dispatch_client_tool_chat_completion", fake_client_tools)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Search the web"}],
            "tools": [_weather_tool("web-search")],
            "tool_choice": {"type": "function", "function": {"name": "web-search"}},
        },
    )

    assert response.status_code == 200
    assert captured["tool_name"] == "web-search"
    assert "ai_ask_called" not in captured


def test_unsupported_hosted_or_custom_tool_types_return_openai_errors(monkeypatch) -> None:
    async def fail_dispatch(**kwargs: Any) -> Dict[str, Any]:
        raise AssertionError(f"dispatch must not run for invalid tools: {kwargs}")

    monkeypatch.setattr(openai_compat, "_dispatch_ai_ask_chat_completion", fail_dispatch)
    monkeypatch.setattr(openai_compat, "_dispatch_client_tool_chat_completion", fail_dispatch)

    for tool in [{"type": "web_search"}, {"type": "custom", "name": "shell"}]:
        response = _client().post(
            "/v1/chat/completions",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hi"}],
                "tools": [tool],
            },
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["type"] == "invalid_request_error"
        assert body["error"]["param"] == "tools"
        assert body["error"]["code"] == "unsupported_tool_type"


def test_invalid_tool_choice_returns_openai_error_before_dispatch(monkeypatch) -> None:
    async def fail_dispatch(**kwargs: Any) -> Dict[str, Any]:
        raise AssertionError(f"dispatch must not run for invalid tool_choice: {kwargs}")

    monkeypatch.setattr(openai_compat, "_dispatch_client_tool_chat_completion", fail_dispatch)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [_weather_tool()],
            "tool_choice": {"type": "function", "function": {"name": "unknown_tool"}},
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] == "tool_choice"
    assert body["error"]["code"] == "invalid_value"


def test_client_tool_dispatch_charges_usage(monkeypatch) -> None:
    captured: Dict[str, Any] = {}
    sequence: List[str] = []

    async def fake_events(request_body: Dict[str, Any], request_id: str):
        del request_body, request_id
        sequence.append("events_started")
        yield "hello"
        yield openai_compat.OpenAIUsageMetadata(input_tokens=130, output_tokens=20, total_tokens=150)

    async def fake_budget(directus_service: Any, *, user_info: Dict[str, Any], requested_credits: int) -> None:
        sequence.append("budget_checked")
        captured["budget"] = {
            "directus_service": directus_service,
            "user_info": user_info,
            "requested_credits": requested_credits,
        }

    async def fake_charge(**kwargs: Any) -> None:
        sequence.append("credits_charged")
        captured["charge"] = kwargs

    monkeypatch.setattr(openai_compat, "_direct_client_tool_events", fake_events)
    monkeypatch.setattr(openai_compat, "require_api_key_budget_for_charge", fake_budget)
    monkeypatch.setattr(openai_compat, "charge_credits_via_internal_api", fake_charge)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [_weather_tool()],
        },
    )

    assert response.status_code == 200
    assert captured["budget"]["requested_credits"] == 1
    assert captured["charge"]["credits"] == 1
    assert captured["charge"]["app_id"] == "ai"
    assert captured["charge"]["skill_id"] == "ask"
    assert captured["charge"]["api_key_hash"] == "hash-1"
    assert sequence[:2] == ["budget_checked", "credits_charged"]
    assert sequence.index("credits_charged") < sequence.index("events_started")


def test_streaming_client_tool_dispatch_precharges_before_stream_events(monkeypatch) -> None:
    sequence: List[str] = []

    async def fake_events(request_body: Dict[str, Any], request_id: str):
        del request_body, request_id
        sequence.append("events_started")
        yield "hello"
        yield openai_compat.OpenAIUsageMetadata(input_tokens=130, output_tokens=20, total_tokens=150)

    async def fake_budget(directus_service: Any, *, user_info: Dict[str, Any], requested_credits: int) -> None:
        del directus_service, user_info, requested_credits
        sequence.append("budget_checked")

    async def fake_charge(**kwargs: Any) -> None:
        del kwargs
        sequence.append("credits_charged")

    monkeypatch.setattr(openai_compat, "_direct_client_tool_events", fake_events)
    monkeypatch.setattr(openai_compat, "require_api_key_budget_for_charge", fake_budget)
    monkeypatch.setattr(openai_compat, "charge_credits_via_internal_api", fake_charge)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [_weather_tool()],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert sequence[:2] == ["budget_checked", "credits_charged"]
    assert sequence.index("credits_charged") < sequence.index("events_started")
