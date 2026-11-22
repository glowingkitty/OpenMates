# backend/shared/providers/e2b_project_sandbox.py
#
# E2B sandbox that runs `openmates-sandbox-host` for the hosted Project agent.
# One sandbox per (user, chat, Project). The daemon decodes and encrypts Project
# files exactly like the clients; this module only creates, reaches and kills
# the sandbox. It never sees the Project key or file contents beyond relaying
# opaque ciphertext JSON to the daemon.
# Plan: docs/plans/hosted-project-sandbox (contracts.md sections 2 and 3).

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async

logger = logging.getLogger(__name__)

PROJECT_SANDBOX_TEMPLATE_ENV = "E2B_PROJECT_SANDBOX_TEMPLATE"
PROJECT_SANDBOX_PORT = 7787
PROJECT_SANDBOX_DIR = "/home/user/project"
PROJECT_SANDBOX_IDLE_TIMEOUT_SECONDS = 15 * 60
PROJECT_SANDBOX_METADATA = {"openmates_kind": "project_sandbox"}
DAEMON_READY_TIMEOUT_SECONDS = 30.0
# Sandbox creation retries when the shared E2B account is at its concurrent-sandbox limit.
CREATE_RATE_LIMIT_ATTEMPTS = 4
CREATE_RATE_LIMIT_BACKOFF_SECONDS = 3.0
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0


