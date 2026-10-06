#!/usr/bin/env python3
"""Record real OpenMates CLI E2E pixels from a graphical terminal.

The command runs through util-linux script in a real PTY displayed by Zutty on
an isolated Xvfb display. FFmpeg records that display while transcript and timing
files remain hash-bound sidecar evidence. It never reconstructs terminal pixels.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from typing import Any


TERMINAL_WIDTH = 1280
TERMINAL_HEIGHT = 720
DISPLAY_DEPTH = 24
RESULT_HOLD_SECONDS = 3
MAX_INPUT_STEPS = 64
MAX_KEY_REPEAT = 16
KEY_REPEAT_DELAY_MS = 120
MAX_STEP_WAIT_MS = 30_000
MAX_STEP_HOLD_MS = 5_000
ALLOWED_KEYS = {"Return", "Escape", "Tab", "Up", "Down", "Left", "Right", "space", "ctrl+b", "ctrl+s", "ctrl+c", "ctrl+g", "ctrl+o", "ctrl+q", "ctrl+u", "ctrl+y", "shift+Tab", "Home", "End", "Page_Up", "Page_Down"}
SECRET_FLAGS = {"--api-key", "--password", "--token", "--secret", "--otp", "--totp"}
TERMINAL_GEOMETRY = "160x48"
TERMINAL_FONT_SIZE = "14"
INTERACTIVE_TERMINAL_GEOMETRY = "120x38"
INTERACTIVE_TERMINAL_FONT_SIZE = "13"
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-_][0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
RESPONSE_MEDIA_SCRIPT = Path(__file__).resolve().parent / "response_media.py"


class CliCaptureError(RuntimeError):
    """Raised when real terminal capture cannot proceed safely or truthfully."""


@dataclass(frozen=True)
class CapturePlan:
    width: int
    height: int
    display: str
    output_dir: Path
    video_path: Path
    transcript_path: Path
    events_path: Path
    command_output_path: Path
    manifest_path: Path
    xvfb_argv: list[str]
    terminal_argv: list[str]
    ffmpeg_argv: list[str]


def load_input_plan(path: Path) -> list[dict[str, Any]]:
    """Validate a bounded, non-secret sequence of real terminal inputs."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliCaptureError(f"Invalid terminal input plan: {exc}") from exc
    steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_INPUT_STEPS:
        raise CliCaptureError(f"Terminal input plan must contain 1–{MAX_INPUT_STEPS} steps")
    names: set[str] = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) - {"name", "text", "key", "wheel", "repeat", "wait_for", "wait_for_absent", "wait_timeout_ms", "hold_ms"}:
            raise CliCaptureError("Terminal input plan contains an invalid step")
        name = step.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) or name in names:
            raise CliCaptureError("Terminal input step names must be unique slugs")
        names.add(name)
        input_count = sum(field in step for field in ("text", "key", "wheel"))
        if input_count != 1 and not (input_count == 0 and "wait_for" in step):
            raise CliCaptureError(f"Step {name} needs exactly one input, or only a wait_for marker")
        if "text" in step:
            value = step["text"]
            if not isinstance(value, str) or not value or len(value) > 256 or "\n" in value or "\r" in value:
                raise CliCaptureError(f"Step {name} has invalid text")
            if any(flag in value.lower() for flag in SECRET_FLAGS):
                raise CliCaptureError(f"Step {name} contains a secret-bearing flag")
        if "key" in step and (not isinstance(step["key"], str) or step["key"] not in ALLOWED_KEYS):
            raise CliCaptureError(f"Step {name} has unsupported key")
        if "repeat" in step:
            repeat = step["repeat"]
            if "key" not in step or not isinstance(repeat, int) or isinstance(repeat, bool) or not 1 <= repeat <= MAX_KEY_REPEAT:
                raise CliCaptureError(f"Step {name} has invalid key repeat")
        if "wheel" in step and step["wheel"] not in ("up", "down"):
            raise CliCaptureError(f"Step {name} has unsupported wheel direction")
        if "wait_for" in step and (not isinstance(step["wait_for"], str) or not 1 <= len(step["wait_for"]) <= 120):
            raise CliCaptureError(f"Step {name} has invalid wait_for marker")
        if "wait_for_absent" in step and ("wait_for" not in step or not isinstance(step["wait_for_absent"], str) or not 1 <= len(step["wait_for_absent"]) <= 120):
            raise CliCaptureError(f"Step {name} has invalid wait_for_absent marker")
        for field, maximum, default in (("wait_timeout_ms", MAX_STEP_WAIT_MS, 10_000), ("hold_ms", MAX_STEP_HOLD_MS, 0)):
            value = step.get(field, default)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
                raise CliCaptureError(f"Step {name} has invalid {field}")
    return steps


