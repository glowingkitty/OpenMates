# backend/tests/test_openai_tool_choice.py
#
# Purpose: regression test for OPE-376 — tool_choice="required" was being
# translated to {"type": "function"} (an incomplete/invalid object that the
# OpenAI v2 API rejects with a 400), surfacing to users as
# "AI service encountered an error".
# Architecture: pins the contract between our provider wrapper and the
# upstream OpenAI SDK/API shape. If we ever change the mapping again, this
# test should fail loudly instead of bubbling up as a generic AI error.
# Refs: backend/apps/ai/llm_providers/openai_client.py (lines 275 and 468).

import asyncio
from typing import Any, Dict, List

import pytest

try:
    from backend.apps.ai.llm_providers import openai_client
except ImportError:
    pytestmark = pytest.mark.skip(reason="Backend AI deps not installed")
    openai_client = None  # type: ignore[assignment]


class _CapturingCompletions:
    """Stub that records the payload and returns a minimal chat-completion."""

    def __init__(self) -> None:
        self.captured: Dict[str, Any] = {}

    async def create(self, **payload: Any) -> Any:
        self.captured = payload

        class _Msg:
            content = "ok"
            tool_calls = None

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            id = "chatcmpl-test"
            model = payload.get("model")
            choices = [_Choice()]
            usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()

            def model_dump(self) -> Dict[str, Any]:
                return {
                    "id": self.id,
                    "model": self.model,
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "ok", "tool_calls": None},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

        return _Resp()


class _StubClient:
    def __init__(self) -> None:
        self.chat = type("C", (), {})()
        self.chat.completions = _CapturingCompletions()


@pytest.mark.parametrize("tool_choice", ["required", "auto", "none"])
def test_tool_choice_is_passed_as_bare_string(monkeypatch: pytest.MonkeyPatch, tool_choice: str) -> None:
    """tool_choice must reach the OpenAI SDK as a bare string, never as
    an incomplete {"type": "function"} object (OPE-376 regression)."""
    stub = _StubClient()
    monkeypatch.setattr(openai_client, "_openai_direct_client", stub)
    monkeypatch.setattr(openai_client, "_is_reasoning_model", lambda _m: False)
    # Skip token-breakdown helper which imports tiktoken tables we don't need here.
    monkeypatch.setattr(
        openai_client,
        "calculate_token_breakdown",
        lambda *_a, **_k: {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
        raising=False,
    )

    tools: List[Dict[str, Any]] = [
        {
            "name": "dummy_tool",
            "description": "test",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    asyncio.run(
        openai_client._invoke_openai_direct_api(
            task_id="t-1",
            model_id="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=16,
            tools=tools,
            tool_choice=tool_choice,
            stream=False,
        )
    )

    captured = stub.chat.completions.captured
    assert captured.get("tool_choice") == tool_choice, (
        f"tool_choice must be passed as the bare string {tool_choice!r}, "
        f"got: {captured.get('tool_choice')!r}"
    )
