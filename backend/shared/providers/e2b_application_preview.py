# backend/shared/providers/e2b_application_preview.py
#
# Planning utilities for generated application previews in E2B.
# This module deliberately separates deterministic file/command validation from
# sandbox creation so API and worker tests can prove safety constraints without
# making network calls to E2B.

from __future__ import annotations

import base64
import logging
import re
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEPENDENCY_FILENAMES = {"package.json", "package-lock.json", "requirements.txt"}
VITE_ALLOWED_HOSTS_ENV = "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"
VITE_OPENMATES_CONFIG_PATH = "vite.config.openmates.mjs"
PREVIEW_READINESS_TIMEOUT_SECONDS = 90.0
PREVIEW_READINESS_INTERVAL_SECONDS = 1.5
PREVIEW_READINESS_REQUEST_TIMEOUT_SECONDS = 5.0
VITE_CONFIG_FILENAMES = {
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.cjs",
    "vite.config.ts",
    "vite.config.mts",
}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[^\s]+"),
]

logger = logging.getLogger(__name__)


class ApplicationPreviewPlanningError(ValueError):
    """Raised when generated application preview input is unsafe or incomplete."""


@dataclass(frozen=True)
class ApplicationPreviewFile:
    path: str
    content: str = ""
    content_base64: str | None = None
    mime_type: str | None = None
    source_embed_id: str | None = None


@dataclass(frozen=True)
class ApplicationPreviewEntrypoint:
    name: str
    command: str
    port: int


@dataclass(frozen=True)
class ApplicationPreviewPlan:
    files: list[ApplicationPreviewFile]
    install_commands: list[str]
    start_commands: list[dict[str, object]]


@dataclass(frozen=True)
class ApplicationPreviewRuntime:
    sandbox_id: str
    upstream_base_url: str
    ports: dict[str, int]
    upstream_base_urls: dict[str, str] | None = None
    latest_screenshot_url: str | None = None
    latest_screenshot_bytes: bytes | None = None
    latest_screenshot_mime_type: str | None = None


def plan_application_preview_startup(
    *,
    files: list[ApplicationPreviewFile],
    entrypoints: list[ApplicationPreviewEntrypoint],
) -> ApplicationPreviewPlan:
    if not entrypoints:
        raise ApplicationPreviewPlanningError("Application preview requires at least one entrypoint")

    normalized_files = [_normalize_file(file) for file in files]
    if not normalized_files:
        raise ApplicationPreviewPlanningError("Application preview requires at least one file")

    return ApplicationPreviewPlan(
        files=normalized_files,
        install_commands=_dependency_commands(normalized_files),
        start_commands=[_start_command(entrypoint) for entrypoint in entrypoints],
    )


def _normalize_file(file: ApplicationPreviewFile) -> ApplicationPreviewFile:
    path = _safe_application_path(file.path)
    if file.content and _looks_like_secret(file.content):
        raise ApplicationPreviewPlanningError("Application preview files appear to contain secrets")
    return ApplicationPreviewFile(
        path=path,
        content=file.content,
        content_base64=file.content_base64,
        mime_type=file.mime_type,
        source_embed_id=file.source_embed_id,
    )


def _safe_application_path(path: str) -> str:
    raw = path.strip().replace("\\", "/")
    if not raw:
        raise ApplicationPreviewPlanningError("Application preview file path is required")
    pure_path = PurePosixPath(raw)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise ApplicationPreviewPlanningError("Application preview file path is unsafe")
    return pure_path.as_posix()


def _looks_like_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _dependency_commands(files: list[ApplicationPreviewFile]) -> list[str]:
    names = {file.path.rsplit("/", 1)[-1] for file in files}
    commands: list[str] = []
    if "requirements.txt" in names:
        commands.append("python -m pip install -r requirements.txt")
    if "package.json" in names:
        if "package-lock.json" in names:
            commands.append("npm ci --ignore-scripts --no-audit --no-fund")
        else:
            commands.append("npm install --ignore-scripts --no-audit --no-fund")
    return commands


