"""Tests for real graphical OpenMates CLI E2E recording.

The recorder must preserve a real PTY transcript while FFmpeg captures pixels
from a graphical terminal on an isolated Xvfb display. Tests use synthetic
commands and injected binaries so no account data or external API is required.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "cli_video_capture.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cli_video_capture", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_capture_plan_uses_exact_graphical_terminal_profile(tmp_path: Path) -> None:
    module = load_module()
    plan = module.build_capture_plan(
        argv=["node", "frontend/packages/openmates-cli/dist/cli.js", "--help"],
        output_dir=tmp_path,
        display_number=91,
        xvfb_binary="/usr/bin/Xvfb",
        terminal_binary="/usr/bin/x-terminal-emulator",
        ffmpeg_binary="/usr/bin/ffmpeg",
    )

    assert plan.width == 1280
    assert plan.height == 720
    assert plan.display == ":91"
    assert plan.video_path == tmp_path / "raw-terminal.mp4"
    assert plan.transcript_path == tmp_path / "transcript.txt"
    assert "1280x720x24" in plan.xvfb_argv
    assert "1280x720" in plan.ffmpeg_argv
    assert "160x48" in plan.terminal_argv
    assert "14" in plan.terminal_argv
    assert "node frontend/packages/openmates-cli/dist/cli.js --help" in plan.terminal_argv[-1]
    assert "sleep 3" in plan.terminal_argv[-1]
    assert "printf '%s\\n'" not in plan.terminal_argv[-1]
    assert "time.sleep(0.03)" in plan.terminal_argv[-1]


def test_interactive_plan_runs_cli_directly_and_validates_bounded_inputs(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "input.json"
    path.write_text('{"steps":[{"name":"ready","wait_for":"OpenMates"},{"name":"sidebar","key":"ctrl+b","wait_for":"Chats"},{"name":"tasks","text":"/tasks"},{"name":"enter","key":"Return","wait_for":"Tasks","hold_ms":400}]}', encoding="utf-8")
    steps = module.load_input_plan(path)
    assert [step["name"] for step in steps] == ["ready", "sidebar", "tasks", "enter"]
    plan = module.build_capture_plan(
        argv=["node", "frontend/packages/openmates-cli/dist/cli.js"], output_dir=tmp_path,
        xvfb_binary="Xvfb", terminal_binary="zutty", ffmpeg_binary="ffmpeg", interactive=True,
    )
    assert plan.terminal_argv[-1] == "node frontend/packages/openmates-cli/dist/cli.js"
    assert "sleep 3" not in plan.terminal_argv[-1]
    assert "120x38" in plan.terminal_argv
    assert "13" in plan.terminal_argv
    path.write_text('{"steps":[{"name":"secret","text":"--api-key abc"}]}', encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="secret-bearing"):
        module.load_input_plan(path)
    path.write_text('{"steps":[{"name":"bad","key":"ctrl+alt+Delete"}]}', encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="unsupported key"):
        module.load_input_plan(path)


def test_interactive_capture_prefers_zutty_and_uses_software_renderer(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: {
        "zutty": "/usr/bin/zutty", "x-terminal-emulator": "/usr/bin/x-terminal-emulator",
    }.get(name))
    plan = module.build_capture_plan(
        argv=["node", "frontend/packages/openmates-cli/dist/cli.js"], output_dir=tmp_path,
        xvfb_binary="Xvfb", ffmpeg_binary="ffmpeg", interactive=True,
    )
    assert plan.terminal_argv[0] == "/usr/bin/zutty"
    plan.video_path.write_bytes(b"synthetic captured pixels")
    plan.transcript_path.write_text("New chat\n", encoding="utf-8")
    plan.events_path.write_text("{}\n", encoding="utf-8")
    input_plan = tmp_path / "input.json"
    input_plan.write_text('{"steps":[{"name":"ready","wait_for":"New chat"}]}', encoding="utf-8")
    launched: dict[str, dict[str, str]] = {}

    class Process:
        returncode = None
        stderr = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def send_signal(self, _signal):
            pass

        def terminate(self):
            self.returncode = -15

    def fake_popen(argv, **kwargs):
        launched[argv[0]] = kwargs["env"]
        return Process()

    monkeypatch.setattr(module, "build_capture_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(module, "drive_terminal_inputs", lambda **_kwargs: [{"name": "ready", "at_ms": 0, "transcript_offset": 9, "marker": "New chat"}])
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    result = module.capture_cli_video(
        argv=["node", "frontend/packages/openmates-cli/dist/cli.js"],
        output_dir=tmp_path, target_environment="isolated-test", input_plan=input_plan,
    )
    assert result["exit_status"] == 0
    assert launched["/usr/bin/zutty"]["LIBGL_ALWAYS_SOFTWARE"] == "true"
    assert launched["/usr/bin/zutty"]["GALLIUM_DRIVER"] == "llvmpipe"


def test_interactive_driver_uses_real_x_window_and_records_checkpoint_times(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    module = load_module()
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("OpenMates", encoding="utf-8")
    commands = []

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        if "search" in argv:
            return SimpleNamespace(returncode=0, stdout="42\n", stderr="")
        if "key" in argv:
            transcript.write_text("OpenMates\nTasks", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    checkpoints = module.drive_terminal_inputs(
        steps=[{"name": "tasks", "key": "Return", "wait_for": "Tasks"}],
        transcript_path=transcript, display=":91", terminal=SimpleNamespace(poll=lambda: None),
        started_at=module.time.monotonic(), xdotool_binary="xdotool",
    )
    assert checkpoints[0]["name"] == "tasks"
    assert checkpoints[0]["at_ms"] >= 0
    assert [command[1] for command in commands] == ["search", "windowmove", "windowsize", "windowfocus", "key"]
    assert commands[2][-2:] == ["1280", "720"]


def test_interactive_driver_waits_for_mapped_pty_and_retries_focus(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    module = load_module()
    transcript = tmp_path / "transcript.txt"
    calls: list[list[str]] = []
    searches = focuses = 0

    def fake_run(argv, **_kwargs):
        nonlocal searches, focuses
        calls.append(argv)
        if "search" in argv:
            searches += 1
            assert "--onlyvisible" in argv
            if searches == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            transcript.write_text("New chat\n", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="42\n", stderr="")
        if "windowfocus" in argv:
            focuses += 1
            return SimpleNamespace(returncode=1 if focuses == 1 else 0, stdout="", stderr="not mapped" if focuses == 1 else "")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    checkpoints = module.drive_terminal_inputs(
        steps=[{"name": "ready", "wait_for": "New chat"}],
        transcript_path=transcript, display=":91", terminal=SimpleNamespace(poll=lambda: None),
        started_at=module.time.monotonic(), xdotool_binary="xdotool",
    )
    assert [checkpoint["name"] for checkpoint in checkpoints] == ["ready"]
    assert searches == 2 and focuses == 2
    assert [call[1] for call in calls] == ["search", "search", "windowmove", "windowsize", "windowfocus", "windowfocus"]


def test_interactive_driver_accepts_pre_rendered_initial_marker_only(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    module = load_module()
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("New chat\nRecent chats\n", encoding="utf-8")

    def fake_run(argv, **_kwargs):
        if "search" in argv:
            return SimpleNamespace(returncode=0, stdout="42\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    terminal = SimpleNamespace(poll=lambda: None)
    checkpoints = module.drive_terminal_inputs(
        steps=[{"name": "initial-closed", "wait_for": "New chat"}],
        transcript_path=transcript, display=":91", terminal=terminal,
        started_at=module.time.monotonic(), xdotool_binary="xdotool",
    )
    assert checkpoints[0]["transcript_offset"] == transcript.stat().st_size

    with pytest.raises(module.CliCaptureError, match="did not reach checkpoint later"):
        module.drive_terminal_inputs(
            steps=[{"name": "initial-closed", "wait_for": "New chat"},
                   {"name": "later", "wait_for": "Recent chats", "wait_timeout_ms": 10}],
            transcript_path=transcript, display=":91", terminal=terminal,
            started_at=module.time.monotonic(), xdotool_binary="xdotool",
        )


def test_capture_plan_rejects_non_openmates_commands_and_secret_argv(tmp_path: Path) -> None:
    module = load_module()
    with pytest.raises(module.CliCaptureError, match="OpenMates CLI"):
        module.build_capture_plan(argv=["python3", "helper.py"], output_dir=tmp_path)
    with pytest.raises(module.CliCaptureError, match="secret-bearing"):
        module.build_capture_plan(
            argv=["node", "frontend/packages/openmates-cli/dist/cli.js", "--api-key", "secret"],
            output_dir=tmp_path,
        )
    with pytest.raises(module.CliCaptureError, match="secret-bearing"):
        module.build_capture_plan(
            argv=["node", "frontend/packages/openmates-cli/dist/cli.js", "--token=secret"],
            output_dir=tmp_path,
        )


def test_manifest_binds_real_video_transcript_events_and_exit_status(tmp_path: Path) -> None:
    module = load_module()
    video = tmp_path / "raw-terminal.mp4"
    transcript = tmp_path / "transcript.txt"
    events = tmp_path / "events.jsonl"
    input_plan = tmp_path / "input.json"
    video.write_bytes(b"real terminal pixels")
    transcript.write_text("$ openmates --help\nOpenMates CLI\n", encoding="utf-8")
    events.write_text('{"kind":"output","at_ms":10}\n', encoding="utf-8")
    input_plan.write_text('{"steps":[]}', encoding="utf-8")

    manifest = module.build_capture_manifest(
        argv=["openmates", "--help"],
        video_path=video,
        transcript_path=transcript,
        events_path=events,
        exit_status=0,
        target_environment="https://api.dev.openmates.org",
        classification="cli_e2e",
        input_plan_path=input_plan,
    )

    assert manifest["capture_kind"] == "real_terminal_screen"
    assert manifest["exit_status"] == 0
    assert manifest["video_sha256"].startswith("sha256:")
    assert manifest["transcript_sha256"].startswith("sha256:")
    assert manifest["events_sha256"].startswith("sha256:")
    assert manifest["input_plan_sha256"].startswith("sha256:")
    assert manifest["reconstructed"] is False


def test_cli_response_media_uses_latest_replacement_scope(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    video = tmp_path / "raw-terminal.mp4"
    video.write_bytes(b"real terminal pixels")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return module.subprocess.CompletedProcess(command, 0, stdout='{"snippets":{"html":"<video></video>"}}', stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    payload = module.publish_response_media(video, classification="cli_e2e", dry_run=True)

    assert payload["snippets"]["html"] == "<video></video>"
    command, kwargs = calls[0]
    assert "--latest-run-type" in command
    assert command[command.index("--latest-run-type") + 1] == "openmates-cli-e2e"
    assert "--dry-run" in command
    assert kwargs == {"check": False, "capture_output": True, "text": True}


def test_main_does_not_fail_cli_capture_when_response_media_upload_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_module()
    video = tmp_path / "raw-terminal.mp4"
    video.write_bytes(b"real terminal pixels")

    def fake_capture_cli_video(**_kwargs):
        return {
            "exit_status": 0,
            "video_path": str(video),
        }

    def fake_publish_response_media(*_args, **_kwargs):
        raise module.CliCaptureError("response_media: Error response from daemon: No such container: api")

    monkeypatch.setattr(module, "capture_cli_video", fake_capture_cli_video)
    monkeypatch.setattr(module, "publish_response_media", fake_publish_response_media)

    monkeypatch.setattr(module.sys, "argv", [
        "cli_video_capture.py",
        "--output-dir",
        str(tmp_path),
        "--target-environment",
        "https://api.dev.openmates.org",
        "--",
        "node",
        "frontend/packages/openmates-cli/dist/cli.js",
        "--help",
    ])

    status = module.main()

    assert status == 0
    payload = module.json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["manifest"]["response_media_error"].startswith("response_media:")


def test_timeout_finalizes_video_and_keeps_failure_verdict(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace

    module = load_module()
    paths = {
        name: tmp_path / name
        for name in ("video", "transcript", "events", "output", "manifest")
    }
    for path in paths.values():
        path.write_bytes(b"synthetic test evidence")
    plan = SimpleNamespace(
        output_dir=tmp_path,
        display=":91",
        xvfb_argv=["xvfb"],
        ffmpeg_argv=["ffmpeg"],
        terminal_argv=["terminal"],
        video_path=paths["video"],
        transcript_path=paths["transcript"],
        events_path=paths["events"],
        command_output_path=paths["output"],
        manifest_path=paths["manifest"],
    )
    finalized = []

    class Process:
        def __init__(self, argv, **kwargs):
            self.name = argv[0]
            self.returncode = None
            self.stderr = io.StringIO()
            self.waits = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.waits += 1
            if self.name == "terminal" and self.waits == 1:
                raise module.subprocess.TimeoutExpired("terminal", timeout)
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        def send_signal(self, sig):
            finalized.append(self.name)

    monkeypatch.setattr(module, "build_capture_plan", lambda **k: plan)
    monkeypatch.setattr(module.subprocess, "Popen", Process)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(module.time, "sleep", lambda *a: None)
    result = module.capture_cli_video(
        argv=["openmates", "chats", "list"],
        output_dir=tmp_path,
        target_environment="isolated-test",
    )
    assert result["exit_status"] == 124 and "ffmpeg" in finalized
    assert paths["manifest"].is_file() and result["video_sha256"]
