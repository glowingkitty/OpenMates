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
import textwrap
import time
from typing import Any, Callable, Iterable
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
TERMINAL_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
TERMINAL_VIDEO_SIZE = "1280x720"
TERMINAL_FONT_SIZE = 28
TERMINAL_COLUMNS = 72
TERMINAL_TYPING_INTERVAL_SECONDS = 0.04
TERMINAL_TUTORIAL_MIN_SECONDS = 15.0
TERMINAL_RESULT_HOLD_SECONDS = 8.0
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
    "test_account_provenance",
}
MAX_REVIEW_INTERVAL_SECONDS = 3.0
MAX_ADDITIONAL_FRAME_REQUESTS = 10
END_FRAME_OFFSET_SECONDS = 0.1
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
REVIEW_REQUEST_FIELDS = {"spec_id", "subject_commit", "captions", "expected_proof", "frames", "video_metadata"}
REVIEW_CAPTION_FIELDS = {"id", "narration_id", "text", "start", "end", "claim_ids"}
REVIEW_PROOF_FIELDS = {"claim_id", "text", "acceptance_criteria", "evidence_intervals"}
REVIEW_FRAME_FIELDS = {"timestamp", "timestamp_seconds", "path", "sha256"}
REVIEW_METADATA_FIELDS = {"duration_seconds", "sha256", "width", "height"}


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
        return {**candidate, "artifact_hash": sha256_file(artifact_path)}
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
            if process.poll() is not None and (reached_eof or not ready):
                break
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


