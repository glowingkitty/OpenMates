# backend/shared/python_utils/video_frames.py
#
# ffmpeg/ffprobe helpers for generated MP4 clips: probe the real duration and
# size, extract the first or last frame as JPEG (used to chain clips), a frame
# at a given time, and the first/middle/last frames a safety review looks at.
# Pure utility: no skill, embed, storage or provider imports. All subprocess
# calls have timeouts and temporary files are always removed.

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Literal, Sequence

FFMPEG_TIMEOUT_SECONDS = 60.0
FRAME_JPEG_QUALITY = 2  # ffmpeg -q:v scale, 2 = near-lossless JPEG
# Seek this far before the end when extracting the last frame; the final
# decodable frame is then taken with -update 1 (keeps overwriting the output).
LAST_FRAME_SEEK_SECONDS = 0.5


class VideoFrameError(RuntimeError):
    """ffmpeg/ffprobe failed, timed out, or the input is not a valid video."""


@dataclass(frozen=True)
class VideoInfo:
    """Measured properties of an MP4 stream."""

    duration_seconds: float
    width: int
    height: int
    fps: float


async def _run(*args: str) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise VideoFrameError(f"{args[0]} is not installed") from exc
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=FFMPEG_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise VideoFrameError(f"{args[0]} timed out") from exc
    if process.returncode != 0:
        tail = stderr.decode("utf-8", "replace").strip()[-300:]
        raise VideoFrameError(f"{args[0]} failed ({process.returncode}): {tail}")
    return stdout


def _write_temp(data: bytes, suffix: str) -> str:
    handle, path = tempfile.mkstemp(suffix=suffix, prefix="om_video_")
    with os.fdopen(handle, "wb") as file:
        file.write(data)
    return path


def _parse_fps(rate: str) -> float:
    numerator, _, denominator = rate.partition("/")
    try:
        den = float(denominator) if denominator else 1.0
        return float(numerator) / den if den else 0.0
    except ValueError:
        return 0.0


async def probe_video(mp4: bytes) -> VideoInfo:
    """Return measured duration, size and frame rate of an MP4."""
    path = _write_temp(mp4, ".mp4")
    try:
        raw = await _run(
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path,
        )
    finally:
        os.unlink(path)
    try:
        payload = json.loads(raw)
        stream = next(s for s in payload["streams"] if s.get("codec_type") == "video")
        duration = float(stream.get("duration") or payload["format"]["duration"])
        return VideoInfo(
            duration_seconds=duration,
            width=int(stream["width"]),
            height=int(stream["height"]),
            fps=_parse_fps(str(stream.get("avg_frame_rate", "0/1"))),
        )
    except (StopIteration, KeyError, ValueError, TypeError) as exc:
        raise VideoFrameError("ffprobe output has no usable video stream") from exc


async def extract_frame(mp4: bytes, *, position: Literal["first", "last"]) -> bytes:
    """Extract the first or last frame of an MP4 as JPEG bytes."""
    if position not in ("first", "last"):
        raise ValueError("position must be 'first' or 'last'")
    video_path = _write_temp(mp4, ".mp4")
    frame_path = video_path + ".jpg"
    try:
        args = ["ffmpeg", "-v", "error", "-y"]
        if position == "last":
            args += ["-sseof", f"-{LAST_FRAME_SEEK_SECONDS}"]
        args += ["-i", video_path, "-q:v", str(FRAME_JPEG_QUALITY)]
        args += ["-update", "1", "-frames:v", "999" if position == "last" else "1", frame_path]
        await _run(*args)
        if not os.path.exists(frame_path):
            raise VideoFrameError("ffmpeg produced no frame")
        with open(frame_path, "rb") as file:
            data = file.read()
    finally:
        for path in (video_path, frame_path):
            if os.path.exists(path):
                os.unlink(path)
    if not data:
        raise VideoFrameError("ffmpeg produced an empty frame")
    return data


async def extract_frame_at(mp4: bytes, *, seconds: float) -> bytes:
    """Extract the frame shown at ``seconds`` as JPEG bytes."""
    if seconds < 0:
        raise ValueError("seconds must not be negative")
    video_path = _write_temp(mp4, ".mp4")
    frame_path = video_path + ".jpg"
    try:
        await _run("ffmpeg", "-v", "error", "-y", "-ss", f"{seconds:.3f}", "-i", video_path,
                   "-q:v", str(FRAME_JPEG_QUALITY), "-frames:v", "1", frame_path)
        if not os.path.exists(frame_path):
            raise VideoFrameError("ffmpeg produced no frame")
        with open(frame_path, "rb") as file:
            data = file.read()
    finally:
        for path in (video_path, frame_path):
            if os.path.exists(path):
                os.unlink(path)
    if not data:
        raise VideoFrameError("ffmpeg produced an empty frame")
    return data


async def review_frames(mp4: bytes) -> Sequence[bytes]:
    """First, middle and last frame of an MP4 (JPEG), the frames an output safety check looks at."""
    info = await probe_video(mp4)
    return (
        await extract_frame(mp4, position="first"),
        await extract_frame_at(mp4, seconds=info.duration_seconds / 2),
        await extract_frame(mp4, position="last"),
    )
