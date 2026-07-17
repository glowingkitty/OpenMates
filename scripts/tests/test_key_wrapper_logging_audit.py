#!/usr/bin/env python3
"""Audit key wrapper code for unsafe sensitive-value logging.

The unified key wrapper migration intentionally copies ciphertext without ever
decrypting or exposing object keys. This deterministic guard catches future
debug logging that would pass key/content variables into logger or print calls.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

AUDITED_FILES = (
    "backend/core/api/app/services/directus/chat_key_wrapper_methods.py",
    "backend/core/api/app/services/directus/project_methods.py",
    "backend/core/api/app/services/directus/user_plan_methods.py",
    "backend/core/api/app/services/directus/user_task_methods.py",
    "backend/core/api/app/routes/chats.py",
    "backend/core/api/app/routes/sdk.py",
    "backend/core/api/app/routes/sync_api.py",
    "backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py",
    "backend/core/api/app/routes/handlers/websocket_handlers/chat_content_batch_handler.py",
)

SENSITIVE_NAME_PARTS = (
    "encrypted_chat_key",
    "encrypted_project_key",
    "encrypted_plan_key",
    "encrypted_task_key",
    "encrypted_key",
    "decrypted",
    "plaintext",
    "private_metadata",
    "share_key",
    "share_url",
    "content_key",
    "object_key",
)


def _source_segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def _contains_sensitive_name(source: str, node: ast.AST) -> bool:
    segment = _source_segment(source, node).lower()
    return any(name in segment for name in SENSITIVE_NAME_PARTS)


def _is_logger_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "logger"
        and func.attr in {"debug", "info", "warning", "error", "exception", "critical"}
    )


def _is_print_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "print"


def _sensitive_fstring_expressions(source: str, node: ast.AST) -> list[str]:
    if not isinstance(node, ast.JoinedStr):
        return []
    return [
        _source_segment(source, value.value) or ast.unparse(value.value)
        for value in node.values
        if isinstance(value, ast.FormattedValue) and _contains_sensitive_name(source, value.value)
    ]


def test_key_wrapper_code_does_not_log_sensitive_key_material() -> None:
    violations: list[str] = []

    for relative_path in AUDITED_FILES:
        path = REPO_ROOT / relative_path
        assert path.exists(), f"Missing audited key-wrapper path: {relative_path}"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not (_is_logger_call(node) or _is_print_call(node)):
                continue

            for arg in node.args:
                for formatted in _sensitive_fstring_expressions(source, arg):
                    violations.append(f"{relative_path}:{node.lineno} logs sensitive f-string expression {formatted!r}")

            logged_args = node.args[1:] if _is_logger_call(node) else node.args
            for arg in logged_args:
                if _contains_sensitive_name(source, arg):
                    violations.append(f"{relative_path}:{node.lineno} logs sensitive argument {_source_segment(source, arg)!r}")
            for keyword in node.keywords:
                if _contains_sensitive_name(source, keyword.value):
                    violations.append(f"{relative_path}:{node.lineno} logs sensitive keyword {keyword.arg!r}")

    assert not violations, "Unsafe key-wrapper logging detected:\n" + "\n".join(violations)
