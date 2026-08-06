#!/usr/bin/env python3
"""Regression tests for interactive OpenCode chat spawning.

The separate-chat workflow must launch OpenCode, preserve plan-mode safety,
and never fall back to the retired Claude CLI path used by spawn-chat.
"""

from pathlib import Path
import json
import re
from subprocess import CompletedProcess
import sys
from types import SimpleNamespace

import pytest

from scripts import _zellij_utils, sessions


@pytest.fixture(autouse=True)
def use_test_opencode_binary(monkeypatch) -> None:
    monkeypatch.setattr(_zellij_utils, "_resolve_opencode_bin", lambda: "opencode")


def test_spawn_opencode_session_uses_interactive_plan_agent(tmp_path: Path, monkeypatch) -> None:
    calls = iter(
        [
            CompletedProcess([], 0, stdout="", stderr=""),
            CompletedProcess([], 0, stdout="research-example active\n", stderr=""),
        ]
    )
    captured = {}

    monkeypatch.setattr(_zellij_utils, "_run_zellij", lambda *_args, **_kwargs: next(calls))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def capture_popen(command, **_kwargs):
        captured["layout"] = Path(command[2]).read_text(encoding="utf-8")
        return object()

    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", capture_popen)

    assert _zellij_utils.spawn_opencode_session(
        "research-example",
        'Review the "example" flow.',
        str(tmp_path),
        permission_mode="plan",
    )

    layout = captured["layout"]
    assert 'pane command="opencode"' in layout
    assert '"run" "--attach" "http://127.0.0.1:4096" "--interactive"' in layout
    assert '"--title" "research-example" "--agent" "plan"' in layout
    assert "Review the \\\"example\\\" flow." in layout
    assert "claude" not in layout
    assert "--auto" not in layout


def test_spawn_opencode_execute_mode_auto_approves_permissions(tmp_path: Path, monkeypatch) -> None:
    calls = iter(
        [
            CompletedProcess([], 0, stdout="", stderr=""),
            CompletedProcess([], 0, stdout="fix-example active\n", stderr=""),
        ]
    )
    captured = {}

    monkeypatch.setattr(_zellij_utils, "_run_zellij", lambda *_args, **_kwargs: next(calls))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def capture_popen(command, **_kwargs):
        captured["layout"] = Path(command[2]).read_text(encoding="utf-8")
        return object()

    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", capture_popen)

    assert _zellij_utils.spawn_opencode_session(
        "fix-example",
        "Implement the fix.",
        str(tmp_path),
        permission_mode="execute",
    )

    layout = captured["layout"]
    assert 'pane command="opencode"' in layout
    assert '"run" "--attach" "http://127.0.0.1:4096" "--interactive"' in layout
    assert '"--title" "fix-example" "--agent" "build" "--model" "openai/gpt-5.6-sol" "--auto"' in layout
    assert '"--agent" "plan"' not in layout


def test_resume_opencode_session_uses_existing_session_id(tmp_path: Path, monkeypatch) -> None:
    calls = iter(
        [
            CompletedProcess([], 0, stdout="", stderr=""),
            CompletedProcess([], 0, stdout="resume-example active\n", stderr=""),
        ]
    )
    captured = {}

    monkeypatch.setattr(_zellij_utils, "_run_zellij", lambda *_args, **_kwargs: next(calls))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def capture_popen(command, **_kwargs):
        captured["layout"] = Path(command[2]).read_text(encoding="utf-8")
        return object()

    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", capture_popen)

    assert _zellij_utils.resume_opencode_session(
        "resume-example",
        "ses_existing",
        str(tmp_path),
        "Continue the interrupted review.",
    )

    layout = captured["layout"]
    assert 'pane command="opencode"' in layout
    assert '"--session" "ses_existing"' in layout
    assert '"--agent" "plan"' in layout
    assert "--auto" not in layout
    assert "claude" not in layout


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


