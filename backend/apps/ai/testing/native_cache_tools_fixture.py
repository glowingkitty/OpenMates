"""Deterministic signed replay for one native-cache, changing-tools chat.

Only the exact test group reaches this fixture. Unknown phases return no response,
so the isolated provider gate fails closed before any external dispatch.
"""

from __future__ import annotations

import json
from typing import Any


GROUP = "native_cache_tools_v1"
PROMPTS = {
    1: "What is the square root of 144?",
    2: "Why does twelve make sense as that answer?",
    3: "What is the square root of 169?",
    4: "How do those two examples help explain square roots?",
    5: "What simple rule should I remember from both examples?",
}


def _chunk(module: str, name: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "pydantic", "module": module, "class": name, "value": value}


def _call(name: str, arguments: dict[str, Any], model: str) -> dict[str, Any]:
    google = "gemini" in model
    return _chunk(
        "backend.apps.ai.llm_providers.google_client" if google else "backend.apps.ai.llm_providers.openai_shared",
        "ParsedGoogleToolCall" if google else "ParsedOpenAIToolCall",
        {"tool_call_id": "native-fixture-call", "function_name": name,
         "function_arguments_raw": json.dumps(arguments), "function_arguments_parsed": arguments,
         "parsing_error": None,
         **({"provider_transport_state": [{"type": "function_call", "call_id": "native-fixture-call",
                                          "name": name, "arguments": json.dumps(arguments)}]}
            if not google else {})},
    )


def _tool_names(tools: Any) -> set[str]:
    return {function["name"] for tool in tools or [] if isinstance(tool, dict)
            if isinstance(function := tool.get("function"), dict)
            and isinstance(function.get("name"), str)}


def _last_turn(messages: Any) -> tuple[int | None, list[dict[str, Any]]]:
    if not isinstance(messages, list):
        return None, []
    for index in range(len(messages) - 1, -1, -1):
        item = messages[index]
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = str(item.get("content", ""))
        for turn, prompt in PROMPTS.items():
            if prompt in content:
                return turn, [part for part in messages[index + 1:] if isinstance(part, dict)]
    return None, []


def _preprocessing_arguments(turn: int) -> dict[str, Any]:
    skill = ["math-calculate"] if turn in {1, 3} else []
    # The real preprocessor always adds math-calculate when task_area is math,
    # even if relevant_app_skills is empty. Explanatory turns must classify as
    # general so the signed main fixture can observe the intended removal.
    task_area = "math" if skill else "general"
    return {"llm_response_temp": 0.4, "complexity": "simple", "task_area": task_area,
            "user_unhappy": False, "china_model_sensitive": False,
            "enable_subchats": False, "load_app_settings_and_memories": [],
            "relevant_app_skills": skill, "relevant_focus_modes": [],
            "relevant_embedded_previews": [], "topic_area": "general_misc",
            "topic_shift": "same_topic", "harmful_or_illegal": 0,
            "misuse_risk": 0, "output_language": "en",
            "title": "Synthetic Square Roots", "icon_names": ["calculator"]}


def _frame(turn: int) -> str:
    return f"PRIVATE_NATIVE_CACHE_FRAME_TURN_{turn}"


def _replayed_prefix_valid(native: dict[str, Any], turn: int) -> bool:
    """A new cold segment cannot claim cache hits for prior synthetic turns."""
    messages = native.get("messages")
    if not isinstance(messages, list) or _last_turn(messages)[0] != turn:
        return False
    for prior in range(1, turn):
        if not any(message.get("role") == "user" and PROMPTS[prior] in str(message.get("content", ""))
                   for message in messages if isinstance(message, dict)):
            return False
        if not any(message.get("role") == "assistant"
                   and _frame(prior) in json.dumps(message.get("provider_transport_state", []))
                   for message in messages if isinstance(message, dict)):
            return False
    return True


def _tool_phase(tail: list[dict[str, Any]], *, expected_tools: bool,
                expression: str | None) -> str | None:
    if not expected_tools:
        return "answer" if not tail else None
    if not tail:
        return "call"
    if (len(tail) == 2 and tail[0].get("role") == "assistant"
            and tail[1].get("role") == "tool"
            and tail[1].get("tool_call_id") == "native-fixture-call"):
        state = tail[0].get("provider_transport_state")
        if (isinstance(state, list) and any(
                isinstance(item, dict) and item.get("type") == "function_call"
                and item.get("call_id") == "native-fixture-call"
                and item.get("name") == "math-calculate"
                and item.get("arguments") == json.dumps({"expression": expression})
                for item in state)):
            return "answer"
    return None


