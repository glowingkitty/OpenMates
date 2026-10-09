"""Synthetic replay admits only the five-turn selected-tool native route."""

# contract-test-file: infrastructure
# contract-test: supporting surface=gui.web assertions=billing.usage.receipt-token-breakdown

import copy
import json
import logging

import pytest

from backend.apps.ai.testing.native_cache_tools_fixture import (
    PROMPTS, generate_fixture, safe_native_main_miss_diagnostic,
)
from backend.apps.ai.testing.caching_llm_wrapper import _deserialize_stream_chunks
from backend.apps.ai.llm_providers.native_cache_context import NativeCacheProviderOutput
from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata


def _kwargs(turn: int, *, tools: bool, native: bool, returned: bool = False):
    assert tools == (turn in {1, 3})
    messages = []
    for prior in range(1, turn):
        messages.extend([
            {"role": "user", "content": PROMPTS[prior]},
            {"role": "assistant", "content": "prior answer", "provider_transport_state": [
                {"type": "reasoning", "encrypted_content": f"PRIVATE_NATIVE_CACHE_FRAME_TURN_{prior}"}]},
        ])
    messages.append({"role": "user", "content": PROMPTS[turn]})
    if returned:
        messages.extend([
            {"role": "assistant", "content": "", "provider_transport_state": [
                {"type": "function_call", "call_id": "native-fixture-call",
                 "name": "math-calculate", "arguments": (
                     '{"expression": "sqrt(144)"}' if turn == 1 else '{"expression": "sqrt(169)"}')} ]},
            {"role": "tool", "tool_call_id": "native-fixture-call", "content": "12"},
        ])
    tool = {"type": "function", "function": {"name": "math-calculate",
            "parameters": {"type": "object", "properties": {}}}}
    canonical = [{"role": "system", "content": "Stable prefix"}, *messages]
    events = []
    if turn >= 2:
        events.append({"after_message_index": 2 * (2 - 1) + 1, "remove_tools": ["math-calculate"]})
    if turn >= 3:
        events.append({"after_message_index": 2 * (3 - 1) + 1, "add_tools": [tool]})
    if turn >= 4:
        events.append({"after_message_index": 2 * (4 - 1) + 1, "remove_tools": ["math-calculate"]})
    return {"model": "gpt-6.1-sol", "messages": canonical,
            "tools": [tool],
            "native_cache_context": {"messages": canonical, "baseline_tools": [tool],
                                     "events": events} if native else None}


def test_native_replay_requires_matching_tools_and_continuation():
    for turn in range(1, 6):
        enabled = turn in {1, 3}
        kwargs = _kwargs(turn, tools=enabled, native=True, returned=enabled)
        response = generate_fixture("llm/gpt-6.1-sol", kwargs)
        assert response["response"]["type"] == "mixed_stream"
        assert any(chunk.get("class") == "NativeCacheProviderOutput"
                   for chunk in response["response"]["chunks"])
    assert generate_fixture("llm/gpt-6.1-sol", _kwargs(2, tools=False, native=False)) is None
    assert generate_fixture("llm/other-model", _kwargs(2, tools=False, native=True)) is None


def test_native_replay_reports_cache_metrics_and_tool_invocation():
    cold = generate_fixture("llm/gpt-6.1-sol", _kwargs(1, tools=True, native=True))
    cached = generate_fixture("llm/gpt-6.1-sol", _kwargs(3, tools=True, native=True))
    assert cold["response"]["chunks"][0]["value"]["function_name"] == "math-calculate"
    assert cached["response"]["chunks"][0]["value"]["function_arguments_parsed"] == {
        "expression": "sqrt(169)"}
    assert cold["response"]["chunks"][2]["value"]["cache_read_input_tokens"] == 0
    assert cached["response"]["chunks"][2]["value"]["cache_read_input_tokens"] > 0
    assert cold["response"]["chunks"][1]["class"] == "NativeCacheProviderOutput"
    assert cold["response"]["chunks"][1]["value"]["output"][-1] == {
        "type": "function_call", "call_id": "native-fixture-call",
        "name": "math-calculate", "arguments": '{"expression": "sqrt(144)"}'}
    chunks = _deserialize_stream_chunks(cached["response"]["chunks"])
    assert isinstance(chunks[1], NativeCacheProviderOutput)
    assert isinstance(chunks[2], OpenAIUsageMetadata)
    assert isinstance(_deserialize_stream_chunks(generate_fixture(
        "llm/gpt-6.1-sol", _kwargs(2, tools=False, native=True)
    )["response"]["chunks"])[-1], NativeCacheProviderOutput)


