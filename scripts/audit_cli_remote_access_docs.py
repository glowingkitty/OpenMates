#!/usr/bin/env python3
"""Audit public documentation for the canonical remote-access command.

The live bridge has one foreground command rather than lifecycle subcommands.
This deterministic check prevents package, user-guide, architecture, and VS
Code setup copy from drifting back to synthetic or daemon-style behavior.
Spec: docs/specs/cli-remote-access-live-bridge/spec.yml.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "docs/user-guide/cli/remote-access.md",
    ROOT / "frontend/packages/openmates-cli/README.md",
    ROOT / "docs/architecture/platforms/cli-package.md",
    ROOT / "frontend/apps/vscode_extension/src/extension.ts",
    ROOT / "frontend/apps/vscode_extension/src/webviewHtml.ts",
]
REQUIRED_GUIDE_MARKERS = [
    "foreground",
    "--path",
    "read-only",
    "offline",
    "encrypted end to end",
    "projects files list",
    "projects files search",
    "projects files read",
    "context_confirmation_required",
    "never fall back to an ai model",
]
REQUIRED_SHARED_MARKERS = [
    "--personal",
    "--team <team>",
    "cli-only",
    "exact project id",
    "exact source id",
]
OBSOLETE_COMMAND = re.compile(r"openmates\s+remote-access\s+(?:start|stop|status|search)\b")


def main() -> int:
    failures: list[str] = []
    for path in DOCS:
        if not path.is_file():
            failures.append(f"missing {path.relative_to(ROOT)}")
            continue
        source = path.read_text(encoding="utf-8")
        if OBSOLETE_COMMAND.search(source):
            failures.append(f"{path.relative_to(ROOT)} advertises an obsolete lifecycle subcommand")

    guide = DOCS[0].read_text(encoding="utf-8").lower() if DOCS[0].is_file() else ""
    for marker in REQUIRED_GUIDE_MARKERS:
        if marker not in guide:
            failures.append(f"{DOCS[0].relative_to(ROOT)} missing required behavior: {marker}")
    for path in DOCS[:3]:
        source = path.read_text(encoding="utf-8").lower() if path.is_file() else ""
        for marker in REQUIRED_SHARED_MARKERS:
            if marker not in source:
                failures.append(f"{path.relative_to(ROOT)} missing Project requester behavior: {marker}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS CLI remote-access documentation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
