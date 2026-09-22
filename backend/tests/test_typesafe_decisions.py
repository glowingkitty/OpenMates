"""Unit tests for the OpenRouter Jev decision transport."""

# contract-test-file: infrastructure

from __future__ import annotations

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
        assert secret_path == "kv/data/providers/openrouter"
        assert secret_key == "api_key"
        return "test-key"


@pytest.mark.asyncio
async def test_parses_all_decision_answer_types() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
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
