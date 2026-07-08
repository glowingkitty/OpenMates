#!/usr/bin/env python3
"""Regression tests for Vercel cost-control Bash guardrails."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASH_GUARD = PROJECT_ROOT / ".claude" / "hooks" / "bash-guard.sh"


def run_bash_guard(command: str) -> subprocess.CompletedProcess[str]:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    return subprocess.run(
        ["bash", str(BASH_GUARD)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        check=False,
    )


def test_bash_guard_blocks_vercel_project_build_machine_patch():
    result = run_bash_guard(
        "python3 - <<'PY'\n"
        "client.patch('https://api.vercel.com/v9/projects/prj_123', "
        "json={'resourceConfig': {'buildMachineType': 'turbo'}})\n"
        "PY"
    )

    assert result.returncode == 2
    assert "Vercel project-setting mutations are forbidden" in result.stderr


def test_bash_guard_allows_vercel_project_read():
    result = run_bash_guard(
        "python3 - <<'PY'\n"
        "client.get('https://api.vercel.com/v9/projects/prj_123')\n"
        "PY"
    )

    assert result.returncode == 0


def test_bash_guard_blocks_running_repo_script_with_vercel_build_machine_mutation(tmp_path):
    script = PROJECT_ROOT / "scripts" / ".tmp" / "vercel_paid_machine_mutation_test.py"
    script.parent.mkdir(exist_ok=True)
    script.write_text(
        "client.patch('https://api.vercel.com/v9/projects/prj_123', "
        "json={'resourceConfig': {'buildMachineType': 'turbo'}})\n",
        encoding="utf-8",
    )
    try:
        result = run_bash_guard("python3 scripts/.tmp/vercel_paid_machine_mutation_test.py")
    finally:
        script.unlink(missing_ok=True)

    assert result.returncode == 2
    assert "Refusing to run a repo script" in result.stderr
