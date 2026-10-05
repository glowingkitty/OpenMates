# contract-test-file: infrastructure
"""A live preprocessing call keeps correction text out of development logs."""

import logging

import pytest

from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, UnifiedOpenAIResponse
from backend.apps.ai.utils import llm_utils


@pytest.mark.asyncio
async def test_chat_direction_review_redacts_logged_instruction_without_changing_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    private_instruction = "Return to the synthetic goal: secret-marker-4317"

    async def fake_provider(**_kwargs):
        return UnifiedOpenAIResponse(
            task_id="synthetic-review", model_id="fake/model", success=True,
            tool_calls_made=[ParsedOpenAIToolCall(
                tool_call_id="review-call", function_name="review_chat_direction",
                function_arguments_raw='{"warranted":true,"instruction":"' + private_instruction + '"}',
                function_arguments_parsed={"warranted": True, "instruction": private_instruction},
            )],
        )

    class CacheWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _prefix: fake_provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _id: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheWithoutClient)

    with caplog.at_level(logging.DEBUG, logger=llm_utils.logger.name):
        result = await llm_utils.call_preprocessing_llm(
            task_id="synthetic-review", model_id="fake/model",
            message_history=[{"role": "user", "content": "Synthetic review context."}],
            tool_definition={"type": "function", "function": {
                "name": "review_chat_direction", "description": "Review the direction.",
                "parameters": {"type": "object", "properties": {
                    "warranted": {"type": "boolean"}, "instruction": {"type": "string"},
                }, "required": ["warranted", "instruction"]},
            }},
            allow_retries=False, observability_purpose="chat_direction_review",
        )

    assert result.error_message is None
    assert result.arguments == {"warranted": True, "instruction": private_instruction}
    output_records = [record for record in caplog.records
                      if getattr(record, "event_type", None) == "llm_preprocessing_output"]
    assert len(output_records) == 1
    logged_args = output_records[0].tool_calls_made[0]["function_arguments_parsed"]
    assert logged_args["warranted"] is True
    assert logged_args["instruction"] == {
        "length": len(private_instruction), "content": "[REDACTED_CONTENT]",
    }
    assert private_instruction not in str([record.__dict__ for record in caplog.records])