def test_prior_math_tool_can_be_removed_then_readded_in_native_timeline():
    second = _kwargs(2, tools=False, native=True)
    assert generate_fixture("llm/gpt-6.1-sol", second) is not None

    third = _kwargs(3, tools=True, native=True)
    assert generate_fixture("llm/gpt-6.1-sol", third) is not None
    cold = _kwargs(3, tools=True, native=True)
    cold["native_cache_context"]["messages"] = [
        {"role": "system", "content": "Stable prefix"},
        {"role": "user", "content": PROMPTS[3]},
    ]
    cold["native_cache_context"]["events"] = []
    assert generate_fixture("llm/gpt-6.1-sol", cold) is None
    dropped = _kwargs(3, tools=True, native=True)
    del dropped["native_cache_context"]["messages"][2]["provider_transport_state"]
    assert generate_fixture("llm/gpt-6.1-sol", dropped) is None


def test_tool_result_phase_requires_matching_private_call_and_result():
    proper = _kwargs(3, tools=True, native=True, returned=True)
    assert generate_fixture("llm/gpt-6.1-sol", proper) is not None
    bad_result = _kwargs(3, tools=True, native=True, returned=True)
    bad_result["messages"][-1]["tool_call_id"] = "other-call"
    assert generate_fixture("llm/gpt-6.1-sol", bad_result) is None
    bad_call = _kwargs(3, tools=True, native=True, returned=True)
    bad_call["messages"][-2]["provider_transport_state"][0]["arguments"] = "{}"
    assert generate_fixture("llm/gpt-6.1-sol", bad_call) is None


def test_prior_marker_in_visible_text_does_not_fake_native_replay():
    forged = _kwargs(5, tools=False, native=True)
    prior = forged["messages"][2]
    prior["content"] = "PRIVATE_NATIVE_CACHE_FRAME_TURN_1"
    prior.pop("provider_transport_state")
    assert generate_fixture("llm/gpt-6.1-sol", forged) is None


def test_preprocessing_classification_does_not_force_removed_math_tool():
    """The product's math task-area rule augments even an empty skill list."""
    for turn in range(1, 6):
        response = generate_fixture("llm_non_stream/gemini-3.5-flash-lite", {
            "model": "gemini-3.5-flash-lite",
            "messages": [{"role": "system", "content": "Classify"},
                         {"role": "user", "content": PROMPTS[turn]}],
            "tools": [{"type": "function", "function": {
                "name": "analyze_request_properties", "parameters": {"type": "object"},
            }}],
            "tool_choice": "required",
        })
        assert response is not None, turn
        arguments = response["response"]["value"]["value"]["tool_calls_made"][0]["function_arguments_parsed"]
        math_selected = turn in {1, 3}
        assert arguments["relevant_app_skills"] == (["math-calculate"] if math_selected else [])
        assert (arguments["task_area"] == "math") is math_selected