def _start_command(entrypoint: ApplicationPreviewEntrypoint) -> dict[str, object]:
    name = entrypoint.name.strip()
    command = entrypoint.command.strip()
    if not name or not command:
        raise ApplicationPreviewPlanningError("Application preview entrypoint name and command are required")
    if entrypoint.port < 1024 or entrypoint.port > 65_535:
        raise ApplicationPreviewPlanningError("Application preview entrypoint port is invalid")

    normalized_command = _bind_command_to_port(command, entrypoint.port)
    return {"name": name, "command": normalized_command, "port": entrypoint.port}


def _bind_command_to_port(command: str, port: int) -> str:
    if command.startswith("uvicorn "):
        bound = command
        if " --host " not in f" {bound} ":
            bound = f"{bound} --host 0.0.0.0"
        if " --port " not in f" {bound} ":
            bound = f"{bound} --port {port}"
        return bound

    if command == "npm run dev" or command.startswith("npm run dev "):
        if "--host" not in command:
            return f"{command} -- --host 0.0.0.0"
        return command

    return command if shlex.split(command) else command


def start_application_preview_in_e2b(
    *,
    files: list[ApplicationPreviewFile],
    entrypoints: list[ApplicationPreviewEntrypoint],
    api_key: str,
    enable_internet: bool = True,
) -> ApplicationPreviewRuntime:
    """Start a generated application preview in E2B and return proxy metadata."""
    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc

    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")

    plan = plan_application_preview_startup(files=files, entrypoints=entrypoints)
    sandbox = Sandbox.create(
        api_key=api_key,
        secure=True,
        allow_internet_access=enable_internet,
        network={"allow_public_traffic": True},
    )
    _write_files(sandbox, plan.files)
    for command in plan.install_commands:
        sandbox.commands.run(command, timeout=180)

    ports = {str(command["name"]): int(command["port"]) for command in plan.start_commands}
    upstream_base_urls = {name: _sandbox_host(sandbox, port) for name, port in ports.items()}
    vite_allowed_hosts = _vite_allowed_hosts(upstream_base_urls)
    vite_config_path = _write_vite_allowed_hosts_config(sandbox, plan.files, vite_allowed_hosts)
    for command in plan.start_commands:
        sandbox.commands.run(
            _with_vite_preview_settings(str(command["command"]), vite_allowed_hosts, vite_config_path),
            background=True,
            timeout=30,
        )

    primary_name = "frontend" if "frontend" in upstream_base_urls else next(iter(upstream_base_urls))
    _wait_for_preview_ready(upstream_base_urls[primary_name])
    return ApplicationPreviewRuntime(
        sandbox_id=str(getattr(sandbox, "sandbox_id", "")),
        upstream_base_url=upstream_base_urls[primary_name],
        upstream_base_urls=upstream_base_urls,
        ports=ports,
        latest_screenshot_url=_sandbox_screenshot_url(sandbox),
        latest_screenshot_bytes=_sandbox_screenshot_bytes(sandbox),
        latest_screenshot_mime_type="image/png",
    )


def kill_application_preview_sandbox_in_e2b(*, sandbox_id: str, api_key: str) -> bool:
    """Kill a running E2B sandbox for an application preview session."""
    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc

    if not sandbox_id.strip():
        raise RuntimeError("E2B sandbox id is required")
    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")
    return bool(Sandbox.kill(sandbox_id=sandbox_id, api_key=api_key))


def _write_files(sandbox: Any, files: list[ApplicationPreviewFile]) -> None:
    payload = []
    for file in files:
        content = file.content_base64 if file.content_base64 is not None else file.content
        payload.append({"path": file.path, "data": content})
    sandbox.files.write_files(payload)


def _sandbox_host(sandbox: Any, port: int) -> str:
    if hasattr(sandbox, "get_host"):
        host = sandbox.get_host(port)
        return str(host if str(host).startswith("http") else f"https://{host}")
    ports = getattr(sandbox, "ports", None)
    if ports and hasattr(ports, "get_host"):
        host = ports.get_host(port)
        return str(host if str(host).startswith("http") else f"https://{host}")
    raise RuntimeError("E2B sandbox does not expose a preview host helper")


