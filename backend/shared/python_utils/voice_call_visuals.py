"""Bounded, call-local camera ingress and exact uploaded source authorization.

Background frames never enter storage. Only a user turn freezes a source; its
browser upload is independently checked before a tool may consume that image.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import math
import re
import time
from typing import Any

MAX_FRAME_BYTES = 256 * 1024
MAX_SOURCE_FRAMES = 8
SOURCE_SAVE_TIMEOUT = 20
MAX_FRAME_AGE_SECONDS = 60
FRAME_TOKEN_RESERVE = 258  # Admission only; actual IMAGE/VIDEO provider usage bills.
_FRAME_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class CameraFrame:
    frame_id: str
    data: str
    captured_at: int
    content_hash: str


class VoiceCallVisuals:
    def __init__(self) -> None:
        self.enabled = False
        self.latest: CameraFrame | None = None
        self.last_frame_at = -math.inf
        self.latest_received_at = -math.inf
        self.sources: dict[str, tuple[CameraFrame, asyncio.Future]] = {}

    def set_enabled(self, enabled: Any) -> None:
        if type(enabled) is not bool:
            raise ValueError("Invalid camera state")
        self.enabled = enabled
        if not enabled:
            self.latest = None

    def accept(self, event: dict, *, now: float | None = None) -> CameraFrame | None:
        from PIL import Image
        now = time.monotonic() if now is None else now
        if not self.enabled:
            raise ValueError("Camera is disabled")
        frame_id, encoded, captured = event.get("frame_id"), event.get("data"), event.get("captured_at")
        if (not isinstance(frame_id, str) or not _FRAME_ID.fullmatch(frame_id)
                or not isinstance(encoded, str) or len(encoded) > MAX_FRAME_BYTES * 4 // 3 + 8
                or isinstance(captured, bool) or not isinstance(captured, (int, float))
                or not math.isfinite(captured) or abs(captured - time.time() * 1000) > 60_000):
            raise ValueError("Invalid camera frame")
        try:
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > MAX_FRAME_BYTES:
                raise ValueError("Invalid camera frame size")
            with Image.open(BytesIO(raw)) as image:
                if image.format != "JPEG" or not (1 <= image.width <= 1280 and 1 <= image.height <= 720):
                    raise ValueError("Invalid camera frame dimensions")
                image.verify()
        except Exception as exc:
            raise ValueError("Invalid camera JPEG") from exc
        # Network timing can compress otherwise valid one-second observations,
        # and switching cameras must not reset the call's provider budget.
        # Drop excess samples without turning a healthy camera into an error or
        # replacing the exact source most recently admitted to the provider.
        if now - self.last_frame_at < 1:
            return None
        self.latest = CameraFrame(frame_id, encoded, int(captured), hashlib.sha256(raw).hexdigest())
        self.last_frame_at = now
        self.latest_received_at = time.monotonic()
        return self.latest

    @property
    def camera_active(self) -> bool:
        """Only recent admitted input contributes activity or a new source."""
        return (self.enabled and self.latest is not None
            and time.monotonic() - self.latest_received_at <= MAX_FRAME_AGE_SECONDS
            and abs(time.time() * 1000 - self.latest.captured_at) <= MAX_FRAME_AGE_SECONDS * 1000)

    def freeze(self, user_message_id: str) -> CameraFrame | None:
        if user_message_id in self.sources:
            return None
        if not self.camera_active:
            self.latest = None
            return None
        if len(self.sources) >= MAX_SOURCE_FRAMES:
            first = next(iter(self.sources))
            _, old = self.sources.pop(first)
            if not old.done():
                old.set_result(None)
        self.sources[user_message_id] = (self.latest, asyncio.get_running_loop().create_future())
        return self.latest

    async def acknowledge(self, event: dict, *, directus: Any, user_id: str) -> None:
        if not isinstance(event.get("user_message_id"), str) or not isinstance(event.get("frame_id"), str):
            raise ValueError("Invalid camera source acknowledgement")
        source = self.sources.get(event.get("user_message_id"))
        if source is None or source[0].frame_id != event.get("frame_id") or source[1].done():
            raise ValueError("Unknown camera source acknowledgement")
        frame, future = source
        if event.get("type") == "source_frame_failed":
            future.set_result(None)
            return
        reference = event.get("embed_reference")
        if (not isinstance(reference, dict) or set(reference) != {"type", "embed_id"}
                or reference.get("type") != "image" or not isinstance(reference.get("embed_id"), str)
                or not _FRAME_ID.fullmatch(reference["embed_id"])):
            raise ValueError("Invalid camera source reference")
        rows = await directus.get_items("upload_files", params={"filter": {"_and": [
            {"embed_id": {"_eq": reference["embed_id"]}}, {"user_id": {"_eq": user_id}},
            {"content_hash": {"_eq": frame.content_hash}}, {"content_type": {"_eq": "image/jpeg"}},
        ]}, "fields": "embed_id,user_id,content_hash,content_type", "limit": 1})
        # The bounded tool wait can expire (or the call can close/evict this
        # source) while Directus is in flight. A late ACK grants no authority
        # and must not turn an ordinary source timeout into an audio failure.
        if future.done():
            return
        if (not rows or any(rows[0].get(key) != value for key, value in (
                ("embed_id", reference["embed_id"]), ("user_id", user_id),
                ("content_hash", frame.content_hash), ("content_type", "image/jpeg")))):
            future.set_result(None)
            raise PermissionError("Camera source upload binding mismatch")
        future.set_result({"frame_id": frame.frame_id, "data": frame.data,
            "captured_at": frame.captured_at, "content_hash": frame.content_hash,
            "embed_reference": reference})

    async def source(self, user_message_id: str) -> dict | None:
        source = self.sources.get(user_message_id)
        if source is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(source[1]), SOURCE_SAVE_TIMEOUT)
        except asyncio.TimeoutError:
            if not source[1].done():
                source[1].set_result(None)
            return None

    def close(self) -> None:
        self.set_enabled(False)
        for _, future in self.sources.values():
            if not future.done():
                future.set_result(None)
        self.sources.clear()
