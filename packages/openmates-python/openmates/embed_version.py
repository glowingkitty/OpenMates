"""Stateless Rust version reconstruction; no HTTP, profile or fallback."""
from __future__ import annotations
import json
from .session_client import SessionClientError, _failure

def _reconstruct_embed_version_local(rows: list, key: bytes) -> str:
    try:
        if len(key) != 32 or not 1 <= len(rows) <= 10000:
            raise ValueError()
        encoded = json.dumps({"rows": rows, "key": list(key)}, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 64 * 1024 * 1024:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise SessionClientError("invalid_argument", "Invalid typed version reconstruction input.") from None
    try:
        from ._native import reconstruct_embed_version
    except ImportError:
        raise SessionClientError("native_binding_unavailable", "Install a native SDK build containing version reconstruction.") from None
    try:
        content = reconstruct_embed_version(encoded)
        if type(content) is not str or len(content.encode("utf-8")) > 16 * 1024 * 1024:
            raise SessionClientError("protocol", "The native version result is invalid.")
        return content
    except Exception as error:
        mapped = _failure(error)
        code = mapped.code if mapped.code in {"crypto", "protocol", "invalid_argument", "cancelled"} else "native_failure"
        raise SessionClientError(code, "Local version reconstruction failed.") from None
