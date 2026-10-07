"""Tests for real graphical OpenMates CLI E2E recording.

The recorder must preserve a real PTY transcript while FFmpeg captures pixels
from a graphical terminal on an isolated Xvfb display. Tests use synthetic
commands and injected binaries so no account data or external API is required.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
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
    path.write_text('{"steps":[{"name":"ready","wait_for":"OpenMates"},{"name":"navigation","key":"ctrl+g"},{"name":"sidebar","key":"ctrl+b","wait_for":"Chats"},{"name":"tasks","text":"/tasks"},{"name":"enter","key":"Return","wait_for":"Tasks","hold_ms":400}]}', encoding="utf-8")
    steps = module.load_input_plan(path)
    assert [step["name"] for step in steps] == ["ready", "navigation", "sidebar", "tasks", "enter"]
    path.write_text('{"steps":[{"name":"palette","key":"ctrl+p"}]}', encoding="utf-8")
    assert module.load_input_plan(path)[0]["key"] == "ctrl+p"
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


def test_pointer_proof_key_sequence_passes_recorder_validation(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "pointer-input.json"
    keys = ["ctrl+g", "ctrl+p", "Escape", "Escape", "End", "Return"]
    path.write_text(json.dumps({"steps": [
        {"name": f"pointer-key-{index}", "key": key}
        for index, key in enumerate(keys)
    ]}), encoding="utf-8")
    assert [step["key"] for step in module.load_input_plan(path)] == keys


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


def test_interactive_driver_wheels_over_sidebar_and_rejects_mixed_inputs(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    module = load_module()
    input_path = tmp_path / "wheel-plan.json"
    input_path.write_text(json.dumps({"steps": [{"name": "sidebar-wheel", "wheel": "down", "wait_for": "selected"}]}), encoding="utf-8")
    steps = module.load_input_plan(input_path)
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("ready\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        if "search" in argv:
            return SimpleNamespace(returncode=0, stdout="42\n", stderr="")
        if argv[1:3] == ["click", "5"]:
            transcript.write_text("ready\nselected\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    checkpoints = module.drive_terminal_inputs(
        steps=steps, transcript_path=transcript, display=":91",
        terminal=SimpleNamespace(poll=lambda: None), started_at=module.time.monotonic(),
        xdotool_binary="xdotool",
    )
    assert [command[1] for command in commands][-2:] == ["mousemove", "click"]
    assert commands[-2] == ["xdotool", "mousemove", "--window", "42", "80", "360"]
    assert commands[-1] == ["xdotool", "click", "5"]
    assert checkpoints[0]["marker"] == "selected"

    input_path.write_text(json.dumps({"steps": [{"name": "mixed", "wheel": "down", "key": "Down"}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="exactly one input"):
        module.load_input_plan(input_path)
    input_path.write_text(json.dumps({"steps": [{"name": "bad-wheel", "wheel": "left"}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="unsupported wheel direction"):
        module.load_input_plan(input_path)


def _screen(*rows: str) -> str:
    return "\x1b[?2026h" + "".join(f"\x1b[{index};1H\x1b[2K{row}" for index, row in enumerate(rows, 1)) + "\x1b[?2026l"


def test_click_plan_resolves_visible_cells_and_rejects_ambiguous_targets(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "pointer-plan.json"
    steps = [
        {"name": "project", "click": {"text": "Projects"}},
        {"name": "second", "click": {"text": "Open", "occurrence": 1}},
        {"name": "card", "click": {"row": 3, "column": 12}},
        {"name": "narrow", "resize": {"width": 900, "height": 600}},
    ]
    path.write_text(json.dumps({"steps": steps}), encoding="utf-8")
    assert module.load_input_plan(path) == steps
    frame = _screen("漢 Projects Open    ", "Open                ", "Card                ",
                    "                    ", "                    ")
    assert module.resolve_click_cell(frame, {"text": "Projects"}) == (1, 7, 20, 5)
    assert module.resolve_click_cell(frame, {"text": "Open", "occurrence": 1}) == (2, 2, 20, 5)
    assert module.resolve_click_cell(frame, {"row": 3, "column": 12}) == (3, 12, 20, 5)
    with pytest.raises(module.CliCaptureError, match="ambiguous"):
        module.resolve_click_cell(frame, {"text": "Open"})
    with pytest.raises(module.CliCaptureError, match="outside"):
        module.resolve_click_cell(frame, {"row": 6, "column": 1})
    with pytest.raises(module.CliCaptureError, match="complete"):
        module.resolve_click_cell(frame[:-8], {"text": "Projects"})


@pytest.mark.parametrize("click", [
    {"text": ""}, {"text": "Projects", "occurrence": -1},
    {"text": "Projects", "occurrence": True}, {"text": "Projects", "row": 1},
    {"row": 0, "column": 1}, {"row": 1, "column": 257}, {"row": True, "column": 1},
])
def test_click_plan_rejects_invalid_targets(tmp_path: Path, click: dict) -> None:
    module = load_module()
    path = tmp_path / "bad-pointer-plan.json"
    path.write_text(json.dumps({"steps": [{"name": "bad", "click": click}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="invalid click"):
        module.load_input_plan(path)


def test_click_plan_rejects_secret_bearing_target(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "secret-pointer-plan.json"
    path.write_text(json.dumps({"steps": [{"name": "secret", "click": {"text": "--api-key value"}}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="secret-bearing"):
        module.load_input_plan(path)


def test_pointer_driver_uses_xtest_press_release_and_recalculates_after_resize(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    module = load_module()
    transcript = tmp_path / "transcript.txt"
    transcript.write_text(_screen(*(["Projects".ljust(20)] + [" " * 20] * 4)), encoding="utf-8")
    commands: list[list[str]] = []
    size = {"WIDTH": 800, "HEIGHT": 500}

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        if argv[1] == "search":
            return SimpleNamespace(returncode=0, stdout="42\n", stderr="")
        if argv[1] == "getwindowgeometry":
            return SimpleNamespace(returncode=0, stdout=f"WIDTH={size['WIDTH']}\nHEIGHT={size['HEIGHT']}\n", stderr="")
        if argv[1] == "windowsize" and argv[-2:] == ["900", "600"]:
            size.update(WIDTH=900, HEIGHT=600)
            transcript.write_text(transcript.read_text() + _screen(*(["Projects".ljust(30)] + [" " * 30] * 5)), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    checkpoints = module.drive_terminal_inputs(
        steps=[{"name": "first", "click": {"text": "Projects"}},
               {"name": "resize", "resize": {"width": 900, "height": 600}, "wait_for": "Projects"},
               {"name": "second", "click": {"text": "Projects"}}],
        transcript_path=transcript, display=":91", terminal=SimpleNamespace(poll=lambda: None),
        started_at=module.time.monotonic(), xdotool_binary="xdotool",
    )
    assert [command[1] for command in commands].count("mousedown") == 2
    assert [command[1] for command in commands].count("mouseup") == 2
    assert checkpoints[0]["pointer"]["columns"] == 20
    assert checkpoints[0]["pointer"]["rows"] == 5
    assert checkpoints[0]["pointer"]["window_width"] == 800
    assert checkpoints[2]["pointer"]["columns"] == 30
    assert checkpoints[2]["pointer"]["rows"] == 6
    assert checkpoints[2]["pointer"]["window_width"] == 900
    assert checkpoints[0]["pointer"]["x"] != checkpoints[2]["pointer"]["x"]


@pytest.mark.parametrize("repeat", [1, 8, 16])
def test_interactive_plan_accepts_bounded_key_repeats(tmp_path: Path, repeat: int) -> None:
    module = load_module()
    path = tmp_path / "repeat-plan.json"
    path.write_text(json.dumps({"steps": [{"name": "visit-fields", "key": "Tab", "repeat": repeat}]}), encoding="utf-8")
    assert module.load_input_plan(path)[0]["repeat"] == repeat


@pytest.mark.parametrize("step", [
    {"key": "Tab", "repeat": 0}, {"key": "Tab", "repeat": 17},
    {"key": "Tab", "repeat": True}, {"key": "Tab", "repeat": "8"},
    {"key": "Tab", "repeat": 1.5}, {"text": "hello", "repeat": 2},
    {"wheel": "down", "repeat": 2}, {"wait_for": "ready", "repeat": 2},
])
def test_interactive_plan_rejects_invalid_or_non_key_repeats(tmp_path: Path, step: dict) -> None:
    module = load_module()
    path = tmp_path / "invalid-repeat-plan.json"
    path.write_text(json.dumps({"steps": [{"name": "bad-repeat", **step}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="invalid key repeat"):
        module.load_input_plan(path)


@pytest.mark.parametrize("step", [
    {"key": "Tab", "text": "hello", "repeat": 2},
    {"key": "Tab", "wheel": "down", "repeat": 2},
])
def test_interactive_plan_rejects_repeated_mixed_inputs(tmp_path: Path, step: dict) -> None:
    module = load_module()
    path = tmp_path / "mixed-repeat-plan.json"
    path.write_text(json.dumps({"steps": [{"name": "bad-repeat", **step}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="exactly one input"):
        module.load_input_plan(path)


def test_interactive_plan_rejects_unbounded_repeat_delay_override(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "repeat-delay-plan.json"
    path.write_text(json.dumps({"steps": [{"name": "bad-repeat", "key": "Tab", "repeat": 2, "repeat_delay_ms": 0}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="invalid step"):
        module.load_input_plan(path)


def test_interactive_driver_sends_repeated_real_tab_keys(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    module = load_module()
    plan = tmp_path / "repeat-plan.json"
    plan.write_text(json.dumps({"steps": [{"name": "visit-fields", "key": "Tab", "repeat": 8}]}), encoding="utf-8")
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("ready\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        if "search" in argv:
            return SimpleNamespace(returncode=0, stdout="42\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    checkpoints = module.drive_terminal_inputs(
        steps=module.load_input_plan(plan), transcript_path=transcript, display=":91",
        terminal=SimpleNamespace(poll=lambda: None), started_at=module.time.monotonic(),
        xdotool_binary="xdotool",
    )
    assert commands[-1] == ["xdotool", "key", "--clearmodifiers", "--repeat", "8", "--delay", "120", "Tab"]
    assert [checkpoint["name"] for checkpoint in checkpoints] == ["visit-fields"]


@pytest.mark.parametrize("output,ready", [
    ("Files\n", False),
    ("\x1b[?2026hFiles Refreshing Project…\x1b[?2026l", False),
    ("\x1b[?2026hFiles Refreshing Project…\x1b[?2026l\x1b[?2026hFiles\x1b[?2026l", True),
    ("\x1b[?2026hFiles\x1b[?2026l\x1b[?2026hFiles Refreshing Project…", False),
    ("\x1b[?2026hFiles\x1b[?2026l\x1b[?2026hLoading another view\x1b[?2026l", False),
])
def test_loading_absence_requires_latest_complete_tui_frame(output: str, ready: bool) -> None:
    module = load_module()
    assert module.input_step_ready(output, "Files", "Refreshing Project…") is ready


def test_interactive_driver_waits_until_loading_disappears(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    module = load_module()
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("initial\n", encoding="utf-8")
    waits: list[float] = []

    def fake_run(argv, **_kwargs):
        if "search" in argv:
            return SimpleNamespace(returncode=0, stdout="42\n", stderr="")
        if "key" in argv:
            with transcript.open("a", encoding="utf-8") as handle:
                handle.write("\x1b[?2026hFiles Refreshing Project…\x1b[?2026l")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def settle(seconds):
        waits.append(seconds)
        with transcript.open("a", encoding="utf-8") as handle:
            handle.write("\x1b[?2026hFiles / nested folder\x1b[?2026l")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", settle)
    checkpoints = module.drive_terminal_inputs(
        steps=[{"name": "refreshed", "key": "Return", "wait_for": "Files", "wait_for_absent": "Refreshing Project…"}],
        transcript_path=transcript, display=":91", terminal=SimpleNamespace(poll=lambda: None),
        started_at=module.time.monotonic(), xdotool_binary="xdotool",
    )
    assert 0.05 in waits
    assert checkpoints[0]["absent_marker"] == "Refreshing Project…"
    assert checkpoints[0]["transcript_offset"] == transcript.stat().st_size

    input_path = tmp_path / "absent-plan.json"
    input_path.write_text(json.dumps({"steps": [{"name": "refreshed", "key": "Return", "wait_for": "Files", "wait_for_absent": "Refreshing Project…"}]}), encoding="utf-8")
    assert module.load_input_plan(input_path)[0]["wait_for_absent"] == "Refreshing Project…"
    input_path.write_text(json.dumps({"steps": [{"name": "invalid", "key": "Return", "wait_for_absent": ""}]}), encoding="utf-8")
    with pytest.raises(module.CliCaptureError, match="invalid wait_for_absent"):
        module.load_input_plan(input_path)


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

@pytest.mark.parametrize("key", ["ctrl+o", "ctrl+u", "shift+Tab", "Home", "End", "Page_Up", "Page_Down"])
def test_workspace_navigation_keys_are_recordable(tmp_path, key):
    module = load_module()
    path = tmp_path / "navigation.json"
    path.write_text(json.dumps({"steps": [{"name": "navigate", "key": key}]}))
    assert module.load_input_plan(path)[0]["key"] == key
