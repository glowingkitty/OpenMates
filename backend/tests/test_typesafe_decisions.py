"""Unit tests for direct TypeSafe Jev decisions and OpenRouter failover."""

# contract-test-file: infrastructure

from __future__ import annotations

import json

import httpx
import pytest

from backend.shared.providers.typesafe.client import (
    DecisionProviderUnavailable,
    DecisionRequestTooLarge,
    JevDecisionClient,
    MAX_SERIALIZED_STATE_CHARS,
)
from backend.shared.providers.typesafe.models import ChoiceAnswer, NoulAnswer, ScoreAnswer


class FakeSecrets:
    async def get_secret(self, *, secret_path: str, secret_key: str) -> str:
        assert secret_path == "kv/data/providers/typesafe"
        assert secret_key == "api_key"
        return "test-key"


@pytest.mark.asyncio
async def test_parses_all_decision_answer_types() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert json.loads(request.content)["model"] == "jev-1.13.0"
        assert request.headers["authorization"] == "Bearer test-key"
        assert "HTTP-Referer" not in request.headers
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "route": {"type": "choice", "choice": "code", "probabilities": {"code": 0.9, "general": 0.1}, "confidence": 0.8},
                    "unsafe": {"type": "noul", "noul": 0.03},
                    "risk": {"type": "score", "score": 1.2, "legend": {"0": "safe", "1": "risky"}, "probabilities": {"0": 0.2, "1": 0.8}, "confidence": 0.7},
                },
                "usage": {"input_tokens": 123, "output_tokens": 20},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await JevDecisionClient(
            secrets_manager=FakeSecrets(), http_client=http_client, max_retries=0
        ).evaluate(
            state={"message": "write Python"},
            questions={
                "route": {"type": "choice", "instructions": "route", "criteria": {"code": None, "general": None}},
                "unsafe": {"type": "noul", "instructions": "unsafe?"},
                "risk": {"type": "score", "instructions": "risk", "criteria": ["safe", "risky"]},
            },
        )

    assert isinstance(result.answers["route"], ChoiceAnswer)
    assert isinstance(result.answers["unsafe"], NoulAnswer)
    assert isinstance(result.answers["risk"], ScoreAnswer)
    assert result.usage.input_tokens == 123


@pytest.mark.asyncio
async def test_retries_one_transient_failure() -> None:
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(529, headers={"Retry-After": "0.01"})
        return httpx.Response(
            200,
            json={"model": "jev", "answers": {"ok": {"type": "noul", "noul": 0.9}}, "usage": {}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await JevDecisionClient(
            secrets_manager=FakeSecrets(), http_client=http_client, max_retries=1
        ).evaluate(state="hello", questions={"ok": {"type": "noul", "instructions": "ok?"}})

    assert attempts == 2
    assert isinstance(result.answers["ok"], NoulAnswer)


@pytest.mark.asyncio
async def test_outage_and_oversized_state_return_typed_failures() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JevDecisionClient(
            secrets_manager=FakeSecrets(), http_client=http_client, max_retries=0
        )
        with pytest.raises(DecisionProviderUnavailable):
            await client.evaluate(state="hello", questions={"ok": {"type": "noul", "instructions": "ok?"}})
        with pytest.raises(DecisionRequestTooLarge):
            await client.evaluate(
                state="x" * (MAX_SERIALIZED_STATE_CHARS + 1),
                questions={"ok": {"type": "noul", "instructions": "ok?"}},
            )


class SeparateSecrets:
    def __init__(self, *, direct_key: str | None = "direct-key", router_key: str | None = "router-key") -> None:
        self.keys = {"kv/data/providers/typesafe": direct_key, "kv/data/providers/openrouter": router_key}
        self.lookups: list[str] = []

    async def get_secret(self, *, secret_path: str, secret_key: str) -> str | None:
        assert secret_key == "api_key"
        self.lookups.append(secret_path)
        return self.keys[secret_path]


QUESTIONS = {"ok": {"type": "noul", "instructions": "ok?"}}
ANSWER = {"model": "jev-1.13.0", "answers": {"ok": {"type": "noul", "noul": 0.9}}, "usage": {"input_tokens": 10, "output_tokens": 2}}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 403, 429, 503, 529, "timeout"])
async def test_primary_outage_uses_separate_router_credentials(failure) -> None:
    requests = []
    secrets = SeparateSecrets()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.typesafe.ai":
            assert request.headers["authorization"] == "Bearer direct-key"
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(failure)
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer router-key"
        assert request.headers["HTTP-Referer"] == "https://openmates.org"
        assert json.loads(request.content)["model"] == "typesafe/jev-1.13"
        return httpx.Response(200, json=ANSWER)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=45) as http_client:
        result = await JevDecisionClient(secrets_manager=secrets, http_client=http_client,
                                         timeout_seconds=0.2, max_retries=0).evaluate(state="hello", questions=QUESTIONS)
    assert result.provider == "openrouter"
    assert len(requests) == 2
    assert all(request.extensions["timeout"]["read"] == 0.2 for request in requests)
    assert result.usage.input_tokens == 10


@pytest.mark.asyncio
async def test_healthy_primary_never_loads_or_calls_router() -> None:
    secrets = SeparateSecrets()
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.typesafe.ai"
        return httpx.Response(200, json=ANSWER)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await JevDecisionClient(secrets_manager=secrets, http_client=http_client).evaluate(state="hello", questions=QUESTIONS)
    assert result.provider == "typesafe"
    assert secrets.lookups == ["kv/data/providers/typesafe"]
    assert "provider" not in result.model_dump()


@pytest.mark.asyncio
async def test_missing_primary_key_uses_existing_router(monkeypatch) -> None:
    monkeypatch.delenv("SECRET__TYPESAFE__API_KEY", raising=False)
    secrets = SeparateSecrets(direct_key=None)
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer router-key"
        return httpx.Response(200, json=ANSWER)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await JevDecisionClient(secrets_manager=secrets, http_client=http_client).evaluate(state="hello", questions=QUESTIONS)
    assert result.provider == "openrouter"


@pytest.mark.asyncio
async def test_direct_environment_key_after_vault_failure(monkeypatch) -> None:
    monkeypatch.setenv("SECRET__TYPESAFE__API_KEY", "environment-key")
    class UnavailableSecrets:
        async def get_secret(self, **kwargs):
            raise RuntimeError("synthetic vault failure")
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.typesafe.ai"
        assert request.headers["authorization"] == "Bearer environment-key"
        return httpx.Response(200, json=ANSWER)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        await JevDecisionClient(secrets_manager=UnavailableSecrets(), http_client=http_client).evaluate(state="hello", questions=QUESTIONS)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(422, {"error": "bad question"}), (413, {}), (200, {"model": "jev", "answers": {}, "usage": {}})])
async def test_request_or_schema_failure_does_not_fail_over(status, body) -> None:
    from backend.shared.providers.typesafe.client import DecisionProviderError
    requests = []
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(DecisionProviderError):
            await JevDecisionClient(secrets_manager=SeparateSecrets(), http_client=http_client, max_retries=0).evaluate(state="hello", questions=QUESTIONS)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_explicit_primary_probe_cannot_pass_through_fallback(monkeypatch) -> None:
    monkeypatch.delenv("SECRET__TYPESAFE__API_KEY", raising=False)
    client = JevDecisionClient(secrets_manager=SeparateSecrets(direct_key=None), provider="typesafe")
    assert not await client.health_check()
    with pytest.raises(DecisionProviderUnavailable):
        await client.evaluate(state="hello", questions=QUESTIONS)