def _wait_for_preview_ready(
    url: str,
    *,
    timeout_seconds: float = PREVIEW_READINESS_TIMEOUT_SECONDS,
    interval_seconds: float = PREVIEW_READINESS_INTERVAL_SECONDS,
    fetch_status: Callable[[str], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_status: int | None = None
    last_error: Exception | None = None
    status_fetcher = fetch_status or _fetch_preview_status

    while True:
        try:
            status = status_fetcher(url)
            if 200 <= status < 400:
                return
            last_status = status
            last_error = None
        except (TimeoutError, OSError, URLError) as exc:
            last_error = exc

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = f"last status {last_status}" if last_status is not None else f"last error {last_error}"
            raise RuntimeError(f"Application preview did not become ready at {url}: {detail}")
        sleep(min(interval_seconds, remaining))


def _fetch_preview_status(url: str) -> int:
    request = Request(url, headers={"User-Agent": "OpenMates application preview readiness"}, method="GET")
    try:
        with urlopen(request, timeout=PREVIEW_READINESS_REQUEST_TIMEOUT_SECONDS) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)


def _vite_allowed_hosts(upstream_base_urls: dict[str, str]) -> list[str]:
    hosts = []
    for url in upstream_base_urls.values():
        hostname = urlparse(url).hostname
        if hostname and hostname not in hosts:
            hosts.append(hostname)
    return hosts


def _with_vite_allowed_hosts(command: str, allowed_hosts: list[str]) -> str:
    if not allowed_hosts or VITE_ALLOWED_HOSTS_ENV in command:
        return command
    return f"{VITE_ALLOWED_HOSTS_ENV}={shlex.quote(','.join(allowed_hosts))} {command}"


def _with_vite_preview_settings(command: str, allowed_hosts: list[str], vite_config_path: str | None) -> str:
    configured = _with_vite_allowed_hosts(command, allowed_hosts)
    if not vite_config_path or not _is_vite_dev_command(command) or "--config" in command:
        return configured
    return f"{configured} --config {shlex.quote(vite_config_path)}"


def _is_vite_dev_command(command: str) -> bool:
    parts = shlex.split(command)
    if not parts:
        return False
    return parts[:3] == ["npm", "run", "dev"] or parts[0].endswith("vite") or parts[0] == "vite"


def _write_vite_allowed_hosts_config(sandbox: Any, files: list[ApplicationPreviewFile], allowed_hosts: list[str]) -> str | None:
    if not allowed_hosts or not _has_vite_dependency(files) or _has_existing_vite_config(files):
        return None
    hosts = ", ".join(repr(host) for host in allowed_hosts)
    sandbox.files.write_files([
        {
            "path": VITE_OPENMATES_CONFIG_PATH,
            "data": (
                "import { defineConfig } from 'vite';\n\n"
                "export default defineConfig({\n"
                "  server: {\n"
                f"    allowedHosts: [{hosts}],\n"
                "  },\n"
                "});\n"
            ),
        }
    ])
    return VITE_OPENMATES_CONFIG_PATH


def _has_vite_dependency(files: list[ApplicationPreviewFile]) -> bool:
    for file in files:
        if file.path.rsplit("/", 1)[-1] == "package.json" and "vite" in file.content:
            return True
    return False


def _has_existing_vite_config(files: list[ApplicationPreviewFile]) -> bool:
    return any(file.path.rsplit("/", 1)[-1] in VITE_CONFIG_FILENAMES for file in files)


def _sandbox_screenshot_url(sandbox: Any) -> str | None:
    value = getattr(sandbox, "latest_screenshot_url", None) or getattr(sandbox, "screenshot_url", None)
    return str(value) if value else None


def _sandbox_screenshot_bytes(sandbox: Any) -> bytes | None:
    screenshot = getattr(sandbox, "take_screenshot", None)
    if not callable(screenshot):
        return None

    try:
        value = screenshot(format="bytes")
    except TypeError:
        try:
            value = screenshot()
        except Exception as exc:  # pragma: no cover - depends on E2B runtime capabilities.
            logger.warning("E2B screenshot capture failed: %s", exc, exc_info=True)
            return None
    except Exception as exc:  # pragma: no cover - depends on E2B runtime capabilities.
        logger.warning("E2B screenshot capture failed: %s", exc, exc_info=True)
        return None

    return _coerce_screenshot_bytes(value)


def _coerce_screenshot_bytes(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    for attr in ("bytes", "data", "content"):
        nested = getattr(value, attr, None)
        if isinstance(nested, bytes):
            return nested
        if isinstance(nested, bytearray):
            return bytes(nested)
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except ValueError:
            return None
    return None
