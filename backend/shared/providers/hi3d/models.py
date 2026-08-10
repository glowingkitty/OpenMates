"""Typed normalized models for the Hi3D API.

Provider response details stay in this shared package so skills and workers can
consume a stable contract without reproducing Hi3D-specific state strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Hi3DTaskState(str, Enum):
    """Normalized asynchronous task states."""

    CREATED = "created"
    QUEUEING = "queueing"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class Hi3DView(str, Enum):
    """Hi3D multi-view positions in required provider order."""

    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class Hi3DTaskResult:
    """Successful normalized task output."""

    task_id: str
    state: Hi3DTaskState
    model_url: str
    cover_url: str | None = None
    content_id: str | None = None
