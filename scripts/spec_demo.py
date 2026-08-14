#!/usr/bin/env python3
"""Build privacy-safe implementation demonstration evidence.

This local-only tool captures explicit CLI argv through a pseudo-terminal,
renders terminal/caption media with FFmpeg, and prepares bounded frame evidence.
It never sends full videos to models and keeps product APIs out of this workflow.
Architecture: docs/specs/narrated-spec-demonstration-videos/spec.yml.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from typing import Any, Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
TERMINAL_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
TERMINAL_VIDEO_SIZE = "1280x720"
TERMINAL_FONT_SIZE = 28
TERMINAL_COLUMNS = 72
TERMINAL_VISIBLE_LINES = 14
TERMINAL_TYPING_INTERVAL_SECONDS = 0.04
TERMINAL_MAX_OUTPUT_GAP_SECONDS = 1.2
TERMINAL_TUTORIAL_MIN_SECONDS = 15.0
TERMINAL_RESULT_HOLD_SECONDS = 8.0
CLI_TEST_ACCOUNT_HARNESS = ("node", "scripts/openmates_cli_test_account.mjs")
OPENMATES_CLI_DIST_PATH = "frontend/packages/openmates-cli/dist/cli.js"
TEAMS_CLI_PROOF_HELPER_PATH = "scripts/teams_cli_proof.mjs"
PLAYWRIGHT_CAPTION_MIN_FONT_SIZE = 8
PLAYWRIGHT_CAPTION_MAX_FONT_SIZE = 20
SECRET_SCANNER_CLI = REPO_ROOT / "frontend/packages/secret-scanner/src/cli.ts"
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-_][0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
SHOWINFO_PTS_RE = re.compile(r"\bpts_time:([0-9]+(?:\.[0-9]+)?)")
SECRET_ENV_NAME_RE = re.compile(r"(?:_KEY|_SECRET|_TOKEN|_PASSWORD|_PASSWD|_CREDENTIAL)$|(?:^|_)WEBHOOK(?:_|$)|^(?:API_KEY|AUTH_TOKEN|SECRET|DATABASE_URL|REDIS_URL|MONGODB_URI|AMQP_URL)$")
PLAYWRIGHT_SOURCE_FIELDS = {
    "command_or_spec",
    "target",
    "deployment_reference",
    "run_id",
    "subject_commit",
    "artifact_path",
    "artifact_sha256",
    "test_account_provenance",
}
MAX_REVIEW_INTERVAL_SECONDS = 3.0
MAX_ADDITIONAL_FRAME_REQUESTS = 10
END_FRAME_OFFSET_SECONDS = 0.1
MEDIA_TIMESTAMP_DECIMALS = 3
DEFAULT_NARRATION_PROVIDER = "elevenlabs"
DEFAULT_NARRATION_MODEL = "eleven_flash_v2_5"
DEFAULT_NARRATION_VOICE = "warm_neutral"
REVIEW_VERDICTS = {"supported", "contradicted", "not_visible", "ambiguous", "wrong_time"}
DEFECT_RETURN_STAGES = {
    "implementation": "implementation",
    "test_coverage": "tests",
    "recording": "capture",
    "narration": "captions",
    "composition": "render",
    "environment": "environment",
}
FULL_VIDEO_REVIEW_KEYS = {"video", "video_path", "video_bytes", "video_base64", "video_attachment"}
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVIEW_REQUEST_FIELDS = {"spec_id", "subject_commit", "captions", "expected_proof", "frames", "video_metadata", "narration_audio"}
REVIEW_CAPTION_FIELDS = {"id", "narration_id", "text", "start", "end", "claim_ids"}
REVIEW_PROOF_FIELDS = {"claim_id", "text", "acceptance_criteria", "evidence_intervals"}
REVIEW_FRAME_FIELDS = {"timestamp", "timestamp_seconds", "path", "sha256"}
REVIEW_METADATA_REQUIRED_FIELDS = {"duration_seconds", "sha256", "width", "height"}
REVIEW_METADATA_OPTIONAL_FIELDS = {
    "black_bar_scan_status",
    "demo_audio_mixed",
    "device_profile",
    "hold_last_frame_seconds",
    "playback_rate",
    "target_height",
    "target_width",
}
REVIEW_METADATA_FIELDS = REVIEW_METADATA_REQUIRED_FIELDS | REVIEW_METADATA_OPTIONAL_FIELDS
NARRATION_AUDIO_FIELDS = {"status", "provider", "model", "voice", "path", "sha256", "mime_type", "duration_seconds", "reused_from"}
DEVICE_PROFILES = {
    "cli-terminal": {"width": 1280, "height": 720, "surface": "cli", "label": "CLI terminal"},
    "web-phone": {"width": 390, "height": 844, "surface": "web", "label": "phone web"},
    "web-laptop": {"width": 1440, "height": 900, "surface": "web", "label": "laptop web"},
    "apple-iphone-portrait": {"width": 393, "height": 852, "surface": "apple", "label": "iPhone portrait"},
    "apple-ipad-landscape": {"width": 1366, "height": 1024, "surface": "apple", "label": "iPad landscape"},
}
POST_EXIT_PTY_DRAIN_SECONDS = 0.5
DEVICE_PROFILE_ALIASES = {
    "cli": "cli-terminal",
    "terminal": "cli-terminal",
    "mobile": "web-phone",
    "phone": "web-phone",
    "web-mobile": "web-phone",
    "laptop": "web-laptop",
    "web-desktop": "web-laptop",
    "desktop": "web-laptop",
    "iphone": "apple-iphone-portrait",
    "iphone-portrait": "apple-iphone-portrait",
    "ipad": "apple-ipad-landscape",
    "ipad-landscape": "apple-ipad-landscape",
}
DEVICE_ASPECT_RATIO_TOLERANCE = 0.01
CAPTURE_READY_TRIM_LEAD_SECONDS = 0.15
BLACK_BAR_DARK_LUMA_MAX = 16
BLACK_BAR_DARK_PIXEL_RATIO = 0.98
BLACK_BAR_CENTER_DARK_PIXEL_RATIO = 0.80
BLACK_BAR_MIN_PIXELS = 8
BLACK_BAR_MIN_FRACTION = 0.025
BLACK_BAR_MAX_EDGE_FRACTION = 0.25
MIN_TUTORIAL_NARRATION_SENTENCES = 3
MIN_TUTORIAL_NARRATION_WORDS = 24
MIN_PROOF_PLAYBACK_RATE = 0.75
MAX_PROOF_OUTPUT_SECONDS = 35.0
GENERIC_NARRATION_RE = re.compile(
    r"\b(?:it works|works correctly|feature works|successfully demonstrates|as you can see|proof video|demo video)\b",
    re.IGNORECASE,
)
VISIBLE_NARRATION_RE = re.compile(
    r"\b(?:screen|page|card|button|menu|field|terminal|command|result|message|audio|play|player|caption|visible|shows?|opens?|lists?|renders?)\b",
    re.IGNORECASE,
)


class DemonstrationError(RuntimeError):
    """Raised when demonstration evidence cannot be produced truthfully."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _write_private(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _normalise_terminal_text(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def select_playwright_source(
    candidates: Iterable[dict[str, Any]],
    *,
    run_id: str,
    subject_commit: str,
) -> dict[str, Any]:
    """Select one exact deployed Playwright recording and attach its hash."""
    for candidate in candidates:
        if candidate.get("run_id") != run_id or candidate.get("subject_commit") != subject_commit:
            continue
        missing = sorted(field for field in PLAYWRIGHT_SOURCE_FIELDS if not candidate.get(field))
        if missing:
            raise DemonstrationError(f"Playwright source missing {', '.join(missing)}")
        artifact_path = Path(str(candidate["artifact_path"]))
        if not artifact_path.is_file():
            raise DemonstrationError(f"Playwright artifact does not exist: {artifact_path}")
        actual_hash = sha256_file(artifact_path)
        if candidate.get("artifact_sha256") != actual_hash:
            raise DemonstrationError("Playwright artifact hash no longer matches deployed proof-source attestation")
        return {**candidate, "artifact_hash": actual_hash}
    raise DemonstrationError(f"No Playwright recording matches run {run_id} and commit {subject_commit}")


def verify_playwright_render_input(selected: dict[str, Any], source_video: Path) -> None:
    artifact_path = Path(str(selected.get("artifact_path", "")))
    if artifact_path.resolve() != source_video.resolve() or selected.get("artifact_hash") != sha256_file(source_video):
        raise DemonstrationError("Render input does not match the selected Playwright artifact")


