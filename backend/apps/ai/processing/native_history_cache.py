"""Private, temporary provider transcript assembled from one authorized chat history.

This module has no storage access. A caller may seal its result in the existing
AI inference cache, but a missing or divergent transcript always starts cold.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from typing import Any, Mapping, Sequence

from backend.shared.python_utils.native_cache_history import canonical_content_sha256


NATIVE_HISTORY_VERSION = 2
MAX_NATIVE_EMBED_FINGERPRINTS = 128
_APP_SKILL_JSON_BLOCK = re.compile(
    r"(?m)^```json[ \t]*\r?\n(?P<body>\{[^\r\n]{1,16384}\})\r?\n```[ \t]*(?:\r?\n)?"
)


def _field(message: Any, name: str) -> Any:
    return message.get(name) if isinstance(message, dict) else getattr(message, name, None)


def visible_fingerprint(message: Any) -> dict[str, str]:
    """Bind replay to visible content and the metadata supplied to inference."""
    role = _field(message, "role")
    content = _field(message, "content")
    message_id = _field(message, "message_id") or _field(message, "id")
    if role not in {"user", "assistant", "system"} or not isinstance(message_id, str) or not message_id:
        raise ValueError("Native history requires stable visible message identities")
    sender_name = _field(message, "sender_name")
    if role == "assistant" and sender_name in {None, "assistant"}:
        sender_name = "assistant"
    content_sha256 = _field(message, "native_cache_canonical_content_sha256")
    if content_sha256 is None:
        content_sha256 = canonical_content_sha256(content)
    elif (not isinstance(content_sha256, str)
          or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None):
        raise ValueError("Native canonical history fingerprint is invalid")
    serialized = json.dumps(
        {"role": role, "message_id": message_id, "content_sha256": content_sha256,
         "sender_name": sender_name, "category": _field(message, "category"),
         "created_at": _field(message, "created_at")},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return {"role": role, "message_id": message_id, "sha256": hashlib.sha256(serialized).hexdigest()}


def visible_boundary(history: Sequence[Any]) -> list[dict[str, str]]:
    return [visible_fingerprint(message) for message in history]


def matched_visible_prefix(state: Mapping[str, Any], history: Sequence[Any]) -> int | None:
    """Require a complete, ordered prefix and exactly one new user message."""
    recorded = state.get("visible_history")
    if not isinstance(recorded, list) or not recorded or len(history) != len(recorded) + 1:
        return None
    try:
        actual = visible_boundary(history)
    except (TypeError, ValueError):
        return None
    if actual[:-1] != recorded or actual[-1]["role"] != "user":
        return None
    return len(recorded)


def _tool_map(tools: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ValueError("Native history accepts only selected function tools")
        function = tool.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name or name in result:
            raise ValueError("Native history requires unique selected tool names")
        result[name] = tool
    return result


def selected_tool_delta(
    previous: Sequence[dict[str, Any]], selected: Sequence[dict[str, Any]],
    *, openai: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return exact additions/removals; OpenAI changes schema by cold reset."""
    old = _tool_map(previous)
    new = _tool_map(selected)
    if openai and any(name in new and new[name] != tool for name, tool in old.items()):
        raise ValueError("OpenAI selected tool schema changed")
    removed = [name for name in old if name not in new]
    added = [copy.deepcopy(tool) for name, tool in new.items() if name not in old or old[name] != tool]
    return added, removed


def new_native_segment(
    *, model_id: str, server_model_id: str, provider_prefix: str,
    cacheable_system_prefix: str, selected_tools: Sequence[dict[str, Any]],
    messages: Sequence[dict[str, Any]], visible_history: Sequence[Any],
) -> dict[str, Any]:
    if not cacheable_system_prefix or not messages or messages[0] != {"role": "system", "content": cacheable_system_prefix}:
        raise ValueError("Native history needs a stable system prefix")
    if messages[-1].get("role") != "user":
        raise ValueError("Native history must begin after the current user message")
    return {
        "version": NATIVE_HISTORY_VERSION,
        "model_id": model_id,
        "server_model_id": server_model_id,
        "provider_prefix": provider_prefix,
        "cacheable_system_prefix": cacheable_system_prefix,
        "baseline_tools": copy.deepcopy(list(selected_tools)),
        "active_tools": copy.deepcopy(list(selected_tools)),
        "events": [],
        "messages": copy.deepcopy(list(messages)),
        "visible_history": visible_boundary(visible_history),
        "last_system_suffix": "",
        "last_clock_instruction": None,
    }


