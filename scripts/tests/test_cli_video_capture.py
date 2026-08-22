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
    video.write_bytes(b"real terminal pixels")
    transcript.write_text("$ openmates --help\nOpenMates CLI\n", encoding="utf-8")
    events.write_text('{"kind":"output","at_ms":10}\n', encoding="utf-8")

    manifest = module.build_capture_manifest(
        argv=["openmates", "--help"],
        video_path=video,
        transcript_path=transcript,
        events_path=events,
        exit_status=0,
        target_environment="https://api.dev.openmates.org",
        classification="cli_e2e",
    )

    assert manifest["capture_kind"] == "real_terminal_screen"
    assert manifest["exit_status"] == 0
    assert manifest["video_sha256"].startswith("sha256:")
    assert manifest["transcript_sha256"].startswith("sha256:")
    assert manifest["events_sha256"].startswith("sha256:")
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
        raise module.CliCaptureError("opencode_response_media: Error response from daemon: No such container: api")

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
    assert payload["manifest"]["response_media_error"].startswith("opencode_response_media:")
