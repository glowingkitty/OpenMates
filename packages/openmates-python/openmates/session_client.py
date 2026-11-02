"""Async first-party sessions backed directly by the OpenMates Rust SDK.

No CLI discovery, saved-profile reads or subprocess transport. Caller-owned
session exports contain secrets and require an explicit opt-in.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Literal
from .essential_session import SessionChatMonitor, SessionCompletionRecovery
from .first_page_session import SessionFirstPageStore, SessionFirstPageCallback
# Public DTOs and errors live in session_types; this module re-exports them so
# ``openmates.session_client`` remains the stable import path.
from .session_types import (
    SessionAnonymousOptions,
    SessionAnonymousOutcome,
    SessionChatDetailsFullHistory,
    SessionChatDetailsHistory,
    SessionChatDetailsLatestHistory,
    SessionChatDetailsMessage,
    SessionChatDetailsMetadata,
    SessionChatDetailsOptions,
    SessionChatDetailsRead,
    SessionClientError,
    SessionDraftRecord,
    SessionFullChatRead,
    SessionMessageWindow,
    SessionMessageWindowCursor,
    SessionMessageWindowOptions,
    SessionPlanCreate,
    SessionPlanEvidence,
    SessionPlanFilters,
    SessionPlanFlow,
    SessionPlanPatch,
    SessionProjectCreate,
    SessionProjectFilters,
    SessionProjectPatch,
    SessionProjectUnlinkInput,
    SessionSavedChatExactMessage,
    SessionSavedChatExactOptions,
    SessionSavedChatMessageMetadata,
    SessionSavedChatRead,
    SessionSavedChatReadMetadata,
    SessionSavedChatReadOptions,
    SessionSettingsReadError,
    SessionTaskCreate,
    SessionTaskFilters,
    SessionTaskPatch,
    SessionWorkScope,
    SessionWorkflowCreate,
    SessionWorkflowFileSaveStatus,
    SessionWorkflowFileSyncOptions,
    SessionWorkflowFilters,
    SessionWorkflowGraph,
    SessionWorkflowNode,
    SessionWorkflowPatch,
    SessionWorkflowRunOptions,
    SessionWorkflowWaitOptions,
    _failure,
)
from .session_facades import SessionEmbeds, SessionDrafts, SessionTasks, SessionAccount, SessionProjects, SessionPlans, SessionWorkflows


class SessionClient:
    def __init__(
        self,
        *,
        api_url: str,
        enhanced_privacy: bool,
        allow_private_operations: bool,
        app_url: str | None = None,
    ):
        if (
            not isinstance(api_url, str)
            or not isinstance(enhanced_privacy, bool)
            or not isinstance(allow_private_operations, bool)
        ):
            raise SessionClientError(
                "invalid_argument",
                "Supply an explicit endpoint, privacy and private-operation policy.",
            )
        try:
            from ._native import NativeSessionClient
        except ImportError:
            raise SessionClientError(
                "native_binding_unavailable",
                "Install an OpenMates build containing the native session extension for this platform.",
            ) from None
        try:
            self._native = NativeSessionClient(
                json.dumps(
                    {
                        "api_url": api_url,
                        "app_url": app_url,
                        "enhanced_privacy": enhanced_privacy,
                        "allow_private_operations": allow_private_operations,
                    }
                )
            )
        except Exception as error:
            raise _failure(error) from None

        self._essential_epoch = 0
        self.completion_recovery = SessionCompletionRecovery(self)
        self.embeds = SessionEmbeds(self)
        self.drafts = SessionDrafts(self)
        self.tasks = SessionTasks(self)
        self.projects = SessionProjects(self)
        self.account = SessionAccount(self)
        self.plans = SessionPlans(self)
        self.workflows = SessionWorkflows(self)

    def __repr__(self) -> str:
        return "<openmates.SessionClient>"

    def _check_epoch(self, epoch, message="Session authority changed before native dispatch."):
        if epoch != self._essential_epoch:
            raise SessionClientError("cancelled", message)

    def _dispatch_prepared(self, operation, prepare, epoch):
        # No caller argument lookup/encoding follows the final negative check.
        # The native method receives only this operation's owned tuple values.
        self._check_epoch(epoch)
        arguments = prepare()
        self._check_epoch(epoch)
        return operation(*arguments)

    def _prepared_call(self, operation, prepare, *, epoch=None, essential=False):
        # Synchronous factory: this epoch belongs to actual invocation/ticket
        # creation, never the later first poll of a scheduled Python coroutine.
        original = self._essential_epoch if epoch is None else epoch
        async def drive():
            output = await self._call(lambda: self._dispatch_prepared(operation, prepare, original))
            if essential:
                self._check_epoch(original, "Session authority changed before essential output returned.")
            return output
        return drive()

    def _essential_call(self, operation):
        epoch = self._essential_epoch
        async def drive():
            self._check_epoch(epoch)
            output = await self._call(operation)
            self._check_epoch(epoch, "Session authority changed before essential output returned.")
            return output
        return drive()

    async def watch_chats(self) -> SessionChatMonitor:
        ticket = asyncio.create_task(self._prepared_call(self._native.chat_monitor_open, lambda: (), essential=True))
        try:
            raw = await asyncio.shield(ticket)
        except asyncio.CancelledError:
            async def abandoned_start():
                try:
                    value = json.loads(await ticket)
                    self._native.chat_monitor_close(value["id"])
                except Exception:
                    pass
            asyncio.create_task(abandoned_start())
            raise
        value = json.loads(raw)
        if type(value.get("id")) is not str or type(value.get("scope")) is not dict:
            raise SessionClientError("protocol", "Invalid chat monitor handle.")
        return SessionChatMonitor(self, value["id"], value["scope"])

    async def _call(self, operation):
        future = None
        try:
            future = operation()
            # Host cancellation must not drop a credential rotation or HTTP
            # transaction at an ambiguous commit point. The native task finishes.
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if future is not None:
                future.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )
            raise
        except Exception as error:
            raise _failure(error) from None

    async def login_password(
        self, email: str, password: str, *, tfa: str | None = None, stay_logged_in: bool = False
    ) -> dict[str, Any]:
        """Set server cookie lifetime; never select or persist local key storage."""
        if type(stay_logged_in) is not bool:
            raise SessionClientError("invalid_argument", "Invalid password login preference.")
        self._essential_epoch += 1
        return json.loads(
            await self._prepared_call(self._native.login_password, lambda: (email, password, tfa, stay_logged_in))
        )

    async def import_session(self, session: dict[str, Any]) -> None:
        self._essential_epoch += 1
        await self._prepared_call(self._native.import_session, lambda: (json.dumps(session),))

    async def export_session(self, *, include_secrets: bool) -> dict[str, Any]:
        """Return the credential revision and session only with explicit consent."""
        return json.loads(
            await self._prepared_call(self._native.export_session, lambda: (include_secrets is True,))
        )

    async def validate_session(self) -> None:
        await self._prepared_call(self._native.validate_session, lambda: ())

    async def list(
        self,
        workspace: Literal[
            "chats", "apps", "projects", "workflows", "tasks", "settings"
        ],
    ) -> list[dict[str, Any]]:
        if workspace != "apps":
            return json.loads(await self._prepared_call(self._native.list, lambda: (workspace,)))
        epoch = self._essential_epoch
        # Original opaque operation owns B cancellation before any scheduling.
        # The actual native future remains shielded to apply received headers.
        try:
            self._check_epoch(epoch, "Session authority changed before native dispatch.")
            operation = self._native.apps_inventory_open()
            self._check_epoch(epoch, "Session authority changed before native dispatch.")
            ticket = asyncio.ensure_future(operation.run())
        except Exception as error:
            raise _failure(error) from None
        try:
            output = await asyncio.shield(ticket)
        except asyncio.CancelledError:
            operation.cancel()
            async def discard_inventory():
                try:
                    (await ticket).discard()
                except Exception:
                    pass
            asyncio.create_task(discard_inventory())
            raise
        except Exception as error:
            raise _failure(error) from None
        try:
            if epoch != self._essential_epoch:
                raise SessionClientError("cancelled", "Session authority changed before inventory output returned.")
            return json.loads(output.release_json())
        except Exception as error:
            raise _failure(error) from None
        finally:
            output.discard()

    async def cache_chat_stage(self, chat_id: str, *, include_secrets: bool) -> dict[str, Any]:
        """Stage exact encrypted bytes; no plaintext publication or implicit persistence."""
        if include_secrets is not True:
            raise SessionClientError("invalid_argument", "Explicit credential storage consent is required.")
        epoch = self._essential_epoch
        ticket = asyncio.create_task(self._prepared_call(self._native.cache_chat_stage, lambda: (chat_id, True), epoch=epoch))
        try:
            raw = await asyncio.shield(ticket)
        except asyncio.CancelledError:
            async def discard_admitted():
                try:
                    value = json.loads(await ticket)
                    self._native.cache_chat_discard(value["id"])
                except Exception:
                    pass
            asyncio.create_task(discard_admitted())
            raise
        value = json.loads(raw)
        if epoch != self._essential_epoch:
            try:
                self._native.cache_chat_discard(value["id"])
            except Exception:
                pass
            raise SessionClientError("cancelled", "Session authority changed before essential output returned.")
        return value

    async def cache_chat_commit(self, stage_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Forward the actual durable write receipt; no DTO-derived ACK."""
        return json.loads(await self._essential_call(lambda: self._native.cache_chat_commit(stage_id, json.dumps(receipt, allow_nan=False))))

    async def cache_chat_discard(self, stage_id: str) -> None:
        try:
            self._native.cache_chat_discard(stage_id)
        except Exception as error:
            raise _failure(error) from None

    async def read_chat_with_first_page(self, chat_id: str, store: SessionFirstPageStore, *, include_secrets: bool, include_private_output: bool, on_first_page: SessionFirstPageCallback) -> dict[str, Any]:
        """Opt-in same-read callback; explicit durable store and both consents required."""
        from .first_page_session import read_chat_with_first_page
        return await read_chat_with_first_page(self,chat_id,store,include_secrets=include_secrets,include_private_output=include_private_output,on_first_page=on_first_page)

    async def run_skill(self, app: str, skill: str, input: dict[str, Any]) -> Any:
        """Temporary structured result; no Apps history save or automatic file download."""
        epoch = self._essential_epoch
        try:
            encoded = json.dumps(input)
        except Exception:
            raise SessionClientError("invalid_argument", "Invalid App input JSON.") from None
        # The stdlib encoder may call a dict subclass's caller-owned items().
        if epoch != self._essential_epoch:
            raise SessionClientError("cancelled", "Session authority changed before App dispatch.")

        def prepare_original():
            # _call starts in a scheduled task; queued cancellation may run first.
            if epoch != self._essential_epoch:
                raise SessionClientError("cancelled", "Session authority changed before App dispatch.")
            return self._native.run_skill_prepare(app, skill, encoded)

        ticket = asyncio.create_task(self._call(prepare_original))
        try:
            output = await asyncio.shield(ticket)
        except asyncio.CancelledError:
            async def discard_result():
                try:
                    (await ticket).discard()
                except Exception:
                    pass
            asyncio.create_task(discard_result())
            raise
        try:
            if epoch != self._essential_epoch:
                raise SessionClientError("cancelled", "Session authority changed before App output returned.")
            return json.loads(output.release_json())
        except Exception as error:
            raise _failure(error) from None
        finally:
            output.discard()

    async def chat_details(self, chat_id: str, options: SessionChatDetailsOptions | None = None) -> SessionChatDetailsRead:
        """Shared rich read, default latest limit30/stored (may return fewer), with exact omission semantics."""
        epoch = self._essential_epoch
        ticket = asyncio.create_task(self._prepared_call(self._native.chat_details_prepare, lambda: (chat_id, json.dumps({} if options is None else options)), epoch=epoch))
        try:
            output = await asyncio.shield(ticket)
        except asyncio.CancelledError:
            async def discard_read():
                try:
                    (await ticket).discard()
                except Exception:
                    pass
            asyncio.create_task(discard_read())
            raise
        try:
            if epoch != self._essential_epoch:
                raise SessionClientError("cancelled", "Session authority changed before essential output returned.")
            return json.loads(output.release_json())
        except Exception as error:
            raise _failure(error) from None
        finally:
            output.discard()

    async def open_chat(self, chat_id: str) -> SessionFullChatRead:
        """Full Rust read; optional slug comes only from authenticated encrypted metadata.

        Missing slug stays absent. This does not establish freshness/durability.
        """
        epoch = self._essential_epoch
        ticket = asyncio.create_task(self._prepared_call(self._native.open_chat_prepare, lambda: (chat_id,), epoch=epoch))
        try:
            output = await asyncio.shield(ticket)
        except asyncio.CancelledError:
            async def discard_read():
                try:
                    (await ticket).discard()
                except Exception:
                    pass
            asyncio.create_task(discard_read())
            raise
        try:
            if epoch != self._essential_epoch:
                raise SessionClientError("cancelled", "Session authority changed before essential output returned.")
            return json.loads(output.release_json())
        except Exception as error:
            raise _failure(error) from None
        finally:
            output.discard()

    async def chat_message_window(self, chat_id: str, options: SessionMessageWindowOptions | None = None) -> SessionMessageWindow:
        """Return one Rust-decrypted page; never replace complete cached history."""
        return json.loads(await self._prepared_call(self._native.chat_message_window, lambda: (chat_id, json.dumps({} if options is None else options)), essential=True))

    async def saved_chat_read(self, chat_id: str, options: SessionSavedChatReadOptions | None = None) -> SessionSavedChatRead:
        """Read at most 100 saved rows; default 30, with fixed IO and byte bounds."""
        return json.loads(await self._prepared_call(self._native.saved_chat_read, lambda: (chat_id, json.dumps({} if options is None else options)), essential=True))

    async def saved_chat_exact_message(self, chat_id: str, options: SessionSavedChatExactOptions) -> SessionSavedChatExactMessage:
        """Explicit oversized-row fallback; no complete-history/cache authority."""
        return json.loads(await self._prepared_call(self._native.saved_chat_exact_message, lambda: (chat_id, json.dumps({} if options is None else options)), essential=True))


    async def set_team(self, team_id: str | None) -> None:
        self._essential_epoch += 1
        await self._prepared_call(self._native.set_team, lambda: (team_id,))

    def cancel(self) -> None:
        self._essential_epoch += 1
        try:
            self._native.cancel()
        except Exception as error:
            raise _failure(error) from None

    def respond_to_consent(self, request_id: str, approved_ids: list[str]) -> None:
        try:
            self._native.consent(request_id, approved_ids)
        except Exception as error:
            raise _failure(error) from None

    async def stream(
        self, text: str, *, chat_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        epoch = self._essential_epoch
        try:
            startup = self._dispatch_prepared(self._native.start_send, lambda: (text, chat_id), epoch)
        except Exception as error:
            raise _failure(error) from None
        try:
            stream_id = await self._call(lambda: startup)
        except asyncio.CancelledError:
            # Admission may finish after Python abandons the await. Recover its
            # ID and cancel/drain it rather than stranding an inaccessible turn.
            async def abandoned_start():
                try:
                    admitted = await self._call(lambda: startup)
                    try:
                        self._cancel_stream(admitted)
                    except SessionClientError:
                        pass
                    await self._drain_saved_stream(admitted)
                except SessionClientError:
                    pass

            asyncio.create_task(abandoned_start())
            raise
        finished = False
        try:
            if epoch != self._essential_epoch:
                raise SessionClientError("cancelled", "Session authority changed before stream output returned.")
            while True:
                output = await self._next_saved_stream_event(stream_id)
                try:
                    if epoch != self._essential_epoch:
                        raise SessionClientError("cancelled", "Session authority changed before stream output returned.")
                    event = json.loads(output.release_json())
                except Exception as error:
                    raise _failure(error) from None
                finally:
                    output.discard()
                if event["type"] == "error":
                    finished = True
                    raise SessionClientError(
                        event["error"]["code"], event["error"]["message"]
                    )
                if event["type"] == "completed":
                    finished = True
                yield event
                if finished:
                    return
        finally:
            if not finished:
                try:
                    self._cancel_stream(stream_id)
                except SessionClientError:
                    pass
                await self._drain_saved_stream(stream_id)

    async def _next_saved_stream_event(self, stream_id):
        ticket = asyncio.create_task(self._call(lambda: self._native.next_event_prepare(stream_id)))
        try:
            return await asyncio.shield(ticket)
        except asyncio.CancelledError:
            async def discard_event():
                try:
                    (await ticket).discard()
                except Exception:
                    pass
            asyncio.create_task(discard_event())
            raise

    async def _drain_saved_stream(self, stream_id):
        try:
            while True:
                output = await self._next_saved_stream_event(stream_id)
                try:
                    terminal = output.is_terminal()
                finally:
                    output.discard()
                if terminal:
                    return
        except Exception:
            pass

    async def _drain_stream(self, stream_id):
        try:
            while True:
                event = json.loads(
                    await self._call(lambda: self._native.next_event(stream_id))
                )
                if event["type"] in {"error", "completed"}:
                    break
        except SessionClientError:
            pass

    async def send(self, text: str, *, chat_id: str | None = None) -> dict[str, Any]:
        async for event in self.stream(text, chat_id=chat_id):
            if event["type"] == "completed":
                return event["chat"]
        raise SessionClientError(
            "protocol", "The native stream ended without a result."
        )

    async def stream_anonymous(
        self,
        anonymous_id: str,
        text: str,
        *,
        options: SessionAnonymousOptions | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Ephemeral public inference; the ID is explicit and account headers are absent."""
        epoch = self._essential_epoch
        try:
            startup = self._dispatch_prepared(
                self._native.start_anonymous,
                lambda: (anonymous_id, text, json.dumps({} if options is None else options)), epoch
            )
        except Exception as error:
            raise _failure(error) from None
        try:
            stream_id = await self._call(lambda: startup)
        except asyncio.CancelledError:

            async def abandoned_start():
                try:
                    admitted = await self._call(lambda: startup)
                    self._cancel_stream(admitted)
                    await self._drain_stream(admitted)
                except SessionClientError:
                    pass

            asyncio.create_task(abandoned_start())
            raise
        finished = False
        try:
            while True:
                event = json.loads(
                    await self._call(lambda: self._native.next_event(stream_id))
                )
                if event["type"] == "error":
                    finished = True
                    raise SessionClientError(
                        event["error"]["code"], event["error"]["message"]
                    )
                if event["type"] == "completed":
                    finished = True
                    yield {
                        "type": "completed",
                        "outcome": {**event["outcome"], "chat": event["chat"]},
                    }
                    return
                yield event
        finally:
            if not finished:
                try:
                    self._cancel_stream(stream_id)
                except SessionClientError:
                    pass
                await self._drain_stream(stream_id)

    def _cancel_stream(self, stream_id: str) -> None:
        try:
            self._native.cancel_stream(stream_id)
        except Exception as error:
            raise _failure(error) from None

    async def send_anonymous(
        self,
        anonymous_id: str,
        text: str,
        *,
        options: SessionAnonymousOptions | None = None,
    ) -> SessionAnonymousOutcome:
        async for event in self.stream_anonymous(anonymous_id, text, options=options):
            if event["type"] == "completed":
                return event["outcome"]
        raise SessionClientError(
            "protocol", "The anonymous stream ended without a result."
        )

    async def logout(self) -> None:
        self._essential_epoch += 1
        await self._prepared_call(self._native.logout, lambda: ())

    async def close(self) -> None:
        self._essential_epoch += 1
        await self._call(lambda: self._native.close())

    async def __aenter__(self) -> SessionClient:
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()


__all__ = ['SessionAccount', 'SessionAnonymousOptions', 'SessionAnonymousOutcome', 'SessionChatDetailsFullHistory', 'SessionChatDetailsHistory', 'SessionChatDetailsLatestHistory', 'SessionChatDetailsMessage', 'SessionChatDetailsMetadata', 'SessionChatDetailsOptions', 'SessionChatDetailsRead', 'SessionClient', 'SessionClientError', 'SessionDraftRecord', 'SessionDrafts', 'SessionEmbeds', 'SessionFullChatRead', 'SessionMessageWindow', 'SessionMessageWindowCursor', 'SessionMessageWindowOptions', 'SessionPlanCreate', 'SessionPlanEvidence', 'SessionPlanFilters', 'SessionPlanFlow', 'SessionPlanPatch', 'SessionPlans', 'SessionProjectCreate', 'SessionProjectFilters', 'SessionProjectPatch', 'SessionProjectUnlinkInput', 'SessionProjects', 'SessionSavedChatExactMessage', 'SessionSavedChatExactOptions', 'SessionSavedChatMessageMetadata', 'SessionSavedChatRead', 'SessionSavedChatReadMetadata', 'SessionSavedChatReadOptions', 'SessionSettingsReadError', 'SessionTaskCreate', 'SessionTaskFilters', 'SessionTaskPatch', 'SessionTasks', 'SessionWorkScope', 'SessionWorkflowCreate', 'SessionWorkflowFileSaveStatus', 'SessionWorkflowFileSyncOptions', 'SessionWorkflowFilters', 'SessionWorkflowGraph', 'SessionWorkflowNode', 'SessionWorkflowPatch', 'SessionWorkflowRunOptions', 'SessionWorkflowWaitOptions', 'SessionWorkflows']