def input_step_ready(output: str, marker: str, absent_marker: str | None = None) -> bool:
    """Check loading-state absence only in the latest complete TUI frame.

    Historical output still contains earlier loading messages, and an unfinished
    synchronized paint must never count as a ready screen.
    """
    if absent_marker is not None:
        start = output.rfind("\x1b[?2026h")
        end = output.rfind("\x1b[?2026l")
        if start < 0 or end < start:
            return False
        output = output[start:end]
    plain = ANSI_ESCAPE_RE.sub("", output).replace("\r", "")
    return marker in plain and (absent_marker is None or absent_marker not in plain)


def drive_terminal_inputs(
    *, steps: list[dict[str, Any]], transcript_path: Path, display: str,
    terminal: subprocess.Popen[str], started_at: float, xdotool_binary: str | None = None,
    timeout_seconds: float = 120,
) -> list[dict[str, Any]]:
    """Send XTEST keys to the actual graphical terminal and record checkpoints."""
    xdotool = xdotool_binary or shutil.which("xdotool")
    if not xdotool:
        raise CliCaptureError("Interactive capture requires xdotool")
    process_env = {**os.environ, "DISPLAY": display}
    capture_deadline = started_at + timeout_seconds
    deadline = min(time.monotonic() + 10, capture_deadline)
    window_id = ""
    while time.monotonic() < deadline and terminal.poll() is None:
        found = subprocess.run([xdotool, "search", "--onlyvisible", "--name", "^OpenMates CLI$"], env=process_env, capture_output=True, text=True, check=False, timeout=3)
        window_id = found.stdout.strip().splitlines()[-1] if found.returncode == 0 and found.stdout.strip() else ""
        # A titled X window can exist before Zutty maps it or starts its PTY.
        # Its first rendered frame may predate focus, so the readiness marker
        # below deliberately scans the full transcript for step zero.
        if window_id and transcript_path.exists():
            break
        time.sleep(0.1)
    if not window_id or not transcript_path.exists():
        raise CliCaptureError("Graphical OpenMates CLI terminal did not map and start its PTY")
    subprocess.run([xdotool, "windowmove", "--sync", window_id, "0", "0"], env=process_env, capture_output=True, text=True, check=True, timeout=5)
    subprocess.run([xdotool, "windowsize", "--sync", window_id, str(TERMINAL_WIDTH), str(TERMINAL_HEIGHT)], env=process_env, capture_output=True, text=True, check=True, timeout=5)
    focus_error = ""
    while time.monotonic() < deadline and terminal.poll() is None:
        focused = subprocess.run([xdotool, "windowfocus", "--sync", window_id], env=process_env, capture_output=True, text=True, check=False, timeout=3)
        if focused.returncode == 0:
            break
        focus_error = focused.stderr.strip()
        time.sleep(0.1)
    else:
        raise CliCaptureError(f"Graphical OpenMates CLI terminal could not receive keyboard focus: {focus_error[-300:]}")
    checkpoints: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if terminal.poll() is not None:
            raise CliCaptureError(f"Terminal exited before input step {step['name']}")
        if time.monotonic() >= capture_deadline:
            raise CliCaptureError(f"Terminal input budget expired before step {step['name']}")
        # The first readiness marker may have been rendered while the X window
        # was discovered and focused. Inputs and later markers must still see
        # only output produced after their step begins.
        initial_readiness = index == 0 and "wait_for" in step and all(field not in step for field in ("text", "key", "wheel"))
        start_offset = 0 if initial_readiness else (transcript_path.stat().st_size if transcript_path.exists() else 0)
        if "text" in step:
            command = [xdotool, "type", "--clearmodifiers", "--delay", "15", "--", step["text"]]
        elif "key" in step:
            command = [xdotool, "key", "--clearmodifiers"]
            if "repeat" in step:
                command.extend(["--repeat", str(step["repeat"]), "--delay", str(KEY_REPEAT_DELAY_MS)])
            command.append(step["key"])
        elif "wheel" in step:
            # A real XTEST wheel event over the left sidebar is routed by the
            # terminal to the CLI's scroll handler. Keep the pointer inside the
            # sidebar rather than relying on the current pointer position.
            move = subprocess.run([xdotool, "mousemove", "--window", window_id, "80", "360"],
                                  env=process_env, capture_output=True, text=True, check=False, timeout=8)
            if move.returncode != 0:
                raise CliCaptureError(f"Terminal wheel pointer failed at {step['name']}: {move.stderr[-500:]}")
            command = [xdotool, "click", "4" if step["wheel"] == "up" else "5"]
        else:
            command = None
        if command:
            sent = subprocess.run(command, env=process_env, capture_output=True, text=True, check=False, timeout=8)
            if sent.returncode != 0:
                raise CliCaptureError(f"Terminal input {step['name']} failed: {sent.stderr[-500:]}")
        marker = step.get("wait_for")
        absent_marker = step.get("wait_for_absent")
        if marker:
            stop_at = min(capture_deadline, time.monotonic() + step.get("wait_timeout_ms", 10_000) / 1000)
            while time.monotonic() < stop_at:
                if terminal.poll() is not None:
                    raise CliCaptureError(f"Terminal exited while waiting for {step['name']}")
                if transcript_path.exists():
                    with transcript_path.open("rb") as handle:
                        handle.seek(start_offset)
                        output = handle.read().decode("utf-8", errors="replace")
                    if input_step_ready(output, marker, absent_marker):
                        break
                time.sleep(0.05)
            else:
                raise CliCaptureError(f"Terminal output did not reach checkpoint {step['name']}: {marker}")
        time.sleep(step.get("hold_ms", 0) / 1000)
        checkpoints.append({
            "name": step["name"],
            "at_ms": round((time.monotonic() - started_at) * 1000),
            "transcript_offset": transcript_path.stat().st_size if transcript_path.exists() else 0,
            "marker": marker,
            **({"absent_marker": absent_marker} if absent_marker is not None else {}),
        })
    return checkpoints


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _is_openmates_cli(argv: list[str]) -> bool:
    if not argv:
        return False
    if Path(argv[0]).name == "openmates":
        return True
    if len(argv) < 2 or Path(argv[0]).name not in {"node", "nodejs"}:
        return False
    cli_path = Path(argv[1]).as_posix()
    return cli_path.endswith("/openmates-cli/dist/cli.js") or cli_path == "/workspace/cli/dist/cli.js"


