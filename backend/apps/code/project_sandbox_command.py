# backend/apps/code/project_sandbox_command.py
#
# Cloud Project command (code.run target e2b with argv) executed in the chat's
# hosted PROJECT SANDBOX instead of the separate E2B workspace. The sandbox
# already holds the decrypted Project, so no client snapshot is uploaded: the
# argv runs in /home/user/project, files it changed are read by the sandbox
# daemon (POST /v1/scan) and committed as ciphertext revisions through
# commit_revisions. The result goes to the model with a write_back summary.
# Called from the worker thread of run_code_task (sync, with its run_async).
# Spec: code-run.cloud.commands, code-run.cloud.workspace,
# code-run.cloud.command-changes-sync-back, projects.sandbox.*.

from __future__ import annotations

import asyncio
import logging
import shlex
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.shared.providers.e2b_code_runner import CodeRunCancelled, CodeRunResult
from backend.shared.providers.e2b_project_sandbox import (
    COMMAND_USER,
    PROJECT_SANDBOX_DIR,
    ProjectSandboxError,
    connect_project_sandbox,
)
from backend.shared.providers.e2b_project_workspace import WorkspaceCommand, WorkspaceOutcome, WorkspaceState

logger = logging.getLogger(__name__)

POLL_SECONDS = 0.3
SCAN_TIMEOUT_SECONDS = 120.0
BACKGROUND_READY_POLL_SECONDS = 1.0
DEFAULT_READY_TIMEOUT_SECONDS = 90


class ProjectSandboxCommandError(RuntimeError):
    """The sandbox could not run the command; the message is safe for the model (no contents, no grants)."""


@dataclass
class SandboxCommandOutcome(WorkspaceOutcome):
    """WorkspaceOutcome whose `changes` stay empty: the daemon commits revisions itself."""

    write_back: dict[str, Any] | None = None


@dataclass
class _Sink:
    events: list[tuple[str, str]] = field(default_factory=list)

    def push(self, kind: str, data: Any) -> None:
        self.events.append((kind, data if isinstance(data, str) else str(data)))

    def drain(self) -> list[tuple[str, str]]:
        events, self.events = self.events, []
        return events


def command_line(command: WorkspaceCommand) -> str:
    """`cd <folder under the Project> && exec <argv>`; refuses folders that leave the Project."""
    folder = command.cwd.strip("/") if command.cwd not in {"", "."} else ""
    if ".." in folder.split("/"):
        raise ProjectSandboxCommandError("The working folder must stay inside the Project.")
    cwd = f"{PROJECT_SANDBOX_DIR}/{folder}" if folder else PROJECT_SANDBOX_DIR
    return f"cd {shlex.quote(cwd)} && exec {shlex.join(command.argv)}"


def _timeout_wrapper(line: str, timeout_seconds: int) -> str:
    return f"timeout {timeout_seconds}s bash -lc {shlex.quote(line)}"


def _exit_exception() -> type[BaseException]:
    from e2b import CommandExitException

    return CommandExitException


async def _start_foreground(sandbox: Any, line: str, timeout_seconds: int, sink: _Sink):
    handle = await sandbox.commands.run(
        _timeout_wrapper(line, timeout_seconds), background=True, timeout=timeout_seconds + 10,
        user=COMMAND_USER)
    exit_type = _exit_exception()

    async def wait() -> int | None:
        try:
            result = await handle.wait(on_stdout=lambda d: sink.push("stdout", d),
                                       on_stderr=lambda d: sink.push("stderr", d))
        except exit_type as exc:  # E2B raises on a non-zero exit code
            return getattr(exc, "exit_code", None)
        return getattr(result, "exit_code", None)

    return handle, asyncio.ensure_future(wait())


async def _start_background(sandbox: Any, command: WorkspaceCommand, line: str) -> str:
    log = f"/home/user/.openmates-bg-{uuid.uuid4().hex[:12]}.log"
    await sandbox.commands.run(f"nohup bash -lc {shlex.quote(line)} > {shlex.quote(log)} 2>&1 &", timeout=30,
                                 user=COMMAND_USER)
    return log


async def _probe(sandbox: Any, url: str) -> bool:
    result = await sandbox.commands.run(
        f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 2 {shlex.quote(url)} || true", timeout=10,
        user=COMMAND_USER)
    code = str(getattr(result, "stdout", "") or "").strip()
    return bool(code) and code != "000"


async def _tail(sandbox: Any, log: str) -> str:
    result = await sandbox.commands.run(f"tail -c 16000 {shlex.quote(log)} || true", timeout=10,
                                         user=COMMAND_USER)
    return str(getattr(result, "stdout", "") or "")


def _flush(sink: _Sink, on_output: Callable[[str, str], None]) -> None:
    for kind, text in sink.drain():
        on_output(kind, text)


def _run_foreground(run_async, sandbox, line, command, on_output, should_cancel) -> int | None:
    sink = _Sink()
    handle, task = run_async(_start_foreground(sandbox, line, command.timeout_seconds, sink))
    while True:
        done, _ = run_async(asyncio.wait({task}, timeout=POLL_SECONDS))
        _flush(sink, on_output)
        if done:
            return task.result()
        if should_cancel():
            run_async(handle.kill())
            task.cancel()
            raise CodeRunCancelled("Code run cancelled by user")


