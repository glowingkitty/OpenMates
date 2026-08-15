#!/usr/bin/env python3
# contract-test-file: tooling
"""Regression tests for the agent-side OpenCode version pin.

The shared Bash guard must reject package-manager and self-upgrade commands
that can replace OpenCode. Read-only version checks and quoted research text
must remain allowed so the guard does not interfere with investigations.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASH_GUARD = PROJECT_ROOT / ".claude" / "hooks" / "bash-guard.sh"


def run_bash_guard(command: str) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run(
        ["bash", str(BASH_GUARD)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        check=False,
    )


def test_blocks_opencode_package_mutations():
    commands = [
        "npm install -g opencode-ai@latest",
        "npm uninstall --global opencode-ai",
        "pnpm add -g opencode-ai@1.18.18",
        "bun remove -g opencode-ai",
        "yarn global add opencode-ai@1.18.18",
        "opencode upgrade",
        "/home/superdev/.npm-global/bin/opencode update",
    ]

    for command in commands:
        result = run_bash_guard(command)
        assert result.returncode == 2, command
        assert "OpenCode is pinned to 1.17.20" in result.stderr
        assert "user must update it manually" in result.stderr


def test_blocks_package_less_global_update():
    result = run_bash_guard("npm update -g")

    assert result.returncode == 2
    assert "OpenCode is pinned to 1.17.20" in result.stderr


def test_allows_read_only_and_non_opencode_commands():
    commands = [
        "opencode --version",
        "/home/superdev/.npm-global/bin/opencode --version",
        "npm install -g typescript",
        "python3 -c 'print(\"npm install -g opencode-ai@latest\")'",
    ]

    for command in commands:
        result = run_bash_guard(command)
        assert result.returncode == 0, (command, result.stderr)
