#!/usr/bin/env python3
"""
Synchronizes the Obsidian memory vault task system end-to-end.

The task workflow is intentionally file-first: notes can be captured with tags
like #todo, #bug, or #event, then normalized into frontmatter and rendered into
generated Kanban boards. This wrapper keeps the manual command and optional cron
entry short while preserving each underlying script as a focused unit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_script(name: str, *args: str) -> None:
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / name), *args]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    run_script("normalize_obsidian_task_notes.py", "--write")
    run_script("generate_obsidian_task_boards.py")


if __name__ == "__main__":
    main()
