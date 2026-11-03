# contract-test-file: infrastructure
"""Text pseudo tool calls must not end a turn as an empty answer (S7ZNB follow-up).

Before the fix, a model that wrote ``<tool_call>{...}</tool_call>`` (or a JSON
function-call block) into its reply instead of calling the tool natively had the
block silently withheld: one provider call, no answer, no billing, no error.
"""
import json
from types import SimpleNamespace

import pytest

from backend.apps.ai.utils.pseudo_tool_call import (
    PSEUDO_TOOL_CALL_RETRY_PROMPT,
    PseudoToolCallRecovery,
    known_tool_names,
    pseudo_tool_call_reason,
)
from backend.tests.test_main_processor_invalid_tool_calls import (
    _repository_google_provider_catalogue,  # noqa: F401 - autouse fixture shared with the loop harness
    _run_mocked_protocol_guard_main_processor,
)

KNOWN = known_tool_names(["web-search", "web-read"])
XML_CALL = '<tool_call>{"name": "web_search", "arguments": {"query": "tech CEOs"}}</tool_call>'
JSON_FENCE_CALL = '```json\n{"name": "web-search", "arguments": {"query": "tech CEOs"}}\n```'
LEGIT_JSON_ANSWER = (
    "Use this configuration for the client:\n\n"
    '```json\n{"name": "my-service", "arguments": ["--port", "8080"], "retries": 3}\n```\n\n'
    "Restart the service after saving the file."
)
TOOLS = [{"type": "function", "function": {"name": "web-search", "description": "Search the web."}}]
METADATA = {"web": SimpleNamespace(skills=[SimpleNamespace(
    id="search", parallel_safe=False, exclude_fields_for_llm=None, pricing=None,
    tool_schema={"type": "object", "properties": {"query": {"type": "string"}}},
)], instructions=[], focuses=[])}


async def run(monkeypatch, streams):
    return await _run_mocked_protocol_guard_main_processor(
        monkeypatch, streams, generated_tools=TOOLS, discovered_apps_metadata=METADATA,
        preprocessing_overrides={"selected_app_ids": ["web"], "relevant_app_skills": ["web-search"]},
    )


def text(output):
    return "".join(chunk for chunk in output if isinstance(chunk, str))


def failures(output):
    return [chunk for chunk in output if isinstance(chunk, dict) and chunk.get("__main_processing_failure__")]


def split(value, size=7):
    return [value[i:i + size] for i in range(0, len(value), size)]


@pytest.mark.parametrize("block, reason", [
    (XML_CALL.replace("<tool_call>", "<function_call>").replace("</tool_call>", "</function_call>"),
     "tool_call_markup"),
    ('[TOOL_CALLS] [{"name": "web-search", "arguments": {"query": "x"}}]', "tool_call_markup"),
    (JSON_FENCE_CALL, "json_fence_tool_call"),
    ('```\n{"type": "function", "function": {"name": "web.search", "arguments": "{}"}}\n```',
     "json_fence_tool_call"),
    ('{"tool": "web-read", "input": {"url": "https://example.org"}}', "bare_json_tool_call"),
    ('{"app_id": "web", "skill_id": "search", "parameters": {"query": "x"}}', "bare_json_tool_call"),
])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
def test_classifier_matches_call_shaped_blocks_naming_known_tools(block, reason):
    assert pseudo_tool_call_reason(block, KNOWN) == reason


@pytest.mark.parametrize("block", [
    LEGIT_JSON_ANSWER,
    '```json\n{"name": "my-service", "arguments": []}\n```',  # unknown tool name
    '```json\n{"name": "web-search"}\n```',  # no arguments: not call-shaped
    '```python\nprint({"name": "web-search", "arguments": {}})\n```',  # other language
    '{"name": "web-search", "arguments": {"query": "x"}} is what a call looks like.',  # prose, not pure JSON
    "<function_call> is an XML tag some models use.",  # markup without a known tool
    "Plain answer mentioning web search.",
])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
def test_classifier_keeps_ordinary_answers_and_code_samples(block):
    assert pseudo_tool_call_reason(block, KNOWN) is None


def test_recovery_retries_once_then_errors_and_ignores_substantive_answers():
    recovery = PseudoToolCallRecovery()
    kwargs = {"detected": True, "native_call_count": 0, "has_retry_iteration": True}
    assert recovery.action(**kwargs, visible_text="x" * 500) == "ignore"
    assert recovery.action(**{**kwargs, "native_call_count": 1}, visible_text="") == "ignore"
    assert recovery.action(**kwargs, visible_text="Let me search.") == "retry"
    assert recovery.action(**kwargs, visible_text="") == "error"
    assert PseudoToolCallRecovery().action(**{**kwargs, "has_retry_iteration": False}, visible_text="") == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("first_turn", [split(XML_CALL), ["Let me look that up.\n\n", JSON_FENCE_CALL]])
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
async def test_text_pseudo_tool_call_retries_step_once_with_tools_and_nudge(monkeypatch, first_turn):
    answer = "Here is the real answer."
    output, calls = await run(monkeypatch, [first_turn, [answer]])

    assert len(calls) == 2
    assert calls[1]["tools"] and calls[1]["tool_choice"] != "none"
    assert calls[1]["message_history"][-1] == {"role": "user", "content": PSEUDO_TOOL_CALL_RETRY_PROMPT}
    published = text(output)
    assert answer in published
    assert "tool_call" not in published and '"arguments"' not in published
    assert not failures(output)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
async def test_repeated_text_pseudo_tool_call_surfaces_failure_instead_of_empty_answer(monkeypatch):
    output, calls = await run(monkeypatch, [split(XML_CALL), [JSON_FENCE_CALL]])

    assert len(calls) == 2
    assert text(output) == ""
    assert failures(output) == [{"__main_processing_failure__": True, "reason": "protocol_guard"}]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_legit_answer_with_json_code_block_is_published_unchanged(monkeypatch):
    output, calls = await run(monkeypatch, [split(LEGIT_JSON_ANSWER, 11)])

    assert len(calls) == 1
    assert text(output) == LEGIT_JSON_ANSWER
    assert not failures(output)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_substantive_answer_with_stray_pseudo_call_keeps_answer_without_retry(monkeypatch):
    prose = "Elon Musk leads Tesla and SpaceX, while Sam Altman leads OpenAI. " * 6
    output, calls = await run(monkeypatch, [[prose + "\n\n", XML_CALL]])

    assert len(calls) == 1
    assert text(output).strip() == prose.strip()
    assert json.dumps({"query": "tech CEOs"}) not in text(output)
    assert not failures(output)