def _run_background(run_async, sandbox, command, line, on_output, should_cancel) -> tuple[int, bool]:
    log = run_async(_start_background(sandbox, command, line))
    deadline = time.monotonic() + min(command.timeout_seconds, DEFAULT_READY_TIMEOUT_SECONDS)
    ready = False
    while time.monotonic() < deadline:
        if should_cancel():
            raise CodeRunCancelled("Code run cancelled by user")
        if run_async(_probe(sandbox, str(command.ready_url))):
            ready = True
            break
        time.sleep(BACKGROUND_READY_POLL_SECONDS)
    on_output("stdout", run_async(_tail(sandbox, log)))
    on_output("status", "Dev server is ready.\n" if ready else "Dev server did not become ready in time.\n")
    return (0 if ready else 1), ready


async def _scan_and_commit(handle, service, *, user_id, chat_id, project_id, team_id, directus_service,
                           cache_service) -> dict[str, Any]:
    from backend.core.api.app.services.project_sandbox_writeback import commit_revisions

    try:
        answer = await handle.client.call("/v1/scan", {}, timeout=SCAN_TIMEOUT_SECONDS)
    except ProjectSandboxError as exc:
        logger.warning("Project sandbox scan failed: %s", exc.code)
        return {"committed": [], "merged": [], "conflicts": [], "rejected": [], "scan_error": exc.code}
    revisions = answer.get("revisions") or []
    summary: dict[str, Any] = {"committed": [], "merged": [], "conflicts": [], "rejected": []}
    if revisions:
        outcome = await commit_revisions(
            handle, revisions, user_id=user_id, chat_id=chat_id, project_id=project_id, team_id=team_id,
            operation_id=str(uuid.uuid4()), directus_service=directus_service, cache_service=cache_service)
        summary = outcome.summary()
    await service.touch(user_id=user_id, chat_id=chat_id, project_id=project_id)
    return summary


def execute_sandbox_command(
    payload: dict[str, Any], on_output: Callable[[str, str], None], should_cancel: Callable[[], bool],
    cache_service: Any, run_async: Callable[[Any], Any], secrets_manager: Any, *,
    service: Any = None, directus_service: Any = None,
):
    """Run the command in the chat's Project sandbox; return (CodeRunResult, SandboxCommandOutcome)."""
    from backend.core.api.app.services.project_sandbox_service import (
        ProjectSandboxService,
        ProjectSandboxUnavailable,
    )

    command_run = payload["command_run"]
    user_id, chat_id = str(payload["user_id"]), str(payload["chat_id"])
    project_id = str(command_run["project_id"])
    team_id = command_run.get("team_id")
    if directus_service is None:
        from backend.core.api.app.services.directus import DirectusService

        directus_service = DirectusService(cache_service=cache_service)
    service = service or ProjectSandboxService(cache_service, directus_service, secrets_manager=secrets_manager)
    command = WorkspaceCommand(
        argv=tuple(command_run["argv"]), cwd=str(command_run.get("cwd") or "."),
        timeout_seconds=int(command_run["timeout_seconds"]), background=bool(command_run.get("background")),
        ready_url=command_run.get("ready_url"))
    line = command_line(command)
    started = time.monotonic()
    on_output("status", "Starting sandbox...\n")
    try:
        handle = run_async(service.ensure_ready(user_id=user_id, chat_id=chat_id, project_id=project_id,
                                                team_id=team_id))
        sandbox = run_async(connect_project_sandbox(handle.sandbox_id, secrets_manager=secrets_manager))
    except ProjectSandboxUnavailable as exc:
        raise ProjectSandboxCommandError(f"The Project sandbox is unavailable ({exc.reason}).") from exc
    except ProjectSandboxError as exc:
        raise ProjectSandboxCommandError(f"The Project sandbox could not be reached ({exc.code}).") from exc
    on_output("status", f"Running {shlex.join(command.argv)}...\n")
    ready: bool | None = None
    if command.background:
        exit_code, ready = _run_background(run_async, sandbox, command, line, on_output, should_cancel)
    else:
        exit_code = _run_foreground(run_async, sandbox, line, command, on_output, should_cancel)
    write_back = run_async(_scan_and_commit(
        handle, service, user_id=user_id, chat_id=chat_id, project_id=project_id, team_id=team_id,
        directus_service=directus_service, cache_service=cache_service))
    duration = time.monotonic() - started
    outcome = SandboxCommandOutcome(
        exit_code=exit_code, duration_seconds=duration, sandbox_id=handle.sandbox_id, reused=True,
        state=WorkspaceState(sandbox_id=handle.sandbox_id, created_at=time.time()), changes=[],
        not_synced=[], ready=ready, write_back=write_back)
    result = CodeRunResult(exit_code=exit_code, duration_seconds=duration, output_truncated=False,
                           sandbox_id=handle.sandbox_id, artifacts=[], skipped_artifacts=[])
    return result, outcome