def test_native_fixture_miss_codes_identify_only_the_rejected_predicate():
    good = _kwargs(2, tools=False, native=True)
    assert safe_native_main_miss_diagnostic("llm/gpt-6.1-sol", good)["reason"] == "accepted"
    variants = {}
    missing = copy.deepcopy(good)
    missing["native_cache_context"] = None
    variants["native_absent"] = missing
    wire = copy.deepcopy(good)
    wire["native_cache_context"]["messages"] = wire["messages"][:-1]
    variants["wire_messages_mismatch"] = wire
    baseline = copy.deepcopy(good)
    baseline["tools"] = []
    variants["baseline_mismatch"] = baseline
    invalid = copy.deepcopy(good)
    invalid["native_cache_context"]["events"][0]["after_message_index"] = -1
    variants["native_invalid"] = invalid
    prefix = copy.deepcopy(good)
    prefix["messages"][2].pop("provider_transport_state")
    variants["prefix_invalid"] = prefix
    still_math = copy.deepcopy(good)
    still_math["native_cache_context"]["events"] = []
    variants["active_math_mismatch"] = still_math
    model = copy.deepcopy(good)
    model["model"] = "other"
    variants["model_mismatch"] = model
    phase = _kwargs(1, tools=True, native=True, returned=True)
    phase["messages"][-1]["tool_call_id"] = "wrong-call"
    variants["tool_phase_invalid"] = phase

    for code, request in variants.items():
        diagnostic = safe_native_main_miss_diagnostic("llm/gpt-6.1-sol", request)
        assert diagnostic is not None
        assert diagnostic["reason"] == code
        assert diagnostic["turn"] in {"turn_1", "turn_2"}
        assert all(type(value) in {str, int, bool} for value in diagnostic.values())


@pytest.mark.asyncio
async def test_signed_mock_miss_logs_only_fixed_safe_diagnostic(monkeypatch):
    from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
    from backend.shared.testing.api_response_cache import MockCacheMiss
    from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    request = _kwargs(2, tools=False, native=True)
    request["native_cache_context"]["events"] = []
    request["tool_choice"] = {"PRIVATE_CHOICE_SENTINEL": "PRIVATE_VALUE_SENTINEL"}
    request["messages"][-1]["content"] += " PRIVATE_USER_SENTINEL"
    request["messages"][2]["provider_transport_state"].append({
        "type": "reasoning", "encrypted_content": "PRIVATE_FRAME_SENTINEL",
    })
    class NoCassette:
        def fingerprint_llm_call(self, **_kwargs):
            return "PRIVATE_FINGERPRINT_SENTINEL"

        def load(self, *_args):
            return None

    async def forbidden_provider(**_kwargs):
        raise AssertionError("provider egress")

    wrapped = wrap_provider_with_cache(forbidden_provider, NoCassette())
    activate_mock_mode("mock", "native_cache_tools_v1", task_id="signed-diagnostic-test")
    # Capture the exact logger once regardless of suite logging configuration.
    from backend.apps.ai.testing import caching_llm_wrapper
    fixture_logger = caching_llm_wrapper.logger
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    prior_level = fixture_logger.level
    fixture_logger.setLevel(logging.WARNING)
    fixture_logger.addHandler(handler)
    try:
        with pytest.raises(MockCacheMiss) as raised:
            stream = await wrapped(stream=True, **request)
            async for _chunk in stream:
                pass
        diagnostic = raised.value.safe_native_diagnostic
        assert diagnostic["reason"] == "active_math_mismatch"
        assert diagnostic["tool_choice"] == "other"
        assert diagnostic["math_active"] is True
        assert diagnostic["prior_frames"] == 1
        logs = [record.getMessage() for record in records
                if "Native signed fixture miss" in record.getMessage()]
        assert len(logs) == 1
        assert json.loads(logs[0].split("Native signed fixture miss ", 1)[1]) == diagnostic
        joined = logs[0] + str(raised.value)
        for forbidden in ("PRIVATE_USER_SENTINEL", "PRIVATE_FRAME_SENTINEL",
                          "PRIVATE_FINGERPRINT_SENTINEL", "PRIVATE_CHOICE_SENTINEL",
                          "PRIVATE_VALUE_SENTINEL", "native-fixture-call"):
            assert forbidden not in joined
    finally:
        fixture_logger.removeHandler(handler)
        fixture_logger.setLevel(prior_level)
        deactivate_mock_mode()
