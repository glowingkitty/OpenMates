# contract-test-file: infrastructure
"""A live preprocessing call keeps correction text out of development logs."""

import json
import logging

import pytest

from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, UnifiedOpenAIResponse
from backend.apps.ai.utils import llm_utils


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose,function_name,arguments", [
    ("chat_direction_review", "review_chat_direction", {
        "warranted": True, "instruction": "Return to the synthetic goal: secret-marker-4317",
    }),
    ("early_chat_metadata", "early_chat_metadata", {
        "title": "Private synthetic title secret-marker-4317",
        "summary": "Private synthetic summary secret-marker-4317",
    }),
])
async def test_auxiliary_response_redacts_logged_text_without_changing_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    purpose: str, function_name: str, arguments: dict,
) -> None:
    async def fake_provider(**_kwargs):
        return UnifiedOpenAIResponse(
            task_id="synthetic-review", model_id="fake/model", success=True,
            tool_calls_made=[ParsedOpenAIToolCall(
                tool_call_id="review-call", function_name=function_name,
                function_arguments_raw=json.dumps(arguments),
                function_arguments_parsed=arguments,
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
    # Some backend imports install a non-propagating JSON logger before this
    # test runs. Capture the source logger directly so the privacy assertion
    # verifies its structured record regardless of suite order.
    monkeypatch.setattr(llm_utils.logger, "handlers", [*llm_utils.logger.handlers, caplog.handler])
    monkeypatch.setattr(llm_utils.logger, "propagate", False)

    with caplog.at_level(logging.DEBUG, logger=llm_utils.logger.name):
        result = await llm_utils.call_preprocessing_llm(
            task_id="synthetic-review", model_id="fake/model",
            message_history=[{"role": "user", "content": "Synthetic review context."}],
            tool_definition={"type": "function", "function": {
                "name": function_name, "description": "Generate auxiliary metadata.",
                "parameters": {"type": "object", "properties": {
                    key: {"type": "boolean" if isinstance(value, bool) else "string"}
                    for key, value in arguments.items()
                }, "required": list(arguments)},
            }},
            allow_retries=False, observability_purpose=purpose,
        )

    assert result.error_message is None
    assert result.arguments == arguments
    output_records = [record for record in caplog.records
                      if getattr(record, "event_type", None) == "llm_preprocessing_output"]
    assert len(output_records) == 1
    logged_args = output_records[0].tool_calls_made[0]["function_arguments_parsed"]
    for key, value in arguments.items():
        if isinstance(value, str):
            assert logged_args[key] == {"length": len(value), "content": "[REDACTED_CONTENT]"}
            assert value not in str([record.__dict__ for record in caplog.records])
        else:
            assert logged_args[key] == value
