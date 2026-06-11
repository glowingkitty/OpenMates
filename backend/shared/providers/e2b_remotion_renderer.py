# backend/shared/providers/e2b_remotion_renderer.py
#
# Deterministic planning utilities for Remotion video rendering in E2B. The
# planner validates generated files and commands without creating a sandbox so
# tests can prove safety constraints without network calls or paid rendering.

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from backend.apps.ai.utils.remotion_fences import normalize_remotion_filename
from backend.shared.providers.e2b_application_preview import ApplicationPreviewFile


REMOTION_RENDER_OUTPUT = "out/openmates-remotion.mp4"
REMOTION_THUMBNAIL_OUTPUT = "out/openmates-remotion-thumbnail.png"
REMOTION_TEMPLATE_ENV = "E2B_REMOTION_TEMPLATE"
REMOTION_TEMPLATE_WORKDIR = "/home/user/remotion"
REMOTION_DEFAULT_WIDTH = 640
REMOTION_DEFAULT_HEIGHT = 360
REMOTION_RENDER_FLAGS = "--concurrency=1 --chromium-flags=\"--disable-dev-shm-usage --no-sandbox\""
REMOTION_BINARY = "./node_modules/.bin/remotion"
REMOTION_PACKAGE_JSON = {
    "scripts": {"render": "remotion render src/Root.tsx Main out/openmates-remotion.mp4"},
    "dependencies": {
        "@remotion/cli": "latest",
        "remotion": "latest",
        "react": "latest",
        "react-dom": "latest",
    },
    "devDependencies": {"typescript": "latest"},
}
REMOTION_CHROME_DEPS_INSTALL = (
    "sudo apt-get update && "
    "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
    "libnspr4 libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 "
    "libxdamage1 libxrandr2 libgbm1 libasound2 libxshmfence1"
)
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


class RemotionRenderPlanningError(ValueError):
    """Raised when generated Remotion render input is unsafe or incomplete."""


@dataclass(frozen=True)
class RemotionRenderPlan:
    files: list[ApplicationPreviewFile]
    install_commands: list[str]
    render_command: str
    output_path: str
    thumbnail_command: str
    thumbnail_path: str
    sandbox_template: str | None = None
    working_directory: str | None = None
    enable_internet: bool = True


@dataclass(frozen=True)
class RemotionRenderResult:
    video_bytes: bytes
    thumbnail_bytes: bytes
    sandbox_id: str
    logs: list[str]


def plan_remotion_render(
    *,
    source: str,
    filename: str | None = None,
    enable_internet: bool = True,
    sandbox_template: str | None = None,
) -> RemotionRenderPlan:
    if not source.strip():
        raise RemotionRenderPlanningError("Remotion source is required")
    if any(pattern.search(source) for pattern in SECRET_PATTERNS):
        raise RemotionRenderPlanningError("Remotion source appears to contain secrets")

    normalized_filename = _safe_remotion_source_path(filename)
    component_path = f"src/{normalized_filename}"
    root_content = _build_root_source(component_path)
    files = [
        ApplicationPreviewFile(path="package.json", content=json.dumps(REMOTION_PACKAGE_JSON, separators=(",", ":"))),
        ApplicationPreviewFile(path="src/Root.tsx", content=root_content),
        ApplicationPreviewFile(path=component_path, content=source),
    ]
    template = sandbox_template.strip() if sandbox_template else None
    working_directory = REMOTION_TEMPLATE_WORKDIR if template else None
    install_commands = [] if template else [
        REMOTION_CHROME_DEPS_INSTALL,
        "NODE_OPTIONS=--max-old-space-size=768 npm install --ignore-scripts --no-audit --no-fund",
    ]
    render_command = f"{REMOTION_BINARY} render src/Root.tsx Main {REMOTION_RENDER_OUTPUT} {REMOTION_RENDER_FLAGS}"
    thumbnail_command = (
        f"{REMOTION_BINARY} still src/Root.tsx Main {REMOTION_THUMBNAIL_OUTPUT} --frame=0 {REMOTION_RENDER_FLAGS}"
    )
    if working_directory:
        render_command = f"cd {working_directory} && {render_command}"
        thumbnail_command = f"cd {working_directory} && {thumbnail_command}"

    return RemotionRenderPlan(
        files=files,
        install_commands=install_commands,
        render_command=render_command,
        output_path=REMOTION_RENDER_OUTPUT,
        thumbnail_command=thumbnail_command,
        thumbnail_path=REMOTION_THUMBNAIL_OUTPUT,
        sandbox_template=template,
        working_directory=working_directory,
        enable_internet=enable_internet,
    )