def capture_pty(
    argv: list[str],
    *,
    run_id: str,
    target_environment: str,
    output_dir: Path,
    test_account_provenance: str,
    timeout_seconds: float = 120.0,
    max_output_bytes: int = 5 * 1024 * 1024,
) -> dict[str, Any]:
    """Run explicit argv in a PTY and retain only normalized terminal events."""
    if not argv or not all(isinstance(value, str) and value for value in argv):
        raise DemonstrationError("PTY capture requires a non-empty explicit argv list")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    master_fd, slave_fd = pty.openpty()
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave_fd)
    events: list[dict[str, Any]] = [{"time_seconds": 0.0, "stream": "input", "argv": list(argv)}]
    reached_eof = False
    output_bytes = 0
    failure: DemonstrationError | None = None
    post_exit_started: float | None = None
    try:
        while True:
            if time.monotonic() - started > timeout_seconds:
                failure = DemonstrationError(f"PTY command timed out after {timeout_seconds:g} seconds")
                break
            ready, _, _ = select.select([master_fd], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        chunk = b""
                        reached_eof = True
                    else:
                        raise
                if chunk:
                    output_bytes += len(chunk)
                    if output_bytes > max_output_bytes:
                        failure = DemonstrationError(f"PTY output limit exceeded {max_output_bytes} bytes")
                        break
                    events.append(
                        {
                            "time_seconds": round(time.monotonic() - started, 6),
                            "stream": "output",
                            "text": _normalise_terminal_text(chunk.decode("utf-8", errors="replace")),
                        }
                    )
            if process.poll() is not None:
                if reached_eof:
                    break
                if post_exit_started is None:
                    post_exit_started = time.monotonic()
                if time.monotonic() - post_exit_started >= POST_EXIT_PTY_DRAIN_SECONDS:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    break
            else:
                post_exit_started = None
    finally:
        os.close(master_fd)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    if failure:
        raise failure
    exit_status = process.wait()
    transcript = f"$ {shlex.join(argv)}\n" + "".join(
        str(event.get("text", "")) for event in events if event.get("stream") == "output"
    )
    if not transcript.endswith("\n"):
        transcript += "\n"
    transcript += (
        f"[exit_status={exit_status}]\n"
        f"[run_id={run_id}]\n"
        f"[target_environment={target_environment}]\n"
        f"[test_account_provenance={test_account_provenance}]\n"
    )
    event_text = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
    transcript_path = output_dir / "transcript.txt"
    events_path = output_dir / "events.jsonl"
    _write_private(transcript_path, transcript)
    _write_private(events_path, event_text)
    return {
        "argv": argv,
        "target_environment": target_environment,
        "run_id": run_id,
        "exit_status": exit_status,
        "transcript_hash": sha256_file(transcript_path),
        "event_hash": sha256_file(events_path),
        "artifact_hash": sha256_file(events_path),
        "test_account_provenance": test_account_provenance,
        "duration_seconds": round(time.monotonic() - started, 6),
    }


def user_facing_cli_argv(argv: list[str]) -> list[str]:
    """Return the command a CLI user should see for test-account harness runs."""
    if len(argv) >= 2 and Path(argv[0]).name == "node":
        script_path = Path(argv[1]).as_posix().lstrip("./")
        if script_path == TEAMS_CLI_PROOF_HELPER_PATH or script_path.endswith(f"/{TEAMS_CLI_PROOF_HELPER_PATH}"):
            slug = ""
            name = ""
            for index, value in enumerate(argv[2:]):
                if value == "--slug" and index + 3 < len(argv):
                    slug = argv[index + 3]
                if value == "--name" and index + 3 < len(argv):
                    name = argv[index + 3]
            visible = ["openmates", "teams", "create"]
            if name:
                visible.extend(["--name", name])
            if slug:
                visible.extend(["--slug", slug])
            visible.append("--switch")
            return visible
    if argv[: len(CLI_TEST_ACCOUNT_HARNESS)] == list(CLI_TEST_ACCOUNT_HARNESS):
        return ["openmates", *argv[len(CLI_TEST_ACCOUNT_HARNESS) :]]
    if len(argv) >= 2 and Path(argv[0]).name == "node":
        script_path = Path(argv[1]).as_posix().lstrip("./")
        if script_path in {"dist/cli.js", OPENMATES_CLI_DIST_PATH} or script_path.endswith(f"/{OPENMATES_CLI_DIST_PATH}"):
            return ["openmates", *argv[2:]]
    return list(argv)


def mark_reconstructed(source: dict[str, Any], *, displayed_transcript_hash: str) -> dict[str, Any]:
    if displayed_transcript_hash != source.get("transcript_hash"):
        raise DemonstrationError("Reconstructed terminal transcript hash does not match captured transcript hash")
    return {
        **source,
        "reconstructed": True,
        "visible_label": "Reconstructed from exact sanitized terminal transcript",
    }


def _ffmpeg_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _playwright_caption_force_style(metadata: dict[str, Any]) -> str:
    """Keep burned-in web proof captions readable without covering mobile controls."""
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    font_size = max(
        PLAYWRIGHT_CAPTION_MIN_FONT_SIZE,
        min(PLAYWRIGHT_CAPTION_MAX_FONT_SIZE, round(width / 72)),
    )
    margin_v = max(12, min(24, round(height * 0.018)))
    outline = 1 if font_size <= PLAYWRIGHT_CAPTION_MIN_FONT_SIZE else 2
    return (
        "FontName=DejaVu Sans,"
        f"FontSize={font_size},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline={outline},Shadow=0,Alignment=2,MarginV={margin_v}"
    )


def resolve_device_profile(name: str | None) -> dict[str, Any] | None:
    if name is None or not str(name).strip():
        return None
    key = str(name).strip().lower()
    canonical = DEVICE_PROFILE_ALIASES.get(key, key)
    profile = DEVICE_PROFILES.get(canonical)
    if profile is None:
        supported = ", ".join(sorted(DEVICE_PROFILES))
        raise DemonstrationError(f"Unsupported proof-video device profile {name!r}; use one of: {supported}")
    return {"id": canonical, **profile}


def assert_device_profile_dimensions(metadata: dict[str, Any], profile: dict[str, Any] | None) -> None:
    if profile is None:
        return
    width = int(profile["width"])
    height = int(profile["height"])
    if metadata.get("width") != width or metadata.get("height") != height:
        actual = f"{metadata.get('width')}x{metadata.get('height')}"
        expected = f"{width}x{height}"
        label = str(profile.get("label") or profile["id"])
        raise DemonstrationError(
            f"{label} proof video must be {expected}, got {actual}. "
            "Do not letterbox, pillarbox, or wrap device recordings in a generic landscape canvas."
        )
    expected_ratio = width / height
    actual_ratio = int(metadata["width"]) / int(metadata["height"])
    if abs(actual_ratio - expected_ratio) > DEVICE_ASPECT_RATIO_TOLERANCE:
        raise DemonstrationError(f"Proof-video aspect ratio does not match device profile {profile['id']}")


def _black_bar_probe_times(duration_seconds: float) -> list[float]:
    if duration_seconds <= 0:
        raise DemonstrationError("Video duration must be positive before black-bar scanning")
    first_probe = min(duration_seconds - END_FRAME_OFFSET_SECONDS, max(0.25, duration_seconds * 0.1))
    candidates = {first_probe, min(duration_seconds - END_FRAME_OFFSET_SECONDS, duration_seconds * 0.5)}
    if duration_seconds > 2.0:
        candidates.add(min(duration_seconds - END_FRAME_OFFSET_SECONDS, duration_seconds - 1.0))
    return sorted(max(0.0, round(value, 3)) for value in candidates)


def _crop_dark_ratio(frame_path: Path, *, crop: str) -> float:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(frame_path),
            "-vf",
            f"crop={crop},format=gray",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise DemonstrationError(f"FFmpeg black-bar edge scan failed: {stderr.strip()[-500:]}")
    if not result.stdout:
        raise DemonstrationError("FFmpeg black-bar edge scan returned no pixels")
    dark_pixels = sum(1 for value in result.stdout if value <= BLACK_BAR_DARK_LUMA_MAX)
    return dark_pixels / len(result.stdout)


def _edge_dark_ratio(frame_path: Path, *, edge: str, edge_pixels: int) -> float:
    crop = {
        "top": f"iw:{edge_pixels}:0:0",
        "bottom": f"iw:{edge_pixels}:0:ih-{edge_pixels}",
        "left": f"{edge_pixels}:ih:0:0",
        "right": f"{edge_pixels}:ih:iw-{edge_pixels}:0",
    }[edge]
    return _crop_dark_ratio(frame_path, crop=crop)


def _center_dark_ratio(frame_path: Path) -> float:
    return _crop_dark_ratio(frame_path, crop="iw/2:ih/2:iw/4:ih/4")


def assert_no_letterbox_or_pillarbox(video_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    width = int(metadata["width"])
    height = int(metadata["height"])
    edge_pixels = max(
        BLACK_BAR_MIN_PIXELS,
        min(int(min(width, height) * BLACK_BAR_MIN_FRACTION), int(min(width, height) * BLACK_BAR_MAX_EDGE_FRACTION)),
    )
    scan_dir = video_path.parent / ".black-bar-scan"
    scan_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    scan_dir.chmod(0o700)
    offenders: list[str] = []
    try:
        for index, timestamp in enumerate(_black_bar_probe_times(float(metadata["duration_seconds"]))):
            frame_path = scan_dir / f"probe-{index:02d}.png"
            extract_frame(video_path, timestamp_seconds=timestamp, output_path=frame_path)
            ratios = {
                edge: _edge_dark_ratio(frame_path, edge=edge, edge_pixels=edge_pixels)
                for edge in ("top", "bottom", "left", "right")
            }
            center_ratio = _center_dark_ratio(frame_path)
            if (
                ratios["top"] >= BLACK_BAR_DARK_PIXEL_RATIO
                and ratios["bottom"] >= BLACK_BAR_DARK_PIXEL_RATIO
                and center_ratio < BLACK_BAR_CENTER_DARK_PIXEL_RATIO
            ):
                offenders.append(f"letterbox@{timestamp:g}s")
            if (
                ratios["left"] >= BLACK_BAR_DARK_PIXEL_RATIO
                and ratios["right"] >= BLACK_BAR_DARK_PIXEL_RATIO
                and center_ratio < BLACK_BAR_CENTER_DARK_PIXEL_RATIO
            ):
                offenders.append(f"pillarbox@{timestamp:g}s")
    finally:
        shutil.rmtree(scan_dir, ignore_errors=True)
    if offenders:
        raise DemonstrationError(
            "Proof video appears letterboxed or pillarboxed; black edge detected at "
            + ", ".join(offenders[:6])
        )
    return {
        "status": "passed",
        "edge_pixels": edge_pixels,
        "probes": len(_black_bar_probe_times(float(metadata["duration_seconds"]))),
    }


def build_cli_terminal_timeline(*, argv: list[str], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build visible typing and output states with bounded network waits."""
    command = f"$ {shlex.join(argv)}"
    visible = command
    typing_completed_at = 0.0
    states: list[dict[str, Any]] = [{"start": 0.0, "text": visible}]
    first_output_at: float | None = None
    output_cursor = typing_completed_at
    previous_event_time: float | None = None
    for event in events:
        if event.get("stream") != "output":
            continue
        event_time = max(0.0, float(event.get("time_seconds", 0.0)))
        if first_output_at is None and not visible.endswith("\n"):
            visible += "\n"
        visible += str(event.get("text", ""))
        if previous_event_time is None:
            output_cursor += min(event_time, TERMINAL_MAX_OUTPUT_GAP_SECONDS)
        else:
            output_cursor += min(max(0.0, event_time - previous_event_time), TERMINAL_MAX_OUTPUT_GAP_SECONDS)
        previous_event_time = event_time
        shifted_time = output_cursor
        first_output_at = shifted_time if first_output_at is None else first_output_at
        states.append({"start": shifted_time, "text": visible})
    last_change = float(states[-1]["start"])
    duration = max(TERMINAL_TUTORIAL_MIN_SECONDS, last_change + TERMINAL_RESULT_HOLD_SECONDS)
    for index, state in enumerate(states):
        state["end"] = float(states[index + 1]["start"]) if index + 1 < len(states) else duration
    return {
        "states": states,
        "typing_completed_at": typing_completed_at,
        "first_output_at": first_output_at,
        "duration_seconds": duration,
    }


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _terminal_ass_text(text: str) -> str:
    wrapped: list[str] = []
    for line in text.splitlines():
        wrapped.extend(textwrap.wrap(line, width=TERMINAL_COLUMNS, replace_whitespace=False) or [""])
    escaped = "\n".join(wrapped[-TERMINAL_VISIBLE_LINES:]).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return escaped.replace("\n", r"\N")


def _write_terminal_timeline(path: Path, timeline: dict[str, Any]) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Terminal,DejaVu Sans Mono,{TERMINAL_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,32,32,32,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = "".join(
        f"Dialogue: 0,{_ass_timestamp(float(state['start']))},{_ass_timestamp(float(state['end']))},Terminal,,0,0,0,,{_terminal_ass_text(str(state['text']))}\n"
        for state in timeline["states"]
        if float(state["end"]) > float(state["start"])
    )
    _write_private(path, header + dialogues)


def render_terminal_video(timeline: dict[str, Any], captions_path: Path, audio_path: Path | None, output_path: Path) -> None:
    """Render a readable timed terminal tutorial with canonical captions."""
    for path in (captions_path, TERMINAL_FONT, *((audio_path,) if audio_path else ())):
        if not path.is_file():
            raise DemonstrationError(f"Required render input does not exist: {path}")
    duration_seconds = float(timeline.get("duration_seconds", 0))
    if duration_seconds <= 0:
        raise DemonstrationError("Video duration must be positive")
    if duration_seconds > MAX_PROOF_OUTPUT_SECONDS:
        raise DemonstrationError("Proof-video output must not exceed 35 seconds")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timeline_path = output_path.with_suffix(".terminal.ass")
    _write_terminal_timeline(timeline_path, timeline)
    terminal = _ffmpeg_filter_path(timeline_path)
    captions = _ffmpeg_filter_path(captions_path)
    video_filter = (
        f"subtitles='{terminal}',"
        f"subtitles='{captions}':force_style='FontName=DejaVu Sans,FontSize=22,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=36'"
    )
    audio_args = ["-i", str(audio_path)] if audio_path else []
    audio_output = ["-af", "apad", "-c:a", "aac", "-b:a", "128k"] if audio_path else ["-an"]
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=#111827:s={TERMINAL_VIDEO_SIZE}:r=30",
            *audio_args,
            "-t",
            str(duration_seconds),
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            *audio_output,
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DemonstrationError(f"FFmpeg terminal render failed: {result.stderr.strip()[-1000:]}")
    timeline_path.unlink(missing_ok=True)


def render_captioned_video(
    source_path: Path,
    captions_path: Path,
    audio_path: Path | None,
    output_path: Path,
    *,
    playback_rate: float = 1.0,
    hold_last_frame_seconds: float = 0.0,
    demo_audio_path: Path | None = None,
) -> None:
    """Burn canonical captions into a copy without mutating the raw recording."""
    optional_paths = (demo_audio_path,) if demo_audio_path else ()
    for path in (source_path, captions_path, *((audio_path,) if audio_path else ()), *optional_paths):
        if not path.is_file():
            raise DemonstrationError(f"Required render input does not exist: {path}")
    if source_path.resolve() == output_path.resolve():
        raise DemonstrationError("Caption output must not replace the raw recording")
    if not MIN_PROOF_PLAYBACK_RATE <= playback_rate <= 4.0:
        raise DemonstrationError("Playback rate must be between 0.75 and 4.0")
    if hold_last_frame_seconds < 0 or hold_last_frame_seconds > 30:
        raise DemonstrationError("Hold-last-frame duration must be between 0 and 30 seconds")
    if demo_audio_path is not None and audio_path is None:
        raise DemonstrationError("Product audio requires explicit narration audio with retained provenance")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    captions = _ffmpeg_filter_path(captions_path)
    source_duration = media_duration_seconds(source_path)
    source_metadata = video_metadata(source_path)
    output_duration = round((source_duration / playback_rate) + hold_last_frame_seconds, 3)
    if output_duration > MAX_PROOF_OUTPUT_SECONDS:
        raise DemonstrationError("Proof-video output must not exceed 35 seconds")
    video_filters = [f"setpts=PTS/{playback_rate:g}"]
    if hold_last_frame_seconds:
        video_filters.append(f"tpad=stop_mode=clone:stop_duration={hold_last_frame_seconds:g}")
    video_filters.append(f"subtitles='{captions}':force_style='{_playwright_caption_force_style(source_metadata)}'")
    audio_inputs: list[str] = []
    input_args = ["-i", str(source_path)]
    audio_map: list[str] = []
    if audio_path is not None:
        input_args.extend(["-i", str(audio_path)])
        audio_inputs.append(f"[1:a:0]volume=1.0,apad,atrim=0:{output_duration:g}[narr]")
        audio_map = ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    if demo_audio_path is not None:
        demo_index = 2 if audio_path is not None else 1
        input_args.extend(["-stream_loop", "-1", "-i", str(demo_audio_path)])
        audio_inputs.append(f"[{demo_index}:a:0]volume=0.30,atrim=0:{output_duration:g}[demo]")
        if audio_path is not None:
            audio_inputs.append(
                "[narr][demo]amix=inputs=2:duration=longest:dropout_transition=0,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
            )
        else:
            audio_inputs.append("[demo]aformat=sample_fmts=fltp:channel_layouts=stereo[aout]")
            audio_map = ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    elif audio_path is not None:
        audio_inputs.append("[narr]aformat=sample_fmts=fltp:channel_layouts=stereo[aout]")
    filter_complex = ";".join([f"[0:v:0]{','.join(video_filters)}[vout]", *audio_inputs])
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            *audio_map,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            *([] if audio_map else ["-an"]),
            "-t",
            str(output_duration),
            "-map_metadata",
            "-1",
            "-map_metadata:s",
            "-1",
            "-map_chapters",
            "-1",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DemonstrationError(f"FFmpeg caption render failed: {result.stderr.strip()[-1000:]}")


def redact_text_with_canonical_scanner(text: str) -> dict[str, Any]:
    """Return typed-placeholder text without exposing matched values."""
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(SECRET_SCANNER_CLI)],
        input=json.dumps({"text": text, "knownSecrets": _known_secret_values(), "redact": True}),
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise DemonstrationError(f"Canonical secret redaction failed: {result.stderr.strip()[-500:]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DemonstrationError("Canonical secret redaction returned invalid JSON") from exc
    redacted = payload.get("redacted")
    types = payload.get("types")
    count = payload.get("count")
    if (
        not isinstance(redacted, str)
        or not isinstance(types, list)
        or not all(isinstance(value, str) for value in types)
        or isinstance(count, bool)
        or not isinstance(count, int)
    ):
        raise DemonstrationError("Canonical secret redaction returned an invalid payload")
    return {
        "text": redacted,
        "types": types,
        "count": count,
    }


def anonymize_cli_capture(run_dir: Path, capture: dict[str, Any]) -> dict[str, Any]:
    """Replace sensitive values with conspicuous typed placeholders before rendering."""
    transcript_path = run_dir / "transcript.txt"
    transcript = redact_text_with_canonical_scanner(transcript_path.read_text(encoding="utf-8"))
    _write_private(transcript_path, transcript["text"])
    redacted_argv = [redact_text_with_canonical_scanner(str(value))["text"] for value in capture.get("argv", [])]
    return {
        **capture,
        "argv": redacted_argv,
        "transcript_hash": sha256_file(transcript_path),
        "anonymization": {
            "applied": transcript["count"] > 0,
            "finding_count": transcript["count"],
            "finding_types": transcript["types"],
            "placeholder_style": "typed_and_numbered",
        },
    }


def _known_secret_values() -> list[dict[str, str]]:
    values: dict[str, str] = {}
    for name, value in os.environ.items():
        if value and SECRET_ENV_NAME_RE.search(name):
            values[name] = value
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, _, value = stripped.partition("=")
            name = name.strip()
            value = value.strip().strip("'\"")
            if value and SECRET_ENV_NAME_RE.search(name):
                values.setdefault(name, value)
    return [{"name": name, "value": value} for name, value in values.items()]


def build_artifact_manifest(*, raw: Path, derived: Path, subject_commit: str) -> dict[str, Any]:
    if raw.resolve() == derived.resolve():
        raise DemonstrationError("Raw and derived demonstration artifacts must be distinct")
    return {
        "subject_commit": subject_commit,
        "raw": {"kind": "raw", "path": str(raw), "hash": sha256_file(raw)},
        "derived": {"kind": "derived", "path": str(derived), "hash": sha256_file(derived)},
    }


def video_metadata(video_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:format_tags:stream=codec_type,width,height,codec_name:stream_tags",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DemonstrationError(f"ffprobe failed: {result.stderr.strip()[-500:]}")
    try:
        payload = json.loads(result.stdout)
        stream = next(item for item in payload["streams"] if item.get("width") and item.get("height"))
        audio_stream = next((item for item in payload["streams"] if item.get("codec_type") == "audio"), None)
        duration = float(payload["format"]["duration"])
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DemonstrationError("ffprobe did not return complete video metadata") from exc
    tags = {
        str(key).lower(): str(value)
        for key, value in (payload.get("format", {}).get("tags") or {}).items()
    }
    for item in payload.get("streams", []):
        for key, value in (item.get("tags") or {}).items():
            tags.setdefault(str(key).lower(), str(value))
    return {
        "duration_seconds": round(duration, 3),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "codec": str(stream.get("codec_name") or "unknown"),
        "has_audio": audio_stream is not None,
        "audio_codec": str(audio_stream.get("codec_name") or "unknown") if audio_stream else "",
        "sha256": sha256_file(video_path),
        "tags": tags,
    }


def media_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DemonstrationError(f"ffprobe failed: {result.stderr.strip()[-500:]}")
    try:
        return round(float(json.loads(result.stdout)["format"]["duration"]), 3)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DemonstrationError("ffprobe did not return complete audio metadata") from exc


def trim_source_to_ready_marker(
    source_path: Path,
    output_path: Path,
    *,
    ready_timestamp_seconds: float,
    lead_seconds: float = CAPTURE_READY_TRIM_LEAD_SECONDS,
) -> dict[str, Any]:
    """Accurately trim loading/setup frames using an explicit capture marker."""
    if not source_path.is_file():
        raise DemonstrationError(f"Proof source does not exist: {source_path}")
    if ready_timestamp_seconds < 0 or lead_seconds < 0:
        raise DemonstrationError("Capture-ready marker and trim lead must be non-negative")
    trim_start = round(max(0.0, ready_timestamp_seconds - lead_seconds), 3)
    duration = media_duration_seconds(source_path)
    if trim_start >= duration:
        raise DemonstrationError("Capture-ready marker is outside the source video")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(trim_start),
            "-i",
            str(source_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not output_path.is_file():
        raise DemonstrationError(f"FFmpeg marker trim failed: {result.stderr.strip()[-1000:]}")
    return {
        "ready_timestamp_seconds": round(ready_timestamp_seconds, 3),
        "trim_start_seconds": trim_start,
        "source_duration_seconds": duration,
        "trimmed_duration_seconds": video_metadata(output_path)["duration_seconds"],
    }


def _narration_audio_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix in {".m4a", ".mp4"}:
        return "audio/mp4"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".ogg":
        return "audio/ogg"
    raise DemonstrationError("Narration audio must be mp3, m4a, wav, or ogg")


def prepare_narration_audio(
    *,
    run_dir: Path,
    audio_path: Path,
    provider: str = DEFAULT_NARRATION_PROVIDER,
    model: str = DEFAULT_NARRATION_MODEL,
    voice: str = DEFAULT_NARRATION_VOICE,
    reused_from: str = "",
) -> dict[str, Any]:
    if provider != DEFAULT_NARRATION_PROVIDER:
        raise DemonstrationError("Narration audio provider must be ElevenLabs")
    if model != DEFAULT_NARRATION_MODEL:
        raise DemonstrationError(f"Narration audio must use {DEFAULT_NARRATION_MODEL}")
    if not voice.strip():
        raise DemonstrationError("Narration audio requires an ElevenLabs voice")
    if not audio_path.is_file():
        raise DemonstrationError(f"Narration audio does not exist: {audio_path}")
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    target = run_dir / f"narration-audio{audio_path.suffix.lower()}"
    if audio_path.resolve() != target.resolve():
        shutil.copyfile(audio_path, target)
        target.chmod(0o600)
    return {
        "status": "passed",
        "provider": provider,
        "model": model,
        "voice": voice,
        "path": str(target),
        "sha256": sha256_file(target),
        "mime_type": _narration_audio_mime_type(target),
        "duration_seconds": media_duration_seconds(target),
        "reused_from": reused_from,
    }


def narration_audio_not_required() -> dict[str, Any]:
    return {
        "status": "not_required",
        "provider": "",
        "model": "",
        "voice": "",
        "path": "",
        "sha256": "",
        "mime_type": "",
        "duration_seconds": 0.0,
        "reused_from": "",
    }


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def write_single_caption(path: Path, *, text: str, duration_seconds: float) -> None:
    if not text.strip() or duration_seconds <= 0:
        raise DemonstrationError("Caption text and duration are required")
    _write_private(
        path,
        f"1\n{_srt_timestamp(0)} --> {_srt_timestamp(duration_seconds)}\n{text.strip()}\n",
    )


def write_tutorial_captions(
    path: Path,
    *,
    text: str,
    duration_seconds: float,
    narration_id: str,
    first_transition_at: float | None = None,
) -> list[dict[str, Any]]:
    """Split tutorial narration into readable sentence-level caption cues."""
    assert_realistic_tutorial_narration(text)
    sentences = [value.strip() for value in re.split(r"(?<=[.!?])\s+", text.strip()) if value.strip()]
    if not sentences or duration_seconds <= 0:
        raise DemonstrationError("Tutorial narration and duration are required")
    weights = [max(1, len(sentence.split())) for sentence in sentences]
    segments: list[dict[str, Any]] = []
    cursor = 0.0
    blocks: list[str] = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights, strict=True), start=1):
        if index == 1 and first_transition_at is not None and len(sentences) > 1:
            end = min(duration_seconds, max(0.1, first_transition_at))
        elif index == len(sentences):
            end = duration_seconds
        else:
            remaining_weights = sum(weights[index - 1 :])
            end = cursor + (duration_seconds - cursor) * weight / remaining_weights
        segments.append(
            {
                "id": f"CAP-{index}",
                "narration_id": narration_id,
                "text": sentence,
                "start": round(cursor, 3),
                "end": round(end, 3),
                "claim_ids": ["CLAIM-1"],
            }
        )
        blocks.append(
            f"{index}\n{_srt_timestamp(cursor)} --> {_srt_timestamp(end)}\n{sentence}\n"
        )
        cursor = end
    _write_private(path, "\n".join(blocks))
    return segments


def clamp_intervals_to_duration(items: list[dict[str, Any]], *, duration_seconds: float) -> list[dict[str, Any]]:
    if duration_seconds <= 0:
        raise DemonstrationError("Interval duration must be positive")
    clamped: list[dict[str, Any]] = []
    for item in items:
        start = round(float(item["start"]), MEDIA_TIMESTAMP_DECIMALS)
        end = round(min(float(item["end"]), duration_seconds), MEDIA_TIMESTAMP_DECIMALS)
        if not 0 <= start < end <= duration_seconds:
            raise DemonstrationError("Caption interval is outside the rendered video duration")
        clamped.append({**item, "start": start, "end": end})
    return clamped


def assert_realistic_tutorial_narration(text: str) -> None:
    sentences = [value.strip() for value in re.split(r"(?<=[.!?])\s+", text.strip()) if value.strip()]
    words = re.findall(r"\b\w+\b", text)
    if len(sentences) < MIN_TUTORIAL_NARRATION_SENTENCES or len(words) < MIN_TUTORIAL_NARRATION_WORDS:
        raise DemonstrationError(
            "Tutorial narration must use at least three concrete sentences that describe the visible action and result"
        )
    if GENERIC_NARRATION_RE.search(text):
        raise DemonstrationError("Tutorial narration is too generic; describe the visible UI/action/result instead")
    if not VISIBLE_NARRATION_RE.search(text):
        raise DemonstrationError("Tutorial narration must mention visible UI, terminal output, or playback state")


def prepare_review_artifacts(
    *,
    run_dir: Path,
    video_path: Path,
    spec_id: str,
    subject_commit: str,
    narration_id: str,
    caption_text: str,
    expected_proof: str,
    acceptance_criteria: list[str],
    source: dict[str, Any],
    narration_audio: dict[str, Any],
    caption_segments: list[dict[str, Any]] | None = None,
    device_profile: dict[str, Any] | None = None,
    render_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = video_metadata(video_path)
    if device_profile is not None:
        assert_device_profile_dimensions(metadata, device_profile)
        metadata.update(
            {
                "device_profile": device_profile["id"],
                "target_width": int(device_profile["width"]),
                "target_height": int(device_profile["height"]),
                "black_bar_scan_status": assert_no_letterbox_or_pillarbox(video_path, metadata),
            }
        )
    if render_metadata:
        metadata.update(render_metadata)
    if not isinstance(narration_audio, dict) or narration_audio.get("status") not in {"passed", "not_required"}:
        raise DemonstrationError("Narration audio metadata must be passed or not_required")
    missing_audio_fields = NARRATION_AUDIO_FIELDS - set(narration_audio)
    if missing_audio_fields:
        raise DemonstrationError(f"Narration audio metadata missing {sorted(missing_audio_fields)[0]}")
    if narration_audio.get("status") == "passed" and not metadata.get("has_audio"):
        raise DemonstrationError("Rendered demonstration video must contain the requested narration audio track")
    captions = caption_segments or [
        {
            "id": "CAP-1",
            "narration_id": narration_id,
            "text": caption_text,
            "start": 0.0,
            "end": metadata["duration_seconds"],
            "claim_ids": ["CLAIM-1"],
        }
    ]
    captions = clamp_intervals_to_duration(captions, duration_seconds=float(metadata["duration_seconds"]))
    frame_dir = run_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    frame_dir.chmod(0o700)
    frames: list[dict[str, Any]] = []
    for index, timestamp in enumerate(
        build_review_frame_times(
            duration_seconds=metadata["duration_seconds"],
            interval_seconds=MAX_REVIEW_INTERVAL_SECONDS,
            caption_intervals=[(float(caption["start"]), float(caption["end"])) for caption in captions],
        )
    ):
        frame = extract_frame(
            video_path,
            timestamp_seconds=timestamp,
            output_path=frame_dir / f"frame-{index:04d}.png",
        )
        frame["path"] = str(Path(frame["path"]).relative_to(run_dir))
        frames.append(frame)
    if not acceptance_criteria or not all(isinstance(value, str) and value for value in acceptance_criteria):
        raise DemonstrationError("Every demonstration claim requires acceptance-criterion links")
    expected = [
        {
            "claim_id": "CLAIM-1",
            "text": expected_proof,
            "acceptance_criteria": acceptance_criteria,
            "evidence_intervals": [[0.0, round(float(metadata["duration_seconds"]), MEDIA_TIMESTAMP_DECIMALS)]],
        }
    ]
    review_audio = {
        **narration_audio,
        "path": Path(str(narration_audio["path"])).name if narration_audio.get("path") else "",
    }
    request = build_review_request(
        spec_id=spec_id,
        subject_commit=subject_commit,
        captions=captions,
        expected_proof=expected,
        frames=frames,
        video_metadata=metadata,
        narration_audio=review_audio,
    )
    manifest = {
        "schema_version": 1,
        "spec_id": spec_id,
        "subject_commit": subject_commit,
        "source": source,
        "video_path": str(video_path),
        "video_metadata": metadata,
        "narration_audio": narration_audio,
        "captions": captions,
        "expected_proof": expected,
        "privacy": {"status": "passed", "findings": [], "scan": "not_run"},
        "review": {
            "status": "pending",
            "run_id": f"review-{run_dir.name}",
            "attempts": [],
            "additional_frame_requests": [],
        },
        "publication": {"status": "pending"},
        "retained_paths": [
            str(run_dir / "transcript.txt"),
            str(run_dir / "captions.srt"),
            *([str(narration_audio["path"])] if narration_audio.get("path") else []),
        ],
        "disposable_artifacts": [
            {"path": str(video_path), "kind": "derived_video", "sha256": metadata["sha256"]},
            *[
                {
                    "path": str(run_dir / frame["path"]),
                    "kind": "review_frame",
                    "sha256": frame["sha256"],
                }
                for frame in frames
            ],
        ],
    }
    _write_run_json(run_dir / "review-request.json", request)
    _write_run_json(run_dir / "manifest.json", manifest)
    return manifest


def produce_cli_demonstration(
    *,
    run_dir: Path,
    argv: list[str],
    spec_id: str,
    subject_commit: str,
    run_id: str,
    target_environment: str,
    test_account_provenance: str,
    narration_id: str,
    caption_text: str,
    expected_proof: str,
    acceptance_criteria: list[str],
    narration_audio_path: Path | None,
    narration_audio_provider: str = DEFAULT_NARRATION_PROVIDER,
    narration_audio_model: str = DEFAULT_NARRATION_MODEL,
    narration_audio_voice: str = DEFAULT_NARRATION_VOICE,
    narration_audio_reused_from: str = "",
    anonymize_sensitive: bool = False,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    if timeout_seconds <= 0 or timeout_seconds > 600:
        raise DemonstrationError("CLI proof timeout must be between 0 and 600 seconds")
    capture = capture_pty(
        argv,
        run_id=run_id,
        target_environment=target_environment,
        output_dir=run_dir,
        test_account_provenance=test_account_provenance,
        timeout_seconds=timeout_seconds,
    )
    if capture.get("exit_status") != 0:
        raise DemonstrationError(f"CLI proof command exited with status {capture.get('exit_status')}")
    terminal_events: list[dict[str, Any]] = []
    try:
        if anonymize_sensitive:
            capture = anonymize_cli_capture(run_dir, capture)
        display_argv = user_facing_cli_argv(list(capture["argv"]))
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("stream") == "output" and anonymize_sensitive:
                event["text"] = redact_text_with_canonical_scanner(str(event.get("text", "")))["text"]
            terminal_events.append(event)
    except Exception:
        if anonymize_sensitive:
            (run_dir / "transcript.txt").unlink(missing_ok=True)
        raise
    finally:
        (run_dir / "events.jsonl").unlink(missing_ok=True)
    timeline = build_cli_terminal_timeline(argv=display_argv, events=terminal_events)
    duration = float(timeline["duration_seconds"])
    captions_path = run_dir / "captions.srt"
    video_path = run_dir / "demo.mp4"
    narration_audio = (
        prepare_narration_audio(
            run_dir=run_dir,
            audio_path=narration_audio_path,
            provider=narration_audio_provider,
            model=narration_audio_model,
            voice=narration_audio_voice,
            reused_from=narration_audio_reused_from,
        )
        if narration_audio_path is not None
        else narration_audio_not_required()
    )
    caption_segments = write_tutorial_captions(
        captions_path,
        text=caption_text,
        duration_seconds=duration,
        narration_id=narration_id,
        first_transition_at=timeline["first_output_at"],
    )
    render_terminal_video(
        timeline,
        captions_path,
        Path(str(narration_audio["path"])) if narration_audio.get("path") else None,
        video_path,
    )
    return prepare_review_artifacts(
        run_dir=run_dir,
        video_path=video_path,
        spec_id=spec_id,
        subject_commit=subject_commit,
        narration_id=narration_id,
        caption_text=caption_text,
        expected_proof=expected_proof,
        acceptance_criteria=acceptance_criteria,
        source={"kind": "cli", **capture, "display_argv": display_argv},
        narration_audio=narration_audio,
        caption_segments=caption_segments,
    )


def produce_playwright_demonstration(
    *,
    run_dir: Path,
    source_video: Path,
    source: dict[str, Any],
    spec_id: str,
    subject_commit: str,
    narration_id: str,
    caption_text: str,
    expected_proof: str,
    acceptance_criteria: list[str],
    narration_audio_path: Path | None,
    narration_audio_provider: str = DEFAULT_NARRATION_PROVIDER,
    narration_audio_model: str = DEFAULT_NARRATION_MODEL,
    narration_audio_voice: str = DEFAULT_NARRATION_VOICE,
    narration_audio_reused_from: str = "",
    device_profile_name: str | None = None,
    playback_rate: float = 1.0,
    hold_last_frame_seconds: float = 0.0,
    demo_audio_path: Path | None = None,
) -> dict[str, Any]:
    selected = select_playwright_source([source], run_id=str(source["run_id"]), subject_commit=subject_commit)
    verify_playwright_render_input(selected, source_video)
    source_metadata = video_metadata(source_video)
    device_profile = resolve_device_profile(device_profile_name)
    if device_profile is None:
        raise DemonstrationError("Playwright proof videos require --device-profile")
    assert_device_profile_dimensions(source_metadata, device_profile)
    if not MIN_PROOF_PLAYBACK_RATE <= playback_rate <= 4.0:
        raise DemonstrationError("Playback rate must be between 0.75 and 4.0")
    if hold_last_frame_seconds < 0 or hold_last_frame_seconds > 30:
        raise DemonstrationError("Hold-last-frame duration must be between 0 and 30 seconds")
    output_duration = round((source_metadata["duration_seconds"] / playback_rate) + hold_last_frame_seconds, 3)
    if output_duration > MAX_PROOF_OUTPUT_SECONDS:
        raise DemonstrationError("Proof-video output must not exceed 35 seconds")
    if demo_audio_path is not None and narration_audio_path is None:
        raise DemonstrationError("Product audio requires explicit narration audio with retained provenance")
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    _write_private(run_dir / "transcript.txt", caption_text.strip() + "\n")
    captions_path = run_dir / "captions.srt"
    narration_audio = (
        prepare_narration_audio(
            run_dir=run_dir,
            audio_path=narration_audio_path,
            provider=narration_audio_provider,
            model=narration_audio_model,
            voice=narration_audio_voice,
            reused_from=narration_audio_reused_from,
        )
        if narration_audio_path is not None
        else narration_audio_not_required()
    )
    caption_segments = write_tutorial_captions(
        captions_path,
        text=caption_text,
        duration_seconds=output_duration,
        narration_id=narration_id,
    )
    video_path = run_dir / "demo.mp4"
    render_captioned_video(
        source_video,
        captions_path,
        Path(str(narration_audio["path"])) if narration_audio.get("path") else None,
        video_path,
        playback_rate=playback_rate,
        hold_last_frame_seconds=hold_last_frame_seconds,
        demo_audio_path=demo_audio_path,
    )
    return prepare_review_artifacts(
        run_dir=run_dir,
        video_path=video_path,
        spec_id=spec_id,
        subject_commit=subject_commit,
        narration_id=narration_id,
        caption_text=caption_text,
        expected_proof=expected_proof,
        acceptance_criteria=acceptance_criteria,
        source={"kind": "playwright", **selected},
        narration_audio=narration_audio,
        caption_segments=caption_segments,
        device_profile=device_profile,
        render_metadata={
            "playback_rate": playback_rate,
            "hold_last_frame_seconds": hold_last_frame_seconds,
            "demo_audio_mixed": demo_audio_path is not None,
        },
    )


def record_review(run_dir: Path, claims: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review = manifest.get("review")
    if not isinstance(review, dict):
        raise DemonstrationError("Manifest review record must be a mapping")
    attempts = review.setdefault("attempts", [])
    if not isinstance(attempts, list):
        raise DemonstrationError("Manifest review attempts must be a list")
    expected_claim_ids = [
        item.get("claim_id") for item in manifest.get("expected_proof", []) if isinstance(item, dict)
    ]
    actual_claim_ids = [item.get("claim_id") for item in claims if isinstance(item, dict)]
    if (
        not expected_claim_ids
        or len(actual_claim_ids) != len(set(actual_claim_ids))
        or sorted(actual_claim_ids) != sorted(expected_claim_ids)
    ):
        raise DemonstrationError("Review must provide exactly one verdict for every expected claim")
    result = evaluate_review_claims(claims, prior_attempts=len(attempts))
    attempts.append(result)
    review.update(
        {
            "status": result["status"],
            "attempt_count": result["attempt_number"],
            "requires_user_input": result["requires_user_input"],
        }
    )
    _write_run_json(run_dir / "review.json", review)
    _write_run_json(manifest_path, manifest)
    return manifest


def build_review_frame_times(
    *,
    duration_seconds: float,
    interval_seconds: float = MAX_REVIEW_INTERVAL_SECONDS,
    scene_times: Iterable[float] = (),
    action_times: Iterable[float] = (),
    caption_intervals: Iterable[tuple[float, float]] = (),
    state_change_times: Iterable[float] = (),
) -> list[float]:
    if duration_seconds <= 0:
        raise DemonstrationError("Review duration must be positive")
    if interval_seconds <= 0 or interval_seconds > MAX_REVIEW_INTERVAL_SECONDS:
        raise DemonstrationError("Periodic review interval must be positive and no longer than three seconds")
    times = {0.0, round(float(duration_seconds), 3)}
    current = 0.0
    while current < duration_seconds:
        times.add(round(current, 3))
        current += interval_seconds

    def add_time(value: float) -> None:
        if 0 <= value <= duration_seconds:
            times.add(round(float(value), 3))

    for value in scene_times:
        add_time(value)
    for start, end in caption_intervals:
        add_time(start)
        add_time(end)
    for value in [*action_times, *state_change_times]:
        add_time(value - 0.25)
        add_time(value)
        add_time(value + 0.25)
    return sorted(times)


def assert_frame_only_review_request(request: dict[str, Any]) -> None:
    def finite_number(value: Any) -> bool:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)

    def require_fields(value: Any, allowed: set[str], label: str) -> None:
        if not isinstance(value, dict):
            raise DemonstrationError(f"Review request {label} must be a mapping")
        unknown = set(value) - allowed
        if unknown:
            raise DemonstrationError(f"Review request contains unsupported field in {label}: {sorted(unknown)[0]}")

    def inspect(value: Any, key: str = "") -> None:
        if key in FULL_VIDEO_REVIEW_KEYS:
            raise DemonstrationError("Review request must not contain the full video")
        if isinstance(value, bytes):
            raise DemonstrationError("Review request must not contain full video or other binary bytes")
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                inspect(child_value, str(child_key))
        elif isinstance(value, list):
            for child_value in value:
                inspect(child_value, key)

    inspect(request)
    require_fields(request, REVIEW_REQUEST_FIELDS, "root")
    missing_root = REVIEW_REQUEST_FIELDS - set(request)
    if missing_root:
        raise DemonstrationError(f"Review request missing required field: {sorted(missing_root)[0]}")
    if not isinstance(request["spec_id"], str) or not request["spec_id"]:
        raise DemonstrationError("Review request spec_id must be a non-empty string")
    if not isinstance(request["subject_commit"], str) or not request["subject_commit"]:
        raise DemonstrationError("Review request subject_commit must be a non-empty string")
    for field in ("captions", "expected_proof", "frames"):
        if not isinstance(request[field], list) or not request[field]:
            raise DemonstrationError(f"Review request {field} must be a non-empty list")
    metadata = request["video_metadata"]
    require_fields(metadata, REVIEW_METADATA_FIELDS, "video_metadata")
    if REVIEW_METADATA_REQUIRED_FIELDS - set(metadata):
        raise DemonstrationError("Review request video_metadata is missing required fields")
    duration = metadata.get("duration_seconds")
    if (
        not finite_number(duration)
        or duration <= 0
        or not isinstance(metadata.get("width"), int)
        or isinstance(metadata.get("width"), bool)
        or metadata["width"] <= 0
        or not isinstance(metadata.get("height"), int)
        or isinstance(metadata.get("height"), bool)
        or metadata["height"] <= 0
        or not isinstance(metadata.get("sha256"), str)
        or not SHA256_RE.fullmatch(metadata["sha256"])
    ):
        raise DemonstrationError("Review request video_metadata contains invalid values")
    audio = request["narration_audio"]
    require_fields(audio, NARRATION_AUDIO_FIELDS, "narration_audio")
    if NARRATION_AUDIO_FIELDS - set(audio):
        raise DemonstrationError("Review request narration_audio is missing required fields")
    if audio.get("status") == "not_required":
        if any(audio.get(field) for field in ("provider", "model", "voice", "path", "sha256", "mime_type", "duration_seconds", "reused_from")):
            raise DemonstrationError("Review request not_required narration_audio must not contain audio provenance")
    elif (
        audio.get("status") != "passed"
        or audio.get("provider") != DEFAULT_NARRATION_PROVIDER
        or audio.get("model") != DEFAULT_NARRATION_MODEL
        or not isinstance(audio.get("voice"), str)
        or not audio["voice"].strip()
        or not isinstance(audio.get("path"), str)
        or not audio["path"].strip()
        or not isinstance(audio.get("sha256"), str)
        or not SHA256_RE.fullmatch(audio["sha256"])
        or not isinstance(audio.get("mime_type"), str)
        or not audio["mime_type"].startswith("audio/")
        or not finite_number(audio.get("duration_seconds"))
        or audio["duration_seconds"] <= 0
        or not isinstance(audio.get("reused_from"), str)
    ):
        raise DemonstrationError("Review request narration_audio contains invalid values")
    for item in request.get("captions", []):
        require_fields(item, REVIEW_CAPTION_FIELDS, "captions")
        if REVIEW_CAPTION_FIELDS - set(item):
            raise DemonstrationError("Review request caption is missing required fields")
        start, end = item.get("start"), item.get("end")
        if (
            not all(isinstance(item.get(field), str) and item[field] for field in ("id", "narration_id", "text"))
            or not isinstance(item.get("claim_ids"), list)
            or not item["claim_ids"]
            or not all(isinstance(value, str) and value for value in item["claim_ids"])
            or not finite_number(start)
            or not finite_number(end)
            or not 0 <= start < end <= duration
        ):
            raise DemonstrationError("Review request caption contains invalid values")
    for item in request.get("expected_proof", []):
        require_fields(item, REVIEW_PROOF_FIELDS, "expected_proof")
        if REVIEW_PROOF_FIELDS - set(item) or not item.get("acceptance_criteria") or not item.get("evidence_intervals"):
            raise DemonstrationError("Review request proof is missing required traceability fields")
        intervals = item["evidence_intervals"]
        if (
            not all(isinstance(item.get(field), str) and item[field] for field in ("claim_id", "text"))
            or not isinstance(item["acceptance_criteria"], list)
            or not all(isinstance(value, str) and value for value in item["acceptance_criteria"])
            or not isinstance(intervals, list)
            or not all(
                isinstance(interval, list)
                and len(interval) == 2
                and all(finite_number(value) for value in interval)
                and 0 <= interval[0] < interval[1] <= duration
                for interval in intervals
            )
        ):
            raise DemonstrationError("Review request proof contains invalid traceability values")
    for item in request.get("frames", []):
        require_fields(item, REVIEW_FRAME_FIELDS, "frames")
        timestamp_fields = {"timestamp", "timestamp_seconds"} & set(item)
        if not item.get("path") or not item.get("sha256") or len(timestamp_fields) != 1:
            raise DemonstrationError("Review request frame is missing required fields")
        timestamp = item.get("timestamp_seconds", item.get("timestamp"))
        if (
            not finite_number(timestamp)
            or not 0 <= timestamp <= duration
            or not isinstance(item["path"], str)
            or not isinstance(item["sha256"], str)
            or not SHA256_RE.fullmatch(item["sha256"])
        ):
            raise DemonstrationError("Review request frame contains invalid values")
    frames = request.get("frames")
    if not isinstance(frames, list):
        raise DemonstrationError("Review request frames must be a list")
    for frame in frames:
        if not isinstance(frame, dict) or not str(frame.get("path", "")).lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            raise DemonstrationError("Review request may attach image frames only")


def build_review_request(
    *,
    spec_id: str,
    subject_commit: str,
    captions: list[dict[str, Any]],
    expected_proof: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    video_metadata: dict[str, Any],
    narration_audio: dict[str, Any],
) -> dict[str, Any]:
    allowed_metadata = {key: video_metadata[key] for key in REVIEW_METADATA_FIELDS if key in video_metadata}
    request = {
        "spec_id": spec_id,
        "subject_commit": subject_commit,
        "captions": captions,
        "expected_proof": expected_proof,
        "frames": frames,
        "video_metadata": allowed_metadata,
        "narration_audio": narration_audio,
    }
    assert_frame_only_review_request(request)
    return request


def register_exact_timestamp_request(
    review: dict[str, Any],
    *,
    timestamp_seconds: float,
    reason: str,
) -> dict[str, Any]:
    if timestamp_seconds < 0 or not reason.strip():
        raise DemonstrationError("Exact timestamp requests require a non-negative timestamp and reason")
    requests = review.setdefault("additional_frame_requests", [])
    if not isinstance(requests, list):
        raise DemonstrationError("additional_frame_requests must be a list")
    if len(requests) >= MAX_ADDITIONAL_FRAME_REQUESTS:
        raise DemonstrationError("Additional exact-timestamp frame request limit reached")
    record = {
        "timestamp_seconds": round(float(timestamp_seconds), 3),
        "reason": reason.strip(),
        "status": "requested",
    }
    requests.append(record)
    return record


def extract_frame(video_path: Path, *, timestamp_seconds: float, output_path: Path) -> dict[str, Any]:
    if timestamp_seconds < 0:
        raise DemonstrationError("Frame timestamp must be non-negative")
    duration_seconds = video_metadata(video_path)["duration_seconds"]
    seek_seconds = min(timestamp_seconds, max(0.0, duration_seconds - END_FRAME_OFFSET_SECONDS))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(seek_seconds),
            "-copyts",
            "-i",
            str(video_path),
            "-vf",
            "showinfo",
            "-frames:v",
            "1",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not output_path.is_file():
        raise DemonstrationError(f"FFmpeg frame extraction failed: {result.stderr.strip()[-500:]}")
    pts_match = SHOWINFO_PTS_RE.search(result.stderr)
    if not pts_match:
        raise DemonstrationError("FFmpeg frame extraction did not report a decoded frame timestamp")
    return {
        "timestamp_seconds": round(float(pts_match.group(1)), 3),
        "path": str(output_path),
        "sha256": sha256_file(output_path),
    }


def evaluate_review_claims(claims: list[dict[str, Any]], *, prior_attempts: int) -> dict[str, Any]:
    if not claims:
        raise DemonstrationError("Review requires at least one claim verdict")
    if isinstance(prior_attempts, bool) or not isinstance(prior_attempts, int) or not 0 <= prior_attempts < 4:
        raise DemonstrationError("Prior review attempts must be an integer from 0 to 3")
    failed_claim_ids: list[str] = []
    return_stages: list[str] = []
    invalidate = False
    for claim in claims:
        claim_id = claim.get("claim_id")
        verdict = claim.get("verdict")
        if not isinstance(claim_id, str) or not claim_id:
            raise DemonstrationError("Every review verdict requires a claim_id")
        if verdict not in REVIEW_VERDICTS:
            raise DemonstrationError(f"Unsupported review verdict for {claim_id}: {verdict}")
        observation = claim.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            raise DemonstrationError(f"Review claim {claim_id} requires a frame-grounded observation")
        if "frame" not in observation.lower():
            raise DemonstrationError(f"Review claim {claim_id} observation must reference reviewed frames")
        if verdict == "supported":
            continue
        defect_class = claim.get("defect_class")
        if defect_class not in DEFECT_RETURN_STAGES:
            raise DemonstrationError(f"Failed claim {claim_id} requires one approved defect_class")
        failed_claim_ids.append(claim_id)
        stage = DEFECT_RETURN_STAGES[defect_class]
        if stage not in return_stages:
            return_stages.append(stage)
        if defect_class in {"implementation", "test_coverage"}:
            invalidate = True
    attempt_number = prior_attempts + 1
    status = "failed" if failed_claim_ids else "passed"
    return {
        "status": status,
        "attempt_number": attempt_number,
        "failed_claim_ids": failed_claim_ids,
        "return_stages": return_stages,
        "invalidate_implementation_evidence": invalidate,
        "requires_user_input": status == "failed" and attempt_number >= 4,
        "claims": claims,
    }


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_run_json(path: Path, value: dict[str, Any]) -> None:
    _write_private(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def delete_disposable_artifacts(run_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Delete only manifest-owned files after validating every path first."""
    root = run_dir.resolve()
    retained = {Path(str(value)).resolve() for value in manifest.get("retained_paths", [])}
    control_names = {"manifest.json", "publication.json", "review.json", "review-request.json"}
    artifacts = manifest.get("disposable_artifacts", [])
    if not isinstance(artifacts, list):
        raise DemonstrationError("disposable_artifacts must be a list")
    paths: list[Path] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("kind") not in {"derived_video", "review_frame"}:
            raise DemonstrationError("Disposable artifact requires an approved kind")
        path = Path(str(artifact.get("path", ""))).resolve()
        if not path.is_relative_to(root):
            raise DemonstrationError(f"Disposable path is outside demonstration run directory: {path}")
        if path in retained or path.name in control_names:
            raise DemonstrationError(f"Disposable artifact targets a retained or control file: {path.name}")
        expected_hash = artifact.get("sha256")
        if not isinstance(expected_hash, str) or not path.is_file() or sha256_file(path) != expected_hash:
            raise DemonstrationError(f"Disposable artifact hash mismatch: {path.name}")
        paths.append(path)
    deleted: list[str] = []
    for path in paths:
        if path.is_file():
            path.unlink()
            deleted.append(str(path))
    for directory in sorted({path.parent for path in paths}, key=lambda item: len(item.parts), reverse=True):
        if directory != root and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return deleted


def publish_reviewed_video(
    run_dir: Path,
    manifest: dict[str, Any],
    *,
    now: datetime,
    uploader: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if manifest.get("privacy", {}).get("status") != "passed" or manifest.get("review", {}).get("status") != "passed":
        raise DemonstrationError("OpenCode response-media publication requires passed privacy and demonstration review")
    audio_status = manifest.get("narration_audio", {}).get("status")
    if audio_status not in {"passed", "not_required"}:
        raise DemonstrationError("OpenCode response-media publication requires passed or intentionally disabled narration audio")
    if audio_status == "passed" and manifest.get("video_metadata", {}).get("has_audio") is not True:
        raise DemonstrationError("OpenCode response-media publication requires the requested narration audio track")
    publication = manifest.setdefault("publication", {})
    if not isinstance(publication, dict):
        raise DemonstrationError("Manifest publication record must be a mapping")
    if publication.get("status") == "delivered":
        _write_run_json(run_dir / "publication.json", publication)
        _write_run_json(run_dir / "manifest.json", manifest)
        return manifest
    video_path = Path(str(manifest.get("video_path", "")))
    if not video_path.is_file():
        raise DemonstrationError("Reviewed demonstration video does not exist")
    now_text = _utc_text(now)
    first_attempt_text = publication.setdefault("first_attempt_at", now_text)
    publication["last_attempt_at"] = now_text
    first_attempt = datetime.fromisoformat(str(first_attempt_text).replace("Z", "+00:00"))
    publication.setdefault("retry_until", _utc_text(first_attempt + timedelta(hours=24)))
    alt_text = (
        f"Reviewed implementation demonstration for {manifest.get('spec_id', 'unknown')} "
        f"at {manifest.get('subject_commit', 'unknown')}"
    )
    if uploader is None:
        uploader = upload_response_media
    try:
        upload = uploader(path=video_path, alt=alt_text)
    except Exception as exc:
        publication["status"] = "publication_pending"
        publication["failure_reason"] = f"OpenCode response-media upload did not complete: {str(exc)[:500]}"
        publication["next_retry_at"] = _utc_text(now + timedelta(minutes=15))
        _write_run_json(run_dir / "publication.json", publication)
        _write_run_json(run_dir / "manifest.json", manifest)
        return manifest

    snippets = upload.get("snippets") if isinstance(upload, dict) else None
    if not isinstance(upload, dict) or not upload.get("key") or not isinstance(snippets, dict):
        publication["status"] = "publication_pending"
        publication["failure_reason"] = "OpenCode response-media upload completed without usable snippets."
        publication["next_retry_at"] = _utc_text(now + timedelta(minutes=15))
    else:
        publication.update(
            {
                "status": "delivered",
                "delivered_at": now_text,
                "delivery_kind": "opencode_response_media",
                "response_media_key": str(upload["key"]),
                "response_media_kind": str(upload.get("kind", "media")),
                "response_media_markdown": str(snippets.get("markdown", "")),
                "response_media_html": str(snippets.get("html", "")),
            }
        )
        if "expires_in" in upload:
            publication["response_media_expires_in"] = upload["expires_in"]
        publication.pop("failure_reason", None)
        publication.pop("next_retry_at", None)
        publication["deleted_paths"] = delete_disposable_artifacts(run_dir, manifest)
        publication["video_deleted_at"] = now_text
    _write_run_json(run_dir / "publication.json", publication)
    _write_run_json(run_dir / "manifest.json", manifest)
    return manifest


def upload_response_media(*, path: Path, alt: str) -> dict[str, Any]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/opencode_response_media.py"),
        str(path),
        "--alt",
        alt,
        "--output",
        "json",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise DemonstrationError(result.stderr.strip() or result.stdout.strip() or "response-media upload failed")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DemonstrationError("response-media upload returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise DemonstrationError("response-media upload returned an invalid payload")
    return parsed


def expire_pending_video(run_dir: Path, manifest: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    publication = manifest.get("publication")
    if not isinstance(publication, dict) or publication.get("status") not in {"publication_pending", "not_configured"}:
        return manifest
    retry_until_text = publication.get("retry_until")
    if not isinstance(retry_until_text, str) or not retry_until_text:
        raise DemonstrationError("Pending publication is missing retry_until")
    retry_until = datetime.fromisoformat(retry_until_text.replace("Z", "+00:00"))
    if now.astimezone(timezone.utc) < retry_until.astimezone(timezone.utc):
        return manifest
    publication.update(
        {
            "status": "expired_deleted",
            "expired_at": _utc_text(now),
            "failure_reason": "OpenCode response-media proof embed did not complete within 24 hours.",
            "deleted_paths": delete_disposable_artifacts(run_dir, manifest),
            "video_deleted_at": _utc_text(now),
        }
    )
    (run_dir / ".publication-link").unlink(missing_ok=True)
    _write_run_json(run_dir / "publication.json", publication)
    _write_run_json(run_dir / "manifest.json", manifest)
    return manifest


def sweep_expired_videos(root: Path, *, now: datetime) -> dict[str, int]:
    scanned = 0
    expired = 0
    if not root.is_dir():
        return {"scanned": 0, "expired_deleted": 0}
    for manifest_path in root.rglob("manifest.json"):
        scanned += 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_status = manifest.get("publication", {}).get("status")
        result = expire_pending_video(manifest_path.parent, manifest, now=now)
        if previous_status != "expired_deleted" and result.get("publication", {}).get("status") == "expired_deleted":
            expired += 1
    return {"scanned": scanned, "expired_deleted": expired}


def sweep_publications(
    root: Path,
    *,
    now: datetime,
    uploader: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, int]:
    counts = {"scanned": 0, "retried": 0, "delivered": 0, "expired_deleted": 0}
    if not root.is_dir():
        return counts
    lock_path = root / ".publication-sweep.lock"
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return counts
        for manifest_path in root.rglob("manifest.json"):
            counts["scanned"] += 1
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
            if publication.get("status") not in {"publication_pending", "not_configured"}:
                continue
            retry_until = datetime.fromisoformat(str(publication.get("retry_until", "")).replace("Z", "+00:00"))
            if now.astimezone(timezone.utc) >= retry_until.astimezone(timezone.utc):
                expire_pending_video(manifest_path.parent, manifest, now=now)
                counts["expired_deleted"] += 1
                continue
            next_retry_text = publication.get("next_retry_at")
            if next_retry_text:
                next_retry = datetime.fromisoformat(str(next_retry_text).replace("Z", "+00:00"))
                if now.astimezone(timezone.utc) < next_retry.astimezone(timezone.utc):
                    continue
            counts["retried"] += 1
            result = publish_reviewed_video(
                manifest_path.parent,
                manifest,
                now=now,
                uploader=uploader,
            )
            if result.get("publication", {}).get("status") == "delivered":
                counts["delivered"] += 1
    return counts


def doctor() -> dict[str, Any]:
    checks = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "terminal_font": TERMINAL_FONT.is_file(),
        "node": shutil.which("node") is not None,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build narrated specification demonstration evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    cli_parser = subparsers.add_parser("produce-cli")
    cli_parser.add_argument("--run-dir", type=Path, required=True)
    cli_parser.add_argument("--spec-id", required=True)
    cli_parser.add_argument("--subject-commit", required=True)
    cli_parser.add_argument("--run-id", required=True)
    cli_parser.add_argument("--target-environment", required=True)
    cli_parser.add_argument("--test-account-provenance", required=True)
    cli_parser.add_argument("--narration-id", required=True)
    cli_parser.add_argument("--caption", required=True)
    cli_parser.add_argument("--expected-proof", required=True)
    cli_parser.add_argument("--acceptance-criterion", action="append", required=True)
    cli_parser.add_argument("--audio-path", type=Path, required=True)
    cli_parser.add_argument("--audio-provider", default=DEFAULT_NARRATION_PROVIDER)
    cli_parser.add_argument("--audio-model", default=DEFAULT_NARRATION_MODEL)
    cli_parser.add_argument("--audio-voice", default=DEFAULT_NARRATION_VOICE)
    cli_parser.add_argument("--audio-reused-from", default="")
    cli_parser.add_argument("--anonymize-sensitive", action="store_true")
    cli_parser.add_argument("argv", nargs=argparse.REMAINDER)
    review_parser = subparsers.add_parser("record-review")
    review_parser.add_argument("--run-dir", type=Path, required=True)
    review_parser.add_argument("--claims-json", required=True)
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--run-dir", type=Path, required=True)
    expire_parser = subparsers.add_parser("expire")
    expire_parser.add_argument("--run-dir", type=Path, required=True)
    sweep_parser = subparsers.add_parser("sweep-expired")
    sweep_parser.add_argument("--root", type=Path, default=REPO_ROOT / "test-results/spec-demos")
    retry_parser = subparsers.add_parser("sweep-publications")
    retry_parser.add_argument("--root", type=Path, default=REPO_ROOT / "test-results/spec-demos")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        result = doctor()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    if args.command == "produce-cli":
        command_argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
        result = produce_cli_demonstration(
            run_dir=args.run_dir,
            argv=command_argv,
            spec_id=args.spec_id,
            subject_commit=args.subject_commit,
            run_id=args.run_id,
            target_environment=args.target_environment,
            test_account_provenance=args.test_account_provenance,
            narration_id=args.narration_id,
            caption_text=args.caption,
            expected_proof=args.expected_proof,
            acceptance_criteria=args.acceptance_criterion,
            narration_audio_path=args.audio_path,
            narration_audio_provider=args.audio_provider,
            narration_audio_model=args.audio_model,
            narration_audio_voice=args.audio_voice,
            narration_audio_reused_from=args.audio_reused_from,
            anonymize_sensitive=args.anonymize_sensitive,
        )
        print(json.dumps({"status": "review_ready", "manifest": str(args.run_dir / "manifest.json"), "privacy": result["privacy"]}, sort_keys=True))
        return 0
    if args.command == "record-review":
        claims = json.loads(args.claims_json)
        if not isinstance(claims, list):
            raise DemonstrationError("--claims-json must contain a JSON array")
        result = record_review(args.run_dir, claims)
        print(json.dumps({"status": result["review"]["status"], "attempt_count": result["review"]["attempt_count"]}, sort_keys=True))
        return 0
    if args.command == "publish":
        manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
        result = publish_reviewed_video(
            args.run_dir,
            manifest,
            now=datetime.now(timezone.utc),
        )
        publication = result["publication"]
        print(
            json.dumps(
                {
                    "status": publication["status"],
                    "markdown": publication.get("response_media_markdown", ""),
                    "html": publication.get("response_media_html", ""),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "sweep-expired":
        print(json.dumps(sweep_expired_videos(args.root, now=datetime.now(timezone.utc)), sort_keys=True))
        return 0
    if args.command == "sweep-publications":
        print(
            json.dumps(
                sweep_publications(
                    args.root,
                    now=datetime.now(timezone.utc),
                ),
                sort_keys=True,
            )
        )
        return 0
    if args.command == "expire":
        manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
        result = expire_pending_video(args.run_dir, manifest, now=datetime.now(timezone.utc))
        print(json.dumps({"status": result["publication"]["status"]}, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