def _native_main_verdict(
    category: str, kwargs: dict[str, Any], turn: int | None,
    tail: list[dict[str, Any]],
) -> tuple[str, str | None]:
    """One validation path for replay and fixed-enum mock-miss diagnosis."""
    if turn is None:
        return "turn_unrecognized", None
    if (category != "llm/gpt-6.1-sol"
            or (kwargs.get("model") or kwargs.get("model_id")) != "gpt-6.1-sol"):
        return "model_mismatch", None
    native = kwargs.get("native_cache_context")
    if not isinstance(native, dict):
        return "native_absent", None
    if kwargs.get("messages") != native.get("messages"):
        return "wire_messages_mismatch", None
    if kwargs.get("tools") != native.get("baseline_tools"):
        return "baseline_mismatch", None
    from backend.apps.ai.llm_providers.native_cache_context import validate_native_cache_context
    try:
        _baseline, _events, active_tools = validate_native_cache_context(native, native["messages"])
    except (KeyError, TypeError, ValueError):
        return "native_invalid", None
    try:
        if not _replayed_prefix_valid(native, turn):
            return "prefix_invalid", None
    except (TypeError, ValueError):
        return "prefix_invalid", None
    expected_tools = turn in {1, 3}
    if ("math-calculate" in active_tools) != expected_tools:
        return "active_math_mismatch", None
    expression = "sqrt(144)" if turn == 1 else "sqrt(169)" if turn == 3 else None
    phase = _tool_phase(tail, expected_tools=expected_tools, expression=expression)
    if phase is None:
        return "tool_phase_invalid", None
    return "accepted", phase


def safe_native_main_miss_diagnostic(
    category: str, kwargs: dict[str, Any],
) -> dict[str, str | int | bool] | None:
    """Bounded enums/counts only; never include provider text or private frames."""
    if (not category.startswith("llm/")
            or (category != "llm/gpt-6.1-sol"
                and not isinstance(kwargs.get("native_cache_context"), dict))):
        return None
    wire = kwargs.get("messages")
    turn, tail = _last_turn(wire)
    if turn is None:
        return None  # Unrecognized requests have no signed-fixture diagnosis.
    reason, _phase = _native_main_verdict(category, kwargs, turn, tail)
    native = kwargs.get("native_cache_context")
    replay = native.get("messages") if isinstance(native, dict) else None
    replay = replay if isinstance(replay, list) else []
    events = native.get("events") if isinstance(native, dict) else None
    baseline = native.get("baseline_tools") if isinstance(native, dict) else None
    active = native.get("active_tools") if isinstance(native, dict) else None
    baseline = baseline if isinstance(baseline, list) else []
    active = active if isinstance(active, list) else []
    active_names = _tool_names(active)
    if isinstance(native, dict) and replay:
        from backend.apps.ai.llm_providers.native_cache_context import validate_native_cache_context
        try:
            _baseline, _events, validated_active = validate_native_cache_context(native, replay)
            active_names = set(validated_active)
        except (KeyError, TypeError, ValueError):
            pass
    prior_users = 0
    prior_frames = 0
    for prior in range(1, turn):
        if any(isinstance(message, dict) and message.get("role") == "user"
               and PROMPTS[prior] in str(message.get("content", "")) for message in replay):
            prior_users += 1
        try:
            if any(isinstance(message, dict) and message.get("role") == "assistant"
                   and _frame(prior) in json.dumps(message.get("provider_transport_state", []))
                   for message in replay):
                prior_frames += 1
        except (TypeError, ValueError):
            pass
    choice = kwargs.get("tool_choice")
    return {
        "reason": reason,
        "turn": f"turn_{turn}",
        "model_class": "gpt_6_1_sol" if (kwargs.get("model") or kwargs.get("model_id")) == "gpt-6.1-sol" else "other",
        "tool_choice": choice if isinstance(choice, str) and choice in {"auto", "none", "required"} else "other",
        "native_present": isinstance(native, dict),
        "wire_equals_frozen": isinstance(native, dict) and wire == replay,
        "tools_equal_baseline": isinstance(native, dict) and kwargs.get("tools") == baseline,
        "wire_message_count": min(len(wire), 8) if isinstance(wire, list) else 0,
        "replay_message_count": min(len(replay), 8),
        "event_count": min(len(events), 8) if isinstance(events, list) else 0,
        "baseline_count": min(len(baseline), 8),
        "active_count": min(len(active_names), 8),
        "math_active": "math-calculate" in active_names,
        "prior_users": prior_users,
        "prior_frames": prior_frames,
        "tail_class": "empty" if not tail else "paired" if len(tail) == 2
            and tail[0].get("role") == "assistant" and tail[1].get("role") == "tool" else "other",
    }


