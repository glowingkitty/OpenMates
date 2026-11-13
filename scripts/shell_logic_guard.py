#!/usr/bin/env python3
"""Deploy guard for shell logic edits (client-core plan TASK-11).

Purpose: report deploys that edit guarded shell logic without a linked Rust
change or a `shell-only: <reason>` line in the deploy message.
Architecture: docs/plans/client-core-one-core-three-shells/plan.yml (deploy_guard),
.claude/rules/client-core.md. Reports only; it never inspects semantics.
Tests: scripts/tests/test_shell_logic_guard.py.
CLI: shell_logic_guard.py --message-file FILE [--root DIR] PATH...   (prefix a path with D: for a deletion)
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from datetime import date
from pathlib import Path

import yaml

GUARDED = (
    "apple/OpenMates/Sources/Core/**",
    "apple/OpenMatesShared/**",
    "frontend/packages/ui/src/services/**",
)
EXEMPT_PARTS = ("frontend/packages/ui/src/services/rustCore/",)
CORE_PREFIXES = (
    "packages/openmates-rust/",
    "packages/openmates-apple-bindings/",
    "packages/openmates-browser-bindings/",
    "packages/openmates-session-bindings/",
)
REASONS = ("ui", "platform-api", "credential-storage", "byte-adapter", "binding-glue", "deletion", "bugfix-in-frozen-code")
CORE_STATUSES = {"rust-twin", "rust-default", "rust-only"}
# Plan rollout: warn-only for two weeks after landing, then sessions.py deploy refuses.
BLOCKING_FROM = date(2026, 11, 26)
CAPABILITIES_FILE = Path(__file__).resolve().parent.parent / "docs/migration/rust/capabilities.yml"
_LINE_RE = re.compile(r"^\s*shell-only:\s*(\S+)(?:\s+(\S+))?", re.IGNORECASE | re.MULTILINE)


def is_blocking(today: date | None = None) -> bool:
    """True once the warn-only rollout window has ended."""
    return (today or date.today()) >= BLOCKING_FROM

def is_guarded(path: str) -> bool:
    if "/__tests__/" in f"/{path}" or any(path.startswith(p) for p in EXEMPT_PARTS):
        return False
    prefixes = tuple(g[:-2] for g in GUARDED)
    return path.startswith(prefixes) and any(fnmatch.fnmatch(path, g) for g in GUARDED)


def load_capabilities(path: Path = CAPABILITIES_FILE) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {c["id"]: c for c in data.get("capabilities", [])}


def check(changes: list[tuple[str, str]], message: str, capabilities: dict[str, dict] | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). changes are (status, path); status "D" = deleted."""
    guarded = [p for s, p in changes if s != "D" and is_guarded(p)]
    if not guarded:
        return [], []
    if any(p.startswith(CORE_PREFIXES) for _, p in changes):
        return [], []
    sample = ", ".join(guarded[:3]) + (" ..." if len(guarded) > 3 else "")
    match = _LINE_RE.search(message or "")
    if not match:
        return ([
            f"Deploy edits guarded shell logic ({sample}) without a change under packages/openmates-*. "
            "Move the logic into the Rust core, or add a message line "
            f"`shell-only: <reason>` with reason in {{{', '.join(REASONS)}}}."
        ], [])
    reason, capability = match.group(1).lower(), match.group(2)
    if reason not in REASONS:
        return ([f"shell-only reason `{reason}` is not allowed; use one of: {', '.join(REASONS)}."], [])
    if reason != "bugfix-in-frozen-code":
        return [], []
    if not capability:
        return (["shell-only: bugfix-in-frozen-code must be followed by a capability id from docs/migration/rust/capabilities.yml."], [])
    caps = capabilities if capabilities is not None else load_capabilities()
    if capability not in caps:
        return ([f"Unknown capability id `{capability}`; valid ids: {', '.join(sorted(caps))}."], [])
    warnings = []
    for shell in ("web", "apple"):
        status = (caps[capability].get(shell) or {}).get("status")
        if status in CORE_STATUSES:
            warnings.append(
                f"Reminder: capability `{capability}` is {status} on {shell}; the fix belongs in the Rust core, not the shell."
            )
    return [], warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-file", required=True)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    changes = [("D", p[2:]) if p.startswith("D:") else ("M", p) for p in args.paths]
    errors, warnings = check(changes, Path(args.message_file).read_text(encoding="utf-8"))
    for line in warnings:
        print(line)
    for line in errors:
        print(f"Error: {line}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
