"""Tests for the sub-agent tool-call budget hook."""
# contract-test-file: tooling

import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "subagent-budget.sh"


def call(tmp_path, payload, **env):
    full = {**os.environ, "OPENMATES_SUBAGENT_BUDGET_DIR": str(tmp_path / "state"),
            "OPENMATES_SUBAGENT_WARN_CALLS": "3", "OPENMATES_SUBAGENT_MAX_CALLS": "5", **env}
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=full, check=False)


def agent(**extra):
    return {"session_id": "s1", "agent_id": "a1", "agent_type": "lane-worker",
            "hook_event_name": "PreToolUse", "tool_name": "Read", **extra}


def test_main_chat_no_state(tmp_path):
    result = call(tmp_path, {"session_id": "s1", "tool_name": "Read"})
    assert result.returncode == 0 and result.stdout == ""
    assert not (tmp_path / "state").exists()


def test_warn_then_block_then_stop_resets(tmp_path):
    results = [call(tmp_path, agent()) for _ in range(6)]
    assert [r.returncode for r in results] == [0, 0, 0, 0, 2, 2]
    assert results[1].stdout == ""
    context = json.loads(results[2].stdout)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("Sub-agent budget: 3 of 5 tool calls used.")
    assert "Sub-agent budget reached (5 tool calls)" in results[4].stderr
    assert call(tmp_path, agent(hook_event_name="SubagentStop")).returncode == 0
    # count reset to 5-15 -> 0, so calls work again
    assert call(tmp_path, agent()).returncode == 0


def test_ci_runner_exempt(tmp_path):
    for _ in range(8):
        assert call(tmp_path, agent(agent_type="ci-runner")).returncode == 0


def test_agents_counted_separately(tmp_path):
    for _ in range(5):
        call(tmp_path, agent())
    assert call(tmp_path, agent(agent_id="a2")).returncode == 0


def test_bad_input_fails_open(tmp_path):
    full = {**os.environ, "OPENMATES_SUBAGENT_BUDGET_DIR": str(tmp_path)}
    result = subprocess.run(["bash", str(HOOK)], input="not json", text=True,
                            capture_output=True, env=full, check=False)
    assert result.returncode == 0


def test_old_state_cleaned(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    old = state / "old.json"
    old.write_text("{}")
    os.utime(old, (1, 1))
    call(tmp_path, agent())
    assert not old.exists()
