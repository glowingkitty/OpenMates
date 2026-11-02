"""Work, embed, draft and account facades of the native ``SessionClient``.

Each facade only marshals typed arguments to JSON and dispatches through the
owning client's prepared native call; the shared Rust core performs the
operation. ``session_client`` re-exports every name.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any

from .project_sources import SessionProjectSourceCreate,SessionProjectSourceCapabilitiesPatch,SessionProjectSource,SessionProjectSourcesDecodedNames,source_json
from .project_task_watch import SessionProjectTaskWatch,SessionProjectTaskWatchCheckpoint
from .session_types import (
    SessionClientError,
    SessionDraftRecord,
    SessionPlanCreate,
    SessionPlanFilters,
    SessionPlanPatch,
    SessionProjectCreate,
    SessionProjectFilters,
    SessionProjectPatch,
    SessionProjectUnlinkInput,
    SessionSettingsReadError,
    SessionTaskCreate,
    SessionTaskFilters,
    SessionTaskPatch,
    SessionWorkScope,
    SessionWorkflowCreate,
    SessionWorkflowFileSaveStatus,
    SessionWorkflowFileSyncOptions,
    SessionWorkflowFilters,
    SessionWorkflowPatch,
    SessionWorkflowRunOptions,
    SessionWorkflowWaitOptions,
    _failure,
)

if TYPE_CHECKING:
    from .session_client import SessionClient


class SessionEmbeds:
    """Explicit Personal Cookie full-ID read through the shared Rust client."""

    def __init__(self, client: SessionClient):
        self._client = client

    def share_url(self, embed_id: str, *, expires: int = 0, password: str = "") -> Awaitable[str]:
        """Await an explicit full-ID Personal read/share. Treat its URL as secret."""
        def arguments():
            if (not isinstance(embed_id, str) or not isinstance(password, str)
                    or isinstance(expires, bool) or not isinstance(expires, int)
                    or not -(1 << 63) <= expires <= (1 << 63) - 1):
                raise SessionClientError("invalid_argument", "Invalid share options.")
            return (embed_id, json.dumps(expires), password)
        # Capture the original epoch when creating the awaitable, before first poll.
        return self._client._prepared_call(self._client._native.embeds_share_url, arguments, essential=True)

    async def version_content(self, embed_id: str, version: int) -> dict[str, Any]:
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or not 1 <= version <= 9007199254740991
        ):
            raise SessionClientError("invalid_argument", "Invalid integer version.")
        return json.loads(
            await self._client._prepared_call(self._client._native.embeds_version_content, lambda: (embed_id, json.dumps(version)), essential=True)
        )


class SessionDrafts:
    """Read-only draft calls through the explicit caller-owned Rust session."""
    def __init__(self, client: SessionClient):
        self._client = client

    async def cached_list(self) -> list[SessionDraftRecord]:
        return json.loads(await self._client._prepared_call(self._client._native.drafts_list_cached, lambda: (), essential=True))

    async def list(self, *, refresh: bool = False) -> list[SessionDraftRecord]:
        return json.loads(await self._client._prepared_call(self._client._native.drafts_list, lambda: (json.dumps({"force_refresh": refresh}),), essential=True))

    async def get(self, chat_id: str, *, refresh: bool = False) -> SessionDraftRecord | None:
        return json.loads(await self._client._prepared_call(self._client._native.drafts_get, lambda: (chat_id, json.dumps({"force_refresh": refresh})), essential=True))

    async def sync(self) -> dict[str, int]:
        return json.loads(await self._client._prepared_call(self._client._native.drafts_sync, lambda: (), essential=True))


class SessionTasks:
    """Typed cookie-auth operations; every call requires explicit Personal/Team scope."""

    def __init__(self, client: SessionClient):
        self._client = client

    async def list(self, *, filters: SessionTaskFilters) -> list[dict[str, Any]]:
        return json.loads(
            await self._client._prepared_call(self._client._native.tasks_list, lambda: (json.dumps(filters),))
        )

    async def show(self, id: str, *, filters: SessionTaskFilters) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.tasks_show, lambda: (id, json.dumps(filters)))
        )

    async def create(
        self, input: SessionTaskCreate, *, filters: SessionTaskFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.tasks_create, lambda: (json.dumps(input), json.dumps(filters)))
        )

    async def update(
        self, id: str, input: SessionTaskPatch, *, filters: SessionTaskFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.tasks_update, lambda: (id, json.dumps(input), json.dumps(filters)))
        )

    async def delete(
        self, id: str, *, confirmed: bool, filters: SessionTaskFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.tasks_delete, lambda: (id, confirmed is True, json.dumps(filters)))
        )


class SessionAccount:
    """Fixed-route settings reads; Shared Rust owns all policy."""
    def __init__(self, client: SessionClient):
        self._client = client

    async def reminders(self) -> Any:
        epoch = self._client._essential_epoch
        operation = output = ticket = None
        abandoned = [False]
        try:
            self._client._check_epoch(epoch, "Session authority changed before reminders dispatch.")
            operation = self._client._native.account_reminders_open()
            self._client._check_epoch(epoch, "Session authority changed before reminders dispatch.")
            ticket = asyncio.ensure_future(operation.run())
            def settled(done):
                if abandoned[0]:
                    try:
                        done.result().discard()
                    except BaseException:
                        pass
                    operation.cancel()
            ticket.add_done_callback(settled)
            try:
                output = await asyncio.shield(ticket)
            except asyncio.CancelledError:
                abandoned[0] = True
                operation.cancel()
                try:
                    output = await asyncio.shield(ticket)
                except BaseException:
                    pass
                raise
            self._client._check_epoch(epoch, "Session authority changed before reminders publication.")
            return json.loads(output.release_json())
        except Exception as error:
            typed = _failure(error)
            if isinstance(typed, SessionSettingsReadError):
                raise typed from None
            raise SessionSettingsReadError(typed.code, str(typed), None) from None
        finally:
            try:
                if output is not None:
                    output.discard()
            finally:
                if operation is not None:
                    operation.cancel()


class SessionProjects:
    """Typed cookie-auth operations; every call requires explicit Personal/Team scope."""

    def __init__(self, client: SessionClient):
        self._client = client

    async def sync_workflow_files(self,workflow_id:str,expected_version:str,*,options:SessionWorkflowFileSyncOptions|None=None,filters:SessionProjectFilters)->list[SessionWorkflowFileSaveStatus]:
        """Headless existing bindings only; approved exact paths are local intent.

        Core still checks real scope, focus, write policy and server approval.
        cancel() invalidates original work; Task.cancel only abandons observation
        while the shielded canonical native transaction retains its own IO.
        """
        def prepare():
            if options is not None and (type(options) is not dict or any(key not in {"source_chat","approved_paths"} for key in options)):
                raise SessionClientError("invalid_argument","Invalid Workflow file synchronization options.")
            intent={} if options is None else options.copy()
            if "source_chat" in intent and type(intent["source_chat"]) is not str:
                raise SessionClientError("invalid_argument","Invalid Workflow file synchronization options.")
            if "approved_paths" in intent:
                paths=intent["approved_paths"]
                if type(paths) is not list or len(paths)>64 or any(type(path) is not str for path in paths):
                    raise SessionClientError("invalid_argument","Invalid Workflow file synchronization options.")
                intent["approved_paths"]=paths.copy()
            value={"workflow_id":workflow_id,"expected_version":expected_version,**intent}
            return (json.dumps(value,ensure_ascii=False,allow_nan=False),json.dumps(filters,ensure_ascii=False,allow_nan=False))
        return json.loads(await self._client._prepared_call(self._client._native.projects_sync_workflow_files,prepare))

    async def list_sources_raw(self, project: str, *, filters: SessionProjectFilters) -> list[Any]:
        """Return raw rows with unknown/encrypted metadata unchanged."""
        return json.loads(await self._client._prepared_call(self._client._native.projects_list_sources_raw, lambda: (project, json.dumps(filters, allow_nan=False))))

    async def list_sources_decoded_names(self, project: str, *, filters: SessionProjectFilters) -> SessionProjectSourcesDecodedNames:
        """Resolve the Project key for display names only; metadata stays raw."""
        return json.loads(await self._client._prepared_call(self._client._native.projects_list_sources_decoded_names, lambda: (project, json.dumps(filters, allow_nan=False))))

    async def create_source(self,project:str,input:SessionProjectSourceCreate,*,filters:SessionWorkScope)->SessionProjectSource:
        return json.loads(await self._client._prepared_call(self._client._native.projects_create_source, lambda: (project, source_json(input), json.dumps(filters,allow_nan=False))))

    async def update_source_capabilities(self,project:str,source_id:str,input:SessionProjectSourceCapabilitiesPatch,*,filters:SessionWorkScope)->SessionProjectSource:
        return json.loads(await self._client._prepared_call(self._client._native.projects_update_source_capabilities, lambda: (project, source_id, source_json(input,patch=True), json.dumps(filters,allow_nan=False))))

    async def watch_tasks(self,project:str,*,source_id:str,filters:SessionWorkScope,checkpoint:SessionProjectTaskWatchCheckpoint|None=None)->SessionProjectTaskWatch:
        ticket=asyncio.create_task(self._client._prepared_call(self._client._native.project_task_watch_open, lambda: (project, json.dumps({"source_id":source_id,"checkpoint":checkpoint},ensure_ascii=False,allow_nan=False), json.dumps(filters,ensure_ascii=False,allow_nan=False))))
        try:
            encoded=await asyncio.shield(ticket)
        except asyncio.CancelledError:
            # Opening has no caller-visible handle yet. Close only its exact
            # native result if the shielded admission completes after abandon.
            def close_admitted(done):
                try:
                    value=json.loads(done.result())
                    self._client._native.project_task_watch_close(value["id"])
                except BaseException:
                    pass
            ticket.add_done_callback(close_admitted)
            raise
        result=json.loads(encoded)
        if not isinstance(result,dict) or not isinstance(result.get("id"),str):
            raise SessionClientError("protocol","Invalid Project Task watch handle.")
        return SessionProjectTaskWatch(self._client,result["id"])

    async def list(self, *, filters: SessionProjectFilters) -> list[dict[str, Any]]:
        return json.loads(
            await self._client._prepared_call(self._client._native.projects_list, lambda: (json.dumps(filters),))
        )

    async def show(self, id: str, *, filters: SessionProjectFilters) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.projects_show, lambda: (id, json.dumps(filters)))
        )

    async def items(self, id: str, *, filters: SessionProjectFilters) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.projects_items, lambda: (id, json.dumps(filters)))
        )

    async def unlink_item(
        self,
        id: str,
        input: SessionProjectUnlinkInput,
        *,
        filters: SessionProjectFilters,
    ) -> dict[str, Any]:
        """Remove matching Project links while retaining the underlying object."""
        return json.loads(
            await self._client._prepared_call(self._client._native.projects_unlink_item, lambda: (id, json.dumps(input), json.dumps(filters)))
        )

    async def create(
        self, input: SessionProjectCreate, *, filters: SessionProjectFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.projects_create, lambda: (json.dumps(input), json.dumps(filters)))
        )

    async def update(
        self, id: str, input: SessionProjectPatch, *, filters: SessionProjectFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.projects_update, lambda: (id, json.dumps(input), json.dumps(filters)))
        )

    async def delete(
        self, id: str, *, confirmed: bool, filters: SessionProjectFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.projects_delete, lambda: (id, confirmed is True, json.dumps(filters)))
        )


class SessionPlans:
    """Named operations through shared typed Rust services with explicit scope."""

    def __init__(self, client: SessionClient):
        self._client = client

    async def list(self, *, filters: SessionPlanFilters) -> list[dict[str, Any]]:
        return json.loads(
            await self._client._prepared_call(self._client._native.plans_list, lambda: (json.dumps(filters),))
        )

    async def show(self, id: str, *, filters: SessionPlanFilters) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.plans_show, lambda: (id, json.dumps(filters)))
        )

    async def create(
        self, input: SessionPlanCreate, *, filters: SessionPlanFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.plans_create, lambda: (json.dumps(input), json.dumps(filters)))
        )

    async def update(
        self, id: str, input: SessionPlanPatch, *, filters: SessionPlanFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.plans_update, lambda: (id, json.dumps(input), json.dumps(filters)))
        )

    async def delete(
        self, id: str, *, confirmed: bool, filters: SessionPlanFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.plans_delete, lambda: (id, confirmed is True, json.dumps(filters)))
        )


class SessionWorkflows:
    """Named operations through shared typed Rust services with explicit scope."""

    def __init__(self, client: SessionClient):
        self._client = client

    async def list(self, *, filters: SessionWorkflowFilters) -> list[dict[str, Any]]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_list, lambda: (json.dumps(filters),))
        )

    async def show(self, id: str, *, filters: SessionWorkflowFilters) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_show, lambda: (id, json.dumps(filters)))
        )

    async def create(
        self, input: SessionWorkflowCreate, *, filters: SessionWorkflowFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_create, lambda: (json.dumps(input), json.dumps(filters)))
        )

    async def update(
        self, id: str, input: SessionWorkflowPatch, *, filters: SessionWorkflowFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_update, lambda: (id, json.dumps(input), json.dumps(filters)))
        )

    async def delete(
        self, id: str, *, confirmed: bool, filters: SessionWorkflowFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_delete, lambda: (id, confirmed is True, json.dumps(filters)))
        )

    async def run(
        self,
        id: str,
        input: SessionWorkflowRunOptions,
        *,
        filters: SessionWorkflowFilters,
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_run, lambda: (id, json.dumps(input), json.dumps(filters)))
        )

    async def run_detail(
        self, id: str, run_id: str, *, filters: SessionWorkflowFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_run_detail, lambda: (id, run_id, json.dumps(filters)))
        )

    async def wait(
        self,
        id: str,
        run_id: str,
        input: SessionWorkflowWaitOptions,
        *,
        filters: SessionWorkflowFilters,
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_wait, lambda: (id, run_id, json.dumps(input), json.dumps(filters)))
        )

    async def cancel_run(
        self, id: str, run_id: str, *, filters: SessionWorkflowFilters
    ) -> dict[str, Any]:
        return json.loads(
            await self._client._prepared_call(self._client._native.workflows_cancel_run, lambda: (id, run_id, json.dumps(filters)))
        )
