# backend/core/api/app/services/notification_sse.py
"""Dependency-free SSE formatting helpers for safe notification streams."""

from __future__ import annotations

import json
from typing import Any


def sse_event(event_type: str, data: dict[str, Any], event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def sse_comment(comment: str) -> str:
    return f": {comment}\n\n"
