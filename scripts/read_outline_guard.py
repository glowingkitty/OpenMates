#!/usr/bin/env python3
"""Refuse whole-file Reads of huge source files and show an outline instead.

PreToolUse Read hook backend. Passes through for ranged reads, small files,
non-source types, missing files, paths outside the repo/worktrees and any error.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import code_map  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CANONICAL = REPO.parent.parent if REPO.parent.name == ".openmates-agent-worktrees" else REPO


def _allowed_root(path: Path) -> bool:
    return any(path == root or root in path.parents for root in (REPO, CANONICAL))


def run(payload: dict) -> int:
    tool_input = payload.get("tool_input") or {}
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return 0
    raw = tool_input.get("file_path")
    if not raw:
        return 0
    path = Path(raw).resolve()
    if path.suffix.lower() not in code_map.SOURCE_EXTS or not path.is_file():
        return 0
    if not _allowed_root(path) or not code_map._is_text(path):
        return 0
    minimum = int(os.environ.get("OPENMATES_READ_OUTLINE_MIN_LINES", "800"))
    count = len(code_map._read_lines(path))
    if count <= minimum:
        return 0
    print(
        f"{raw} has {count} lines. Read a range (offset/limit) instead of the whole file. "
        "Outline:\n" + code_map.outline(path),
        file=sys.stderr,
    )
    return 2


def main() -> int:
    try:
        return run(json.load(sys.stdin))
    except Exception:  # noqa: BLE001 - documented fail-open hook boundary
        return 0


if __name__ == "__main__":
    sys.exit(main())
