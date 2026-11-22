# backend/apps/code/project_sandbox_preview.py
#
# Live preview of a Project web app from the chat's hosted PROJECT SANDBOX, the
# sandbox where the agent's commands already built it. Nothing is uploaded or
# built a second time: the worker reuses (or, with a device's sealed key
# answer, recreates) the sandbox, starts the app's dev server inside the
# Project folder and marks the preview session running. The preview gateway
# then reads the sandbox's traffic token from the sandbox record on every
# request; the token never enters the preview session, a log or the browser.
# Preview time is covered by the sandbox's own per-second charge (each open
# preview renews the sandbox idle timeout); it adds no preview charge.
# Spec: code-run.cloud.project-preview. Plan: docs/plans/project-sandbox-preview.

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from backend.shared.providers.e2b_project_sandbox import (
    COMMAND_USER,
    ProjectSandboxError,
    connect_project_sandbox,
)
from backend.shared.providers.e2b_project_workspace import WorkspaceCommand

logger = logging.getLogger(__name__)

PROJECT_PREVIEW_SOURCE = "project_sandbox"
PROJECT_PREVIEW_PORT = 5173
INSTALL_TIMEOUT_SECONDS = 300
READY_TIMEOUT_SECONDS = 90.0
READY_POLL_SECONDS = 1.0
TOUCH_INTERVAL_SECONDS = 60.0
MAX_FOLDER_LENGTH = 512
VITE_ALLOWED_HOSTS_ENV = "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"
DEV_ARGV = ("npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", str(PROJECT_PREVIEW_PORT), "--strictPort")

Patch = Callable[[str, dict[str, Any]], Awaitable[None]]


class ProjectPreviewError(RuntimeError):
    """The preview could not start; the message is safe to show (no paths outside the Project, no tokens)."""


def normalize_preview_folder(value: Any) -> str:
    """The app folder relative to the Project root ("" for the root); refuses anything that leaves it."""
    if not isinstance(value, str) or len(value) > MAX_FOLDER_LENGTH:
        raise ProjectPreviewError("The app folder is not valid.")
    folder = value.strip().strip("/")
    if folder in {"", "."}:
        return ""
    parts = folder.split("/")
    if "\\" in folder or any(part in {"", ".", ".."} for part in parts):
        raise ProjectPreviewError("The app folder must stay inside the Project.")
    return folder


def dev_server_command(folder: str, allowed_host: str) -> WorkspaceCommand:
    """`npm run dev` on the fixed preview port, admitting the sandbox's own preview host."""
    return WorkspaceCommand(
        argv=("env", f"{VITE_ALLOWED_HOSTS_ENV}={allowed_host}", *DEV_ARGV), cwd=folder or ".",
        timeout_seconds=int(READY_TIMEOUT_SECONDS), background=True,
        ready_url=f"http://127.0.0.1:{PROJECT_PREVIEW_PORT}/")


def _host_name(host: str) -> str:
    return host.split("://", 1)[-1].split("/", 1)[0]


async def _run(sandbox: Any, line: str, timeout: float) -> tuple[int, str]:
    exit_type = _exit_exception()
    try:
        result = await sandbox.commands.run(line, timeout=timeout, user=COMMAND_USER)
    except exit_type as exc:  # E2B raises on a non-zero exit code
        return int(getattr(exc, "exit_code", 1) or 1), str(getattr(exc, "stderr", "") or "")
    return int(getattr(result, "exit_code", 0) or 0), str(getattr(result, "stdout", "") or "")


def _exit_exception() -> type[BaseException]:
    from e2b import CommandExitException

    return CommandExitException


async def _listening(sandbox: Any) -> bool:
    from backend.apps.code.project_sandbox_command import _probe

    return await _probe(sandbox, f"http://127.0.0.1:{PROJECT_PREVIEW_PORT}/")