def _validate_argv(argv: list[str]) -> None:
    if not _is_openmates_cli(argv):
        raise CliCaptureError("Real terminal proof capture requires the OpenMates CLI product command")
    if any(
        value in SECRET_FLAGS or any(value.startswith(f"{flag}=") for flag in SECRET_FLAGS)
        for value in argv
    ):
        raise CliCaptureError("OpenMates CLI proof argv must not contain secret-bearing flags")


def build_capture_plan(
    *,
    argv: list[str],
    output_dir: Path,
    display_number: int = 91,
    xvfb_binary: str | None = None,
    terminal_binary: str | None = None,
    ffmpeg_binary: str | None = None,
    interactive: bool = False,
) -> CapturePlan:
    _validate_argv(argv)
    xvfb = xvfb_binary or shutil.which("Xvfb")
    terminal = terminal_binary or (
        (shutil.which("zutty") or shutil.which("x-terminal-emulator")) if interactive
        else (shutil.which("x-terminal-emulator") or shutil.which("zutty"))
    )
    ffmpeg = ffmpeg_binary or shutil.which("ffmpeg")
    if not xvfb or not terminal or not ffmpeg:
        raise CliCaptureError("Real terminal capture requires Xvfb, a graphical terminal, and FFmpeg")

    output_dir = output_dir.resolve()
    transcript = output_dir / "transcript.txt"
    events = output_dir / "events.jsonl"
    display = f":{display_number}"
    display_command = shlex.join(argv)
    typed_prompt = shlex.quote("$ " + display_command)
    type_command = (
        "python3 -c 'import sys,time; "
        "[(sys.stdout.write(char),sys.stdout.flush(),time.sleep(0.03)) for char in sys.argv[1]]' "
        f"{typed_prompt}"
    )
    shell_command = display_command if interactive else (
        f"{type_command}; printf '\\n'; "
        f"{display_command}; status=$?; sleep {RESULT_HOLD_SECONDS}; exit $status"
    )
    script_argv = [
        "script", "-qef", "-O", str(transcript), "-T", str(events), "-c", shell_command,
    ]
    terminal_name = Path(terminal).name
    if terminal_name in {"zutty", "x-terminal-emulator"}:
        geometry = INTERACTIVE_TERMINAL_GEOMETRY if interactive else TERMINAL_GEOMETRY
        font_size = INTERACTIVE_TERMINAL_FONT_SIZE if interactive else TERMINAL_FONT_SIZE
        terminal_argv = [
            terminal,
            "-display", display,
            "-geometry", geometry,
            "-fontpath", "/usr/share/fonts/truetype/dejavu",
            "-font", "DejaVuSansMono",
            "-fontsize", font_size,
            "-border", "0",
            "-title", "OpenMates CLI",
            "-e", *script_argv,
        ]
    else:
        terminal_argv = [terminal, "-e", *script_argv]
    video = output_dir / "raw-terminal.mp4"
    return CapturePlan(
        width=TERMINAL_WIDTH,
        height=TERMINAL_HEIGHT,
        display=display,
        output_dir=output_dir,
        video_path=video,
        transcript_path=transcript,
        events_path=events,
        command_output_path=output_dir / "command-output.txt",
        manifest_path=output_dir / "manifest.json",
        xvfb_argv=[xvfb, display, "-screen", "0", f"{TERMINAL_WIDTH}x{TERMINAL_HEIGHT}x{DISPLAY_DEPTH}", "-nolisten", "tcp"],
        terminal_argv=terminal_argv,
        ffmpeg_argv=[
            ffmpeg, "-y", "-f", "x11grab", "-framerate", "30", "-video_size", f"{TERMINAL_WIDTH}x{TERMINAL_HEIGHT}",
            "-i", f"{display}.0", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(video),
        ],
    )


