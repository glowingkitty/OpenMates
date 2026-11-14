# backend/tests/test_safeguard_tool_call_recovery.py
#
# The safeguard's forced tool call is often rejected by the provider for schema
# noise (an "allow" verdict with an empty severity) or cut off before the call.
# The model's verdict in failed_generation is used instead of refusing the
# request as "safety check unavailable"; an unreadable answer is retried once;
# anything else stays a technical error (no strike).
#
# Run: python -m pytest backend/tests/test_safeguard_tool_call_recovery.py -v

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


class _ToolCallRejected(Exception):
    """Shape of Groq's 400 when the forced tool call misses the schema."""

    def __init__(self, failed_generation: str):
        super().__init__("Error code: 400 - tool_use_failed")
        self.body = {"error": {"code": "tool_use_failed", "failed_generation": failed_generation}}


def _completion(arguments: dict):
    call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(arguments)))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))])


def _safeguard(*outcomes):
    from backend.shared.providers.groq.safeguard import GroqSafeguardClient

    client = GroqSafeguardClient()
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(side_effect=list(outcomes))
    return client


async def _verdict(client):
    return await client.reason(
        policy_markdown="policy", stage="INPUT_VALIDATION_TEXT_ONLY",
        user_prompt="a watercolor of a lighthouse", sightengine_json={}, vlm_json={},
    )


# contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
class TestSafeguardToolCallRecovery:
    """Groq rejects ~half of the verdicts for schema noise (an "allow" with an empty
    severity); the model's verdict in failed_generation is used instead of
    refusing the request as unavailable."""

    # contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
    @pytest.mark.asyncio
    async def test_schema_rejected_verdict_is_recovered_with_reasoning(self):
        generation = json.dumps({
            "name": "functions.report_safeguard_verdict",
            "arguments": {"decision": "allow", "category": "ALLOW_GENERAL",
                          "severity": "", "reasoning": "stylized, non-sexual", "discrepancies": ""},
        })
        client = _safeguard(_ToolCallRejected(generation))
        verdict = await _verdict(client)
        assert verdict.decision == "allow"
        assert verdict.category == "ALLOW_GENERAL"
        assert verdict.reasoning == "stylized, non-sexual"
        assert client._client.chat.completions.create.await_count == 1

    # contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
    @pytest.mark.asyncio
    async def test_empty_failed_generation_retries_once(self):
        client = _safeguard(
            _ToolCallRejected(""),
            _completion({"decision": "block", "category": "S5_minor_restricted_edit",
                         "severity": "severe", "reasoning": "photo of a minor", "discrepancies": ""}),
        )
        verdict = await _verdict(client)
        assert verdict.decision == "block"
        assert verdict.category == "S5_minor_restricted_edit"
        assert client._client.chat.completions.create.await_count == 2

    # contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
    @pytest.mark.asyncio
    async def test_two_unreadable_answers_are_a_technical_error(self):
        client = _safeguard(_ToolCallRejected(""), _ToolCallRejected(""))
        verdict = await _verdict(client)
        assert verdict.category == "safeguard_error"
        assert verdict.decision == "block"

    # contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
    @pytest.mark.asyncio
    async def test_other_api_errors_are_not_retried(self):
        client = _safeguard(RuntimeError("HTTP 503"))
        verdict = await _verdict(client)
        assert verdict.category == "safeguard_error"
        assert client._client.chat.completions.create.await_count == 1

    # contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
    def test_reasoning_budget_leaves_room_for_the_tool_call(self):
        source = (REPO_ROOT / "backend/shared/providers/groq/safeguard.py").read_text()
        reason_body = source.split("async def reason(", 1)[1].split("async def report_malicious_urls(", 1)[0]
        assert "max_tokens=2000" in reason_body
