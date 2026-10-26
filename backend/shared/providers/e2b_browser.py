"""E2B-only browser lifecycle and authenticated, fixed-operation RPC transport."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any, Awaitable, Callable

import httpx

PRIVATE_NETWORKS = [
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "224.0.0.0/4",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "240.0.0.0/4",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]
RUNTIME_DIR = "/tmp/openmates-browse"
RUNTIME_PYTHON = "/opt/openmates-browser/venv/bin/python"


class BrowserUnavailable(RuntimeError):
    """A safe failure without upstream payloads or browser credentials."""


class BrowserAdmissionRejected(BrowserUnavailable):
    """The provider explicitly rejected creation before allocating a machine."""


class BrowserRpcUnavailable(BrowserUnavailable):
    """Transport metadata without upstream bodies, URLs or credentials."""

    def __init__(self, *, retryable: bool = False, status_code: int | None = None):
        super().__init__("The browser connection is unavailable.")
        self.retryable = retryable
        self.status_code = status_code


class E2BBrowser:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.scope = os.environ.get("SERVER_ENVIRONMENT", "development")

    def validate_creation(self) -> str:
        template = os.environ.get("E2B_BROWSE_TEMPLATE")
        if not template:
            raise BrowserUnavailable(
                "The E2B browser template has not been configured."
            )
        return template

    async def inventory_page(
        self, cursor: str | None = None
    ) -> tuple[list[Any], str | None]:
        from e2b import Sandbox, SandboxQuery

        paginator = Sandbox.list(
            query=SandboxQuery(metadata={"openmates_browse_scope": self.scope}),
            limit=100,
            next_token=cursor,
            api_key=self.api_key,
        )
        rows = await asyncio.to_thread(paginator.next_items)
        return rows, paginator.next_token

    async def create(
        self,
        *,
        session_id: str,
        owner: str,
        on_created: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> dict[str, Any]:
        from e2b import Sandbox
        from e2b.exceptions import SandboxException

        template = self.validate_creation()
        token = secrets.token_urlsafe(32)
        requested_at = time.time()
        try:
            sandbox = await asyncio.to_thread(
                Sandbox.create,
                template,
                api_key=self.api_key,
                request_timeout=20,
                retries=0,
                # Template.set_envs configures build steps only, not runtime commands.
                envs={"PLAYWRIGHT_BROWSERS_PATH": "/opt/openmates-browser/browsers"},
                timeout=120,
                lifecycle={"on_timeout": "pause", "auto_resume": False},
                network={"deny_out": PRIVATE_NETWORKS, "allow_public_traffic": False},
                metadata={
                    "openmates_browser_session": session_id,
                    "openmates_owner_hash": owner,
                    "openmates_browse_scope": self.scope,
                },
            )
        except SandboxException as exc:
            if exc.status_code in (400, 401, 402, 403, 404, 422, 429):
                raise BrowserAdmissionRejected(
                    "Browser hosting did not admit this request."
                ) from None
            raise
        try:
            info = await asyncio.to_thread(sandbox.get_info)
            cpu = getattr(info, "cpu_count", None)
            memory = getattr(info, "memory_mb", None)
            if not isinstance(cpu, int) or not isinstance(memory, int):
                raise BrowserUnavailable("Browser resource metering is unavailable.")
            provider = {
                "sandbox_id": sandbox.sandbox_id,
                "token": token,
                "traffic_access_token": sandbox.traffic_access_token,
                "rpc_url": f"https://{sandbox.get_host(8765)}",
                "cpu_count": cpu,
                "memory_mb": memory,
                "created_at": info.started_at.timestamp(),
                "running_since": info.started_at.timestamp(),
                "provider_deadline": requested_at + 120,
            }
            if not provider["traffic_access_token"]:
                raise BrowserUnavailable(
                    "Authenticated browser ingress is unavailable."
                )
            # Persist the paid handle before installing or starting anything else.
            await on_created(provider)
            if cpu > 2 or memory > 4096:
                raise BrowserUnavailable(
                    "The browser template exceeds its admitted resource ceiling."
                )
            config = json.dumps({"token": token})
            await asyncio.to_thread(
                sandbox.commands.run, f"mkdir -p {RUNTIME_DIR}", timeout=10
            )
            await asyncio.to_thread(
                sandbox.files.write, f"{RUNTIME_DIR}/config.json", config
            )
            source = Path(__file__).with_name("web_browse_runtime.py").read_text()
            await asyncio.to_thread(
                sandbox.files.write, f"{RUNTIME_DIR}/server.py", source
            )
            await asyncio.to_thread(
                sandbox.commands.run,
                f"{RUNTIME_PYTHON} {RUNTIME_DIR}/server.py",
                background=True,
            )
            for _ in range(30):
                try:
                    await self.rpc(
                        provider, {"operation": "control", "mode": "ai"}, timeout=2
                    )
                    return provider
                except BrowserUnavailable:
                    await asyncio.sleep(0.25)
            raise BrowserUnavailable("Browser did not become ready.")
        except BaseException:
            await asyncio.to_thread(sandbox.kill, retries=0)
            if "provider" in locals():
                provider["provider_deadline"] = min(
                    provider["provider_deadline"], time.time()
                )
                provider["deleted"] = True
                await on_created(provider)
            raise

    async def info(self, provider: dict[str, Any]) -> Any:
        from e2b import Sandbox

        return await asyncio.to_thread(
            Sandbox.get_info, provider["sandbox_id"], api_key=self.api_key
        )

    async def keep_running(
        self, provider: dict[str, Any], *, seconds: int = 120
    ) -> None:
        from e2b import Sandbox

        seconds = max(1, min(seconds, 120))
        if abs(provider.get("provider_deadline", 0) - (time.time() + seconds)) > 15:
            await asyncio.to_thread(
                Sandbox.set_timeout,
                provider["sandbox_id"],
                seconds,
                api_key=self.api_key,
                retries=0,
            )
            provider["provider_deadline"] = time.time() + seconds

    async def resume(self, provider: dict[str, Any]) -> None:
        from e2b import Sandbox

        sandbox = await asyncio.to_thread(
            Sandbox.connect,
            provider["sandbox_id"],
            api_key=self.api_key,
            timeout=120,
            retries=0,
        )
        provider["traffic_access_token"] = sandbox.traffic_access_token
        provider["running_since"] = time.time()
        provider["provider_deadline"] = time.time() + 120
        # A successful native resume precedes ingress readiness. In particular,
        # an auto-paused sandbox can still return 502 briefly after connect.
        # Read metadata only: readiness neither changes the controller nor acts.
        deadline = time.monotonic() + 15
        while True:
            try:
                await self.rpc(provider, {"operation": "metadata"}, timeout=2)
                break
            except BrowserRpcUnavailable as exc:
                if not exc.retryable or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.25)

    async def pause(self, provider: dict[str, Any]) -> None:
        from e2b import Sandbox

        await asyncio.to_thread(
            Sandbox.pause, provider["sandbox_id"], api_key=self.api_key, retries=0
        )

    async def kill(self, provider: dict[str, Any]) -> None:
        from e2b import Sandbox

        await asyncio.to_thread(
            Sandbox.kill, provider["sandbox_id"], api_key=self.api_key, retries=0
        )

    async def rpc(
        self, provider: dict[str, Any], body: dict[str, Any], *, timeout: float = 25
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(
                    provider["rpc_url"],
                    json=body,
                    headers={
                        "Authorization": "Bearer " + provider["token"],
                        "e2b-traffic-access-token": provider["traffic_access_token"],
                    },
                )
            if response.status_code != 200:
                raise BrowserRpcUnavailable(
                    retryable=response.status_code in (502, 503, 504),
                    status_code=response.status_code,
                )
            if len(response.content) > 2_000_000:
                raise BrowserUnavailable(
                    "Browser operation was rejected; refresh the observation."
                )
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except BrowserUnavailable:
            raise
        except httpx.HTTPError:
            raise BrowserRpcUnavailable(retryable=True) from None
        except ValueError:
            raise BrowserUnavailable("The browser connection is unavailable.") from None