class ProjectSandboxError(Exception):
    """A sandbox lifecycle or daemon error; ``code`` is a stable machine-readable string."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ProjectSandboxConnection:
    """Everything needed to reach a sandbox daemon again (ids and tokens only)."""

    sandbox_id: str
    sandbox_host: str
    traffic_access_token: str
    bearer_token: str


class ProjectSandboxClient:
    """HTTP client for the daemon, through E2B's authenticated port proxy."""

    def __init__(
        self,
        sandbox_host_url: str,
        traffic_access_token: Optional[str],
        bearer_token: str,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._base = sandbox_host_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {bearer_token}"}
        if traffic_access_token:
            self._headers["e2b-traffic-access-token"] = traffic_access_token
        self._transport = transport

    async def call(self, endpoint: str, body: Optional[dict] = None,
                   timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS) -> dict:
        method = "POST" if body is not None or endpoint != "/v1/hello" else "GET"
        if endpoint in ("/v1/baseline", "/v1/scan", "/v1/key"):
            method = "POST"
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
                response = await client.request(
                    method, f"{self._base}{endpoint}", headers=self._headers,
                    json=body if method == "POST" else None,
                )
        except httpx.HTTPError as exc:
            raise ProjectSandboxError("unreachable", type(exc).__name__) from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise ProjectSandboxError("bad_response", f"status {response.status_code}") from exc
        if response.status_code >= 400:
            code = data.get("error") if isinstance(data, dict) else None
            raise ProjectSandboxError(str(code or f"http_{response.status_code}"))
        if not isinstance(data, dict):
            raise ProjectSandboxError("bad_response")
        return data


DAEMON_USER = "root"
COMMAND_USER = "user"

# E2B re-creates ``user``'s passwordless sudo (sudoers line and sudo group) at every
# sandbox start, so the template cannot remove it. Before the daemon receives any key,
# strip every setuid/setgid bit (sudo, su, pkexec, ...), drop the grants, and verify
# that ``user`` cannot become root; otherwise the sandbox is killed.
HARDEN_COMMAND = (
    "set -e; "
    "find / -xdev \\( -perm -4000 -o -perm -2000 \\) -type f -exec chmod ug-s {} + 2>/dev/null || true; "
    "sed -i '/^user[[:space:]]/d' /etc/sudoers; "
    "gpasswd -d user sudo >/dev/null 2>&1 || true; "
    "test -z \"$(find / -xdev \\( -perm -4000 -o -perm -2000 \\) -type f 2>/dev/null | head -1)\""
)
ESCALATION_PROBE = "sudo -n true 2>/dev/null && echo ESCALATED || echo CONFINED"


def _sdk_errors() -> tuple[type[BaseException], ...]:
    from e2b.exceptions import (
        AuthenticationException, RateLimitException, SandboxException, TimeoutException,
    )

    return (SandboxException, TimeoutException, AuthenticationException, RateLimitException,
            httpx.HTTPError)


def _is_rate_limit(exc: BaseException) -> bool:
    from e2b.exceptions import RateLimitException

    return isinstance(exc, RateLimitException)


async def _api_key(secrets_manager: Any) -> str:
    """The E2B API key; a missing key is a sandbox error, so callers keep the device path."""
    try:
        return await get_e2b_api_key_async(secrets_manager)
    except RuntimeError as exc:
        raise ProjectSandboxError("api_key_unavailable") from exc


def host_url(sandbox_host: str) -> str:
    return f"https://{sandbox_host}"


def client_for(connection: ProjectSandboxConnection,
               transport: Optional[httpx.AsyncBaseTransport] = None) -> ProjectSandboxClient:
    return ProjectSandboxClient(host_url(connection.sandbox_host), connection.traffic_access_token,
                                connection.bearer_token, transport=transport)


async def create_project_sandbox(
    *, project_id: str, job_id: str, chat_id: str, team_id: Optional[str] = None,
    secrets_manager: Any = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> tuple[ProjectSandboxConnection, dict]:
    """Create the sandbox, start the daemon and wait for ``/v1/hello``; returns (connection, hello)."""
    template = os.getenv(PROJECT_SANDBOX_TEMPLATE_ENV, "").strip()
    if not template:
        raise ProjectSandboxError("template_missing")
    from e2b import AsyncSandbox

    api_key = await _api_key(secrets_manager)
    bearer = secrets.token_urlsafe(32)
    for attempt in range(CREATE_RATE_LIMIT_ATTEMPTS):
        try:
            sandbox = await AsyncSandbox.create(
                template=template, api_key=api_key, timeout=PROJECT_SANDBOX_IDLE_TIMEOUT_SECONDS,
                metadata=dict(PROJECT_SANDBOX_METADATA), secure=True, allow_internet_access=True,
                network={"allow_public_traffic": False}, lifecycle={"on_timeout": "kill"},
            )
            break
        except _sdk_errors() as exc:
            # The account's concurrent-sandbox limit is shared with CI runners; a slot frees up within seconds.
            if not _is_rate_limit(exc) or attempt + 1 == CREATE_RATE_LIMIT_ATTEMPTS:
                raise ProjectSandboxError("create_failed", type(exc).__name__) from exc
            logger.warning("Project sandbox create rate-limited; retrying (attempt %s)", attempt + 1)
            await asyncio.sleep(CREATE_RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
    connection = ProjectSandboxConnection(
        sandbox_id=sandbox.sandbox_id, sandbox_host=sandbox.get_host(PROJECT_SANDBOX_PORT),
        traffic_access_token=getattr(sandbox, "traffic_access_token", None) or "",
        bearer_token=bearer,
    )
    try:
        await sandbox.commands.run(HARDEN_COMMAND, user=DAEMON_USER, timeout=120)
        probe = await sandbox.commands.run(ESCALATION_PROBE, user=COMMAND_USER, timeout=30)
        if "CONFINED" not in (probe.stdout or ""):
            raise ProjectSandboxError("escalation_possible")
        # Root, so commands run as the normal ``user`` cannot read the daemon's memory (the Project key).
        envs = {"OMSH_TOKEN": bearer, "OMSH_SANDBOX_ID": connection.sandbox_id,
                "OMSH_JOB_ID": job_id, "OMSH_PROJECT_ID": project_id, "OMSH_CHAT_ID": chat_id,
                "OMSH_PROJECT_DIR": PROJECT_SANDBOX_DIR}
        if team_id:
            envs["OMSH_TEAM_ID"] = team_id
        await sandbox.commands.run(
            "openmates-sandbox-host serve", background=True, timeout=0, user=DAEMON_USER, envs=envs)
        hello = await _wait_for_hello(client_for(connection, transport))
    except (ProjectSandboxError, *_sdk_errors()) as exc:  # never leave a half-started sandbox running
        await kill_project_sandbox(connection.sandbox_id, secrets_manager=secrets_manager)
        if isinstance(exc, ProjectSandboxError):
            raise
        raise ProjectSandboxError("create_failed", type(exc).__name__) from exc
    return connection, hello


async def _wait_for_hello(client: ProjectSandboxClient) -> dict:
    deadline = time.monotonic() + DAEMON_READY_TIMEOUT_SECONDS
    while True:
        try:
            return await client.call("/v1/hello", timeout=5.0)
        except ProjectSandboxError as exc:
            if time.monotonic() >= deadline:
                raise ProjectSandboxError("daemon_not_ready", exc.code) from exc
            await asyncio.sleep(0.5)


async def connect_project_sandbox(sandbox_id: str, *, secrets_manager: Any = None) -> Any:
    """Reconnect to a running sandbox; raises ``ProjectSandboxError('gone')`` when it is not running."""
    from e2b import AsyncSandbox

    api_key = await _api_key(secrets_manager)
    try:
        return await AsyncSandbox.connect(sandbox_id, api_key=api_key)
    except _sdk_errors() as exc:
        raise ProjectSandboxError("gone", type(exc).__name__) from exc


async def extend_idle(sandbox: Any) -> None:
    await sandbox.set_timeout(PROJECT_SANDBOX_IDLE_TIMEOUT_SECONDS)


async def kill_project_sandbox(sandbox_id: str, *, secrets_manager: Any = None) -> bool:
    """Kill a sandbox; True when it existed."""
    from e2b import AsyncSandbox

    api_key = await _api_key(secrets_manager)
    return bool(await AsyncSandbox.kill(sandbox_id, api_key=api_key))


async def list_project_sandbox_ids(*, secrets_manager: Any = None) -> dict[str, float]:
    """Running sandboxes created by this module (tagged by metadata): id -> start time (epoch seconds)."""
    from e2b import AsyncSandbox

    api_key = await _api_key(secrets_manager)
    paginator = AsyncSandbox.list(query={"metadata": dict(PROJECT_SANDBOX_METADATA), "state": ["running"]},
                                  api_key=api_key)
    ids: dict[str, float] = {}
    while paginator.has_next:
        for item in await paginator.next_items():
            ids[item.sandbox_id] = item.started_at.timestamp()
    return ids
