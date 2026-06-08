# backend/shared/providers/e2b_application_preview.py
#
# Planning utilities for generated application previews in E2B.
# This module deliberately separates deterministic file/command validation from
# sandbox creation so API and worker tests can prove safety constraints without
# making network calls to E2B.

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse


DEPENDENCY_FILENAMES = {"package.json", "package-lock.json", "requirements.txt"}
VITE_ALLOWED_HOSTS_ENV = "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[^\s]+"),
]


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
    for command in plan.start_commands:
        sandbox.commands.run(
            _with_vite_allowed_hosts(str(command["command"]), vite_allowed_hosts),
            background=True,
            timeout=30,
        )

    primary_name = "frontend" if "frontend" in upstream_base_urls else next(iter(upstream_base_urls))
    return ApplicationPreviewRuntime(
        sandbox_id=str(getattr(sandbox, "sandbox_id", "")),
        upstream_base_url=upstream_base_urls[primary_name],
        upstream_base_urls=upstream_base_urls,
        ports=ports,
        latest_screenshot_url=_sandbox_screenshot_url(sandbox),
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


def _sandbox_screenshot_url(sandbox: Any) -> str | None:
    value = getattr(sandbox, "latest_screenshot_url", None) or getattr(sandbox, "screenshot_url", None)
    return str(value) if value else None