def resume_native_segment(
    state: Mapping[str, Any], *, model_id: str, server_model_id: str,
    provider_prefix: str, cacheable_system_prefix: str,
    visible_history: Sequence[Any], new_user_message: dict[str, Any],
) -> dict[str, Any] | None:
    if (
        state.get("version") != NATIVE_HISTORY_VERSION
        or state.get("model_id") != model_id
        or state.get("server_model_id") != server_model_id
        or state.get("provider_prefix") != provider_prefix
        or state.get("cacheable_system_prefix") != cacheable_system_prefix
        or matched_visible_prefix(state, visible_history) is None
    ):
        return None
    messages = state.get("messages")
    if (not isinstance(messages, list) or not messages
            or not isinstance(messages[-1], dict)
            or messages[-1].get("role") != "assistant"
            or not isinstance(messages[-1].get("provider_transport_state"), list)
            or not isinstance(state.get("events"), list)):
        return None
    resumed = copy.deepcopy(dict(state))
    resumed["messages"].append(copy.deepcopy(new_user_message))
    resumed["visible_history"] = visible_boundary(visible_history)
    return resumed


def add_dispatch_event(
    state: dict[str, Any], *, system_prompt: str,
    selected_tools: Sequence[dict[str, Any]], openai: bool,
    clock_instruction: str | None = None,
) -> None:
    prefix = state["cacheable_system_prefix"]
    if not system_prompt.startswith(prefix):
        raise ValueError("Native history system prefix changed")
    messages = state["messages"]
    index = len(messages) - 1
    if messages[index].get("role") not in {"user", "tool"}:
        raise ValueError("Native event must follow user or completed tool result")
    added, removed = selected_tool_delta(state["active_tools"], selected_tools, openai=openai)
    event: dict[str, Any] = {"after_message_index": index}
    suffix = system_prompt[len(prefix):]
    if suffix != state.get("last_system_suffix"):
        previous_suffix = state.get("last_system_suffix")
        previous_clock = state.get("last_clock_instruction")
        clock_only_change = (
            isinstance(previous_suffix, str) and isinstance(previous_clock, str)
            and isinstance(clock_instruction, str) and bool(clock_instruction)
            and previous_suffix.count(previous_clock) == 1
            and suffix.count(clock_instruction) == 1
            and previous_suffix.replace(previous_clock, "<current-clock>", 1)
            == suffix.replace(clock_instruction, "<current-clock>", 1)
        )
        if clock_only_change:
            # A fresh server clock supersedes the old date while every other
            # byte of the prior instructions remains applicable. Avoid replaying
            # a large unchanged developer block on each long-chat turn.
            event["system_suffix"] = (
                "Current date and time update for this turn supersedes the prior "
                "date and time statement. All other current-turn instructions "
                f"remain in force.\n{clock_instruction}"
            )
        else:
            # Any other change requires the complete current context. The
            # provider sees previous blocks, so supersede them explicitly.
            event["system_suffix"] = (
                "Current turn context replaces earlier current turn context blocks. "
                "Use only the current facts and instructions below for this turn; "
                "the stable system instructions still apply.\n"
                f"Current turn context:\n{suffix if suffix else '(none)'}"
            )
    if added:
        event["add_tools"] = added
    if removed:
        event["remove_tools"] = removed
    if event.keys() != {"after_message_index"}:
        state["events"].append(event)
    state["active_tools"] = copy.deepcopy(list(selected_tools))
    state["last_system_suffix"] = suffix
    state["last_clock_instruction"] = clock_instruction


def append_provider_output(state: dict[str, Any], output: Sequence[dict[str, Any]], text: str) -> None:
    if not output or any(not isinstance(item, dict) for item in output):
        raise ValueError("Native provider output is incomplete")
    state["messages"].append({
        "role": "assistant", "content": text,
        "provider_transport_state": copy.deepcopy(list(output)),
    })


def append_tool_results(state: dict[str, Any], tool_results: Sequence[dict[str, Any]]) -> None:
    if not tool_results or any(item.get("role") != "tool" or not item.get("tool_call_id") for item in tool_results):
        raise ValueError("Native tool results must be complete")
    state["messages"].extend(copy.deepcopy(list(tool_results)))


