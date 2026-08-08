#!/usr/bin/env python3
"""Regression tests for sessions.py OpenCode transcript lookup.

The fixtures use a tiny local SQLite database with the same stable tables that
OpenCode stores for sessions, messages, and parts. Tests cover the web URL
decoder, child session inclusion, issue-signal extraction, and bounded search
without reading the developer's real local OpenCode database.
"""

# contract-test-file: tooling

from __future__ import annotations

import base64
import json
from pathlib import Path
import sqlite3
import sys

from scripts import sessions


ROOT = Path("/home/superdev/projects/OpenMates")
ROOT_SESSION = "ses_parentChat"
CHILD_SESSION = "ses_childChat"


def encoded_project(path: str = str(ROOT)) -> str:
    return base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii").rstrip("=")


def create_opencode_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE session ("
        "id TEXT PRIMARY KEY, directory TEXT, parent_id TEXT, title TEXT, "
        "time_created INTEGER, time_updated INTEGER);"
        "CREATE TABLE message ("
        "id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, "
        "time_updated INTEGER, data TEXT);"
        "CREATE TABLE part ("
        "id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, "
        "time_created INTEGER, time_updated INTEGER, data TEXT);"
    )
    connection.executemany(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        [
            (ROOT_SESSION, str(ROOT), None, "Debug worktree routing", 1_786_000_000_000, 1_786_000_010_000),
            (CHILD_SESSION, str(ROOT), ROOT_SESSION, "Inspect hook failure", 1_786_000_002_000, 1_786_000_009_000),
        ],
    )
    connection.executemany(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        [
            (
                "msg_root_user",
                ROOT_SESSION,
                1_786_000_000_100,
                1_786_000_000_100,
                json.dumps({"role": "user", "agent": "build"}),
            ),
            (
                "msg_child_tool",
                CHILD_SESSION,
                1_786_000_003_000,
                1_786_000_004_000,
                json.dumps({"role": "assistant", "agent": "build", "modelID": "gpt-5.6-terra"}),
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                "part_root_text",
                "msg_root_user",
                ROOT_SESSION,
                1_786_000_000_100,
                1_786_000_000_100,
                json.dumps({"type": "text", "text": "Please debug the worktree hook setup."}),
            ),
            (
                "part_child_tool",
                "msg_child_tool",
                CHILD_SESSION,
                1_786_000_003_100,
                1_786_000_004_000,
                json.dumps(
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "error",
                            "error": "sessions.py start failed: missing worktree mapping",
                        },
                    }
                ),
            ),
        ],
    )
    connection.commit()
    connection.close()


def test_parse_opencode_chat_url_decodes_project_path() -> None:
    url = f"https://code.dev.openmates.org/{encoded_project()}/session/{ROOT_SESSION}"

    parsed = sessions.parse_opencode_chat_reference(url)

    assert parsed == {"session_id": ROOT_SESSION, "project_directory": str(ROOT)}


def test_read_opencode_chat_includes_children_and_issue_signals(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "opencode.db"
    create_opencode_fixture(database)
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {
            "sessions": {
                "abcd": {
                    "opencode_session_id": ROOT_SESSION,
                    "task": "Debug worktree routing",
                    "mode": "bug",
                    "worktree": {"status": "active", "path": "/tmp/worktree", "binding_mode": "native"},
                    "modified_files": ["scripts/sessions.py"],
                }
            }
        },
    )
    url = f"https://code.dev.openmates.org/{encoded_project()}/session/{ROOT_SESSION}"

    view = sessions.read_opencode_chat(url, db_path=database)

    assert [item["session_id"] for item in view["sessions"]] == [ROOT_SESSION, CHILD_SESSION]
    assert view["repository_sessions"][0]["repository_session_id"] == "abcd"
    assert view["issue_signals"][0]["kind"] == "tool_error"
    assert view["issue_signals"][0]["tool"] == "bash"
    assert "missing worktree mapping" in view["issue_signals"][0]["text"]


def test_search_opencode_chat_filters_to_matching_messages(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "opencode.db"
    create_opencode_fixture(database)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {}})

    view = sessions.search_opencode_chat(ROOT_SESSION, "missing worktree", db_path=database)

    assert view["query"] == "missing worktree"
    assert view["message_count"] == 1
    assert view["messages"][0]["session_id"] == CHILD_SESSION
    assert view["messages"][0]["parts"][0]["matched"] is True


def test_chat_alias_dispatches_to_opencode_chat_reader(monkeypatch, capsys) -> None:
    captured = {}

    def fake_read(reference: str, **kwargs):
        captured["reference"] = reference
        captured["kwargs"] = kwargs
        return {
            "session_id": reference,
            "sessions": [{"title": "Alias test", "directory": str(ROOT), "time_updated": "2026-08-08T00:00:00Z"}],
            "message_count": 0,
            "part_count": 0,
            "issue_signals": [],
            "messages": [],
            "truncated": {},
        }

    monkeypatch.setattr(sessions, "read_opencode_chat", fake_read)
    monkeypatch.setattr(sys, "argv", ["sessions.py", "chat", "read", ROOT_SESSION, "--max-messages", "3"])

    sessions.main()

    assert captured["reference"] == ROOT_SESSION
    assert captured["kwargs"]["max_messages"] == 3
    assert "Session: ses_parentChat" in capsys.readouterr().out
