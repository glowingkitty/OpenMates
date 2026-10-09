"""Provider-neutral, append-only tool and instruction timeline validation.

The caller supplies only preprocessor-selected function schemas. The timeline is
replayed with canonical message indices so a provider can preserve earlier input
byte-for-byte while changing available tools at a later turn.
"""

from copy import deepcopy
import re
from typing import Any
from pydantic import BaseModel, Field


class NativeCacheProviderOutput(BaseModel):
    """Private complete provider output for exact stateless input replay."""

    provider_prefix: str
    model_id: str
    output: list[dict[str, Any]] = Field(repr=False, exclude=True)


class NativeCacheSchemaChanged(ValueError):
    """A provider cannot replay an in-place schema change in this segment."""


def safe_native_provider_error(error: BaseException) -> str:
    """Retain retryable HTTP status without echoing a provider body or traceback."""
    error_type = type(error).__name__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", error_type):
        error_type = "ProviderError"
    try:
        status = getattr(error, "status_code", None)
        if status is None:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
    except Exception:
        status = None
    status_part = f" status={status}" if type(status) is int and 100 <= status <= 599 else ""
    return f"{error_type}{status_part} (details redacted)"


def function_name(tool: dict[str, Any]) -> str:
    """Validate a canonical function tool and return its name."""
    if not isinstance(tool, dict) or tool.get("type") != "function":
        raise ValueError("Native cache tools must be canonical function tools")
    function = tool.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not function["name"]:
        raise ValueError("Native cache function tool is missing its name")
    if not isinstance(function.get("parameters"), dict):
        raise ValueError("Native cache function tool is missing its parameters schema")
    return function["name"]


def validate_native_cache_context(
    context: dict[str, Any], messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], list[str]]:
    """Return copied baseline, indexed events, and final active tool names.

    Events occur after a complete user turn, including all parallel tool results.
    An event's ``after_message_index`` refers to the original canonical history,
    including its first system message. No provider wire item is a canonical
    history index.
    """
    if not isinstance(context, dict):
        raise ValueError("Native cache context must be an object")
    baseline = context.get("baseline_tools")
    raw_events = context.get("events")
    if not isinstance(baseline, list) or not isinstance(raw_events, list):
        raise ValueError("Native cache context requires baseline_tools and events lists")
    baseline = deepcopy(baseline)
    active: dict[str, dict[str, Any]] = {}
    for tool in baseline:
        name = function_name(tool)
        if name in active:
            raise ValueError("Duplicate native cache baseline tool")
        active[name] = tool

    events: dict[int, list[dict[str, Any]]] = {}
    previous_index = -1
    for original in raw_events:
        if not isinstance(original, dict):
            raise ValueError("Native cache event must be an object")
        event = deepcopy(original)
        index = event.get("after_message_index")
        if type(index) is not int or index < 0 or index >= len(messages):
            raise ValueError("Native cache event has an invalid message index")
        if index < previous_index:
            raise ValueError("Native cache events must be ordered by message index")
        previous_index = index
        role = messages[index].get("role")
        if role not in {"user", "tool"}:
            raise ValueError("Native cache event must follow a user or tool result")
        if role == "tool" and index + 1 < len(messages) and messages[index + 1].get("role") == "tool":
            raise ValueError("Native cache event cannot split parallel tool results")
        suffix = event.get("system_suffix")
        additions = event.get("add_tools", [])
        removals = event.get("remove_tools", [])
        if suffix is not None and (not isinstance(suffix, str) or not suffix):
            raise ValueError("Native cache system suffix must be nonempty text")
        if not isinstance(additions, list) or not isinstance(removals, list):
            raise ValueError("Native cache event tool changes must be lists")
        if not suffix and not additions and not removals:
            raise ValueError("Native cache event must change instructions or tools")
        for name in removals:
            if not isinstance(name, str) or name not in active:
                raise ValueError("Native cache event removes an unavailable tool")
            del active[name]
        seen_additions: set[str] = set()
        for tool in additions:
            name = function_name(tool)
            if name in seen_additions:
                raise ValueError("Duplicate native cache tool in one event")
            seen_additions.add(name)
            active[name] = tool
        events.setdefault(index, []).append(event)
    return baseline, events, list(active)


def openai_function_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert one canonical function schema to the Responses API shape."""
    function_name(tool)
    function = deepcopy(tool["function"])
    return {"type": "function", **function, "strict": function.get("strict", False)}


def reject_openai_schema_changes(
    baseline: list[dict[str, Any]], events: dict[int, list[dict[str, Any]]],
) -> None:
    """Require a cold segment reset for undocumented same-name replacements."""
    seen = {function_name(tool): tool for tool in baseline}
    for group in events.values():
        for event in group:
            for tool in event.get("add_tools", []):
                name = function_name(tool)
                if name in seen and seen[name] != tool:
                    raise NativeCacheSchemaChanged(
                        f"OpenAI native tool '{name}' changed schema; start a new cache segment"
                    )
                seen[name] = tool
