"""Codex chats run the repository's Claude hooks through scripts/codex_hook_adapter.py (TASK-4476)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_hook_adapter as adapter  # noqa: E402

CHAT = "11111111-2222-4333-8444-555555555555"
THREAD = "99999999-2222-4333-8444-555555555555"
PATCH = ("*** Begin Patch\n*** Add File: new.py\n+print(1)\n*** Update File: /abs/old.py\n@@\n-a\n+b\n ctx\n"
         "*** Delete File: gone.py\n*** End Patch")


@pytest.fixture
def repo(tmp_path):
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "edit.sh").write_text('#!/bin/bash\nP=$(cat); echo "$P" | grep -q forbidden && '
                                   '{ echo "BLOCKED: forbidden text" >&2; exit 2; }; exit 0\n')
    (hooks / "bash.sh").write_text('#!/bin/bash\nP=$(cat); echo "$P" | grep -q "git push" && '
                                   '{ echo \'{"decision":"block","reason":"no raw push"}\'; exit 0; }; exit 0\n')
    (hooks / "stop.sh").write_text('#!/bin/bash\ncat >/dev/null; echo "plain text"; exit 0\n')
    (hooks / "who.sh").write_text('#!/bin/bash\ncat > "$CLAUDE_PROJECT_DIR/who.json"\n')
    for f in hooks.iterdir():
        f.chmod(0o755)
    settings = {"permissions": {"deny": ["Read(~/.ssh/id_*)", "Bash(git push --force:*)", "Workflow"]}, "hooks": {
        "PreToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": str(hooks / "edit.sh")}]},
                       {"matcher": "Bash", "hooks": [{"type": "command", "command": str(hooks / "bash.sh")}]},
                       {"matcher": "Read", "hooks": [{"type": "command", "command": "exit 2"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": str(hooks / "stop.sh")}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": str(hooks / "who.sh")}]}]}}
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings))
    return tmp_path


def run(repo, event, payload, env=None):
    return adapter.dispatch(event, json.dumps(payload), {"PATH": "/usr/bin:/bin", **(env or {})}, repo)


# contract-test: tooling
def test_apply_patch_becomes_one_claude_payload_per_file():
    files = adapter.edit_payloads({"tool_name": "apply_patch", "cwd": "/w", "tool_input": {"command": PATCH}})
    assert [(f["tool_name"], f["tool_input"]["file_path"]) for f in files] == [
        ("Write", "/w/new.py"), ("Edit", "/abs/old.py"), ("Edit", "/w/gone.py")]
    assert files[1]["tool_input"]["old_string"] == "a\nctx" and files[1]["tool_input"]["new_string"] == "b\nctx"
    assert files[2]["tool_input"]["new_string"] == ""


# contract-test: tooling
def test_edit_hooks_refuse_a_patch_with_exit_2(repo):
    patch = PATCH.replace("+print(1)", "+forbidden")
    code, _, err = run(repo, "PreToolUse", {"tool_name": "apply_patch", "cwd": str(repo), "tool_input": {"command": patch}})
    assert code == 2 and "forbidden" in err
    assert run(repo, "PreToolUse", {"tool_name": "apply_patch", "cwd": str(repo), "tool_input": {"command": PATCH}})[0] == 0


# contract-test: tooling
def test_bash_json_block_passes_through_and_claude_only_matchers_never_fire(repo):
    code, out, _ = run(repo, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "git push origin dev"}})
    assert code == 0 and json.loads(out)["decision"] == "block"
    assert run(repo, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}) == (0, "", "")


# contract-test: tooling
def test_stop_drops_plain_text(repo):
    assert run(repo, "Stop", {"stop_hook_active": False})[:2] == (0, "")


# contract-test: tooling
def test_session_id_is_the_chat_id_and_the_thread_is_recorded(repo, tmp_path):
    chats = tmp_path / "chats"
    chats.mkdir()
    (chats / f"{CHAT}.json").write_text(json.dumps({"chat_id": CHAT, "thread_id": ""}))
    run(repo, "UserPromptSubmit", {"session_id": THREAD, "prompt": "hi"},
        {"OPENMATES_CHAT_ID": CHAT, "OPENMATES_CODEX_CHATS_DIR": str(chats)})
    seen = json.loads((repo / "who.json").read_text())
    assert seen["session_id"] == CHAT and seen["codex_thread_id"] == THREAD
    assert json.loads((chats / f"{CHAT}.json").read_text())["thread_id"] == THREAD


# contract-test: tooling
def test_self_guard_and_agent_guard(repo):
    for command in ("echo {} > ~/.codex/hooks.json", "sed -i s/x/y/ /home/u/.codex/config.toml",
                    "codex -c features.hooks=false"):
        assert run(repo, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}})[0] == 2, command
    assert run(repo, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "cat ~/.codex/hooks.json"}})[0] == 0
    env = {"OPENMATES_CHAT_MODEL": "gpt-6.2-sol"}
    assert run(repo, "PreToolUse", {"tool_name": "spawn_agent", "tool_input": {"model": "gpt-6.2-astra"}}, env)[0] == 2
    assert run(repo, "PreToolUse", {"tool_name": "spawn_agent", "tool_input": {"reasoning_effort": "high"}}, env)[0] == 2
    assert run(repo, "PreToolUse", {"tool_name": "spawn_agent", "tool_input": {"message": "go"}}, env)[0] == 0


# contract-test: tooling
def test_claude_deny_rules_hold_for_codex_shell_and_patches(repo):
    env = {"HOME": "/home/u"}
    key = "/.ssh/" + "id_ed25519"
    for command in (f"cat ~{key}", f"base64 /home/u{key}", "git push --force origin main"):
        assert run(repo, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}}, env)[0] == 2, command
    assert run(repo, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls ~/.ssh/known_hosts"}}, env)[0] == 0
    assert run(repo, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, env)[0] == 0
    patch = f"*** Begin Patch\n*** Add File: /home/u{key}\n+k\n*** End Patch"
    assert run(repo, "PreToolUse", {"tool_name": "apply_patch", "tool_input": {"command": patch}}, env)[0] == 2
