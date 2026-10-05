"""Project client-encrypted context receipts to content-free inference history.

Receipt details remain in the encrypted client transcript. Replaying a receipt
must not reload stale private instructions or bypass the context handoff boundary.
Actual user/assistant messages and unrelated system protocols are unchanged.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

_TYPES = frozenset({"rules_loaded", "memories_loaded", "chat_direction_correction",
                    "project_authoring_recommendation", "project_authoring_recommendations"})
_TYPE_HINT = re.compile(r'"type"\s*:\s*"(' + "|".join(sorted(_TYPES)) + r')"')
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


def _id(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _projection(data: dict, kind: str) -> dict:
    result = {"type": kind, "replayed_receipt": True}
    for field in ("event_id", "chat_id", "turn_id", "delivery_id", "recommendation_id"):
        if (value := _id(data.get(field))) is not None:
            result[field] = value
    if kind in {"rules_loaded", "memories_loaded"}:
        key = data.get("set_key")
        if isinstance(key, str) and _DIGEST.fullmatch(key):
            result["set_key"] = key
        field = "memories" if kind == "memories_loaded" else "rules"
        rules = data.get(field)
        result[field] = []
        if isinstance(rules, list):
            for rule in rules[:24]:
                if not isinstance(rule, dict):
                    continue
                identifier, revision = _id(rule.get("id")), rule.get("revision")
                if identifier and isinstance(revision, str) and _DIGEST.fullmatch(revision):
                    result[field].append({"id": identifier, "revision": revision})
        result["count"] = len(result[field])
    return result


def sanitize_agent_context_message(message: Any) -> Any:
    """Return a shallow copy only for recognized system receipts; never mutate storage."""
    read = message.get if isinstance(message, dict) else lambda key, default=None: getattr(message, key, default)
    role = read("role")
    if getattr(role, "value", role) != "system":
        return message
    content = read("content")
    if not isinstance(content, (str, dict)):
        return message
    data = content
    if isinstance(content, str):
        try:
            data = json.loads(content) if len(content) <= 100_000 else None
        except (ValueError, TypeError):
            data = None
        if not isinstance(data, dict):
            # Known malformed/oversized receipts fail closed rather than
            # replaying private bodies into queue/cache/debug serialization.
            hint = _TYPE_HINT.search(content)
            if not hint or not content.lstrip().startswith("{"):
                return message
            data = {"type": hint.group(1)}
    kind = data.get("type") if isinstance(data, dict) else None
    if not isinstance(kind, str) or kind not in _TYPES:
        return message
    clean_content = json.dumps(_projection(data, kind), sort_keys=True, separators=(",", ":"))
    if isinstance(message, dict):
        return {**message, "content": clean_content}
    if hasattr(message, "model_copy"):
        return message.model_copy(update={"content": clean_content})
    result = copy.copy(message)
    result.content = clean_content
    return result


def project_agent_context_history(history: list) -> list:
    return [sanitize_agent_context_message(message) for message in history]
