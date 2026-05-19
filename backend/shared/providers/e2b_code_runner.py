# backend/shared/providers/e2b_code_runner.py
#
# Restricted E2B code execution provider for OpenMates Code Run.
# Creates an isolated sandbox, writes already-collected chat code files, installs
# supported dependency manifests with conservative commands, and runs one target
# file. The sandbox is never authenticated as an OpenMates device and receives no
# user secrets or account data.

from __future__ import annotations

import os
import base64
import re
import shlex
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, Literal

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager


WORKSPACE_DIR = "/home/user/openmates-run"
INSTALL_TIMEOUT_SECONDS = 120
RUN_TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 100_000
E2B_SECRET_PATH = "kv/data/providers/e2b"
E2B_SECRET_KEY = "api_key"
E2B_ENV_VAR = "SECRET__E2B__API_KEY"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[^\s]+"),
]


@dataclass(frozen=True)
class CodeRunFile:
    path: str
    language: str
    content: str = ""
    is_target: bool = False
    content_base64: str | None = None
    mime_type: str | None = None
    source_embed_id: str | None = None


@dataclass(frozen=True)
class CodeRunResult:
    exit_code: int | None
    duration_seconds: float
    output_truncated: bool
    sandbox_id: str | None = None


OutputKind = Literal["status", "stdout", "stderr"]
OutputCallback = Callable[[OutputKind, str], None]


async def get_e2b_api_key_async(secrets_manager: "SecretsManager" | None = None) -> str:
    """Resolve the E2B API key from Vault, falling back to SECRET__E2B__API_KEY."""
    if secrets_manager:
        try:
            api_key = await secrets_manager.get_secret(
                secret_path=E2B_SECRET_PATH,
                secret_key=E2B_SECRET_KEY,
            )
            if api_key and api_key.strip():
                return api_key.strip()
        except Exception as exc:
            raise RuntimeError("Failed to retrieve E2B API key from Vault") from exc

    env_api_key = os.getenv(E2B_ENV_VAR, "").strip()
    if env_api_key and env_api_key != "IMPORTED_TO_VAULT":
        return env_api_key

    raise RuntimeError(
        f"E2B API key is not configured. Add {E2B_ENV_VAR} so it can be imported "
        f"into Vault at {E2B_SECRET_PATH}/{E2B_SECRET_KEY}."
    )


def redact_execution_output(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED_SECRET>", redacted)
    return redacted


def _shell(command: str, timeout_seconds: int) -> str:
    return f"timeout {timeout_seconds}s bash -lc {shlex.quote(command)}"


def _run_command_for_file(file: CodeRunFile) -> str:
    path = shlex.quote(file.path)
    language = (file.language or "").lower()

    if language in {"python", "py"} or file.path.endswith(".py"):
        return f"python {path}"
    if language in {"javascript", "js", "node"} or file.path.endswith((".js", ".mjs", ".cjs")):
        return f"node {path}"
    if language in {"typescript", "ts"} or file.path.endswith(".ts"):
        return f"npx --yes tsx {path}"
    if language in {"bash", "sh", "shell"} or file.path.endswith(".sh"):
        return f"bash {path}"
    raise ValueError(f"Unsupported executable language for {file.path}")


def _dependency_commands(files: Iterable[CodeRunFile]) -> list[tuple[str, str]]:
    names = {file.path.rsplit("/", 1)[-1] for file in files}
    commands: list[tuple[str, str]] = []

    if "requirements.txt" in names:
        commands.append(("Installing Python dependencies from requirements.txt...", "python -m pip install -r requirements.txt"))

    if "package.json" in names:
        if "package-lock.json" in names:
            commands.append(("Installing JavaScript dependencies with npm ci --ignore-scripts...", "npm ci --ignore-scripts"))
        else:
            commands.append(("Installing JavaScript dependencies with npm install --ignore-scripts...", "npm install --ignore-scripts"))

    return commands


def _file_payload(file: CodeRunFile) -> bytes | str:
    if file.content_base64:
        return base64.b64decode(file.content_base64)
    return file.content


def _emit(callback: OutputCallback, kind: OutputKind, text: str) -> None:
    callback(kind, redact_execution_output(text))


def run_code_in_e2b(files: list[CodeRunFile], target_path: str, on_output: OutputCallback, api_key: str) -> CodeRunResult:
    """Run one target file in an E2B sandbox and stream sanitized output."""
    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc

    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")

    target = next((file for file in files if file.path == target_path), None)
    if target is None:
        raise ValueError("Target file is not present in the execution file set")

    output_chars = 0
    output_truncated = False
    sandbox = None
    billable_started_at = 0.0

    def stream(kind: OutputKind, text: str) -> None:
        nonlocal output_chars, output_truncated
        if output_chars >= MAX_OUTPUT_CHARS:
            output_truncated = True
            return
        remaining = MAX_OUTPUT_CHARS - output_chars
        chunk = text[:remaining]
        output_chars += len(chunk)
        if len(text) > len(chunk):
            output_truncated = True
        _emit(on_output, kind, chunk)

    try:
        _emit(on_output, "status", "Preparing sandbox...\n")
        sandbox = Sandbox.create(api_key=api_key)
        sandbox_id = getattr(sandbox, "sandbox_id", None) or getattr(sandbox, "id", None)
        _emit(on_output, "status", "Sandbox started. Preparing files...\n")

        sandbox.commands.run(f"mkdir -p {shlex.quote(WORKSPACE_DIR)}")
        _emit(on_output, "status", f"Uploading {len(files)} chat files...\n")
        dirs = sorted({file.path.rsplit("/", 1)[0] for file in files if "/" in file.path})
        for directory in dirs:
            sandbox.commands.run(f"mkdir -p {shlex.quote(f'{WORKSPACE_DIR}/{directory}')}")
        sandbox.files.write_files([
            {"path": f"{WORKSPACE_DIR}/{file.path}", "data": _file_payload(file)}
            for file in files
        ])
        billable_started_at = time.monotonic()
        _emit(on_output, "status", "User code setup started. Tracking billable runtime...\n")

        for message, command in _dependency_commands(files):
            _emit(on_output, "status", message + "\n")
            install = sandbox.commands.run(
                _shell(f"cd {shlex.quote(WORKSPACE_DIR)} && {command}", INSTALL_TIMEOUT_SECONDS),
                on_stdout=lambda data: stream("stdout", data),
                on_stderr=lambda data: stream("stderr", data),
            )
            exit_code = getattr(install, "exit_code", None)
            if exit_code not in (None, 0):
                _emit(on_output, "stderr", f"Dependency installation failed with exit code {exit_code}.\n")
                return CodeRunResult(
                    exit_code=exit_code,
                    duration_seconds=time.monotonic() - billable_started_at,
                    output_truncated=output_truncated,
                    sandbox_id=sandbox_id,
                )

        run_command = _run_command_for_file(target)
        _emit(on_output, "status", f"Running {target.path}...\n")
        result = sandbox.commands.run(
            _shell(f"cd {shlex.quote(WORKSPACE_DIR)} && {run_command}", RUN_TIMEOUT_SECONDS),
            on_stdout=lambda data: stream("stdout", data),
            on_stderr=lambda data: stream("stderr", data),
        )
        exit_code = getattr(result, "exit_code", None)
        return CodeRunResult(
            exit_code=exit_code,
            duration_seconds=time.monotonic() - billable_started_at,
            output_truncated=output_truncated,
            sandbox_id=sandbox_id,
        )
    finally:
        if sandbox is not None:
            for method_name in ("kill", "close"):
                method = getattr(sandbox, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
                    break
