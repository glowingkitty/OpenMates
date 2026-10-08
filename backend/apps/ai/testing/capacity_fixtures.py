"""Scripted provider outputs for signed storage-capacity replay only.

The caller gates this module on the nonproduction storage_capacity_ group and
replay mode. Each branch recognizes a concrete pipeline phase; unknown prompts
return None so the normal cache miss stops before provider dispatch.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
import os


SCENARIO = re.compile(
    r"STORAGE_CAPACITY_SCENARIO:(round|tool|child|child_worker|version_create|version_update|"
    r"recovery_embed|recovery_diff|recovery_checkpoint|recovery_save_failure|"
    r"recovery_detached_doc)(?:\b|$)"
)

_VERSION_MARKER = re.compile(r"(?:[a-f0-9]|\[OM_PII_[A-F0-9]{32}\])+")
_BASE_HASH = re.compile(r"[a-f0-9]{64}")
_VERSION_LIMIT = 200_000
_COMPLETION_LIMIT_BYTES = 512 * 1024
_INVALID_COMPLETION = object()


def _version_line(prompt: str, name: str) -> str | None:
    """Keep the entire model-visible line so the client can restore PII tokens."""
    prefix = f"CAPACITY_VERSION_{name}:"
    lines = [line[len(prefix):] for line in prompt.splitlines() if line.startswith(prefix)]
    if len(lines) != 1 or not 0 < len(lines[0]) <= _VERSION_LIMIT:
        return None
    return lines[0] if _VERSION_MARKER.fullmatch(lines[0]) else None


def _version_prompt(messages: Any, scenario: str) -> tuple[str | None, int]:
    for index in range(len(messages or []) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        prompt = message.get("content")
        if isinstance(prompt, str) and f"STORAGE_CAPACITY_SCENARIO:{scenario}" in prompt \
                and "CAPACITY_VERSION_NEW:" in prompt:
            return prompt, index
    return None, -1


def _project_completion(messages: Any) -> dict[str, Any] | object | None:
    """Decode the bounded Project completion presented to the model."""
    for message in reversed(messages or []):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        marker = "Completed tool result (TOON):\n"
        # llm_utils turns sender_name into this attributed prefix before the
        # signed replay fixture sees provider messages.
        attributed = isinstance(content, str) and content.startswith(
            "[async_tool_result]: Automatic tool-completion event, not a new request")
        if message.get("sender_name") != "async_tool_result" and not attributed:
            continue
        if not isinstance(content, str) or len(content.encode("utf-8")) > _COMPLETION_LIMIT_BYTES \
                or marker not in content:
            return _INVALID_COMPLETION
        encoded = content.split(marker, 1)[1]
        try:
            from toon_format import decode as toon_decode
        except ImportError:  # Unit environments use the continuation's JSON fallback.
            toon_decode = json.loads
        try:
            result = toon_decode(encoded)
        except Exception:
            try:
                result = json.loads(encoded)
            except (TypeError, ValueError):
                return _INVALID_COMPLETION
        return result if isinstance(result, dict) else _INVALID_COMPLETION
    return None


def _approved_read_base(completion: dict[str, Any]) -> str | None:
    if completion.get("status") != "completed" or completion.get("tool_name") != "project_read_text" \
            or completion.get("arguments") != {"path": "capacity.txt"}:
        return None
    results = completion.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        return None
    result = results[0]
    base = result.get("expected_base")
    if result.get("operation") != "read_text" or result.get("status") != "completed" \
            or result.get("path") != "capacity.txt" or result.get("truncated") is not False \
            or not isinstance(base, str) or not _BASE_HASH.fullmatch(base):
        return None
    return base


def should_fail_child_prompt_save(prompt: str, user_id: str) -> bool:
    """Verify the signed replay marker before simulating a durable-save failure."""
    if os.getenv("OPENMATES_STORAGE_CAPACITY_FIXTURES") != "true":
        return False
    from backend.shared.testing.mock_context import resolve_live_marker_or_raise

    marker = resolve_live_marker_or_raise(prompt, user_id)
    return bool(marker and marker.mode == "mock" and marker.group_id == "storage_capacity_v1"
                and "STORAGE_CAPACITY_SCENARIO:recovery_save_failure" in prompt)


def _text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    return "\n".join(str(message.get("content", "")) for message in messages if isinstance(message, dict))


def _tool_names(tools: Any) -> set[str]:
    if not isinstance(tools, list):
        return set()
    names = set()
    for tool in tools:
        if isinstance(tool, dict):
            function = tool.get("function")
            name = function.get("name") if isinstance(function, dict) else tool.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def _current_turn_tail(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    for index in range(len(messages) - 1, -1, -1):
        item = messages[index]
        if isinstance(item, dict) and item.get("role") == "user" and SCENARIO.search(str(item.get("content", ""))):
            return [entry for entry in messages[index + 1:] if isinstance(entry, dict)]
    return []


def _tool_returned(messages: Any) -> bool:
    return any(message.get("role") == "tool" for message in _current_turn_tail(messages))


def _call(name: str, arguments: dict[str, Any], *, google: bool, fingerprint: str) -> dict[str, Any]:
    module = "backend.apps.ai.llm_providers.google_client" if google else "backend.apps.ai.llm_providers.openai_shared"
    cls = "ParsedGoogleToolCall" if google else "ParsedOpenAIToolCall"
    return {
        "kind": "pydantic", "module": module, "class": cls,
        "value": {
            "tool_call_id": f"capacity-{fingerprint[:12]}",
            "function_name": name,
            "function_arguments_raw": json.dumps(arguments, sort_keys=True),
            "function_arguments_parsed": arguments,
            "parsing_error": None,
        },
    }


def _main_usage(model: str) -> dict[str, Any]:
    """Replay one provider-style, billable usage report per synthetic main call."""
    if "gemini" in model.lower():
        module, cls = "backend.apps.ai.llm_providers.google_client", "GoogleUsageMetadata"
        value = {"prompt_token_count": 100, "candidates_token_count": 40, "total_token_count": 140}
    elif "mistral" in model.lower():
        module, cls = "backend.apps.ai.llm_providers.mistral_client", "MistralUsage"
        value = {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}
    elif "claude" in model.lower() or "anthropic" in model.lower():
        module, cls = "backend.apps.ai.llm_providers.anthropic_shared", "AnthropicUsageMetadata"
        value = {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}
    else:
        module, cls = "backend.apps.ai.llm_providers.openai_shared", "OpenAIUsageMetadata"
        value = {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}
    return {"kind": "pydantic", "module": module, "class": cls, "value": value}


def _main_stream(model: str, *chunks: Any) -> dict[str, Any]:
    return {"response": {"type": "mixed_stream", "body": "", "chunk_format_version": 1,
                         "chunks": [*({"kind": "text", "value": chunk} if isinstance(chunk, str) else chunk
                                      for chunk in chunks), _main_usage(model)]}}


def _preprocessing_arguments(scenario: str) -> dict[str, Any]:
    return {
        "llm_response_temp": 0.4,
        "complexity": "complex" if scenario in {"child", "recovery_save_failure"} else "simple",
        "task_area": "math" if scenario == "tool" else "code",
        "user_unhappy": False,
        "china_model_sensitive": False,
        "enable_subchats": scenario in {"child", "recovery_save_failure"},
        "load_app_settings_and_memories": [],
        "relevant_app_skills": ["math-calculate"] if scenario == "tool" else [],
        "relevant_focus_modes": [],
        "relevant_embedded_previews": [],
        "topic_area": "general_misc",
        "topic_shift": "same_topic",
        "harmful_or_illegal": 0,
        "misuse_risk": 0,
        "output_language": "en",
        "title": "Synthetic Storage Capacity Chat",
        "icon_names": ["code"],
    }


def _postprocessing_arguments(fingerprint: str) -> dict[str, Any]:
    """Valid, content-free metadata for the exact post-answer utility tool."""
    return {
        "follow_up_app_skill_suggestions": [
            "Search for related storage examples",
            "Calculate a sample archive size",
            "Find a relevant technical reference",
        ],
        "follow_up_general_suggestions": [
            "Explain the synthetic storage result",
            "Compare the sample archive choices",
            "Summarize the completed storage test",
        ],
        "new_chat_app_skill_suggestions": [
            "Search for storage design examples",
            "Calculate another archive estimate",
            "Find more technical references",
        ],
        "new_chat_general_suggestions": [
            "Explain encrypted archive storage",
            "Compare common storage patterns",
            "Summarize a different storage scenario",
        ],
        "harmful_response": 0,
        "top_recommended_apps_for_user": [],
        "chat_summary": f"Synthetic storage response {fingerprint[:12]} completed.",
        "chat_tags": ["synthetic", "storage"],
        "share_cta_text": "Explore a synthetic encrypted storage example",
        "updated_chat_title": "Synthetic Storage Capacity",
        "daily_inspiration_topic_suggestions": [
            "encrypted archive design", "database transaction ordering", "bounded page retrieval",
        ],
        "quick_tip_slug": "",
    }


def generate_fixture(category: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    model = str(kwargs.get("model") or kwargs.get("model_id") or "")
    if not model or not category.startswith(("llm/", "llm_non_stream/")):
        return None
    messages = kwargs.get("messages")
    all_text = _text(messages)
    fingerprint = hashlib.sha256(all_text.encode()).hexdigest()
    scenario_matches = list(SCENARIO.finditer(all_text))
    scenario = scenario_matches[-1].group(1) if scenario_matches else None
    names = _tool_names(kwargs.get("tools"))
    if category.startswith("llm_non_stream/"):
        if (scenario and model == "gemini-3.5-flash-lite"
                and names == {"generate_suggestions_and_metadata"}
                and kwargs.get("tool_choice") == "required"):
            return {"response": {"type": "non_stream", "value": {
                "kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.google_client",
                "class": "UnifiedGoogleResponse",
                "value": {
                    "task_id": str(kwargs.get("task_id", "capacity-postprocessing")),
                    "model_id": model,
                    "success": True,
                    "tool_calls_made": [_call(
                        "generate_suggestions_and_metadata", _postprocessing_arguments(fingerprint),
                        google=True, fingerprint=fingerprint,
                    )["value"]],
                    "usage": {"prompt_token_count": 100, "candidates_token_count": 40,
                              "total_token_count": 140},
                },
            }}}
        if (scenario and model == "gemini-3.5-flash-lite"
                and names == {"analyze_request_properties"}
                and kwargs.get("tool_choice") == "required"):
            return {"response": {"type": "non_stream", "value": {
                "kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.google_client",
                "class": "UnifiedGoogleResponse",
                "value": {
                    "task_id": str(kwargs.get("task_id", "capacity-preprocessing")),
                    "model_id": model,
                    "success": True,
                    "tool_calls_made": [_call(
                        "analyze_request_properties", _preprocessing_arguments(scenario),
                        google=True, fingerprint=fingerprint,
                    )["value"]],
                    "usage": {"prompt_token_count": 100, "candidates_token_count": 40,
                              "total_token_count": 140},
                },
            }}}
        if not all_text.startswith("You are a conversation compression assistant."):
            return None
        summary = (
            "## Conversation History Summary\n"
            f"Synthetic storage checkpoint {fingerprint[:16]}. "
            "The encrypted client ledger remains authoritative for exact content."
            + (" STORAGE_CAPACITY_SCENARIO:recovery_checkpoint"
               if "STORAGE_CAPACITY_SCENARIO:recovery_checkpoint" in all_text else "")
        )
        return {"response": {
            "type": "non_stream",
            "value": {
                "kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.google_client",
                "class": "UnifiedGoogleResponse",
                "value": {
                    "task_id": str(kwargs.get("task_id", "capacity-compression")),
                    "model_id": model,
                    "success": True,
                    "direct_message_content": summary,
                    "tool_calls_made": None,
                    "raw_response": None,
                    "usage": {"prompt_token_count": 100, "candidates_token_count": 40, "total_token_count": 140},
                },
            },
        }}

    if not scenario:
        return None
    google = "gemini" in model.lower()
    if scenario == "child" and "FINAL ANSWER TASK: The waited sub-chats have completed." in all_text:
        return _main_stream(model, f"Synthetic child result {fingerprint[:16]}.")
    if "analyze_request_properties" in names:
        arguments = _preprocessing_arguments(scenario)
        return {"response": {
            "type": "mixed_stream", "body": "", "chunk_format_version": 1,
            "chunks": [_call("analyze_request_properties", arguments, google=google, fingerprint=fingerprint)],
        }}
    if scenario == "child" and "start_sub_chats" in names:
        if _tool_returned(messages):
            return _main_stream(model, f"Synthetic child result {fingerprint[:16]}.")
        arguments = {"execution_mode": "parallel", "sub_chats": [{
            "prompt": "Summarize this disposable synthetic storage task. STORAGE_CAPACITY_SCENARIO:child_worker",
            "title": "Summarize synthetic storage task", "category": "science", "icon": "flask-conical",
            "wait_for_completion": True,
        }]}
        return _main_stream(model, _call("start_sub_chats", arguments, google=google, fingerprint=fingerprint))
    if scenario == "recovery_save_failure" and "start_sub_chats" in names:
        arguments = {"execution_mode": "parallel", "sub_chats": [{
            "prompt": "Synthetic unavailable durability. STORAGE_CAPACITY_SCENARIO:recovery_save_failure",
            "title": "Verify durable save failure", "category": "science", "icon": "flask-conical",
            "wait_for_completion": True,
        }]}
        return _main_stream(model, _call("start_sub_chats", arguments, google=google, fingerprint=fingerprint))
    if scenario == "child_worker":
        # Ordinary child completion uses its final assistant text as the
        # orchestration summary. Main processing does not expose end_subchat.
        return _main_stream(model, "Synthetic child storage result.")
    if scenario == "recovery_embed":
        return _main_stream(model, (
            "```python:recovery_demo.py\n"
            "def recovery_value() -> int:\n"
            "    stable_value = 7\n"
            "    return stable_value\n"
            "```\n"
        ))
    if scenario == "recovery_detached_doc":
        return _main_stream(model, (
            "```docx_model\n"
            "{\"title\":\"Synthetic detached document\","
            "\"filename\":\"Recovery_Detached_Document.docx\","
            "\"blocks\":[{\"type\":\"heading\",\"text\":\"Synthetic detached document\"},"
            "{\"type\":\"paragraph\",\"text\":\"Durable worker output after disconnect.\"}]}\n"
            "```\n"
        ))
    if scenario == "recovery_diff":
        return _main_stream(model, (
            "```diff\n"
            "--- a/recovery_demo.py\n"
            "+++ b/recovery_demo.py\n"
            "@@ -1,3 +1,3 @@\n"
            " def recovery_value() -> int:\n"
            "-    stable_value = 7\n"
            "+    stable_value = 8\n"
            "    return stable_value\n"
            "```\n"
        ))
    if scenario == "recovery_checkpoint":
        return _main_stream(model, f"Synthetic post-checkpoint answer {fingerprint[:16]}.")
    if scenario in {"version_create", "version_update"}:
        # Tool arguments retain model-visible privacy tokens. The authorized
        # client restores them before approval and encryption; never accept a
        # syntactically valid hex prefix of a partially captured line.
        prompt, prompt_index = _version_prompt(messages, scenario)
        new = _version_line(prompt, "NEW") if prompt is not None else None
        old = _version_line(prompt, "OLD") if prompt is not None else None
        if new is None or (scenario == "version_create" and "CAPACITY_VERSION_OLD:" in prompt) \
                or (scenario == "version_update" and old is None):
            return None
        completion = _project_completion(messages[prompt_index + 1:])
        if completion is _INVALID_COMPLETION:
            return None
        expected_write = "project_create_file" if scenario == "version_create" else "project_update_file"
        if completion and completion.get("tool_name") in {"project_create_file", "project_update_file"}:
            results = completion.get("results")
            if completion.get("tool_name") != expected_write or completion.get("status") != "completed" \
                    or not isinstance(completion.get("arguments"), dict) \
                    or completion["arguments"].get("path") != "capacity.txt" or not isinstance(results, list) \
                    or len(results) != 1 or not isinstance(results[0], dict) \
                    or results[0].get("status") != "completed" \
                    or results[0].get("path") != "capacity.txt":
                return None
            return _main_stream(model, f"Synthetic storage response {fingerprint[:16]}.")
        if completion is None and _tool_returned(messages):
            return _main_stream(model, f"Synthetic storage response {fingerprint[:16]}.")
        if scenario == "version_create" and "project_create_file" in names and completion is None:
            arguments = {"path": "capacity.txt", "expected_base": None, "content": new}
            name = "project_create_file"
        elif scenario == "version_update" and completion is None and "project_read_text" in names:
            arguments = {"path": "capacity.txt"}
            name = "project_read_text"
        elif scenario == "version_update" and "project_update_file" in names and completion:
            base = _approved_read_base(completion)
            if base is None:
                return None
            patch = ("--- a/capacity.txt\n+++ b/capacity.txt\n@@ -1 +1 @@\n"
                     f"-{old}\n\\ No newline at end of file\n+{new}\n\\ No newline at end of file\n")
            arguments = {"path": "capacity.txt", "expected_base": base, "patch": patch}
            name = "project_update_file"
        else:
            return None
        return _main_stream(model, _call(name, arguments, google=google, fingerprint=fingerprint))
    if scenario == "tool" and "math-calculate" in names and not _tool_returned(messages):
        return _main_stream(model, _call("math-calculate", {"expression": "sqrt(144)"},
                                         google=google, fingerprint=fingerprint))
    # Unknown child or tool phase fails before dispatch.
    if scenario in {"child", "child_worker"} or (names and scenario == "tool" and "math-calculate" not in names):
        return None
    answer = f"Synthetic storage response {fingerprint[:16]}."
    return _main_stream(model, answer)
