"""Private direct-native essential draft. No CLI, implicit credentials or auto ACK.

Store JSON values are exact opaque Rust UTF8 strings, never parse/rewrite them.
All writers sharing a scope must use one atomic durable CAS generation.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Protocol
from .startup_sync import SessionInitialSyncOperation

if TYPE_CHECKING:
    from .session_client import SessionClient


class SessionDurableStore(Protocol):
    async def generation(self, scope: dict[str, Any]) -> str | None: ...
    async def compare_and_swap(self, input: dict[str, Any]) -> dict[str, Any]:
        """Atomically CAS generation, fsync exact UTF8, return actual stored hash/revision."""
        ...


class SessionChatMonitor:
    def __init__(self, client: SessionClient, id: str, scope: dict[str, Any]):
        self._client = client
        self._id = id
        self._scope = dict(scope)
        self._epoch = client._essential_epoch
        self._closed = False

    def __repr__(self):
        return "<openmates.SessionChatMonitor>"

    @property
    def scope(self) -> dict[str, Any]:
        return dict(self._scope)

    def _valid(self):
        from .session_client import SessionClientError

        if self._closed or self._epoch != self._client._essential_epoch:
            raise SessionClientError(
                "cancelled", "The session monitor is no longer current."
            )

    def __aiter__(self):
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._closed:
            raise StopAsyncIteration
        try:
            self._valid()
            raw = await self._client._essential_call(
                lambda: self._client._native.chat_monitor_next(self._id)
            )
            self._valid()
            value = json.loads(raw)
            if value.get("kind") == "access_denial":
                return value
            if value.get("kind") != "invalidation" or not isinstance(
                value.get("recovery_chat_ids"), list
            ):
                from .session_client import SessionClientError

                raise SessionClientError(
                    "protocol", "Invalid keyless chat invalidation."
                )
            return value
        except BaseException:
            self._close_priority()
            raise

    def access_denial(self) -> dict[str, Any] | None:
        try:
            return json.loads(self._client._native.chat_monitor_access_denial(self._id))
        except Exception as error:
            from .session_client import _failure

            raise _failure(error) from None

    async def validate(self)->None:
        """Explicit foreground reauthorization; persist rotated credentials even on failure."""
        self._valid()
        await self._client._essential_call(lambda:self._client._native.chat_monitor_validate(self._id))
        self._valid()

    def begin_initial_sync(self) -> SessionInitialSyncOperation:
        self._valid()
        # Synchronous native admission precedes any scheduled run coroutine.
        from .session_client import _failure
        try:
            native = self._client._native.initial_sync_open(self._id)
        except Exception as error:
            raise _failure(error) from None
        try:
            self._valid()
            return SessionInitialSyncOperation(self._client, self, native)
        except BaseException:
            native.cancel()
            raise

    async def stage_refresh(
        self, *, include_secrets: bool, selected_chat_id: str | None = None
    ) -> dict[str, Any]:
        from .session_client import SessionClientError

        self._valid()
        if include_secrets is not True:
            raise SessionClientError(
                "invalid_argument", "Explicit credential storage consent is required."
            )
        ticket = asyncio.create_task(
            self._client._essential_call(
                lambda: self._client._native.chat_monitor_stage(
                    self._id, True, selected_chat_id
                )
            )
        )
        try:
            raw = await asyncio.shield(ticket)
        except asyncio.CancelledError:

            async def discard_admitted():
                try:
                    value = json.loads(await ticket)
                    self._client._native.chat_monitor_discard(self._id, value["id"])
                except Exception:
                    pass

            asyncio.create_task(discard_admitted())
            raise
        self._valid()
        value = json.loads(raw)
        if any(
            type(value.get(key)) is not str
            for key in (
                "id",
                "checkpoint_json",
                "credentials_json",
                "ciphertext_sha256",
            )
        ):
            raise SessionClientError("protocol", "Invalid durable refresh stage.")
        return value

    async def stage_refresh_prefer_cache(
        self, *, include_secrets: bool, selected_chat_id: str | None = None
    ) -> dict[str, Any]:
        from .session_client import SessionClientError

        self._valid()
        if include_secrets is not True:
            raise SessionClientError(
                "invalid_argument", "Explicit credential storage consent is required."
            )
        ticket = asyncio.create_task(
            self._client._call(
                lambda: self._client._native.chat_monitor_stage_prefer_cache(
                    self._id, True, selected_chat_id
                )
            )
        )
        try:
            raw = await asyncio.shield(ticket)
        except asyncio.CancelledError:

            async def discard_admitted():
                try:
                    value = json.loads(await ticket)
                    self._client._native.chat_monitor_discard(self._id, value["id"])
                except Exception:
                    pass

            asyncio.create_task(discard_admitted())
            raise
        value = json.loads(raw)
        try:
            self._valid()
        except Exception:
            try:
                self._client._native.chat_monitor_discard(self._id, value["id"])
            except Exception:
                pass
            raise
        if any(
            type(value.get(key)) is not str
            for key in (
                "id",
                "checkpoint_json",
                "credentials_json",
                "ciphertext_sha256",
            )
        ):
            raise SessionClientError("protocol", "Invalid durable refresh stage.")
        return value

    async def commit_refresh(
        self, stage_id: str, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        self._valid()
        raw = await self._client._essential_call(
            lambda: self._client._native.chat_monitor_commit(
                self._id, stage_id, json.dumps(receipt, allow_nan=False)
            )
        )
        self._valid()
        return json.loads(raw)

    async def discard_refresh(self, stage_id: str) -> None:
        self._valid()
        try:
            self._client._native.chat_monitor_discard(self._id, stage_id)
        except Exception as error:
            from .session_client import _failure

            raise _failure(error) from None

    async def refresh_and_publish(
        self,
        store: SessionDurableStore,
        *,
        include_secrets: bool,
        selected_chat_id: str | None = None,
    ) -> dict[str, Any]:
        from .session_client import SessionClientError

        self._valid()
        expected = await store.generation(self.scope)
        self._valid()
        stage = await self.stage_refresh(
            include_secrets=include_secrets, selected_chat_id=selected_chat_id
        )
        committed = False
        try:
            receipt = await store.compare_and_swap(
                {
                    "scope": self.scope,
                    "expected_version": expected,
                    "next_version": stage["id"],
                    "checkpoint_json": stage["checkpoint_json"],
                    "credentials_json": stage["credentials_json"],
                    "ciphertext_sha256": stage["ciphertext_sha256"],
                    "credential_revision": stage["credential_revision"],
                }
            )
            self._valid()
            if receipt.get("stored") is not True:
                raise SessionClientError(
                    "conflict",
                    "A newer durable session snapshot won the storage transaction.",
                )
            result = await self.commit_refresh(
                stage["id"],
                {
                    key: receipt[key]
                    for key in ("ciphertext_sha256", "credential_revision")
                },
            )
            committed = True
            return result
        finally:
            if not committed:
                try:
                    await self.discard_refresh(stage["id"])
                except Exception:
                    pass

    def _close_priority(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._client._native.chat_monitor_close(self._id)
        except Exception as error:
            from .session_client import _failure

            raise _failure(error) from None

    async def close(self):
        self._close_priority()

    async def aclose(self):
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


class SessionCompletionRecovery:
    def __init__(self, client: SessionClient):
        self._client = client

    def __repr__(self):
        return "<openmates.SessionCompletionRecovery>"

    async def discard(self, stage_id: str) -> None:
        try:
            self._client._native.completion_recovery_discard(stage_id)
        except Exception as error:
            from .session_client import _failure

            raise _failure(error) from None

    async def _admission(self, operation):
        ticket = asyncio.create_task(self._client._essential_call(operation))
        try:
            return json.loads(await asyncio.shield(ticket))
        except asyncio.CancelledError:

            async def discard_admitted():
                try:
                    value = json.loads(await ticket)
                    if value.get("kind") == "ready":
                        self._client._native.completion_recovery_discard(value["id"])
                except Exception:
                    pass

            asyncio.create_task(discard_admitted())
            raise

    async def enable(self, enabled: bool) -> None:
        """Explicit Cookie foreground opt-in; default disabled, real Pip identity."""
        await self._client._essential_call(
            lambda: self._client._native.completion_recovery_enable(enabled)
        )

    async def jobs(self) -> list[dict[str, Any]]:
        return json.loads(
            await self._client._essential_call(
                lambda: self._client._native.completion_recovery_jobs()
            )
        )

    async def jobs_for_chat(self, chat_id: str) -> list[dict[str, Any]]:
        """Selected offers only; no global inventory, absence or list TTL proof."""
        return json.loads(await self._client._essential_call(
            lambda: self._client._native.completion_recovery_jobs_for_chat(chat_id)
        ))

    async def stage(self, job_handle: str) -> dict[str, Any]:
        return await self._admission(
            lambda: self._client._native.completion_recovery_stage(job_handle)
        )

    async def resume(self, checkpoint_json: str) -> dict[str, Any]:
        """Opaque exact UTF8; core reauthenticates, the DTO is never authority."""
        return await self._admission(
            lambda: self._client._native.completion_recovery_resume(checkpoint_json)
        )

    async def commit(self, stage_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Call only after the exact checkpoint bytes have been durably stored."""
        return json.loads(
            await self._client._essential_call(
                lambda: self._client._native.completion_recovery_commit(
                    stage_id, json.dumps(receipt, allow_nan=False)
                )
            )
        )
