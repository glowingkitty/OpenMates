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
    def __init__(self, providers: Dict[str, Dict[str, Any]] | None = None) -> None:
        self._providers = providers

    def get_provider_configs(self) -> Dict[str, Dict[str, Any]]:
        return self._providers or {
            "openai": {
                "provider_id": "openai",
                "name": "OpenAI",
                "models": [
                    {
                        "id": "gpt-4o-mini",
                        "name": "GPT-4o Mini",
                        "description": "Fast chat model",
                        "for_app_skill": "ai.ask",
                        "release_date": "2024-07-18",
                        "capability_level": "low",
                        "input_types": ["text"],
                        "output_types": ["text"],
                        "pricing": {
                            "tokens": {
                                "input": {"per_credit_unit": 200},
                                "output": {"per_credit_unit": 45},
                            }
                        },
                        "costs": {"input_per_million_token": {"max_context": 128000}},
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

    def get_provider_config(self, provider_id: str) -> Dict[str, Any] | None:
        return self.get_provider_configs().get(provider_id)


class FakeSecretsManager:
    vault_token = "test-token"
    vault_url = "http://vault.test"

    def __init__(self, configured: set[str] | None = None) -> None:
        self.configured = configured or {"openai", "anthropic"}

    async def get_secret(self, *, secret_path: str, secret_key: str) -> str | None:
        if secret_key != "api_key":
            return None
        provider_id = secret_path.rsplit("/", 1)[-1]
        return "configured" if provider_id in self.configured else None


def _client(
    config: FakeConfigManager | None = None,
    secrets_manager: FakeSecretsManager | None = None,
    *,
    override_auth: bool = True,
) -> TestClient:
    app = FastAPI()
    app.state.config_manager = config or FakeConfigManager()
    app.state.secrets_manager = secrets_manager or FakeSecretsManager()
    app.state.directus_service = object()
    if override_auth:
        app.dependency_overrides[openai_compat.get_session_or_api_key_info] = lambda: {
            "user_id": "user-1",
            "api_key_encrypted_name": "test-key",
            "api_key_hash": "hash-1",
            "device_hash": None,
        }
    app.dependency_overrides[openai_compat.get_directus_service] = lambda: app.state.directus_service
    app.include_router(openai_compat.router)
    return TestClient(app)


# contract-test: direct surface=rest_api assertions=ai-model-routing.catalog.public-read-only,ai-model-routing.catalog.capability-recommendation-variants
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
    assert data["data"][1]["openmates"] == {
        "name": "GPT-4o Mini",
        "description": "Fast chat model",
        "capability_level": "low",
        "input_types": ["text"],
        "output_types": ["text"],
        "context_window_tokens": 128000,
        "features": {"reasoning": False, "tool_use": True, "streaming": True},
        "pricing": {"unit": "tokens_per_credit", "input": 200, "output": 45},
    }


# contract-test: direct surface=rest_api assertions=ai-model-routing.catalog.public-read-only,ai-model-routing.catalog.capability-recommendation-variants
def test_model_catalog_is_public_without_session_or_api_key() -> None:
    client = _client(override_auth=False)

    catalog = client.get("/v1/models")
    model = client.get("/v1/models/openai/gpt-4o-mini")
    chat_route = next(
        route for route in client.app.routes
        if getattr(route, "path", None) == "/v1/chat/completions"
    )

    assert catalog.status_code == 200
    assert model.status_code == 200
    assert openai_compat.get_session_or_api_key_info in {
        dependency.call for dependency in chat_route.dependant.dependencies
    }


# contract-test: direct surface=rest_api assertions=ai-model-routing.catalog.public-read-only
def test_models_omits_chat_models_when_required_provider_key_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("SECRET__ANTHROPIC__API_KEY", raising=False)

    response = _client(secrets_manager=FakeSecretsManager(configured={"openai"})).get("/v1/models")

    assert response.status_code == 200
    model_ids = [model["id"] for model in response.json()["data"]]
    assert model_ids == ["openai/gpt-4o-mini"]


# contract-test: direct surface=rest_api assertions=ai-model-routing.catalog.public-read-only
def test_models_keep_no_api_key_provider_visible_without_secret() -> None:
    config = FakeConfigManager({
        "open_meteo": {
            "provider_id": "open_meteo",
            "name": "Open-Meteo",
            "no_api_key": True,
            "models": [{"id": "weather-chat", "for_app_skill": "ai.ask", "output_types": ["text"]}],
        }
    })

    response = _client(config=config, secrets_manager=FakeSecretsManager(configured=set())).get("/v1/models")

    assert response.status_code == 200
    assert [model["id"] for model in response.json()["data"]] == ["open_meteo/weather-chat"]


# contract-test: direct surface=rest_api assertions=ai-model-routing.catalog.public-read-only
def test_get_model_returns_one_model_or_openai_style_404() -> None:
    known = _client().get("/v1/models/openai/gpt-4o-mini")
    assert known.status_code == 200
    assert known.json()["id"] == "openai/gpt-4o-mini"

    opencode_prefixed = _client().get("/v1/models/openmates/openai/gpt-4o-mini")
    assert opencode_prefixed.status_code == 200
    assert opencode_prefixed.json()["id"] == "openai/gpt-4o-mini"

    unknown = _client().get("/v1/models/openai/unknown-model")
    assert unknown.status_code == 404
    body = unknown.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] == "model"
    assert body["error"]["code"] == "model_not_found"


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
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


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
def test_chat_completions_accepts_opencode_prefixed_model_id(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_dispatch(
        *,
        request_body: Dict[str, Any],
        user_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        del user_info
        captured["model"] = request_body["model"]
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": request_body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
        }

    monkeypatch.setattr(openai_compat, "_dispatch_ai_ask_chat_completion", fake_dispatch)

    response = _client().post(
        "/v1/chat/completions",
        json={
            "model": "openmates/openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Say hello"}],
        },
    )

    assert response.status_code == 200
    assert captured["model"] == "openai/gpt-4o-mini"


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
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


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
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


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
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


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
def test_chat_completions_returns_openai_error_for_malformed_messages() -> None:
    response = _client().post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o-mini", "messages": "not-a-list"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] == "messages"


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
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


# contract-test: direct surface=rest_api assertions=ai-model-routing.surface.semantic-parity
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


# contract-test: supporting surface=rest_api assertions=ai-model-routing.surface.semantic-parity
def test_stream_contract_fixture_is_valid_json() -> None:
    payload = '{"object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}'
    assert json.loads(payload)["object"] == "chat.completion.chunk"
