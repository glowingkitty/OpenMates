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
import json
import queue
import re
import shlex
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, Literal

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager


WORKSPACE_DIR = "/home/user/openmates-run"
INSTALL_TIMEOUT_SECONDS = 120
RUN_TIMEOUT_SECONDS = 300
ARTIFACT_DISCOVERY_TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 100_000
MAX_ARTIFACTS = 10
MAX_ARTIFACT_BYTES = 5_000_000
MAX_TOTAL_ARTIFACT_BYTES = 20_000_000
E2B_SECRET_PATH = "kv/data/providers/e2b"
E2B_SECRET_KEY = "api_key"
E2B_ENV_VAR = "SECRET__E2B__API_KEY"
OUTPUTS_DIR = "outputs"
OUTPUT_MANIFEST = "openmates_outputs.json"
ALLOWED_ARTIFACT_EXTENSIONS = {
    ".csv": ("text/csv", "data"),
    ".gif": ("image/gif", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".jpg": ("image/jpeg", "image"),
    ".json": ("application/json", "data"),
    ".md": ("text/markdown", "text"),
    ".pdf": ("application/pdf", "document"),
    ".png": ("image/png", "image"),
    ".txt": ("text/plain", "text"),
    ".webp": ("image/webp", "image"),
    ".zip": ("application/zip", "archive"),
}
DENIED_ARTIFACT_SEGMENTS = {
    "__pycache__",
    ".cache",
    ".git",
    ".npm",
    ".venv",
    "node_modules",
    "venv",
}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
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
class CodeRunDependencyInstall:
    ecosystem: Literal["python", "npm"]
    packages: tuple[str, ...]


@dataclass(frozen=True)
class CodeRunResult:
    exit_code: int | None
    duration_seconds: float
    output_truncated: bool
    sandbox_id: str | None = None
    artifacts: list[dict[str, object]] | None = None
    skipped_artifacts: list[dict[str, str]] | None = None


OutputKind = Literal["status", "stdout", "stderr"]
OutputCallback = Callable[[OutputKind, str], None]
CancelCallback = Callable[[], bool]


class CodeRunCancelled(RuntimeError):
    """Raised when a user cancels an active sandbox command."""


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
    if language in {"c"} or file.path.endswith(".c"):
        return f"command -v gcc >/dev/null || {{ echo 'C execution is not available in this sandbox yet.' >&2; exit 127; }}; gcc {path} -o /tmp/openmates-run-bin && /tmp/openmates-run-bin"
    if language in {"cpp", "c++", "cplusplus"} or file.path.endswith((".cc", ".cpp", ".cxx")):
        return f"command -v g++ >/dev/null || {{ echo 'C++ execution is not available in this sandbox yet.' >&2; exit 127; }}; g++ {path} -std=c++17 -o /tmp/openmates-run-bin && /tmp/openmates-run-bin"
    if language in {"rust", "rs"} or file.path.endswith(".rs"):
        return f"command -v rustc >/dev/null || {{ echo 'Rust execution is not available in this sandbox yet.' >&2; exit 127; }}; rustc {path} -o /tmp/openmates-run-bin && /tmp/openmates-run-bin"
    if language in {"go", "golang"} or file.path.endswith(".go"):
        return f"command -v go >/dev/null || {{ echo 'Go execution is not available in this sandbox yet.' >&2; exit 127; }}; go run {path}"
    raise ValueError(f"Unsupported executable language for {file.path}")


def _dependency_commands(
    files: Iterable[CodeRunFile],
    dependency_installs: Iterable[CodeRunDependencyInstall] = (),
) -> list[tuple[str, str]]:
    names = {file.path.rsplit("/", 1)[-1] for file in files}
    commands: list[tuple[str, str]] = []

    if "requirements.txt" in names:
        commands.append(("Installing Python dependencies from requirements.txt...", "python -m pip install -r requirements.txt"))
    else:
        python_packages = sorted({pkg for install in dependency_installs if install.ecosystem == "python" for pkg in install.packages})
        if python_packages:
            packages = " ".join(shlex.quote(package) for package in python_packages)
            commands.append(("Installing selected Python packages...", f"python -m pip install {packages}"))

    if "package.json" in names:
        if "package-lock.json" in names:
            commands.append(("Installing JavaScript dependencies with npm ci --ignore-scripts...", "npm ci --ignore-scripts"))
        else:
            commands.append(("Installing JavaScript dependencies with npm install --ignore-scripts...", "npm install --ignore-scripts"))
    else:
        npm_packages = sorted({pkg for install in dependency_installs if install.ecosystem == "npm" for pkg in install.packages})
        if npm_packages:
            packages = " ".join(shlex.quote(package) for package in npm_packages)
            commands.append(("Installing selected npm packages...", f"npm install --ignore-scripts --no-audit --no-fund --package-lock=false {packages}"))

    return commands


def _file_payload(file: CodeRunFile) -> bytes | str:
    if file.content_base64:
        return base64.b64decode(file.content_base64)
    return file.content


def _emit(callback: OutputCallback, kind: OutputKind, text: str) -> None:
    callback(kind, redact_execution_output(text))


def _exit_code_from_result(value: object) -> int | None:
    return getattr(value, "exit_code", None)


def _artifact_discovery_command() -> str:
    allowed = {
        extension: {"mime_type": mime_type, "kind": kind}
        for extension, (mime_type, kind) in ALLOWED_ARTIFACT_EXTENSIONS.items()
    }
    script = f"""
import base64
import json
import os
import posixpath

WORKSPACE = {WORKSPACE_DIR!r}
OUTPUTS_DIR = {OUTPUTS_DIR!r}
OUTPUT_MANIFEST = {OUTPUT_MANIFEST!r}
MAX_ARTIFACTS = {MAX_ARTIFACTS}
MAX_ARTIFACT_BYTES = {MAX_ARTIFACT_BYTES}
MAX_TOTAL_ARTIFACT_BYTES = {MAX_TOTAL_ARTIFACT_BYTES}
ALLOWED = {json.dumps(allowed, sort_keys=True)!r}
DENIED_SEGMENTS = {json.dumps(sorted(DENIED_ARTIFACT_SEGMENTS))!r}
ALLOWED = json.loads(ALLOWED)
DENIED_SEGMENTS = set(json.loads(DENIED_SEGMENTS))

artifacts = []
skipped = []
seen = set()
total_bytes = 0

def skip(path, reason):
    skipped.append({{"path": str(path or ""), "reason": reason}})

def normalize(raw_path):
    raw = str(raw_path or "").replace("\\\\", "/").strip()
    if not raw or raw.startswith("/") or raw.startswith("~") or ":" in raw.split("/", 1)[0]:
        return None, "unsafe_path"
    normalized = posixpath.normpath(raw)
    if normalized in {{"", ".", ".."}} or normalized.startswith("../"):
        return None, "unsafe_path"
    segments = normalized.split("/")
    if any(not segment or segment.startswith(".") for segment in segments):
        return None, "hidden_or_secret_path"
    if any(segment in DENIED_SEGMENTS for segment in segments):
        return None, "denied_path"
    if len(normalized) > 255:
        return None, "path_too_long"
    return normalized, None

def add_candidate(raw_path):
    global total_bytes
    normalized, reason = normalize(raw_path)
    if reason:
        skip(raw_path, reason)
        return
    if normalized in seen:
        return
    extension = os.path.splitext(normalized.lower())[1]
    type_info = ALLOWED.get(extension)
    if not type_info:
        skip(normalized, "unsupported_type")
        return
    full_path = os.path.join(WORKSPACE, *normalized.split("/"))
    if not os.path.isfile(full_path):
        skip(normalized, "not_found")
        return
    size = os.path.getsize(full_path)
    if size <= 0:
        skip(normalized, "empty_file")
        return
    if size > MAX_ARTIFACT_BYTES:
        skip(normalized, "file_too_large")
        return
    if len(artifacts) >= MAX_ARTIFACTS:
        skip(normalized, "too_many_artifacts")
        return
    if total_bytes + size > MAX_TOTAL_ARTIFACT_BYTES:
        skip(normalized, "total_artifacts_too_large")
        return
    with open(full_path, "rb") as handle:
        content = handle.read()
    seen.add(normalized)
    total_bytes += size
    artifacts.append({{
        "path": normalized,
        "normalized_path": normalized,
        "mime_type": type_info["mime_type"],
        "kind": type_info["kind"],
        "size_bytes": size,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }})

outputs_root = os.path.join(WORKSPACE, OUTPUTS_DIR)
if os.path.isdir(outputs_root):
    for root, dirs, files in os.walk(outputs_root):
        dirs[:] = sorted(dirs)
        for filename in sorted(files):
            full_path = os.path.join(root, filename)
            add_candidate(os.path.relpath(full_path, WORKSPACE).replace(os.sep, "/"))

manifest_path = os.path.join(WORKSPACE, OUTPUT_MANIFEST)
if os.path.isfile(manifest_path):
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        entries = manifest.get("outputs") if isinstance(manifest, dict) else manifest
        if not isinstance(entries, list):
            raise ValueError("outputs must be a list")
        for entry in entries:
            if isinstance(entry, str):
                add_candidate(entry)
            elif isinstance(entry, dict):
                add_candidate(entry.get("path"))
            else:
                skip(OUTPUT_MANIFEST, "invalid_manifest_entry")
    except Exception:
        skip(OUTPUT_MANIFEST, "invalid_manifest")

print(json.dumps({{"artifacts": artifacts, "skipped": skipped}}, separators=(",", ":")))
""".strip()
    return "OPENMATES_CODE_RUN_DISCOVER_OUTPUTS=1 python - <<'PY'\n" + script + "\nPY"


def _parse_artifact_discovery(stdout: str) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    payload = json.loads(stdout.strip() or "{}")
    raw_artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    raw_skipped = payload.get("skipped") if isinstance(payload, dict) else None
    artifacts: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    if isinstance(raw_artifacts, list):
        for item in raw_artifacts[:MAX_ARTIFACTS]:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            normalized_path = item.get("normalized_path")
            mime_type = item.get("mime_type")
            kind = item.get("kind")
            content_base64 = item.get("content_base64")
            size_bytes = item.get("size_bytes")
            if (
                not isinstance(path, str)
                or not isinstance(normalized_path, str)
                or not isinstance(mime_type, str)
                or not isinstance(kind, str)
                or not isinstance(content_base64, str)
                or isinstance(size_bytes, bool)
                or not isinstance(size_bytes, int)
                or size_bytes <= 0
                or size_bytes > MAX_ARTIFACT_BYTES
            ):
                continue
            artifacts.append({
                "path": path,
                "normalized_path": normalized_path,
                "mime_type": mime_type,
                "kind": kind,
                "size_bytes": size_bytes,
                "content_base64": content_base64,
            })
    if isinstance(raw_skipped, list):
        for item in raw_skipped[:MAX_ARTIFACTS * 5]:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            reason = item.get("reason")
            if isinstance(path, str) and isinstance(reason, str):
                skipped.append({"path": path, "reason": reason})
    return artifacts, skipped


def _discover_output_artifacts(sandbox: object) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    try:
        result = sandbox.commands.run(_shell(_artifact_discovery_command(), ARTIFACT_DISCOVERY_TIMEOUT_SECONDS))
        return _parse_artifact_discovery(str(getattr(result, "stdout", "") or ""))
    except Exception as exc:
        return [], [{"path": OUTPUTS_DIR, "reason": f"artifact_discovery_failed: {redact_execution_output(str(exc))}"}]


def _run_interruptible_command(
    sandbox: object,
    command: str,
    timeout_seconds: int,
    stream: OutputCallback,
    should_cancel: CancelCallback | None,
) -> int | None:
    handle = sandbox.commands.run(_shell(command, timeout_seconds), background=True, timeout=timeout_seconds + 10)
    events: queue.Queue[tuple[str, object]] = queue.Queue()

    def wait_for_command() -> None:
        try:
            result = handle.wait(
                on_stdout=lambda data: events.put(("stdout", data)),
                on_stderr=lambda data: events.put(("stderr", data)),
            )
            events.put(("done", result))
        except Exception as exc:  # E2B raises on non-zero exit codes.
            events.put(("error", exc))

    waiter = threading.Thread(target=wait_for_command, daemon=True)
    waiter.start()

    while True:
        try:
            kind, value = events.get(timeout=0.2)
        except queue.Empty:
            if should_cancel and should_cancel():
                try:
                    handle.kill()
                finally:
                    raise CodeRunCancelled("Code run cancelled by user")
            if not waiter.is_alive():
                continue
            continue

        if kind in {"stdout", "stderr"}:
            stream(kind, str(value))
            continue
        if kind == "done":
            return _exit_code_from_result(value)
        if kind == "error":
            exit_code = _exit_code_from_result(value)
            if exit_code is not None:
                return exit_code
            if isinstance(value, BaseException):
                raise value
            raise RuntimeError(str(value))


def run_code_in_e2b(
    files: list[CodeRunFile],
    target_path: str,
    on_output: OutputCallback,
    api_key: str,
    dependency_installs: list[CodeRunDependencyInstall] | None = None,
    should_cancel: CancelCallback | None = None,
    enable_internet: bool = True,
) -> CodeRunResult:
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
        _emit(on_output, "status", "Starting sandbox...\n")
        sandbox = Sandbox.create(
            api_key=api_key,
            secure=True,
            allow_internet_access=enable_internet,
            network={"allow_public_traffic": False},
        )
        sandbox_id = getattr(sandbox, "sandbox_id", None) or getattr(sandbox, "id", None)
        if should_cancel and should_cancel():
            raise CodeRunCancelled("Code run cancelled by user")

        sandbox.commands.run(f"mkdir -p {shlex.quote(WORKSPACE_DIR)}")
        _emit(on_output, "status", f"Uploading {len(files)} files...\n")
        dirs = sorted({file.path.rsplit("/", 1)[0] for file in files if "/" in file.path})
        for directory in dirs:
            sandbox.commands.run(f"mkdir -p {shlex.quote(f'{WORKSPACE_DIR}/{directory}')}")
        sandbox.files.write_files([
            {"path": f"{WORKSPACE_DIR}/{file.path}", "data": _file_payload(file)}
            for file in files
        ])
        billable_started_at = time.monotonic()
        if should_cancel and should_cancel():
            raise CodeRunCancelled("Code run cancelled by user")

        for message, command in _dependency_commands(files, dependency_installs or []):
            if should_cancel and should_cancel():
                raise CodeRunCancelled("Code run cancelled by user")
            _emit(on_output, "status", message + "\n")
            exit_code = _run_interruptible_command(
                sandbox,
                f"cd {shlex.quote(WORKSPACE_DIR)} && {command}",
                INSTALL_TIMEOUT_SECONDS,
                stream,
                should_cancel,
            )
            if exit_code not in (None, 0):
                _emit(on_output, "stderr", f"Dependency installation failed with exit code {exit_code}.\n")
                return CodeRunResult(
                    exit_code=exit_code,
                    duration_seconds=time.monotonic() - billable_started_at,
                    output_truncated=output_truncated,
                    sandbox_id=sandbox_id,
                )

        run_command = _run_command_for_file(target)
        if should_cancel and should_cancel():
            raise CodeRunCancelled("Code run cancelled by user")
        _emit(on_output, "status", f"Running ({target.path})...\n")
        exit_code = _run_interruptible_command(
            sandbox,
            f"cd {shlex.quote(WORKSPACE_DIR)} && {run_command}",
            RUN_TIMEOUT_SECONDS,
            stream,
            should_cancel,
        )
        artifacts, skipped_artifacts = _discover_output_artifacts(sandbox)
        return CodeRunResult(
            exit_code=exit_code,
            duration_seconds=time.monotonic() - billable_started_at,
            output_truncated=output_truncated,
            sandbox_id=sandbox_id,
            artifacts=artifacts,
            skipped_artifacts=skipped_artifacts,
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
