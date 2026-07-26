#!/usr/bin/env python3
"""Audit the agent worktree deploy contract in docs and guardrails.

This check prevents workflow drift after the deploy path moves from shared-root
edits to automatic session worktrees with commit-scoped verification.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


REQUIRED_SNIPPETS: dict[str, list[str]] = {
    ".agents/skills/deploy/SKILL.md": [
        "automatic session worktree",
        "dev",
        "worktree deploy queue",
    ],
    ".agents/skills/verify-ui-change/SKILL.md": [
        "automatic worktree",
        "fast latest-ready",
        "exact-SHA verification",
    ],
    "docs/architecture/agent-tooling-parity.md": [
        "Session Worktrees",
        "root checkout is the control plane",
        "Exact-SHA checks",
    ],
    "docs/architecture/infrastructure/cronjobs.md": [
        "sessions.py worktree cleanup --idle-hours 12",
        "Dirty idle worktrees are not committed, pushed, or deleted",
    ],
    ".codex/hooks/bash-guard.sh": [
        "sessions.py worktree",
        "raw git worktree is forbidden",
    ],
    ".opencode/plugins/openmates-hooks.js": [
        "Root checkout is the OpenMates control plane",
        "OPENMATES_ROOT_GUARD",
    ],
    "AGENTS.md": [
        "raw `git worktree` commands",
        "sessions.py worktree ensure",
    ],
    "CLAUDE.md": [
        "raw git worktree commands",
        "sessions.py worktree ensure",
    ],
}


def main() -> int:
    failures: list[str] = []
    for relative_path, snippets in REQUIRED_SNIPPETS.items():
        path = PROJECT_ROOT / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{relative_path}: cannot read file: {exc}")
            continue
        for snippet in snippets:
            if snippet not in text:
                failures.append(f"{relative_path}: missing {snippet!r}")

    if failures:
        print("FAIL worktree deploy contract audit")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS worktree deploy contract audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
