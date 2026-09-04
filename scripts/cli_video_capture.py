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
SECRET_FLAGS = {"--api-key", "--password", "--token", "--secret", "--otp", "--totp"}
TERMINAL_GEOMETRY = "160x48"
TERMINAL_FONT_SIZE = "14"
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-_][0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
RESPONSE_MEDIA_SCRIPT = Path(__file__).resolve().parent / "opencode_response_media.py"


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
) -> CapturePlan:
    _validate_argv(argv)
    xvfb = xvfb_binary or shutil.which("Xvfb")
    terminal = terminal_binary or shutil.which("x-terminal-emulator") or shutil.which("zutty")
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
    shell_command = (
        f"{type_command}; printf '\\n'; "
        f"{display_command}; status=$?; sleep {RESULT_HOLD_SECONDS}; exit $status"
    )
    script_argv = [
        "script", "-qef", "-O", str(transcript), "-T", str(events), "-c", shell_command,
    ]
    terminal_name = Path(terminal).name
    if terminal_name in {"zutty", "x-terminal-emulator"}:
        terminal_argv = [
            terminal,
            "-display", display,
            "-geometry", TERMINAL_GEOMETRY,
            "-fontpath", "/usr/share/fonts/truetype/dejavu",
            "-font", "DejaVuSansMono",
            "-fontsize", TERMINAL_FONT_SIZE,
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
) -> dict[str, Any]:
    required_paths = [video_path, transcript_path, events_path]
    if command_output_path is not None:
        required_paths.append(command_output_path)
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
        raise CliCaptureError(result.stderr.strip() or result.stdout.strip() or "OpenCode response-media upload failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CliCaptureError("OpenCode response-media upload returned invalid JSON") from exc
    snippets = payload.get("snippets") if isinstance(payload, dict) else None
    if not isinstance(snippets, dict) or not snippets.get("html"):
        raise CliCaptureError("OpenCode response-media upload returned no embeddable snippet")
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
) -> dict[str, Any]:
    plan = build_capture_plan(argv=argv, output_dir=output_dir, display_number=display_number)
    plan.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    process_env = {**os.environ, **(env or {}), "DISPLAY": plan.display}
    xvfb = subprocess.Popen(plan.xvfb_argv, env=process_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    ffmpeg: subprocess.Popen[str] | None = None
    terminal: subprocess.Popen[str] | None = None
    try:
        time.sleep(0.4)
        if xvfb.poll() is not None:
            raise CliCaptureError(f"Xvfb exited before capture: {(xvfb.stderr.read() if xvfb.stderr else '').strip()}")
        subprocess.run(["xsetroot", "-display", plan.display, "-solid", "#111827"], env=process_env, check=False, capture_output=True)
        ffmpeg = subprocess.Popen(plan.ffmpeg_argv, env=process_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        time.sleep(0.25)
        terminal = subprocess.Popen(plan.terminal_argv, env=process_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            exit_status = terminal.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            terminal.terminate()
            raise CliCaptureError(f"OpenMates CLI terminal capture timed out after {timeout_seconds:g} seconds") from exc
        time.sleep(0.35)
        ffmpeg.send_signal(signal.SIGINT)
        ffmpeg.wait(timeout=10)
        if ffmpeg.returncode not in {0, 255} or not plan.video_path.is_file():
            raise CliCaptureError(f"FFmpeg terminal capture failed: {(ffmpeg.stderr.read() if ffmpeg.stderr else '')[-1000:]}")
        missing = [path for path in (plan.transcript_path, plan.events_path) if not path.is_file()]
        if missing:
            terminal_error = terminal.stderr.read() if terminal.stderr else ""
            raise CliCaptureError(
                f"Graphical terminal did not produce PTY evidence (exit {exit_status}): {terminal_error[-1000:]}"
            )
        plan.command_output_path.write_text(
            extract_command_output(plan.transcript_path, displayed_command=shlex.join(argv)),
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
    parser.add_argument("--no-response-media", action="store_true", help="Do not upload the latest CLI E2E video for OpenCode embedding")
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