def replay_byte_estimate(state: Mapping[str, Any]) -> int:
    """Conservative serialized bound for context admission and quote checks."""
    return len(json.dumps(state, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def native_replay_fits_budget(
    state: Mapping[str, Any], *, quote_system: str,
    quote_history: Sequence[dict[str, Any]], quote_tools: Sequence[dict[str, Any]],
    input_token_budget: int, max_cached_bytes: int = 16 * 1024 * 1024,
) -> bool:
    """Bound the whole replay, including old raw output and tool declarations."""
    if input_token_budget <= 0 or replay_byte_estimate(state) > max_cached_bytes:
        return False
    wire_bytes = len(json.dumps(
        {"system": quote_system, "messages": quote_history, "tools": quote_tools},
        ensure_ascii=False, separators=(",", ":"), default=str,
    ).encode("utf-8"))
    # The authenticated quote uses the full serialized byte count as a
    # conservative input-token upper bound. Keep this gate at least as strict:
    # dividing by four can underestimate multilingual or opaque provider data.
    return wire_bytes <= input_token_budget


def _server_app_skill_references(tool_calls_info: Sequence[dict[str, Any]] | None) -> Counter[str]:
    """Allow only exact JSON references tied to an executed server tool result."""
    allowed: Counter[str] = Counter()
    for call in tool_calls_info or []:
        if not isinstance(call, dict) or not call.get("app_id") or not call.get("skill_id"):
            continue
        ids = [call.get("embed_id"), *(call.get("embed_ids") or [])]
        ids = {value for value in ids if isinstance(value, str) and value}
        references = [call.get("embed_reference"), *(call.get("embed_references") or [])]
        recorded_for_call: set[str] = set()
        for reference in references:
            if not isinstance(reference, str):
                continue
            try:
                payload = json.loads(reference)
            except (TypeError, ValueError):
                continue
            if (not isinstance(payload, dict) or payload.get("type") != "app_skill_use"
                    or payload.get("embed_id") not in ids
                    or payload.get("app_id") != call["app_id"]
                    or payload.get("skill_id") != call["skill_id"]):
                continue
            key = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if key not in recorded_for_call:
                allowed[key] += 1
                recorded_for_call.add(key)
    return allowed


def collect_server_embed_provenance(
    updated_embeds: Sequence[dict[str, Any]], placeholder: Mapping[str, Any] | None,
    *, app_id: str, skill_id: str,
) -> tuple[list[str], list[str]]:
    """Carry a streamed placeholder reference through a same-ID finished update.

    The single-result embed update returns its ID but omits the reference that
    was streamed when the placeholder was created. Only that exact server
    reference may fill the gap; the finalizer still checks it against the
    rendered fence and seals the finished encrypted row.
    """
    placeholders = (
        placeholder.get("placeholders", []) if placeholder and placeholder.get("multiple")
        else [placeholder] if placeholder else []
    )
    original_refs: dict[str, str] = {}
    for item in placeholders:
        if not isinstance(item, Mapping):
            continue
        embed_id, reference = item.get("embed_id"), item.get("embed_reference")
        if not isinstance(embed_id, str) or not embed_id or not isinstance(reference, str):
            continue
        try:
            payload = json.loads(reference)
        except (TypeError, ValueError):
            continue
        if (isinstance(payload, dict) and payload.get("type") == "app_skill_use"
                and payload.get("embed_id") == embed_id
                and payload.get("app_id") == app_id
                and payload.get("skill_id") == skill_id):
            original_refs[embed_id] = reference

    references: list[str] = []
    embed_ids: list[str] = []
    if updated_embeds:
        for item in updated_embeds:
            embed_id = item.get("parent_embed_id") or item.get("embed_id")
            if embed_id:
                embed_ids.append(embed_id)
            reference = item.get("embed_reference")
            if reference:
                references.append(reference)
            elif item.get("status") == "finished" and embed_id in original_refs:
                references.append(original_refs[embed_id])
    else:
        for item in placeholders:
            if isinstance(item, Mapping) and item.get("embed_id"):
                embed_ids.append(item["embed_id"])
                if item["embed_id"] in original_refs:
                    references.append(original_refs[item["embed_id"]])
    return references, embed_ids


def _server_app_skill_embed_ids(tool_calls_info: Sequence[dict[str, Any]] | None) -> set[str]:
    return {
        payload["embed_id"]
        for reference in _server_app_skill_references(tool_calls_info)
        for payload in [json.loads(reference)]
    }


def _embed_row_fingerprint(row: Any, *, embed_id: str, user_id_hash: str) -> str | None:
    """Hash the encrypted cache row, including all content and version fields."""
    if (not isinstance(row, dict) or row.get("embed_id") != embed_id
            or row.get("type") != "app_skill_use" or row.get("status") != "finished"
            or not isinstance(user_id_hash, str) or not user_id_hash
            or row.get("hashed_user_id") != user_id_hash
            or not isinstance(row.get("encrypted_content"), str)
            or not row["encrypted_content"]):
        return None
    try:
        encoded = json.dumps(row, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


async def validate_native_embed_fingerprints(
    state: Mapping[str, Any], cache_service: Any, user_id_hash: str,
) -> bool:
    """A missing or changed app result makes an old provider transcript cold."""
    fingerprints = state.get("embed_fingerprints")
    if not isinstance(fingerprints, dict) or len(fingerprints) > MAX_NATIVE_EMBED_FINGERPRINTS:
        return False
    if not fingerprints:
        return True
    reader = getattr(cache_service, "get_embed_from_cache", None)
    if reader is None:
        return False
    for embed_id, expected in fingerprints.items():
        if (not isinstance(embed_id, str) or not embed_id
                or not isinstance(expected, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected) is None):
            return False
        try:
            row = await reader(embed_id)
        except Exception:
            return False
        if _embed_row_fingerprint(row, embed_id=embed_id, user_id_hash=user_id_hash) != expected:
            return False
    return True


async def seal_native_embed_fingerprints(
    state: Mapping[str, Any], tool_calls_info: Sequence[dict[str, Any]] | None,
    cache_service: Any, user_id_hash: str,
) -> dict[str, Any] | None:
    """Bind the next followup to all finished server-owned app result rows."""
    if not isinstance(state, Mapping):
        return None
    previous = state.get("embed_fingerprints", {})
    if not isinstance(previous, dict):
        return None
    new_ids = _server_app_skill_embed_ids(tool_calls_info)
    all_ids = set(previous) | new_ids
    if len(all_ids) > MAX_NATIVE_EMBED_FINGERPRINTS:
        return None
    sealed = copy.deepcopy(dict(state))
    if not all_ids:
        sealed["embed_fingerprints"] = {}
        return sealed
    reader = getattr(cache_service, "get_embed_from_cache", None)
    if reader is None:
        return None
    fingerprints: dict[str, str] = {}
    for embed_id in sorted(all_ids):
        if not isinstance(embed_id, str) or not embed_id:
            return None
        try:
            row = await reader(embed_id)
        except Exception:
            return None
        digest = _embed_row_fingerprint(row, embed_id=embed_id, user_id_hash=user_id_hash)
        if digest is None or (embed_id in previous and previous[embed_id] != digest):
            return None
        fingerprints[embed_id] = digest
    sealed["embed_fingerprints"] = fingerprints
    return sealed


def _without_server_app_skill_references(
    rendered: str, tool_calls_info: Sequence[dict[str, Any]] | None,
) -> str:
    allowed = _server_app_skill_references(tool_calls_info)
    if not allowed:
        return rendered

    def remove(match: re.Match[str]) -> str:
        try:
            payload = json.loads(match.group("body"))
        except (TypeError, ValueError):
            return match.group(0)
        if not isinstance(payload, dict) or payload.get("type") != "app_skill_use":
            return match.group(0)
        key = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if allowed[key] <= 0:
            return match.group(0)
        allowed[key] -= 1
        return ""

    return _APP_SKILL_JSON_BLOCK.sub(remove, rendered)


def _presentation_text(text: str) -> str:
    """Ignore blank-line spacing outside code; retain all nonblank content."""
    normalized = text.replace("\r\n", "\n").strip("\n")
    if "```" in normalized:
        return normalized
    return re.sub(r"\n(?:[ \t]*\n)+", "\n\n", normalized)


def finalize_native_cache_state(
    state: Mapping[str, Any], *, raw_final_output: Sequence[dict[str, Any]],
    content_markdown: str, assistant_message_id: str,
    assistant_category: str | None = None, assistant_created_at: int | None = None,
    tool_calls_info: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Seal only a completed transcript matching the canonical visible answer.

    Product-side rewriting can make the provider's answer diverge from the
    assistant message that clients encrypt. Such a segment must start cold on
    the next turn. This deliberately does not guess which rewrites are cosmetic.
    """
    if not isinstance(content_markdown, str) or not assistant_message_id:
        return None
    expected = state.get("expected_visible_response")
    if not isinstance(expected, str):
        return None
    if expected != content_markdown:
        rendered_provider_text = _without_server_app_skill_references(
            content_markdown, tool_calls_info,
        )
        if _presentation_text(expected) != _presentation_text(rendered_provider_text):
            return None
    finalized = copy.deepcopy(dict(state))
    try:
        last = finalized.get("messages", [])[-1]
        if last.get("role") != "assistant" or last.get("provider_transport_state") != list(raw_final_output):
            append_provider_output(
                finalized, raw_final_output,
                str(state.get("raw_final_text") or ""),
            )
        finalized.setdefault("visible_history", []).append(visible_fingerprint({
            "role": "assistant", "message_id": assistant_message_id,
            "content": content_markdown, "category": assistant_category,
            "created_at": assistant_created_at,
        }))
    except (TypeError, ValueError):
        return None
    finalized.pop("expected_visible_response", None)
    finalized.pop("raw_final_text", None)
    return finalized
