"""Local privacy through Rust: 1 MiB UTF-8 text, 4 MiB canonical Rust JSON input (16 MiB wire ceiling),
1024 combined memory/mapping entries and 64 levels of plain JSON nesting.
Prepared/restored UTF-8 output is capped at 1 MiB, checked before replacement
copies. Integer-valued numbers must be safe integers. No login or network is used.
"""
from __future__ import annotations

import json
import math
from typing import Any, TypedDict
from .session_client import SessionClientError, _failure


class PreparedPrivacy(TypedDict):
    text: str
    mappings: list[dict[str, Any]]


def _invalid() -> None:
    raise SessionClientError("invalid_argument", "Invalid typed privacy input.")


def _validate(value: Any, depth: int = 0) -> None:
    if depth > 64:
        _invalid()
    if value is None or type(value) is bool:
        return
    if type(value) in (int, float):
        try:
            if not math.isfinite(value) or (value % 1 == 0 and abs(value) > 9_007_199_254_740_991):
                _invalid()
        except OverflowError:
            _invalid()
        return
    if type(value) is str:
        value.encode("utf-8")
        return
    if type(value) in (list, tuple):
        for entry in value:
            _validate(entry, depth + 1)
        return
    if type(value) is dict:
        for key, entry in value.items():
            if type(key) is not str:
                _invalid()
            _validate(key, depth + 1)
            _validate(entry, depth + 1)
        return
    _invalid()


def _call(value: dict[str, Any]) -> dict[str, Any]:
    try:
        _validate(value)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16 * 1024 * 1024:
            _invalid()
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        _invalid()
    try:
        from ._native import privacy
    except ImportError:
        raise SessionClientError("native_binding_unavailable", "Install a native SDK build containing privacy operations.") from None
    try:
        result = json.loads(privacy(encoded))
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise SessionClientError("protocol", "The native privacy result is invalid.")
        return result
    except Exception as error:
        raise _failure(error) from None


def _text(text: str) -> None:
    if type(text) is not str:
        _invalid()
    try:
        if len(text.encode("utf-8")) > 1024 * 1024:
            _invalid()
    except UnicodeError:
        _invalid()


def prepare_privacy(text: str, *, memories: list[Any] | tuple[Any, ...] = (), existing_mappings: list[Any] | tuple[Any, ...] = (), enhanced: bool = False) -> PreparedPrivacy:
    """Anonymize locally. Keep returned mappings private for later restoration."""
    _text(text)
    if type(memories) not in (list, tuple) or type(existing_mappings) not in (list, tuple) or type(enhanced) is not bool or len(memories) + len(existing_mappings) > 1024:
        _invalid()
    result = _call({"operation": "prepare", "text": text, "memories": memories, "existing_mappings": existing_mappings, "enhanced": enhanced})
    mappings = result.get("mappings")
    if not isinstance(mappings, list) or any(not isinstance(m, dict) or any(not isinstance(m.get(key), str) for key in ("original", "placeholder")) for m in mappings):
        raise SessionClientError("protocol", "The native privacy result is invalid.")
    return result


def restore_privacy(text: str, mappings: list[Any] | tuple[Any, ...]) -> str:
    """Restore known placeholders in one pass, refusing missing private mappings."""
    _text(text)
    if type(mappings) not in (list, tuple) or len(mappings) > 1024:
        _invalid()
    return _call({"operation": "restore", "text": text, "mappings": mappings})["text"]
