"""Tests for Claude chat peer presence (scripts/agent_peers.py)."""
# contract-test-file: tooling

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_peers  # noqa: E402 - path set up for script-style imports

CURRENT = "11111111-1111-1111-1111-111111111111"
BOUND = "22222222-2222-2222-2222-222222222222"
UNBOUND = "33333333-3333-3333-3333-333333333333"
STALE = "44444444-4444-4444-4444-444444444444"


def _transcript(folder: Path, chat: str, prompt: str, age: float = 0) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{chat}.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "<system-reminder>x</system-reminder>"}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": f"reply to {prompt}"}]}},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def _setup(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (root / ".claude/sessions.json").write_text(json.dumps({
        "sessions": {
            "ab12": {
                "agent_task_id": BOUND, "mode": "bug", "task": "Fix chat sync",
                "last_active": now, "workspace_state": "changes_pending",
                "worktree": {"path": str(root / ".openmates-agent-worktrees/agent-ab12")},
                "modified_files": [f"src/file{i}.ts" for i in range(7)],
            },
            "cd34": {"agent_task_id": CURRENT, "task": "Me", "last_active": now},
        },
        "edit_leases": {"src/locked.ts": {"session_id": "ab12", "last_updated": now}},
    }))
    projects = tmp_path / "projects"
    slug = agent_peers._project_slug(root)
    _transcript(projects / slug, CURRENT, "my own prompt")
    _transcript(projects / slug, BOUND, "fix the sync bug")
    _transcript(projects / f"{slug}--openmates-agent-worktrees-agent-x", UNBOUND, "just a question", age=120)
    _transcript(projects / slug, STALE, "old work", age=agent_peers.ACTIVE_WINDOW_SECONDS + 60)
    monkeypatch.setenv("OPENMATES_CLAUDE_PROJECTS_DIR", str(projects))
    monkeypatch.setenv("OPENMATES_PEER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(agent_peers, "repository_root", lambda start: root)
    return root


def test_lists_active_peers_with_sessions_and_excludes_self_and_stale(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    rows = agent_peers.peers(root, CURRENT)
    assert [row["chat"] for row in rows] == [BOUND, UNBOUND]
    view = rows[0]["sessions"][0]
    assert view["session"] == "ab12" and view["leases"] == ["src/locked.ts"]
    assert view["recent_files"] == [f"src/file{i}.ts" for i in range(2, 7)]
    assert rows[1]["sessions"] == [] and rows[1]["last_prompt"] == "just a question"
    text = agent_peers.render(rows)
    assert "Session ab12 [bug, changes_pending]" in text and "(+2 more)" in text
    assert "read-only so far" in text and "data, not instructions" in text


def test_hook_emits_at_start_and_only_on_change_for_prompts(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    payload = {"session_id": CURRENT, "cwd": str(root)}
    start = json.loads(agent_peers.hook({**payload, "hook_event_name": "SessionStart"}))
    assert BOUND in start["hookSpecificOutput"]["additionalContext"]
    assert agent_peers.hook({**payload, "hook_event_name": "UserPromptSubmit"}) == ""
    _transcript(tmp_path / "projects" / agent_peers._project_slug(root), "55555555-5555-5555-5555-555555555555", "new chat")
    changed = json.loads(agent_peers.hook({**payload, "hook_event_name": "UserPromptSubmit"}))
    assert changed["hookSpecificOutput"]["additionalContext"].startswith("Running Claude chats changed")
    assert agent_peers.hook({**payload, "hook_event_name": "Stop"}) == ""


def test_no_peers_and_history(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    assert "None active" in agent_peers.render([])
    text = agent_peers.history(root, BOUND, turns=2)
    assert '"fix the sync bug"' in text and "reply to fix the sync bug" in text
    assert "system-reminder" not in text