def generate_fixture(category: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    model = str(kwargs.get("model") or kwargs.get("model_id") or "")
    turn, tail = _last_turn(kwargs.get("messages"))
    if turn is None or not category.startswith(("llm/", "llm_non_stream/")):
        return None
    if category.rsplit("/", 1)[-1] != model:
        return None
    names = _tool_names(kwargs.get("tools"))
    if category.startswith("llm_non_stream/"):
        if model != "gemini-3.5-flash-lite" or kwargs.get("tool_choice") != "required":
            return None
        if names == {"analyze_request_properties"}:
            arguments = _preprocessing_arguments(turn)
            return {"response": {"type": "non_stream", "value": _chunk(
                "backend.apps.ai.llm_providers.google_client", "UnifiedGoogleResponse",
                {"task_id": str(kwargs.get("task_id", "native-preprocessor")), "model_id": model,
                 "success": True, "tool_calls_made": [_call("analyze_request_properties", arguments, model)["value"]],
                 "usage": {"prompt_token_count": 100, "candidates_token_count": 40, "total_token_count": 140}},
            )}}
        if names == {"generate_suggestions_and_metadata"}:
            arguments = {"follow_up_app_skill_suggestions": ["Calculate another square root"],
                         "follow_up_general_suggestions": ["Explain the answer"],
                         "chat_summary": "A synthetic square-root conversation.",
                         "chat_tags": ["math"], "share_cta_text": "Explore square roots",
                         "updated_chat_title": "Synthetic Square Roots",
                         "daily_inspiration_topic_suggestions": ["square roots"], "quick_tip_slug": ""}
            return {"response": {"type": "non_stream", "value": _chunk(
                "backend.apps.ai.llm_providers.google_client", "UnifiedGoogleResponse",
                {"task_id": str(kwargs.get("task_id", "native-postprocessor")), "model_id": model,
                 "success": True, "tool_calls_made": [_call("generate_suggestions_and_metadata", arguments, model)["value"]],
                 "usage": {"prompt_token_count": 100, "candidates_token_count": 40, "total_token_count": 140}},
            )}}
        return None

    if model == "gemini-3.5-flash-lite" and "analyze_request_properties" in names:
        return {"response": {"type": "mixed_stream", "chunks": [
            _call("analyze_request_properties", _preprocessing_arguments(turn), model),
        ]}}
    if model != "gpt-6.1-sol":
        return None
    reason, phase = _native_main_verdict(category, kwargs, turn, tail)
    if reason != "accepted":
        return None
    expected_tools = turn in {1, 3}
    expression = "sqrt(144)" if turn == 1 else "sqrt(169)" if turn == 3 else None
    if phase == "answer" and expected_tools:
        answer = "The square root is 12." if turn == 1 else "The square root is 13."
    elif phase == "call":
        arguments = {"expression": expression}
        return {"response": {"type": "mixed_stream", "chunks": [
            _call("math-calculate", arguments, model),
            _chunk("backend.apps.ai.llm_providers.native_cache_context", "NativeCacheProviderOutput",
                   {"provider_prefix": "openai", "model_id": model,
                    "output": [{"type": "reasoning", "encrypted_content": _frame(turn)},
                               {"type": "function_call", "call_id": "native-fixture-call",
                                "name": "math-calculate", "arguments": json.dumps(arguments)}]}),
            _chunk("backend.apps.ai.llm_providers.openai_shared", "OpenAIUsageMetadata",
                   {"input_tokens": 240, "output_tokens": 24, "total_tokens": 264,
                    "cache_read_input_tokens": 80 if turn > 1 else 0,
                    "cache_creation_input_tokens": 0, "usage_source": "provider_reported"}),
        ]}}
    else:
        answer = ("Yes. Twelve times twelve is 144." if turn == 2
                  else "Thirteen times thirteen is 169, so the two examples agree." if turn == 4
                  else "A square root is the number that multiplies by itself to make the target.")
    read = 80 if turn > 1 else 0
    return {"response": {"type": "mixed_stream", "chunks": [
        {"kind": "text", "value": answer},
        _chunk("backend.apps.ai.llm_providers.openai_shared", "OpenAIUsageMetadata",
               {"input_tokens": 240, "output_tokens": 28, "total_tokens": 268,
                "cache_read_input_tokens": read, "cache_creation_input_tokens": 0,
                "usage_source": "provider_reported"}),
        _chunk("backend.apps.ai.llm_providers.native_cache_context", "NativeCacheProviderOutput",
               {"provider_prefix": "openai", "model_id": model,
                "output": [{"type": "reasoning", "encrypted_content": _frame(turn)},
                           {"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": answer}]}]}),
    ]}}
