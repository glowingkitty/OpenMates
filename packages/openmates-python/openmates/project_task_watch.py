"""PRIVATE DRAFT: direct typed watch; no CLI/profile or implicit receipt commits."""

from __future__ import annotations
import json
from collections.abc import AsyncIterator
from typing import Any, Literal, TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    from .session_client import SessionClient


class SessionProjectTaskWatchScope(TypedDict):
    api_url: str
    account_id: str
    workspace: Literal["personal"] | dict[Literal["team"], str]
    project_id: str
    source_id: str


class SessionProjectTaskWatchReceipt(TypedDict):
    batch_id: str
    cursor: str


class SessionProjectTaskWatchCheckpoint(TypedDict):
    scope: SessionProjectTaskWatchScope
    cursor: str
    tasks: list[dict[str, Any]]


class SessionProjectTaskWatchTask(TypedDict):
    task_id: str
    task: dict[str, Any]


class SessionProjectTaskWatchSnapshot(TypedDict):
    kind: Literal["snapshot"]
    scope: SessionProjectTaskWatchScope
    cursor: str | None
    tasks: list[SessionProjectTaskWatchTask]
    receipt: SessionProjectTaskWatchReceipt
    checkpoint: SessionProjectTaskWatchCheckpoint


class SessionProjectTaskWatchState(TypedDict):
    kind: Literal["state"]
    state: Literal[
        "starting",
        "reconnecting",
        "connected",
        "revoked",
        "expired",
        "closed",
        "failed",
    ]
    cursor: str | None


SessionProjectTaskWatchEvent = (
    SessionProjectTaskWatchSnapshot | SessionProjectTaskWatchState
)


class SessionProjectTaskWatch(AsyncIterator[SessionProjectTaskWatchEvent]):
    def __init__(self, client: SessionClient, id: str):
        self._client = client
        self._id = id
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> SessionProjectTaskWatchEvent:
        if self._closed:
            raise StopAsyncIteration
        try:
            event = json.loads(
                await self._client._call(
                    lambda: self._client._native.project_task_watch_next(self._id)
                )
            )
            if not isinstance(event, dict) or event.get("kind") not in (
                "snapshot",
                "state",
            ):
                from .session_client import SessionClientError

                raise SessionClientError(
                    "protocol", "Invalid Project Task watch event."
                )
            if event["kind"] == "state" and event.get("state") in (
                "revoked",
                "expired",
                "closed",
                "failed",
            ):
                await self.close()
            return event
        except BaseException:
            try:
                self._close_priority()
            except Exception:
                pass
            raise

    async def commit(self, receipt: SessionProjectTaskWatchReceipt) -> None:
        """Commit only after the exact snapshot/checkpoint is durably published."""
        from .session_client import SessionClientError

        if self._closed:
            raise SessionClientError("cancelled", "The Project Task watch is closed.")
        if (
            type(receipt) is not dict
            or set(receipt) != {"batch_id", "cursor"}
            or any(type(receipt[k]) is not str for k in receipt)
        ):
            raise SessionClientError(
                "invalid_argument", "Supply the exact local publication receipt."
            )
        await self._client._call(
            lambda: self._client._native.project_task_watch_commit(
                self._id, json.dumps(receipt, ensure_ascii=False, allow_nan=False)
            )
        )

    def _close_priority(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client._native.project_task_watch_close(self._id)
        except Exception as error:
            from .session_client import _failure

            raise _failure(error) from None

    async def close(self) -> None:
        self._close_priority()

    async def aclose(self) -> None:
        self._close_priority()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self._close_priority()

    def __del__(self):
        try:
            self._close_priority()
        except Exception:
            pass
