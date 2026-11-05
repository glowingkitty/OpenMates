"""Typed encrypted source authoring; metadata and local root approval stay distinct."""

from __future__ import annotations
import json
import math
from typing import Any, Literal, TypedDict

SessionProjectSourceType = Literal[
    "local_folder", "local_git_repository", "remote_folder", "remote_git_repository"
]
SessionProjectSourceCapability = Literal[
    "read", "search", "import", "write_request", "run_command"
]
SessionProjectSourceStatus = Literal[
    "connected", "offline", "permission_required", "revoked"
]


class _SessionProjectSourceFields(TypedDict):
    source_id: str
    source_type: SessionProjectSourceType
    display_name: str
    metadata: dict[str, Any]
    capabilities: list[SessionProjectSourceCapability]
    status: SessionProjectSourceStatus
    created_at: int
    updated_at: int


class _SessionProjectSourceCreateOptional(TypedDict, total=False):
    last_indexed_at: int | None


class SessionProjectSourceCreate(
    _SessionProjectSourceFields, _SessionProjectSourceCreateOptional
):
    pass


class SessionProjectSourceCapabilitiesPatch(TypedDict):
    capabilities: list[SessionProjectSourceCapability]
    updated_at: int


class SessionProjectSource(_SessionProjectSourceFields):
    last_indexed_at: int | None


class OpenMatesProjectSourceAuthoringUnavailableError(RuntimeError):
    code = "project_source_authoring_unavailable"
    reason = "PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION"

    def __init__(self):
        super().__init__(self.reason)


def source_json(value: object, *, patch: bool = False) -> str:
    # Imported lazily to avoid a SessionClient/type-module import cycle.
    from .session_client import SessionClientError

    try:
        fields = (
            {"capabilities", "updated_at"}
            if patch
            else {
                "source_id",
                "source_type",
                "display_name",
                "metadata",
                "capabilities",
                "status",
                "created_at",
                "updated_at",
                "last_indexed_at",
            }
        )
        if type(value) is not dict or not set(value).issubset(fields):
            raise ValueError()
        if not patch and type(value.get("metadata")) is not dict:
            raise ValueError()
        budget = 1024 * 1024
        active: set[int] = set()

        def visit(item, depth):
            nonlocal budget
            if depth > 128:
                raise ValueError()
            if item is None or type(item) is bool:
                budget -= 4
            elif type(item) is str:
                if len(item) > 1024 * 1024:
                    raise ValueError()
                budget -= len(item.encode("utf-8"))
            elif type(item) in (float, int):
                if type(item) is float and not math.isfinite(item):
                    raise ValueError()
                budget -= 1
            elif type(item) in (dict, list):
                if id(item) in active:
                    raise ValueError()
                active.add(id(item))
                budget -= 2
                for key, child in (
                    item.items() if type(item) is dict else enumerate(item)
                ):
                    if type(item) is dict:
                        if type(key) is not str:
                            raise ValueError()
                        if len(key) > 1024 * 1024:
                            raise ValueError()
                        budget -= len(key.encode("utf-8")) + 3
                    visit(child, depth + 1)
                active.remove(id(item))
            else:
                raise ValueError()
            if budget < 0:
                raise ValueError()

        visit(value, 0)
        chunks = []
        size = 0
        for chunk in json.JSONEncoder(
            ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > 1024 * 1024:
                raise ValueError()
            chunks.append(chunk)
        return "".join(chunks)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise SessionClientError(
            "invalid_argument", "Invalid typed Project source input."
        ) from None


class SessionProjectSourcesDecodedNames(TypedDict):
    """Canonical resolved ID; each raw row adds decoded display_name only."""
    project_id: str
    sources: list[Any]
