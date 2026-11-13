"""Tests for the sub-agent session guard hook."""
# contract-test-file: tooling

import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "subagent-session-guard.sh"


def run(command, agent=True):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    if agent:
        payload.update(agent_id="a1", agent_type="lane-worker")
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, check=False)


@pytest.mark.parametrize("command", [
    'python3 scripts/sessions.py start --mode bug --task "x"',
    "python3 scripts/sessions.py --json start",
    "cd /tmp && python3 /repo/scripts/lane_start.py --x",
    "scripts/lane_start.py",
])
def test_blocks_for_subagent(command):
    result = run(command)
    assert result.returncode == 2
    assert "Sub-agents use the parent's session and worktree" in result.stderr


@pytest.mark.parametrize("command", [
    "python3 scripts/sessions.py status --session 098d",
    'grep -rn "sessions.py start" docs',
    "echo lane_start.py",
])
def test_allows_other_commands(command):
    assert run(command).returncode == 0


def test_main_chat_unaffected():
    assert run("python3 scripts/sessions.py start --mode bug", agent=False).returncode == 0
