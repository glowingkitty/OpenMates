"""Ephemeral fal H3 Max Turbo queue client for the video-call experiment.

Only server-created requests are accepted. Provider URLs are never taken from the
browser, and returned media is downloaded into memory from fal's CDN only.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

MODEL = "minimax/h3-max-turbo/image-to-video"
QUEUE_URL = f"https://queue.fal.run/{MODEL}"
MAX_VIDEO_BYTES = 20 * 1024 * 1024  # browser's 28 MB encoded-message bound
POLL_SECONDS = 0.7
POLL_LIMIT_SECONDS = 75
JOB_LIMIT_SECONDS = 90  # Include polling, result, CDN download and frame extraction.


@dataclass(frozen=True)
class FalJob:
    request_id: str
    status_url: str
    result_url: str
    cancel_url: str


@dataclass(frozen=True)
class FalClip:
    data: bytes
    reported_duration: float | None
    measured_duration: float | None
    request_id: str
    last_frame_jpeg: bytes | None = None


class FalCompletedMediaError(RuntimeError):
    """Generation completed and is billable, but result media was unavailable."""

    def __init__(self, request_id: str, reported_duration: float | None = None):
        super().__init__("Completed fal media could not be delivered")
        self.request_id = request_id
        self.reported_duration = reported_duration


class FalProviderFailed(RuntimeError):
    """The provider reported failure, so generated duration is not established."""


def _validated_queue_url(value: Any, *, request_id: str, suffix: str) -> str:
    """Allow only fal queue URLs for this model family and exact request ID."""
    if not isinstance(value, str):
        raise ValueError("fal queue URL missing")
    parsed = urlparse(value)
    prefix = parsed.path.removesuffix(f"/requests/{request_id}{suffix}")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "queue.fal.run"
        or parsed.path != f"{prefix}/requests/{request_id}{suffix}"
        or prefix not in {"/minimax/h3-max-turbo", f"/{MODEL}"}
        or parsed.query or parsed.fragment
    ):
        raise ValueError("Unexpected fal queue URL")
    return value


def _validated_media_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("fal media URL missing")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or not (
        parsed.hostname == "fal.media" or parsed.hostname.endswith(".fal.media")
    ) or parsed.username or parsed.password or parsed.port:
        raise ValueError("Unexpected fal media URL")
    return value


def _mp4_duration(data: bytes) -> float | None:
    """Read the ISO-BMFF movie header without writing a media file to disk."""
    def atoms(start: int, end: int):
        pos = start
        while pos + 8 <= end:
            size = int.from_bytes(data[pos:pos + 4], "big")
            header = 8
            if size == 1 and pos + 16 <= end:
                size = int.from_bytes(data[pos + 8:pos + 16], "big")
                header = 16
            elif size == 0:
                size = end - pos
            if size < header or pos + size > end:
                return
            yield data[pos + 4:pos + 8], pos + header, pos + size
            pos += size

    for kind, start, end in atoms(0, len(data)):
        if kind != b"moov":
            continue
        for child, head, tail in atoms(start, end):
            if child != b"mvhd" or head + 20 > tail:
                continue
            version = data[head]
            offset = head + (20 if version == 1 else 12)
            width = 8 if version == 1 else 4
            if offset + 4 + width > tail:
                continue
            timescale = int.from_bytes(data[offset:offset + 4], "big")
            duration = int.from_bytes(data[offset + 4:offset + 4 + width], "big")
            if timescale and duration:
                seconds = duration / timescale
                if 0 < seconds < 30:
                    return seconds
    return None


async def _last_frame_jpeg(data: bytes) -> bytes | None:
    """Sample the end of a generated MP4 via ffmpeg pipes; never persist it."""
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-t", "6", "-vf", "fps=2,scale=640:360:force_original_aspect_ratio=decrease", "-f", "image2pipe",
            "-vcodec", "mjpeg", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(process.communicate(data), timeout=8)
        if process.returncode != 0 or len(output) > 3 * 1024 * 1024:
            return None
        end = output.rfind(b"\xff\xd9") + 2
        start = output.rfind(b"\xff\xd8", 0, end)
        if start < 0 or end <= start or end - start > 256 * 1024:
            return None
        return output[start:end]
    except (OSError, asyncio.TimeoutError):
        return None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await asyncio.shield(process.wait())


async def submit_clip(client: httpx.AsyncClient, *, key: str, prompt: str, image_jpeg: bytes | None) -> FalJob:
    if not prompt or len(prompt) > 3000:
        raise ValueError("Video prompt length is invalid")
    payload: dict[str, Any] = {
        "prompt": prompt,
        "duration": 5,
        "resolution": "480P",
        "prompt_expansion_mode": "disabled",
        "enable_safety_checker": True,
    }
    if image_jpeg is not None:
        import base64
        payload["image_url"] = "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")
    response = await client.post(
        QUEUE_URL, json=payload, headers={"Authorization": f"Key {key}"}
    )
    response.raise_for_status()
    result = response.json()
    request_id = result.get("request_id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 100 or not all(
        ch.isalnum() or ch in "-_" for ch in request_id
    ):
        raise ValueError("fal request ID missing")
    # Queue status/result URLs can omit the model's final endpoint segment.
    # Trust only fal's queue host, this model family and the accepted request ID.
    status_url = _validated_queue_url(result.get("status_url"), request_id=request_id, suffix="/status")
    result_url = _validated_queue_url(result.get("response_url"), request_id=request_id, suffix="")
    cancel_url = _validated_queue_url(result.get("cancel_url") or result_url + "/cancel", request_id=request_id, suffix="/cancel")
    return FalJob(request_id, status_url, result_url, cancel_url)


async def cancel_clip(client: httpx.AsyncClient, *, key: str, job: FalJob) -> bool:
    """Best effort: a running provider job can still be billed after cancellation."""
    try:
        response = await client.put(job.cancel_url, headers={"Authorization": f"Key {key}"})
        return response.is_success
    except httpx.HTTPError:
        return False


async def await_clip(client: httpx.AsyncClient, *, key: str, job: FalJob) -> FalClip:
    """Bound all work for one accepted job, including slow or trickling media."""
    headers = {"Authorization": f"Key {key}"}
    deadline = asyncio.get_running_loop().time() + POLL_LIMIT_SECONDS
    completed = False
    reported_seconds: float | None = None

    async def finish() -> FalClip:
        nonlocal completed, reported_seconds
        while asyncio.get_running_loop().time() < deadline:
            status = await client.get(job.status_url, headers=headers)
            status.raise_for_status()
            status_data = status.json()
            state = status_data.get("status")
            if state == "COMPLETED":
                if status_data.get("error") or status_data.get("error_type"):
                    raise FalProviderFailed("fal completed with provider error")
                completed = True
                break
            if state in {"FAILED", "CANCELLED"}:
                raise FalProviderFailed(f"fal job {state.lower()}")
            await asyncio.sleep(POLL_SECONDS)
        else:
            raise TimeoutError("fal job timed out")

        try:
            response = await client.get(job.result_url, headers=headers)
            response.raise_for_status()
            result = response.json()
            if result.get("error") or result.get("error_type"):
                raise FalProviderFailed("fal result reported provider error")
            video = result.get("video") or {}
            if not isinstance(video, dict):
                raise ValueError("fal video response is invalid")
            reported = video.get("duration") or result.get("duration")
            reported_seconds = float(reported) if isinstance(reported, (int, float)) and 0 < reported < 30 else None
            url = _validated_media_url(video.get("url"))
            media = bytearray()
            async with client.stream("GET", url, follow_redirects=False) as download:
                download.raise_for_status()
                if download.headers.get("content-type", "").split(";")[0] not in {"video/mp4", "application/octet-stream"}:
                    raise ValueError("fal did not return MP4 media")
                async for chunk in download.aiter_bytes():
                    media.extend(chunk)
                    if len(media) > MAX_VIDEO_BYTES:
                        raise ValueError("fal video exceeds size limit")
            if not media:
                raise ValueError("fal video is empty")
            return FalClip(bytes(media), reported_seconds, _mp4_duration(media), job.request_id, await _last_frame_jpeg(media))
        except FalProviderFailed:
            raise
        except Exception as exc:
            raise FalCompletedMediaError(job.request_id, reported_seconds) from exc

    try:
        return await asyncio.wait_for(finish(), timeout=JOB_LIMIT_SECONDS)
    except TimeoutError as exc:
        if completed:
            raise FalCompletedMediaError(job.request_id, reported_seconds) from exc
        raise