def render_remotion_in_e2b(*, source: str, filename: str | None, api_key: str, enable_internet: bool = True) -> RemotionRenderResult:
    """Render a Remotion composition in E2B and return MP4/thumbnail bytes."""
    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc
    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")

    plan = plan_remotion_render(
        source=source,
        filename=filename,
        enable_internet=enable_internet,
        sandbox_template=_remotion_template_name(),
    )
    if plan.sandbox_template:
        sandbox = Sandbox.create(plan.sandbox_template, api_key=api_key, secure=True, allow_internet_access=plan.enable_internet)
    else:
        sandbox = Sandbox.create(api_key=api_key, secure=True, allow_internet_access=plan.enable_internet)
    logs: list[str] = []
    try:
        sandbox.files.write_files(_sandbox_file_payload(plan))
        sandbox.commands.run(_command_in_workdir(plan, "mkdir -p out"), timeout=30)
        for command in plan.install_commands:
            install_result = _run_sandbox_command(sandbox, command, label="install", timeout=300)
            logs.append(_safe_log_text(install_result))
        render_result = _run_sandbox_command(sandbox, plan.render_command, label="render", timeout=900)
        logs.append(_safe_log_text(render_result))
        thumbnail_result = _run_sandbox_command(sandbox, plan.thumbnail_command, label="thumbnail", timeout=120)
        logs.append(_safe_log_text(thumbnail_result))
        return RemotionRenderResult(
            video_bytes=_read_sandbox_file_bytes(sandbox, _sandbox_path(plan, plan.output_path)),
            thumbnail_bytes=_read_sandbox_file_bytes(sandbox, _sandbox_path(plan, plan.thumbnail_path)),
            sandbox_id=str(getattr(sandbox, "sandbox_id", "")),
            logs=[log for log in logs if log],
        )
    finally:
        sandbox_id = str(getattr(sandbox, "sandbox_id", ""))
        if sandbox_id:
            try:
                Sandbox.kill(sandbox_id=sandbox_id, api_key=api_key)
            except Exception:
                pass


def kill_remotion_sandbox_in_e2b(*, sandbox_id: str, api_key: str) -> bool:
    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc
    if not sandbox_id.strip():
        raise RuntimeError("E2B sandbox id is required")
    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")
    return bool(Sandbox.kill(sandbox_id=sandbox_id, api_key=api_key))


def _run_sandbox_command(sandbox: object, command: str, *, label: str, timeout: int) -> object:
    try:
        return sandbox.commands.run(command, timeout=timeout)  # type: ignore[attr-defined]
    except Exception as exc:
        raise RuntimeError(f"Remotion E2B {label} command failed: {command}: {exc}") from exc


def _remotion_template_name() -> str | None:
    value = os.getenv(REMOTION_TEMPLATE_ENV, "").strip()
    return value or None


def _sandbox_file_payload(plan: RemotionRenderPlan) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for file in plan.files:
        if plan.sandbox_template and file.path == "package.json":
            continue
        payload.append({"path": _sandbox_path(plan, file.path), "data": file.content})
    return payload


def _sandbox_path(plan: RemotionRenderPlan, path: str) -> str:
    if not plan.working_directory:
        return path
    return f"{plan.working_directory.rstrip('/')}/{path}"


def _command_in_workdir(plan: RemotionRenderPlan, command: str) -> str:
    if not plan.working_directory:
        return command
    return f"cd {plan.working_directory} && {command}"


def _read_sandbox_file_bytes(sandbox: object, path: str) -> bytes:
    value = sandbox.files.read(path)  # type: ignore[attr-defined]
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if hasattr(value, "read"):
        data = value.read()
        return data if isinstance(data, bytes) else str(data).encode("utf-8")
    return bytes(value)


def _safe_log_text(result: object) -> str:
    text = str(getattr(result, "stdout", "") or getattr(result, "stderr", "") or result or "")
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted[-4000:]


def _safe_remotion_source_path(filename: str | None) -> str:
    raw = (filename or "").strip().replace("\\", "/")
    raw_path = PurePosixPath(raw or "Composition.tsx")
    if raw_path.is_absolute() or any(part in {"", ".", ".."} for part in raw_path.parts):
        raise RemotionRenderPlanningError("Remotion source filename is unsafe")
    normalized = normalize_remotion_filename(filename)
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RemotionRenderPlanningError("Remotion source filename is unsafe")
    return path.as_posix()


def _build_root_source(component_path: str) -> str:
    import_path = "./" + component_path.removeprefix("src/").rsplit(".", 1)[0]
    return (
        "import React from 'react';\n"
        "import { Composition, registerRoot } from 'remotion';\n"
        f"import * as UserModule from '{import_path}';\n\n"
        "const Component = UserModule.default ?? UserModule.RemotionVideo ?? UserModule.ProductAnnouncement ?? "
        "Object.values(UserModule).find((value) => typeof value === 'function');\n\n"
        "if (!Component) {\n"
        "  throw new Error('Remotion source must export a React component');\n"
        "}\n\n"
        "export const RemotionRoot = () => (\n"
        f"  <Composition id=\"Main\" component={{Component}} durationInFrames={{150}} fps={{30}} width={{{REMOTION_DEFAULT_WIDTH}}} height={{{REMOTION_DEFAULT_HEIGHT}}} />\n"
        ");\n"
        "\nregisterRoot(RemotionRoot);\n"
    )
