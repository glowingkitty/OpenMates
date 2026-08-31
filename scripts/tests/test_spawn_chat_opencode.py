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
from types import SimpleNamespace
import urllib.parse

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


def test_spawn_opencode_session_uses_sidebar_plan_agent(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def capture_popen(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()

    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", capture_popen)

    assert _zellij_utils.spawn_opencode_session(
        "research-example",
        'Review the "example" flow.',
        str(tmp_path),
        permission_mode="plan",
    )

    command = captured["command"]
    assert command[:8] == [
        "opencode",
        "run",
        "--attach",
        _zellij_utils.OPENCODE_SERVER_URL,
        "--dir",
        str(tmp_path),
        "--format",
        "json",
    ]
    assert command[command.index("--title") + 1] == "research-example"
    assert command[command.index("--agent") + 1] == "plan"
    assert command[-1] == 'Review the "example" flow.'
    assert "--interactive" not in command
    assert "--auto" not in command
    assert "claude" not in " ".join(command).lower()
    assert captured["cwd"] == str(tmp_path)


def test_spawn_opencode_execute_mode_auto_approves_permissions(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def capture_popen(command, **kwargs):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", capture_popen)

    assert _zellij_utils.spawn_opencode_session(
        "fix-example",
        "Implement the fix.",
        str(tmp_path),
        permission_mode="execute",
    )

    command = captured["command"]
    assert command[command.index("--title") + 1] == "fix-example"
    assert command[command.index("--agent") + 1] == "build"
    assert command[command.index("--model") + 1] == "openai/gpt-5.5"
    assert command[command.index("--variant") + 1] == "xhigh"
    assert "--auto" in command
    assert "--interactive" not in command


def test_resume_opencode_session_uses_existing_session_id(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def capture_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", capture_urlopen)

    assert _zellij_utils.resume_opencode_session(
        "resume-example",
        "ses_existing",
        str(tmp_path),
        "Continue the interrupted review.",
    )

    request = captured["request"]
    assert request.method == "POST"
    assert "/session/ses_existing/prompt_async?" in request.full_url
    assert urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query) == {
        "directory": [_zellij_utils.OPENCODE_CONTROL_PLANE_RUNTIME],
    }
    assert json.loads(request.data) == {
        "agent": "plan",
        "parts": [{"type": "text", "text": "Continue the interrupted review."}],
    }
    assert captured["timeout"] == 15


def test_resume_opencode_session_preserves_captured_model(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def capture_urlopen(request, timeout):
        captured["request"] = request
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", capture_urlopen)
    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())

    assert _zellij_utils.resume_opencode_session(
        "resume-example",
        "ses_existing",
        str(tmp_path),
        permission_mode="execute",
        provider_id="openai",
        model_id="gpt-5.6-sol",
        variant="medium",
    )

    assert json.loads(captured["request"].data)["model"] == {
        "providerID": "openai",
        "modelID": "gpt-5.6-sol",
    }
    assert json.loads(captured["request"].data)["variant"] == "medium"


def test_restart_capture_keeps_only_busy_top_level_sessions(tmp_path: Path, monkeypatch) -> None:
    responses = {
        "/session/status": {
            "ses_parent": {"type": "busy"},
            "ses_child": {"type": "retry"},
            "ses_idle": {"type": "idle"},
        },
        "/session/ses_parent": {
            "id": "ses_parent",
            "parentID": None,
            "title": "Active task",
            "directory": "/repo",
            "time": {"updated": 123},
        },
        "/session/ses_parent/message?limit=10": [
            {"info": {"role": "assistant", "agent": "build", "providerID": "openai", "modelID": "gpt-5.6-sol", "variant": "medium"}}
        ],
        "/session/ses_child": {
            "id": "ses_child",
            "parentID": "ses_parent",
            "title": "Reviewer child",
            "time": {"updated": 124},
        },
    }
    monkeypatch.setattr(sessions, "_opencode_api_json", lambda path, timeout=15: responses[path])
    monkeypatch.setattr(sessions, "_now_iso", lambda: "now")
    manifest_path = tmp_path / "restart.json"

    manifest = sessions.capture_opencode_restart_manifest(manifest_path)

    assert [entry["session_id"] for entry in manifest["sessions"]] == ["ses_parent"]
    assert manifest["sessions"][0]["permission_mode"] == "execute"
    assert manifest["sessions"][0]["model_id"] == "gpt-5.6-sol"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest


def test_opencode_api_requests_are_pinned_to_canonical_project(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(sessions.urllib.request, "urlopen", fake_urlopen)

    assert sessions._opencode_api_json("/session/status") == {}
    assert captured["timeout"] == 15
    assert f"directory={sessions.urllib.parse.quote(str(sessions.CONTROL_PLANE_ROOT), safe='')}" in captured["url"]


def test_restart_resume_is_exactly_once_and_verified(tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "restart.json"
    manifest_path.write_text(json.dumps({
        "version": 1,
        "sessions": [{
            "session_id": "ses_parent",
            "updated_before_restart": 100,
            "permission_mode": "execute",
            "provider_id": "openai",
            "model_id": "gpt-5.6-sol",
            "variant": "medium",
            "resume_sent_at": None,
            "resume_verified_at": None,
        }],
    }), encoding="utf-8")
    calls = []
    monkeypatch.setattr(sessions, "prepare_opencode_restore", lambda _session_id: {
        "cwd": "/repo/worktree",
        "repository_session_id": "abcd",
        "advanced": False,
    })
    monkeypatch.setitem(
        sys.modules,
        "_zellij_utils",
        SimpleNamespace(resume_opencode_session=lambda **kwargs: calls.append(kwargs) or True),
    )
    monkeypatch.setattr(sessions, "_opencode_api_json", lambda path, timeout=15: (
        {"ses_parent": {"type": "busy"}} if path == "/session/status" else {"time": {"updated": 101}}
    ))
    monkeypatch.setattr(sessions, "_now_iso", lambda: "now")

    first = sessions.resume_opencode_restart_manifest(manifest_path)
    second = sessions.resume_opencode_restart_manifest(manifest_path)

    assert len(calls) == 1
    assert calls[0]["model_id"] == "gpt-5.6-sol"
    assert first["sessions"][0]["resume_verified_at"] == "now"
    assert second["sessions"][0]["resume_sent_at"] == "now"


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


def test_spawn_opencode_rejects_invalid_mode_and_failed_process(tmp_path: Path, monkeypatch) -> None:
    assert not _zellij_utils.spawn_opencode_session(
        "unsafe-example",
        "Do work.",
        str(tmp_path),
        permission_mode="unexpected",
    )

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr(_zellij_utils.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess(returncode=2))

    assert not _zellij_utils.spawn_opencode_session(
        "fix-example",
        "Implement the fix.\nThen verify it.",
        str(tmp_path),
        permission_mode="execute",
    )


def test_spawn_chat_uses_canonical_root_and_direct_prompt(tmp_path: Path, monkeypatch, capsys) -> None:
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
    monkeypatch.setattr(_zellij_utils, "find_opencode_session_id", lambda *_args, **_kwargs: "ses_spawned")

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
    output = capsys.readouterr().out
    assert "OpenCode session: ses_spawned" in output
    assert "Web chat: https://code.dev.openmates.org" in output
    assert "zellij attach" not in output


def test_spawn_chat_never_references_claude_launcher() -> None:
    source = (Path(sessions.__file__)).read_text(encoding="utf-8")
    command = source[source.index("def cmd_spawn_chat"):source.index("# restore", source.index("def cmd_spawn_chat"))]

    assert "spawn_opencode_session" in command
    assert "spawn_claude_session" not in command
    assert "Claude session" not in command
    assert "zellij attach" not in command


def test_restore_command_never_references_claude_launcher() -> None:
    source = (Path(sessions.__file__)).read_text(encoding="utf-8")
    command = source[source.index("def cmd_restore"):source.index("# CLI", source.index("def cmd_restore"))]

    assert "resume_opencode_session" in command
    assert "resume_claude_session" not in command
    assert "zellij attach" not in command


def test_server_restart_captures_exact_busy_set_and_never_rebuilds_docker() -> None:
    source = (Path(sessions.__file__).parents[1] / "scripts/server-restart.sh").read_text(encoding="utf-8")

    capture_index = source.index("opencode-restart capture")
    stop_index = source.index('send-keys --pane-id "$server_pane" "Ctrl c"')
    resume_index = source.index("opencode-restart resume")

    assert capture_index < stop_index < resume_index
    assert "command -v jq" in source
    assert "docker compose" not in source
    assert "tmux" not in source
    assert 'GIT_COMMON_DIR="$(git -C "$SCRIPT_CHECKOUT" rev-parse --path-format=absolute --git-common-dir)"' in source
    assert 'OPENCODE_PROJECT_ROOT="$PROJECT_DIR"' in source


def test_active_automation_never_spawns_claude_cli() -> None:
    automation_paths = (
        "scripts/_daily_meeting_helper.py",
        "scripts/linear-poller.py",
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
    monkeypatch.setattr(_zellij_utils, "find_opencode_session_id", lambda *_args, **_kwargs: None)

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


def test_spawn_chat_execute_no_deploy_instructions_omits_deploy_prompt(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "worktree"
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    captured = {}

    monkeypatch.setattr(sessions, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", canonical)
    monkeypatch.setitem(sys.modules, "_zellij_utils", _zellij_utils)
    monkeypatch.setattr(_zellij_utils, "spawn_opencode_session", lambda **kwargs: captured.update(kwargs) or True)
    monkeypatch.setattr(_zellij_utils, "find_opencode_session_id", lambda *_args, **_kwargs: "ses_worker")

    sessions.cmd_spawn_chat(SimpleNamespace(
        prompt="Debug the leased group, then stop for coordinator harvest.",
        prompt_file=None,
        name="test-debug-worker",
        mode="execute",
        linear_issue=None,
        no_deploy_instructions=True,
    ))

    assert "Use sessions.py deploy" not in captured["prompt"]
    assert "Do not deploy, commit, merge, or push" in captured["prompt"]
    assert captured["prompt"].endswith("Debug the leased group, then stop for coordinator harvest.")


def test_spawn_chat_execute_readonly_has_consistent_prompt(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "worktree"
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    captured = {}

    monkeypatch.setattr(sessions, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", canonical)
    monkeypatch.setitem(sys.modules, "_zellij_utils", _zellij_utils)
    monkeypatch.setattr(_zellij_utils, "spawn_opencode_session", lambda **kwargs: captured.update(kwargs) or True)
    monkeypatch.setattr(_zellij_utils, "find_opencode_session_id", lambda *_args, **_kwargs: "ses_readonly")

    sessions.cmd_spawn_chat(SimpleNamespace(
        prompt="Read-only investigation. Do not edit files.",
        prompt_file=None,
        name="readonly-investigation",
        mode="execute-readonly",
        linear_issue=None,
        no_deploy_instructions=False,
    ))

    assert captured["permission_mode"] == "execute-readonly"
    assert "EXECUTE-READONLY" in captured["prompt"]
    assert "MUST NOT edit" in captured["prompt"]
    assert "Use sessions.py deploy" not in captured["prompt"]


def test_spawn_chat_rejects_contradictory_execute_prompt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "PROJECT_ROOT", tmp_path / "worktree")
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", tmp_path / "canonical")

    with pytest.raises(SystemExit, match="--mode execute cannot be combined"):
        sessions.cmd_spawn_chat(SimpleNamespace(
            prompt="Read-only investigation. Do not edit files.",
            prompt_file=None,
            name="bad-worker",
            mode="execute",
            linear_issue=None,
            no_deploy_instructions=False,
        ))


def test_spawn_chat_rejects_contradictory_execute_readonly_prompt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "PROJECT_ROOT", tmp_path / "worktree")
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", tmp_path / "canonical")

    with pytest.raises(SystemExit, match="--mode execute-readonly cannot be combined"):
        sessions.cmd_spawn_chat(SimpleNamespace(
            prompt="Implement the fix directly and use sessions.py deploy when done.",
            prompt_file=None,
            name="bad-readonly-worker",
            mode="execute-readonly",
            linear_issue=None,
            no_deploy_instructions=False,
        ))