def build_capture_manifest(
    *,
    argv: list[str],
    video_path: Path,
    transcript_path: Path,
    events_path: Path,
    command_output_path: Path | None = None,
    exit_status: int,
    target_environment: str,
    classification: str,
    input_checkpoints: list[dict[str, Any]] | None = None,
    input_error: str | None = None,
    input_plan_path: Path | None = None,
) -> dict[str, Any]:
    required_paths = [video_path, transcript_path, events_path]
    if command_output_path is not None:
        required_paths.append(command_output_path)
    if input_plan_path is not None:
        required_paths.append(input_plan_path)
    for path in required_paths:
        if not path.is_file():
            raise CliCaptureError(f"Capture artifact is missing: {path}")
    manifest = {
        "schema_version": 1,
        "capture_kind": "real_terminal_screen",
        "reconstructed": False,
        "argv": argv,
        "exit_status": exit_status,
        "target_environment": target_environment,
        "classification": classification,
        "width": TERMINAL_WIDTH,
        "height": TERMINAL_HEIGHT,
        "video_path": str(video_path),
        "video_sha256": _sha256(video_path),
        "transcript_path": str(transcript_path),
        "transcript_sha256": _sha256(transcript_path),
        "events_path": str(events_path),
        "events_sha256": _sha256(events_path),
    }
    if command_output_path is not None:
        manifest["command_output_path"] = str(command_output_path)
        manifest["command_output_sha256"] = _sha256(command_output_path)
    if input_checkpoints is not None:
        manifest["input_checkpoints"] = input_checkpoints
    if input_plan_path is not None:
        manifest["input_plan_path"] = str(input_plan_path)
        manifest["input_plan_sha256"] = _sha256(input_plan_path)
    if input_error:
        manifest["input_error"] = input_error
    return manifest


