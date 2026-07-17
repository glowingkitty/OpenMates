# backend/tests/test_openai_compatible_api_contract.py
#
# Contract tests for the canonical OpenAI-compatible API surface.
# These run against a tiny in-process FastAPI app so failures stay focused on
# route/auth/error shape instead of live model inference or billing.
# The live SDK/OpenCode smoke tests are covered separately by the executable
# spec for docs/specs/openai-compatible-api/spec.yml.

import json
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.core.api.app.routes import openai_compat


class FakeConfigManager:
    def get_provider_configs(self) -> Dict[str, Dict[str, Any]]:
        return {
            "openai": {
                "provider_id": "openai",
                "name": "OpenAI",
                "models": [
                    {
                        "id": "gpt-4o-mini",
                        "name": "GPT-4o Mini",
                        "for_app_skill": "ai.ask",
                        "release_date": "2024-07-18",
                        "input_types": ["text"],
                        "output_types": ["text"],
                        "features": {"tool_use": True, "streaming": True},
                    },
                    {
                        "id": "gpt-image-2",
                        "for_app_skill": "images.generate",
                        "output_types": ["image"],
                    },
                ],
            },
            "anthropic": {
                "provider_id": "anthropic",
                "name": "Anthropic",
                "models": [
                    {
                        "id": "claude-haiku-4-5",
                        "for_app_skill": "ai.ask",
                        "release_date": "2025-10-01",
                        "input_types": ["text"],
                        "output_types": ["text"],
                    }
                ],
            },
        }


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


def test_models_returns_openai_model_list_from_chat_provider_metadata() -> None:
    response = _client().get("/v1/models")

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    model_ids = [model["id"] for model in data["data"]]
    assert model_ids == ["anthropic/claude-haiku-4-5", "openai/gpt-4o-mini"]
    assert data["data"][0]["object"] == "model"
    assert isinstance(data["data"][0]["created"], int)
    assert data["data"][0]["owned_by"] == "anthropic"


def test_get_model_returns_one_model_or_openai_style_404() -> None:
    known = _client().get("/v1/models/openai/gpt-4o-mini")
    assert known.status_code == 200
    assert known.json()["id"] == "openai/gpt-4o-mini"

    unknown = _client().get("/v1/models/openai/unknown-model")
    assert unknown.status_code == 404
    body = unknown.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] == "model"
    assert body["error"]["code"] == "model_not_found"


def test_chat_completions_reuses_ai_ask_dispatch_for_plain_non_streaming(
    monkeypatch,
) -> None:
    captured: Dict[str, Any] = {}

    async def fake_dispatch(
        *,
        request_body: Dict[str, Any],
        user_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        captured["request_body"] = request_body
        captured["user_info"] = user_info
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": request_body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(openai_compat, "_dispatch_ai_ask_chat_completion", fake_dispatch)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"
    assert captured["request_body"]["model"] == "openai/gpt-4o-mini"
    assert captured["request_body"].get("apps_enabled") is None
    assert captured["user_info"]["user_id"] == "user-1"


def test_plain_chat_dispatch_forces_openmates_app_skills_off(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_registry_dispatch(app_id: str, skill_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        captured["app_id"] = app_id
        captured["skill_id"] = skill_id
        captured["payload"] = payload
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
        }

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            return await fake_registry_dispatch(app_id, skill_id, payload)

    monkeypatch.setattr(openai_compat, "_get_global_skill_registry", lambda: FakeRegistry())

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Could you search the web?"}],
            "apps_enabled": True,
            "allowed_apps": ["web-search"],
        },
    )

    assert response.status_code == 200
    assert captured["app_id"] == "ai"
    assert captured["skill_id"] == "ask"
    assert captured["payload"]["apps_enabled"] is False
    assert captured["payload"]["allowed_apps"] == []


def test_chat_completions_streaming_returns_openai_sse(monkeypatch) -> None:
    async def fake_dispatch(
        *,
        request_body: Dict[str, Any],
        user_info: Dict[str, Any],
    ) -> StreamingResponse:
        del request_body, user_info

        async def chunks():
            yield 'data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr(openai_compat, "_dispatch_ai_ask_chat_completion", fake_dispatch)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text


def test_chat_completions_returns_openai_error_for_missing_model() -> None:
    response = _client().post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Say hello"}]},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] == "model"
    assert body["error"]["code"] == "missing_required_parameter"


def test_chat_completions_returns_openai_error_for_malformed_messages() -> None:
    response = _client().post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o-mini", "messages": "not-a-list"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] == "messages"


def test_chat_completions_returns_openai_error_for_invalid_json() -> None:
    response = _client().post(
        "/v1/chat/completions",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "invalid_json"


def test_chat_completions_returns_openai_error_for_unavailable_model() -> None:
    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openai/not-listed",
            "messages": [{"role": "user", "content": "Say hello"}],
        },
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["param"] == "model"
    assert body["error"]["code"] == "model_not_found"


def test_stream_contract_fixture_is_valid_json() -> None:
    payload = '{"object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}'
    assert json.loads(payload)["object"] == "chat.completion.chunk"
