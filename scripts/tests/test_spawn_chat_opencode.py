#!/usr/bin/env python3
"""Regression tests for persisted OpenCode Web chat spawning.

The separate-chat workflow must launch OpenCode through the existing Web server,
preserve plan-mode safety, and never fall back to the retired Claude CLI path.
"""

# contract-test-file: tooling

from pathlib import Path
import json
import re
from subprocess import CompletedProcess
import sys

import pytest

from scripts import _zellij_utils, sessions


@pytest.fixture(autouse=True)
def use_test_opencode_binary(monkeypatch) -> None:
    monkeypatch.setattr(_zellij_utils, "_resolve_opencode_bin", lambda: "opencode")


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


def test_find_opencode_session_id_ignores_older_same_title(tmp_path: Path, monkeypatch) -> None:
    responses = iter(
        [
            [{"id": "ses_old", "title": "fix-example", "created": 100}],
            [
                {"id": "ses_new", "title": "fix-example", "created": 300},
                {"id": "ses_old", "title": "fix-example", "created": 100},
            ],
        ]
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return CompletedProcess(command, 0, stdout=json.dumps(next(responses)), stderr="")

    monkeypatch.setattr(_zellij_utils.subprocess, "run", fake_run)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    assert _zellij_utils.find_opencode_session_id(
        "fix-example",
        str(tmp_path),
        created_after_ms=200,
        attempts=2,
    ) == "ses_new"
    assert captured["cwd"] == str(tmp_path)
    assert captured["command"][-2:] == ["--format", "json"]


def test_active_automation_never_spawns_claude_cli() -> None:
    assert not (Path(sessions.__file__).parents[1] / "scripts/server-restart.sh").exists()
    automation_paths = (
        "scripts/_daily_meeting_helper.py",
    )

    for relative_path in automation_paths:
        source = (Path(sessions.__file__).parents[1] / relative_path).read_text(encoding="utf-8")
        assert "spawn_claude_session" not in source, relative_path
        assert not re.search(r"\bclaude\s+(?:resume|--resume|--dangerously-skip-permissions|-p)\b", source), relative_path


def test_retired_opencode_launch_commands_are_absent():
    from scripts import sessions, _zellij_utils
    for name in ("cmd_spawn_chat", "cmd_restore", "cmd_opencode_restart"):
        assert not hasattr(sessions, name)
    assert not hasattr(_zellij_utils, "spawn_opencode_session")
    assert not hasattr(_zellij_utils, "resume_opencode_session")


def test_retirement_preserves_cli_entrypoint_help():
    """Removing decorated launchers must not decorate the next retained function."""
    import subprocess
    from pathlib import Path
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "sessions.py"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "ci-source" in result.stdout
    assert "spawn-chat" not in result.stdout