def test_spawn_opencode_rejects_invalid_mode_and_exited_session(tmp_path: Path, monkeypatch) -> None:
    assert not _zellij_utils.spawn_opencode_session(
        "unsafe-example",
        "Do work.",
        str(tmp_path),
        permission_mode="unexpected",
    )

    calls = iter(
        [
            CompletedProcess([], 0, stdout="", stderr=""),
            CompletedProcess([], 0, stdout="fix-example [EXITED]\n", stderr=""),
        ]
    )
    monkeypatch.setattr(_zellij_utils, "_run_zellij", lambda *_args, **_kwargs: next(calls))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", lambda *_args, **_kwargs: object())

    assert not _zellij_utils.spawn_opencode_session(
        "fix-example",
        "Implement the fix.\nThen verify it.",
        str(tmp_path),
        permission_mode="execute",
    )


def test_spawn_chat_uses_canonical_root_and_direct_prompt(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "worktree"
    canonical = tmp_path / "canonical"
    (canonical / "scripts").mkdir(parents=True)
    captured = {}

    monkeypatch.setattr(sessions, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", canonical)
    monkeypatch.setitem(sys.modules, "_zellij_utils", _zellij_utils)

    def capture_spawn(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(_zellij_utils, "spawn_opencode_session", capture_spawn)

    sessions.cmd_spawn_chat(
        SimpleNamespace(
            prompt="Review the report.",
            prompt_file=None,
            name="review-report",
            mode="plan",
            linear_issue=None,
        )
    )

    assert captured["cwd"] == str(canonical)
    assert captured["prompt"].endswith("Review the report.")
    assert "scripts/.tmp" not in captured["prompt"]


def test_spawn_chat_never_references_claude_launcher() -> None:
    source = (Path(sessions.__file__)).read_text(encoding="utf-8")
    command = source[source.index("def cmd_spawn_chat"):source.index("# restore", source.index("def cmd_spawn_chat"))]

    assert "spawn_opencode_session" in command
    assert "spawn_claude_session" not in command
    assert "Claude session" not in command


def test_restore_command_never_references_claude_launcher() -> None:
    source = (Path(sessions.__file__)).read_text(encoding="utf-8")
    command = source[source.index("def cmd_restore"):source.index("# CLI", source.index("def cmd_restore"))]

    assert "resume_opencode_session" in command
    assert "resume_claude_session" not in command


def test_server_restart_fails_closed_when_session_discovery_fails() -> None:
    source = (Path(sessions.__file__).parents[1] / "scripts/server-restart.sh").read_text(encoding="utf-8")

    assert "command -v opencode" in source
    assert "command -v jq" in source
    assert "if ! session_json=" in source


def test_active_automation_never_spawns_claude_cli() -> None:
    automation_paths = (
        "scripts/_daily_meeting_helper.py",
        "scripts/linear-poller.py",
        "scripts/linear-enricher.py",
        "scripts/server-restart.sh",
    )

    for relative_path in automation_paths:
        source = (Path(sessions.__file__).parents[1] / relative_path).read_text(encoding="utf-8")
        assert "spawn_claude_session" not in source, relative_path
        assert not re.search(r"\bclaude\s+(?:resume|--resume|--dangerously-skip-permissions|-p)\b", source), relative_path


def test_opencode_poller_records_never_use_claude_transcript_fallback() -> None:
    source = (
        Path(sessions.__file__).parents[1] / "scripts/linear-poller.py"
    ).read_text(encoding="utf-8")
    salvage = source[
        source.index("def _salvage_abandoned_sessions"):
        source.index("def main", source.index("def _salvage_abandoned_sessions"))
    ]

    assert "if claude_session_id\n            else None" in salvage


def test_spawn_chat_reads_prompt_file_before_switching_to_canonical_root(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "worktree"
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    prompt_path = tmp_path / "worker-prompt.md"
    prompt_path.write_text("Investigate the leased group.", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(sessions, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", canonical)
    monkeypatch.setitem(sys.modules, "_zellij_utils", _zellij_utils)
    monkeypatch.setattr(_zellij_utils, "spawn_opencode_session", lambda **kwargs: captured.update(kwargs) or True)

    sessions.cmd_spawn_chat(SimpleNamespace(
        prompt=None,
        prompt_file=str(prompt_path),
        name="prompt-file-worker",
        mode="execute",
        linear_issue=None,
    ))

    assert captured["cwd"] == str(canonical)
    assert captured["prompt"].endswith("Investigate the leased group.")
    assert str(prompt_path) not in captured["prompt"]
