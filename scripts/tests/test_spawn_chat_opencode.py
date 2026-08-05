#!/usr/bin/env python3
"""Regression tests for interactive OpenCode chat spawning.

The separate-chat workflow must launch OpenCode, preserve plan-mode safety,
and never fall back to the retired Claude CLI path used by spawn-chat.
"""

from pathlib import Path
from subprocess import CompletedProcess
import sys
from types import SimpleNamespace

from scripts import _zellij_utils, sessions


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
    assert '"run" "--interactive" "--title" "research-example" "--agent" "plan"' in layout
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
    assert '"run" "--interactive" "--title" "fix-example" "--auto"' in layout
    assert '"--agent" "plan"' not in layout


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


def test_spawn_chat_uses_canonical_control_plane_root(tmp_path: Path, monkeypatch) -> None:
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
    assert "scripts/.tmp/spawn-prompt-review-report.txt" in captured["prompt"]
