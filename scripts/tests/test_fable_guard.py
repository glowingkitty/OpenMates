"""Tests for the Fable guard hook (scripts/fable_guard.py) and the repo's no-Fable-by-default config."""
# contract-test-file: tooling

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import scripts.fable_guard as guard

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "fable-guard.sh"
SESSION = "6f9e5f06-afb7-5f01-951e-0922b9b0a75e"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "STATE_DIR", tmp_path)
    return tmp_path


def _start(model, **extra):
    return {"hook_event_name": "SessionStart", "session_id": SESSION, "source": "startup", "model": model, **extra}


def _prompt(text):
    return {"hook_event_name": "UserPromptSubmit", "session_id": SESSION, "prompt": text}


@pytest.mark.parametrize("model", ["claude-fable-5-2", "fable", "claude-fable-5-2[1m]"])
def test_implicit_fable_chat_is_told_to_stop_and_ask(state, model):
    out = json.loads(guard.handle(_start(model), {}))["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert f"this chat runs on {model}" in out["additionalContext"]
    assert "do no work and no tool calls" in out["additionalContext"]
    assert "/model claude-opus-5-5" in out["additionalContext"]
    assert (state / SESSION).exists()


@pytest.mark.parametrize("model", ["claude-opus-5-5", "opus[1m]", "claude-sonnet-5-5", "haiku", ""])
def test_other_models_are_untouched(state, model):
    assert guard.handle(_start(model), {}) == ""
    assert not list(state.iterdir())


def test_launcher_marked_fable_request_passes(state):
    assert guard.handle(_start("claude-fable-5-2"), {"OPENMATES_FABLE_REQUESTED": "1"}) == ""
    assert not list(state.iterdir())


def test_model_from_environment_when_input_has_none(state):
    assert guard.handle(_start(None), {"ANTHROPIC_MODEL": "claude-fable-5-2"})


def test_sub_agent_session_starts_are_left_to_the_agent_model_guard(state):
    assert guard.handle(_start("claude-fable-5-2", agent_type="lane-worker"), {}) == ""


def test_prompt_naming_fable_confirms_and_clears_the_mark(state):
    guard.handle(_start("claude-fable-5-2"), {})
    assert guard.handle(_prompt("fix the build"), {}) == ""
    assert (state / SESSION).exists()
    out = json.loads(guard.handle(_prompt("Keep Fable, it's a hard one"), {}))["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit" and "explicitly asked for Fable" in out["additionalContext"]
    assert not (state / SESSION).exists()


def test_prompts_in_unmarked_sessions_are_untouched(state):
    assert guard.handle(_prompt("use fable for this"), {}) == ""


def test_hook_script_runs_end_to_end(tmp_path):
    env = {**os.environ, "FABLE_GUARD_STATE": str(tmp_path)}
    env.pop("OPENMATES_FABLE_REQUESTED", None)
    result = subprocess.run(["bash", str(HOOK)], input=json.dumps(_start("claude-fable-5-2")), text=True,
                            capture_output=True, env=env, check=True)
    assert "FABLE GUARD" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    clean = subprocess.run(["bash", str(HOOK)], input=json.dumps(_start("claude-opus-5-5")), text=True,
                           capture_output=True, env=env, check=True)
    assert clean.stdout == ""


def test_hook_is_registered_for_session_start_and_prompts():
    hooks = json.loads((ROOT / ".claude" / "settings.json").read_text())["hooks"]
    def commands(event):
        return [h["command"] for group in hooks[event] for h in group["hooks"]]
    assert any("fable-guard.sh" in c for c in commands("SessionStart"))
    assert any("fable-guard.sh" in c for c in commands("UserPromptSubmit"))


def test_repo_config_never_defaults_to_fable():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    assert "fable" not in json.dumps(settings.get("env", {})).lower()
    assert "fable" not in str(settings.get("model", "")).lower()
    for agent in (ROOT / ".claude" / "agents").glob("*.md"):
        found = re.search(r"^model:\s*(\S+)", agent.read_text(), re.MULTILINE)
        assert not found or found.group(1).lower() in {"sonnet", "haiku", "inherit"}, agent.name