def build_cli_terminal_timeline(*, argv: list[str], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build visible typing and output states while preserving captured delays."""
    command = f"$ {shlex.join(argv)}"
    states: list[dict[str, Any]] = []
    visible = "$ "
    for character in command[2:]:
        states.append({"start": len(states) * TERMINAL_TYPING_INTERVAL_SECONDS, "text": visible})
        visible += character
    typing_completed_at = len(states) * TERMINAL_TYPING_INTERVAL_SECONDS
    if not states:
        states.append({"start": 0.0, "text": visible})
    states.append({"start": typing_completed_at, "text": visible})
    first_output_at: float | None = None
    for event in events:
        if event.get("stream") != "output":
            continue
        event_time = max(0.0, float(event.get("time_seconds", 0.0)))
        if first_output_at is None and not visible.endswith("\n"):
            visible += "\n"
        visible += str(event.get("text", ""))
        shifted_time = typing_completed_at + event_time
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
    escaped = "\n".join(wrapped).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
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


def render_terminal_video(timeline: dict[str, Any], captions_path: Path, output_path: Path) -> None:
    """Render a readable timed terminal tutorial with canonical captions."""
    for path in (captions_path, TERMINAL_FONT):
        if not path.is_file():
            raise DemonstrationError(f"Required render input does not exist: {path}")
    duration_seconds = float(timeline.get("duration_seconds", 0))
    if duration_seconds <= 0:
        raise DemonstrationError("Video duration must be positive")
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
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=#111827:s={TERMINAL_VIDEO_SIZE}:r=30",
            "-t",
            str(duration_seconds),
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
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


def render_captioned_video(source_path: Path, captions_path: Path, output_path: Path) -> None:
    """Burn canonical captions into a copy without mutating the raw recording."""
    for path in (source_path, captions_path):
        if not path.is_file():
            raise DemonstrationError(f"Required render input does not exist: {path}")
    if source_path.resolve() == output_path.resolve():
        raise DemonstrationError("Caption output must not replace the raw recording")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    captions = _ffmpeg_filter_path(captions_path)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            f"subtitles='{captions}'",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
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


def scan_text_with_canonical_scanner(text: str) -> list[str]:
    """Return finding types only; never expose matched secret values."""
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(SECRET_SCANNER_CLI)],
        input=json.dumps({"text": text, "knownSecrets": _known_secret_values()}),
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise DemonstrationError(f"Canonical secret scanner failed: {result.stderr.strip()[-500:]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DemonstrationError("Canonical secret scanner returned invalid JSON") from exc
    types = payload.get("types")
    if not isinstance(types, list) or not all(isinstance(value, str) for value in types):
        raise DemonstrationError("Canonical secret scanner returned invalid finding types")
    return types


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


def scan_text_sources(values: dict[str, str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for field, text in values.items():
        types = sorted(set(scan_text_with_canonical_scanner(text)))
        if types:
            findings.append({"field": field, "types": types})
    return {"status": "failed" if findings else "passed", "findings": findings}


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
            "format=duration:format_tags:stream=width,height,codec_name:stream_tags",
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
        "sha256": sha256_file(video_path),
        "tags": tags,
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
    caption_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata = video_metadata(video_path)
    text_privacy = scan_text_sources(
        {
            "caption_text": caption_text,
            "expected_proof": expected_proof,
            "narration_id": narration_id,
            "video_filename": video_path.name,
            "source_metadata": json.dumps(source, sort_keys=True),
            "acceptance_criteria": json.dumps(acceptance_criteria),
        }
    )
    if text_privacy["status"] != "passed":
        raise DemonstrationError("Text privacy scan found sensitive content before review")
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
            "evidence_intervals": [[0.0, metadata["duration_seconds"]]],
        }
    ]
    request = build_review_request(
        spec_id=spec_id,
        subject_commit=subject_commit,
        captions=captions,
        expected_proof=expected,
        frames=frames,
        video_metadata=metadata,
    )
    manifest = {
        "schema_version": 1,
        "spec_id": spec_id,
        "subject_commit": subject_commit,
        "source": source,
        "video_path": str(video_path),
        "video_metadata": metadata,
        "captions": captions,
        "expected_proof": expected,
        "privacy": {"status": "passed", "findings": [], "text_scan": text_privacy},
        "review": {
            "status": "pending",
            "run_id": f"review-{run_dir.name}",
            "attempts": [],
            "additional_frame_requests": [],
        },
        "publication": {"status": "pending"},
        "retained_paths": [str(run_dir / "transcript.txt"), str(run_dir / "captions.srt")],
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
    anonymize_sensitive: bool = False,
) -> dict[str, Any]:
    capture = capture_pty(
        argv,
        run_id=run_id,
        target_environment=target_environment,
        output_dir=run_dir,
        test_account_provenance=test_account_provenance,
    )
    terminal_events: list[dict[str, Any]] = []
    try:
        if anonymize_sensitive:
            capture = anonymize_cli_capture(run_dir, capture)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("stream") == "output" and anonymize_sensitive:
                event["text"] = redact_text_with_canonical_scanner(str(event.get("text", "")))["text"]
            terminal_events.append(event)
        pre_render_privacy = scan_text_sources(
            {
                "argv": json.dumps(capture["argv"]),
                "transcript": (run_dir / "transcript.txt").read_text(encoding="utf-8"),
                "caption_text": caption_text,
                "expected_proof": expected_proof,
                "output_filename": "demo.mp4",
            }
        )
        if pre_render_privacy["status"] != "passed":
            (run_dir / "transcript.txt").unlink(missing_ok=True)
            raise DemonstrationError("Text privacy scan found sensitive CLI content before rendering")
    except Exception:
        if anonymize_sensitive:
            (run_dir / "transcript.txt").unlink(missing_ok=True)
        raise
    finally:
        (run_dir / "events.jsonl").unlink(missing_ok=True)
    timeline = build_cli_terminal_timeline(argv=list(capture["argv"]), events=terminal_events)
    duration = float(timeline["duration_seconds"])
    captions_path = run_dir / "captions.srt"
    video_path = run_dir / "demo.mp4"
    caption_segments = write_tutorial_captions(
        captions_path,
        text=caption_text,
        duration_seconds=duration,
        narration_id=narration_id,
        first_transition_at=timeline["first_output_at"],
    )
    render_terminal_video(timeline, captions_path, video_path)
    return prepare_review_artifacts(
        run_dir=run_dir,
        video_path=video_path,
        spec_id=spec_id,
        subject_commit=subject_commit,
        narration_id=narration_id,
        caption_text=caption_text,
        expected_proof=expected_proof,
        acceptance_criteria=acceptance_criteria,
        source={"kind": "cli", **capture},
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
) -> dict[str, Any]:
    selected = select_playwright_source([source], run_id=str(source["run_id"]), subject_commit=subject_commit)
    verify_playwright_render_input(selected, source_video)
    source_metadata = video_metadata(source_video)
    pre_render_privacy = scan_text_sources(
        {
            "source_filename": source_video.name,
            "source_metadata": json.dumps(selected, sort_keys=True),
            "caption_text": caption_text,
            "expected_proof": expected_proof,
            "output_filename": "demo.mp4",
            "source_media_tags": json.dumps(source_metadata["tags"], sort_keys=True),
        }
    )
    if pre_render_privacy["status"] != "passed":
        raise DemonstrationError("Text privacy scan found sensitive Playwright content before rendering")
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    _write_private(run_dir / "transcript.txt", caption_text.strip() + "\n")
    captions_path = run_dir / "captions.srt"
    write_single_caption(captions_path, text=caption_text, duration_seconds=source_metadata["duration_seconds"])
    video_path = run_dir / "demo.mp4"
    render_captioned_video(source_video, captions_path, video_path)
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
    if REVIEW_METADATA_FIELDS - set(metadata):
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
) -> dict[str, Any]:
    allowed_metadata = {key: video_metadata[key] for key in ("duration_seconds", "sha256", "width", "height") if key in video_metadata}
    request = {
        "spec_id": spec_id,
        "subject_commit": subject_commit,
        "captions": captions,
        "expected_proof": expected_proof,
        "frames": frames,
        "video_metadata": allowed_metadata,
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
        if verdict == "supported":
            continue
        defect_class = claim.get("defect_class")
        if defect_class not in DEFECT_RETURN_STAGES:
            raise DemonstrationError(f"Failed claim {claim_id} requires one approved defect_class")
        if not isinstance(claim.get("observation"), str) or not claim["observation"].strip():
            raise DemonstrationError(f"Failed claim {claim_id} requires an observation")
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
    webhook_url: str,
    now: datetime,
    send: Callable[..., dict[str, str] | None] | None = None,
    max_attachment_bytes: int = 10 * 1024 * 1024,
    approved_artifact_link: str = "",
    approved_artifact_hosts: set[str] | None = None,
    send_link: Callable[..., dict[str, str] | None] | None = None,
) -> dict[str, Any]:
    if manifest.get("privacy", {}).get("status") != "passed" or manifest.get("review", {}).get("status") != "passed":
        raise DemonstrationError("Discord publication requires passed privacy and demonstration review")
    video_path = Path(str(manifest.get("video_path", "")))
    if not video_path.is_file():
        raise DemonstrationError("Reviewed demonstration video does not exist")
    now_text = _utc_text(now)
    publication = manifest.setdefault("publication", {})
    if not isinstance(publication, dict):
        raise DemonstrationError("Manifest publication record must be a mapping")
    first_attempt_text = publication.setdefault("first_attempt_at", now_text)
    publication["last_attempt_at"] = now_text
    first_attempt = datetime.fromisoformat(str(first_attempt_text).replace("Z", "+00:00"))
    publication.setdefault("retry_until", _utc_text(first_attempt + timedelta(hours=24)))
    link_path = run_dir / ".publication-link"
    oversized = video_path.stat().st_size > max_attachment_bytes
    if oversized and not approved_artifact_link and link_path.is_file():
        approved_artifact_link = link_path.read_text(encoding="utf-8")
    if oversized and approved_artifact_link:
        parsed_link = urlparse(approved_artifact_link)
        allowed_hosts = approved_artifact_hosts or set()
        if parsed_link.scheme != "https" or not parsed_link.hostname or parsed_link.hostname not in allowed_hosts:
            raise DemonstrationError("Artifact link must use an approved HTTPS artifact host")
        link_privacy = scan_text_sources({"approved_artifact_link": approved_artifact_link})
        if link_privacy["status"] != "passed":
            raise DemonstrationError("Approved artifact link failed privacy scanning")
        _write_private(link_path, approved_artifact_link)
    if not webhook_url:
        publication["status"] = "not_configured"
        _write_run_json(run_dir / "publication.json", publication)
        _write_run_json(run_dir / "manifest.json", manifest)
        return manifest

    payload = {
        "content": (
            f"Reviewed implementation demonstration: {manifest.get('spec_id', 'unknown')} "
            f"at {manifest.get('subject_commit', 'unknown')}"
        )
    }
    publication_privacy = scan_text_sources(
        {"discord_message": payload["content"], "video_filename": video_path.name}
    )
    if publication_privacy["status"] != "passed":
        raise DemonstrationError("Discord publication text failed privacy scanning")
    if oversized:
        if approved_artifact_link:
            link_payload = {"content": f"{payload['content']}\nAccess-controlled artifact: {approved_artifact_link}"}
            if send_link is None and send is not None:
                delivery = send(
                    webhook_url=webhook_url,
                    payload=link_payload,
                    content=None,
                    filename="",
                )
            else:
                if send_link is None:
                    send_link = _discord_webhook_module().post_message
                delivery = send_link(webhook_url=webhook_url, payload=link_payload)
            if isinstance(delivery, dict) and delivery.get("message_id"):
                publication.update(
                    {
                        "status": "delivered",
                        "delivered_at": now_text,
                        "message_id": str(delivery["message_id"]),
                        "delivery_kind": "access_controlled_link",
                    }
                )
                publication.pop("failure_reason", None)
                publication.pop("next_retry_at", None)
                publication["deleted_paths"] = delete_disposable_artifacts(run_dir, manifest)
                publication["video_deleted_at"] = now_text
                link_path.unlink(missing_ok=True)
                _write_run_json(run_dir / "publication.json", publication)
                _write_run_json(run_dir / "manifest.json", manifest)
                return manifest
        publication["status"] = "publication_pending"
        publication["failure_reason"] = "Reviewed video exceeds the configured Discord attachment limit and needs an approved access-controlled artifact link."
        publication["next_retry_at"] = _utc_text(now + timedelta(minutes=15))
        _write_run_json(run_dir / "publication.json", publication)
        _write_run_json(run_dir / "manifest.json", manifest)
        return manifest
    if send is None:
        send = _discord_webhook_module().post_attachment
    delivery = send(
        webhook_url=webhook_url,
        payload=payload,
        content=video_path.read_bytes(),
        filename=video_path.name,
    )
    if not isinstance(delivery, dict) or not delivery.get("message_id") or not delivery.get("attachment_id"):
        publication["status"] = "publication_pending"
        publication["failure_reason"] = "Discord did not confirm message and attachment creation."
        publication["next_retry_at"] = _utc_text(now + timedelta(minutes=15))
    else:
        publication.update(
            {
                "status": "delivered",
                "delivered_at": now_text,
                "message_id": str(delivery["message_id"]),
                "attachment_id": str(delivery["attachment_id"]),
            }
        )
        publication.pop("failure_reason", None)
        publication.pop("next_retry_at", None)
        publication["deleted_paths"] = delete_disposable_artifacts(run_dir, manifest)
        publication["video_deleted_at"] = now_text
        link_path.unlink(missing_ok=True)
    _write_run_json(run_dir / "publication.json", publication)
    _write_run_json(run_dir / "manifest.json", manifest)
    return manifest


def _discord_webhook_module() -> Any:
    """Load the sibling helper in both script and repository-module contexts."""
    try:
        import discord_webhook
    except ModuleNotFoundError:
        from scripts import discord_webhook
    return discord_webhook


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
            "failure_reason": "Discord delivery did not complete within 24 hours.",
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
    webhook_url: str,
    send: Callable[..., dict[str, str] | None] | None = None,
    max_attachment_bytes: int = 10 * 1024 * 1024,
    approved_artifact_link: str = "",
    approved_artifact_hosts: set[str] | None = None,
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
                webhook_url=webhook_url,
                now=now,
                send=send,
                max_attachment_bytes=max_attachment_bytes,
                approved_artifact_link=approved_artifact_link,
                approved_artifact_hosts=approved_artifact_hosts,
            )
            if result.get("publication", {}).get("status") == "delivered":
                counts["delivered"] += 1
    return counts


def resolve_discord_webhook(env: dict[str, str]) -> str:
    """Return only the dedicated implementation-demonstration destination."""
    return env.get("DISCORD_WEBHOOK_SPEC_DEMOS", "")


def resolve_artifact_hosts(value: str) -> set[str]:
    return {host.strip().lower() for host in value.split(",") if host.strip()}


def doctor() -> dict[str, Any]:
    checks = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "terminal_font": TERMINAL_FONT.is_file(),
        "node": shutil.which("node") is not None,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks}


def _load_named_env(keys: tuple[str, ...]) -> dict[str, str]:
    values = {key: os.environ.get(key, "") for key in keys}
    env_path = REPO_ROOT / ".env"
    if env_path.is_file() and not all(values.values()):
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key in values and not values[key]:
                values[key] = value.strip().strip("'\"")
    return values


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
    cli_parser.add_argument("--anonymize-sensitive", action="store_true")
    cli_parser.add_argument("argv", nargs=argparse.REMAINDER)
    review_parser = subparsers.add_parser("record-review")
    review_parser.add_argument("--run-dir", type=Path, required=True)
    review_parser.add_argument("--claims-json", required=True)
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--run-dir", type=Path, required=True)
    publish_parser.add_argument("--approved-artifact-link", default="")
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
        env = _load_named_env(("DISCORD_WEBHOOK_SPEC_DEMOS", "SPEC_DEMO_APPROVED_ARTIFACT_LINK", "SPEC_DEMO_ARTIFACT_HOSTS"))
        webhook = resolve_discord_webhook(env)
        result = publish_reviewed_video(
            args.run_dir,
            manifest,
            webhook_url=webhook,
            now=datetime.now(timezone.utc),
            approved_artifact_link=args.approved_artifact_link or env["SPEC_DEMO_APPROVED_ARTIFACT_LINK"],
            approved_artifact_hosts=resolve_artifact_hosts(env["SPEC_DEMO_ARTIFACT_HOSTS"]),
        )
        print(json.dumps({"status": result["publication"]["status"]}, sort_keys=True))
        return 0
    if args.command == "sweep-expired":
        print(json.dumps(sweep_expired_videos(args.root, now=datetime.now(timezone.utc)), sort_keys=True))
        return 0
    if args.command == "sweep-publications":
        env = _load_named_env(("DISCORD_WEBHOOK_SPEC_DEMOS", "SPEC_DEMO_APPROVED_ARTIFACT_LINK", "SPEC_DEMO_ARTIFACT_HOSTS"))
        webhook = resolve_discord_webhook(env)
        print(
            json.dumps(
                sweep_publications(
                    args.root,
                    now=datetime.now(timezone.utc),
                    webhook_url=webhook,
                    approved_artifact_link=env["SPEC_DEMO_APPROVED_ARTIFACT_LINK"],
                    approved_artifact_hosts=resolve_artifact_hosts(env["SPEC_DEMO_ARTIFACT_HOSTS"]),
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