async def start_dev_server(sandbox: Any, folder: str, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                           ready_timeout: float = READY_TIMEOUT_SECONDS) -> str:
    """Start (or reuse) the dev server in ``folder``; return the sandbox host of the preview port."""
    from backend.apps.code.project_sandbox_command import _start_background, command_line

    preview_host = _host_name(str(sandbox.get_host(PROJECT_PREVIEW_PORT)))
    if await _listening(sandbox):
        return preview_host
    project_dir = command_line(WorkspaceCommand(argv=("true",), cwd=folder or ".", timeout_seconds=10,
                                                background=False, ready_url=None)).split(" && ", 1)[0]
    code, out = await _run(sandbox, f"{project_dir} && node -e "
                           "\"process.exit(require('./package.json').scripts?.dev ? 0 : 3)\"", timeout=20)
    if code != 0:
        raise ProjectPreviewError("This folder has no app with a dev script to preview.")
    code, _ = await _run(sandbox, f"{project_dir} && test -d node_modules", timeout=10)
    if code != 0:
        code, _ = await _run(sandbox, f"{project_dir} && timeout {INSTALL_TIMEOUT_SECONDS}s npm install --no-audit "
                             "--no-fund", timeout=INSTALL_TIMEOUT_SECONDS + 15)
        if code != 0:
            raise ProjectPreviewError("Installing the app's dependencies failed.")
    command = dev_server_command(folder, preview_host)
    await _start_background(sandbox, command, command_line(command))
    deadline = time.monotonic() + ready_timeout
    while time.monotonic() < deadline:
        if await _listening(sandbox):
            return preview_host
        await sleep(READY_POLL_SECONDS)
    raise ProjectPreviewError("The app's dev server did not become ready in time.")


def _unavailable_message(reason: str) -> str:
    if reason in {"no_device", "declined"}:
        return "The Project sandbox needs this Project's key: keep OpenMates open on a device with the Project."
    return "The Project sandbox is not available right now."


async def run_project_sandbox_preview_session(
    *, cache_service: Any, session_id: str, payload: dict[str, Any], patch: Patch, service: Any,
    connect: Callable[..., Awaitable[Any]] = connect_project_sandbox, secrets_manager: Any = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Worker entry: ready the Project sandbox, start the dev server and mark the session running."""
    from backend.core.api.app.services.project_sandbox_service import ProjectSandboxUnavailable

    now = time.time()
    await patch(session_id, {"status": "starting", "updated_at": now, "events+": [
        {"kind": "status", "text": "Starting the app in the Project sandbox...", "timestamp": now}]})
    user_id, chat_id = str(payload["user_id"]), str(payload["chat_id"])
    project_id = str(payload["project_id"])
    try:
        folder = normalize_preview_folder(payload.get("cwd") or "")
        handle = await service.ensure_ready(user_id=user_id, chat_id=chat_id, project_id=project_id,
                                            team_id=payload.get("team_id"))
        sandbox = await connect(handle.sandbox_id, secrets_manager=secrets_manager)
        preview_host = await start_dev_server(sandbox, folder, sleep=sleep)
    except ProjectSandboxUnavailable as exc:
        await _fail(patch, session_id, _unavailable_message(exc.reason))
        return
    except ProjectSandboxError as exc:
        logger.warning("Project preview: sandbox unreachable (%s)", exc.code)
        await _fail(patch, session_id, "The Project sandbox could not be reached.")
        return
    except ProjectPreviewError as exc:
        await _fail(patch, session_id, str(exc))
        return
    running_at = time.time()
    await patch(session_id, {
        "status": "running", "project_sandbox_id": handle.sandbox_id,
        "project_preview": {"host": preview_host, "user_id": user_id, "chat_id": chat_id, "project_id": project_id},
        "last_sandbox_touch_at": running_at, "updated_at": running_at,
        "events+": [{"kind": "status", "text": "The app is running in the Project sandbox.", "timestamp": running_at}],
    })


async def _fail(patch: Patch, session_id: str, message: str) -> None:
    at = time.time()
    await patch(session_id, {"status": "failed", "error": message, "updated_at": at,
                             "events+": [{"kind": "error", "text": message, "timestamp": at}]})


async def project_preview_upstream(cache_service: Any, session: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    """Upstream base URL and the server-side access header of a running Project preview, None when gone."""
    from backend.core.api.app.services.project_sandbox_service import _clean_record, sandbox_record_key

    preview = session.get("project_preview")
    if not isinstance(preview, dict) or not isinstance(preview.get("host"), str):
        return None
    record = _clean_record(await cache_service.get(sandbox_record_key(
        str(preview.get("user_id")), str(preview.get("chat_id")), str(preview.get("project_id")))))
    if not record or record.get("sandbox_id") != session.get("project_sandbox_id"):
        return None
    headers = {"e2b-traffic-access-token": record["traffic_access_token"]} if record.get("traffic_access_token") else {}
    return f"https://{preview['host']}", headers


async def keep_project_preview_alive(service: Any, session: dict[str, Any], *, now: float) -> bool:
    """Renew the sandbox idle timeout at most once a minute while the preview is polled; True when renewed."""
    preview = session.get("project_preview")
    if not isinstance(preview, dict) or session.get("status") != "running":
        return False
    if now - float(session.get("last_sandbox_touch_at") or 0) < TOUCH_INTERVAL_SECONDS:
        return False
    await service.touch(user_id=str(preview["user_id"]), chat_id=str(preview["chat_id"]),
                        project_id=str(preview["project_id"]))
    return True

