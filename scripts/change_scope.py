#!/usr/bin/env python3
"""Change-scope limits for sessions started by AI test-user reports.

Architecture: docs/architecture/infrastructure/claude-dispatch.md ("AI test-user
reports"). A session started with OPENMATES_CHANGE_SCOPE=small-fix may only
deploy a small, local bug fix; `sessions.py deploy` calls `check_small_fix`
and refuses anything larger, so the rule is enforced in code and not by prompt.
"""
from __future__ import annotations

import re
from typing import Iterable, NamedTuple

SMALL_FIX = "small-fix"
VALID_SCOPES = (SMALL_FIX,)
MAX_FILES = 6
MAX_NON_TEST_LINES = 150
FORBIDDEN_PREFIXES = (
    "backend/core/directus/schemas/",
    "docs/plans/",
    "specifications/",
)
FORBIDDEN_PARTS = ("migrations/", "/migrations", "alembic/")
ROUTE_DECORATOR_RE = re.compile(r"^\s*@(?:\w+\.)?(?:get|post|put|patch|delete|websocket|api_route)\(", re.I)
TEST_FILE_RE = re.compile(r"(^|/)tests?/|\.spec\.[jt]s$|\.test\.[jt]s$|(^|/)test_[^/]*\.py$")
SOURCE_SUFFIXES = (".py", ".ts", ".js", ".svelte", ".rs", ".swift", ".sh", ".yml", ".yaml", ".json")

REFUSAL = ("Small-fix scope (AI test-user report): this change is too large. "
           "Create an OpenMates Task for Marco instead of deploying.")


class FileChange(NamedTuple):
    path: str
    added: int
    removed: int
    is_new: bool


def is_test_file(path: str) -> bool:
    return bool(TEST_FILE_RE.search(path))


def has_new_route_decorator(added_lines: Iterable[str]) -> bool:
    return any(ROUTE_DECORATOR_RE.match(line) for line in added_lines)


def check_small_fix(changes: list[tuple[str, int, int, bool]], new_route_paths: Iterable[str] = ()) -> list[str]:
    """Return the reasons a change exceeds the small-fix limit (empty when within it).

    `changes` are (path, added, removed, is_new); `new_route_paths` lists files
    whose added lines contain an API route decorator.
    """
    reasons: list[str] = []
    if len(changes) > MAX_FILES:
        reasons.append(f"{len(changes)} files changed (limit {MAX_FILES})")
    lines = sum(a + r for p, a, r, _n in changes if not is_test_file(p))
    if lines > MAX_NON_TEST_LINES:
        reasons.append(f"{lines} changed non-test lines (limit {MAX_NON_TEST_LINES})")
    for path, _a, _r, is_new in changes:
        if is_new and not is_test_file(path) and path.endswith(SOURCE_SUFFIXES):
            reasons.append(f"new source file {path}")
        if path.startswith(FORBIDDEN_PREFIXES) or any(part in path for part in FORBIDDEN_PARTS):
            reasons.append(f"protected area {path}")
    for path in new_route_paths:
        reasons.append(f"new API route in {path}")
    return reasons