def _response_media_run_type(classification: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "-", classification.replace("_", "-")).strip("-._")
    if not suffix or suffix == "cli-e2e":
        return "openmates-cli-e2e"
    return f"openmates-cli-e2e-{suffix}"[:80].rstrip("-._")


def publish_response_media(video_path: Path, *, classification: str, dry_run: bool = False) -> dict[str, Any]:
    command = [
        sys.executable,
        str(RESPONSE_MEDIA_SCRIPT),
        str(video_path),
        "--alt",
        "OpenMates CLI E2E recording",
        "--latest-run-type",
        _response_media_run_type(classification),
        "--output",
        "json",
    ]
    if dry_run:
        command.append("--dry-run")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise CliCaptureError(result.stderr.strip() or result.stdout.strip() or "Response-media upload failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CliCaptureError("Response-media upload returned invalid JSON") from exc
    snippets = payload.get("snippets") if isinstance(payload, dict) else None
    if not isinstance(snippets, dict) or not snippets.get("html"):
        raise CliCaptureError("Response-media upload returned no embeddable snippet")
    return payload


def extract_command_output(transcript_path: Path, *, displayed_command: str) -> str:
    """Return command output without script headers, prompt text, or ANSI codes."""
    normalized = ANSI_ESCAPE_RE.sub("", transcript_path.read_text(encoding="utf-8", errors="replace")).replace("\r", "")
    lines = normalized.splitlines()
    output: list[str] = []
    prompt = f"$ {displayed_command}"
    started = False
    for line in lines:
        if not started:
            if line.strip() == prompt:
                started = True
            continue
        if line.startswith("Script done on "):
            break
        output.append(line)
    return "\n".join(output).strip() + "\n"


def capture_cli_video(
    *,
    argv: list[str],
    output_dir: Path,
    target_environment: str,
    classification: str = "cli_e2e",
    display_number: int = 91,
    timeout_seconds: float = 120,
    env: dict[str, str] | None = None,
    input_plan: Path | None = None,
) -> dict[str, Any]:
    steps = load_input_plan(input_plan) if input_plan else None
    plan = build_capture_plan(argv=argv, output_dir=output_dir, display_number=display_number, interactive=steps is not None)
    plan.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    process_env = {**os.environ, **(env or {}), "DISPLAY": plan.display}
    xvfb = subprocess.Popen(plan.xvfb_argv, env=process_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    ffmpeg: subprocess.Popen[str] | None = None
    terminal: subprocess.Popen[str] | None = None
    checkpoints: list[dict[str, Any]] | None = None
    input_error: str | None = None
    try:
        time.sleep(0.4)
        if xvfb.poll() is not None:
            raise CliCaptureError(f"Xvfb exited before capture: {(xvfb.stderr.read() if xvfb.stderr else '').strip()}")
        subprocess.run(["xsetroot", "-display", plan.display, "-solid", "#111827"], env=process_env, check=False, capture_output=True)
        ffmpeg = subprocess.Popen(plan.ffmpeg_argv, env=process_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        started_at = time.monotonic()
        time.sleep(0.25)
        # CI's Xvfb display has no DRI render device. Zutty uses GLES to draw
        # the real terminal pixels, so choose Mesa's CPU renderer for the
        # interactive proof without changing ordinary one-shot captures.
        terminal_env = {**process_env, "LIBGL_ALWAYS_SOFTWARE": "true", "GALLIUM_DRIVER": "llvmpipe"} if steps is not None else process_env
        terminal = subprocess.Popen(plan.terminal_argv, env=terminal_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if steps is not None:
            try:
                checkpoints = drive_terminal_inputs(
                    steps=steps, transcript_path=plan.transcript_path, display=plan.display,
                    terminal=terminal, started_at=started_at,
                    timeout_seconds=timeout_seconds,
                )
            except (CliCaptureError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                input_error = str(exc)
                terminal.terminate()
        try:
            exit_status = terminal.wait(timeout=max(0.1, timeout_seconds - (time.monotonic() - started_at)))
        except subprocess.TimeoutExpired:
            terminal.terminate()
            try:
                terminal.wait(timeout=2)
            except subprocess.TimeoutExpired:
                terminal.kill()
                terminal.wait(timeout=2)
            # Finalize the recording even on timeout so the failing E2E remains
            # visually inspectable. 124 preserves the timeout verdict.
            exit_status = 124
        if input_error:
            exit_status = 125
        time.sleep(0.35)
        ffmpeg.send_signal(signal.SIGINT)
        ffmpeg.wait(timeout=10)
        if ffmpeg.returncode not in {0, 255} or not plan.video_path.is_file():
            raise CliCaptureError(f"FFmpeg terminal capture failed: {(ffmpeg.stderr.read() if ffmpeg.stderr else '')[-1000:]}")
        missing = [path for path in (plan.transcript_path, plan.events_path) if not path.is_file()]
        if missing:
            terminal_error = terminal.stderr.read() if terminal.stderr else ""
            raise CliCaptureError(
                f"Graphical terminal did not produce PTY evidence "
                f"(terminal exit {terminal.returncode}, input: {input_error or 'none'}): {terminal_error[-1000:]}"
            )
        plan.command_output_path.write_text(
            plan.transcript_path.read_text(encoding="utf-8", errors="replace") if steps is not None
            else extract_command_output(plan.transcript_path, displayed_command=shlex.join(argv)),
            encoding="utf-8",
        )
        plan.command_output_path.chmod(0o600)
        manifest = build_capture_manifest(
            argv=argv,
            video_path=plan.video_path,
            transcript_path=plan.transcript_path,
            events_path=plan.events_path,
            command_output_path=plan.command_output_path,
            exit_status=exit_status,
            target_environment=target_environment,
            classification=classification,
            input_checkpoints=checkpoints if steps is not None else None,
            input_error=input_error,
            input_plan_path=input_plan,
        )
        plan.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        plan.manifest_path.chmod(0o600)
        return manifest
    finally:
        for process in (ffmpeg, terminal, xvfb):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a real OpenMates CLI E2E terminal video")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-environment", required=True)
    parser.add_argument("--classification", default="cli_e2e")
    parser.add_argument("--display-number", type=int, default=91)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--input-plan", type=Path, help="Bounded JSON key and checkpoint plan for an interactive CLI TUI")
    parser.add_argument("--no-response-media", action="store_true", help="Do not upload the latest CLI E2E video for agent embedding")
    parser.add_argument("--response-media-dry-run", action="store_true", help="Validate response-media output without Docker/S3")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
    try:
        result = capture_cli_video(
            argv=argv,
            output_dir=args.output_dir,
            target_environment=args.target_environment,
            classification=args.classification,
            display_number=args.display_number,
            timeout_seconds=args.timeout_seconds,
            input_plan=args.input_plan,
        )
        if not args.no_response_media:
            try:
                result["response_media"] = publish_response_media(
                    Path(result["video_path"]),
                    classification=args.classification,
                    dry_run=args.response_media_dry_run,
                )
            except CliCaptureError as exc:
                result["response_media_error"] = str(exc)
    except CliCaptureError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 2
    print(json.dumps({"status": "passed" if result["exit_status"] == 0 else "failed", "manifest": result}))
    return int(result["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
