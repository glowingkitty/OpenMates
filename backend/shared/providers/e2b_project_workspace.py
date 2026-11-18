# backend/shared/providers/e2b_project_workspace.py
#
# E2B workspace sandbox for cloud Project terminal commands.
# One sandbox per (user, chat, Project) is reused across commands and turns while
# it is alive, so installed dependencies and a started dev server persist. The
# encrypted Project files stay the source of truth: before each command the
# client's file snapshot is synced in (changed files written, removed files
# deleted, untracked outputs such as node_modules kept), and after it the files
# the command changed itself are detected so they can be synced back as diffs.
# The sandbox receives file contents only, never keys or secrets.
# Spec: feature.app-skill.code-run code-run.cloud.commands, code-run.cloud.workspace,
# code-run.cloud.command-changes-sync-back. Plan: docs/plans/cloud-project-commands.

from __future__ import annotations

import hashlib
import json
import os
import shlex
import time
from dataclasses import dataclass, field
from typing import Any

from backend.shared.providers.e2b_code_runner import (
    CODE_RUN_TEMPLATE_ENV,
    CancelCallback,
    CodeRunCancelled,
    OutputCallback,
    _emit,
    _run_interruptible_command,
)

PROJECT_DIR = "/home/user/project"
WORKSPACE_IDLE_TIMEOUT_SECONDS = 15 * 60
WORKSPACE_MAX_LIFETIME_SECONDS = 60 * 60
MAX_SYNC_BACK_FILES = 20
MAX_SYNC_BACK_FILE_BYTES = 256 * 1024
MAX_MODEL_OUTPUT_CHARS = 64 * 1024
BACKGROUND_READY_POLL_SECONDS = 1.0
DEFAULT_READY_TIMEOUT_SECONDS = 90
SCAN_TIMEOUT_SECONDS = 60
# Folders a command may fill freely; they are command-only outputs, never Project files.
DEFAULT_IGNORED_DIRS = (
    "node_modules", "dist", "build", ".svelte-kit", ".cache", "coverage", ".git",
    ".next", ".nuxt", ".turbo", ".vite", "__pycache__", ".venv", "venv", ".pytest_cache",
    "outputs", "test-results", "playwright-report",
)

# Runs inside the sandbox; prints {"files": {path: sha256 | "binary" | "large"}}.
# Honors every .gitignore it walks past (relative to its folder) plus DEFAULT_IGNORED_DIRS.
_SCAN_SCRIPT = r'''
import fnmatch, hashlib, json, os, sys
root, ignored_dirs, limit = sys.argv[1], set(json.loads(sys.argv[2])), int(sys.argv[3])
rules = []
def load(folder):
    path = os.path.join(folder, ".gitignore")
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return
    base = os.path.relpath(folder, root).replace(os.sep, "/")
    base = "" if base == "." else base + "/"
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        rules.append((base, line.rstrip("/"), line.endswith("/")))
def ignored(rel, is_dir):
    name = rel.rsplit("/", 1)[-1]
    for base, pattern, dir_only in rules:
        if dir_only and not is_dir:
            continue
        if not rel.startswith(base):
            continue
        local = rel[len(base):]
        if "/" in pattern.lstrip("/"):
            if fnmatch.fnmatch(local, pattern.lstrip("/")):
                return True
        elif fnmatch.fnmatch(name, pattern.lstrip("/")):
            return True
    return False
files = {}
for folder, dirs, names in os.walk(root):
    load(folder)
    rel_folder = os.path.relpath(folder, root).replace(os.sep, "/")
    rel_folder = "" if rel_folder == "." else rel_folder + "/"
    dirs[:] = sorted(d for d in dirs if d not in ignored_dirs and not ignored(rel_folder + d, True)
                     and not os.path.islink(os.path.join(folder, d)))
    for name in sorted(names):
        rel = rel_folder + name
        full = os.path.join(folder, name)
        if os.path.islink(full) or ignored(rel, False):
            continue
        try:
            size = os.path.getsize(full)
            if size > limit:
                files[rel] = "large"
                continue
            data = open(full, "rb").read()
        except OSError:
            continue
        if b"\0" in data:
            files[rel] = "binary"
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            files[rel] = "binary"
            continue
        files[rel] = hashlib.sha256(data).hexdigest()
print(json.dumps({"files": files}))
'''


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class WorkspaceState:
    """Redis-held identity of one workspace sandbox and the files it holds."""

    sandbox_id: str
    created_at: float
    synced: dict[str, str] = field(default_factory=dict)  # path -> sha256 in the sandbox
    unsynced: dict[str, str] = field(default_factory=dict)  # reported, not synced (binary/large)

    def to_dict(self) -> dict[str, Any]:
        return {"sandbox_id": self.sandbox_id, "created_at": self.created_at,
                "synced": dict(self.synced), "unsynced": dict(self.unsynced)}

    @classmethod
    def from_dict(cls, value: Any) -> "WorkspaceState | None":
        if not isinstance(value, dict) or not isinstance(value.get("sandbox_id"), str):
            return None
        return cls(
            sandbox_id=value["sandbox_id"],
            created_at=float(value.get("created_at") or 0),
            synced={str(k): str(v) for k, v in (value.get("synced") or {}).items()},
            unsynced={str(k): str(v) for k, v in (value.get("unsynced") or {}).items()},
        )


@dataclass(frozen=True)
class WorkspaceCommand:
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    background: bool = False
    ready_url: str | None = None


@dataclass(frozen=True)
class FileChange:
    path: str
    kind: str  # create | update | delete
    expected_base: str | None
    content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {"path": self.path, "kind": self.kind, "expected_base": self.expected_base}
        if self.content is not None:
            item["content"] = self.content
        return item


@dataclass
class WorkspaceOutcome:
    exit_code: int | None
    duration_seconds: float
    sandbox_id: str
    reused: bool
    state: WorkspaceState
    changes: list[FileChange] = field(default_factory=list)
    not_synced: list[dict[str, str]] = field(default_factory=list)
    ready: bool | None = None


def plan_sync(
    snapshot: dict[str, str], synced: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Return (paths to write, paths to delete) to bring the sandbox to the snapshot.

    Only paths this workspace synced before are ever deleted, so dependencies
    and build outputs the commands produced stay in place.
    """
    shas = {path: content_sha256(text) for path, text in snapshot.items()}
    writes = sorted(path for path, sha in shas.items() if synced.get(path) != sha)
    deletes = sorted(path for path in synced if path not in snapshot)
    return writes, deletes


def detect_changes(
    scanned: dict[str, str],
    snapshot_shas: dict[str, str],
    previously_unsynced: dict[str, str],
) -> tuple[list[tuple[str, str]], list[str], list[dict[str, str]], dict[str, str]]:
    """Compare the post-command scan with the synced snapshot.

    Returns (changed_or_new [(path, kind)], deleted paths, not_synced entries,
    unsynced map for the state). Binary or oversized files are reported once per
    content, never synced.
    """
    changed: list[tuple[str, str]] = []
    not_synced: list[dict[str, str]] = []
    unsynced: dict[str, str] = {}
    for path, marker in sorted(scanned.items()):
        if marker in {"binary", "large"}:
            unsynced[path] = marker
            if previously_unsynced.get(path) != marker and snapshot_shas.get(path) is None:
                not_synced.append({"path": path, "reason": "binary_file" if marker == "binary" else "file_too_large"})
            continue
        base = snapshot_shas.get(path)
        if base is None:
            changed.append((path, "create"))
        elif base != marker:
            changed.append((path, "update"))
    deleted = sorted(path for path in snapshot_shas if path not in scanned)
    return changed, deleted, not_synced, unsynced


def truncate_for_model(text: str, limit: int = MAX_MODEL_OUTPUT_CHARS) -> tuple[str, bool]:
    """Keep head and tail of long command output; mark the cut explicitly."""
    if len(text) <= limit:
        return text, False
    half = limit // 2
    omitted = len(text) - 2 * half
    return f"{text[:half]}\n[... {omitted} characters of output omitted ...]\n{text[-half:]}", True


def _project_path(path: str) -> str:
    return f"{PROJECT_DIR}/{path}"


def _connect_or_create(state: WorkspaceState | None, api_key: str, on_output: OutputCallback) -> tuple[Any, bool]:
    from e2b import Sandbox, SandboxException

    if state is not None and time.time() - state.created_at < WORKSPACE_MAX_LIFETIME_SECONDS:
        try:
            sandbox = Sandbox.connect(state.sandbox_id, api_key=api_key, retries=0)
            sandbox.set_timeout(WORKSPACE_IDLE_TIMEOUT_SECONDS)
            _emit(on_output, "status", "Reusing the Project workspace...\n")
            return sandbox, True
        except SandboxException as exc:  # gone, expired or killed: rebuild from the snapshot
            _emit(on_output, "status", f"Workspace unavailable ({type(exc).__name__}); starting a new one...\n")
    _emit(on_output, "status", "Starting sandbox...\n")
    template = {"template": os.environ[CODE_RUN_TEMPLATE_ENV]} if os.getenv(CODE_RUN_TEMPLATE_ENV) else {}
    sandbox = Sandbox.create(
        **template, api_key=api_key, secure=True, timeout=WORKSPACE_IDLE_TIMEOUT_SECONDS,
        allow_internet_access=True, network={"allow_public_traffic": False},
        metadata={"openmates_purpose": "cloud_project_workspace"},
    )
    return sandbox, False


def _sync(sandbox: Any, snapshot: dict[str, str], state: WorkspaceState, on_output: OutputCallback) -> None:
    writes, deletes = plan_sync(snapshot, state.synced)
    _emit(on_output, "status", f"Uploading {len(writes)} changed files...\n")
    dirs = sorted({_project_path(p.rsplit("/", 1)[0]) for p in writes if "/" in p})
    sandbox.commands.run("mkdir -p " + " ".join(shlex.quote(p) for p in [PROJECT_DIR, *dirs]))
    if writes:
        sandbox.files.write_files([{"path": _project_path(p), "data": snapshot[p]} for p in writes])
    if deletes:
        sandbox.commands.run("rm -f -- " + " ".join(shlex.quote(_project_path(p)) for p in deletes))
    state.synced = {path: content_sha256(text) for path, text in snapshot.items()}


def _scan(sandbox: Any) -> dict[str, str]:
    script = f"{PROJECT_DIR}/../.openmates-scan.py"
    sandbox.files.write(script, _SCAN_SCRIPT)
    result = sandbox.commands.run(
        " ".join(shlex.quote(part) for part in [
            "python3", script, PROJECT_DIR, json.dumps(list(DEFAULT_IGNORED_DIRS)), str(MAX_SYNC_BACK_FILE_BYTES),
        ]),
        timeout=SCAN_TIMEOUT_SECONDS,
    )
    parsed = json.loads(str(getattr(result, "stdout", "") or "{}"))
    files = parsed.get("files")
    if not isinstance(files, dict):
        raise RuntimeError("Workspace change scan returned no file list")
    return {str(k): str(v) for k, v in files.items()}


def _command_line(command: WorkspaceCommand) -> str:
    cwd = PROJECT_DIR if command.cwd in {"", "."} else _project_path(command.cwd.strip("/"))
    return f"cd {shlex.quote(cwd)} && exec {shlex.join(command.argv)}"


def _start_background(sandbox: Any, command: WorkspaceCommand, on_output: OutputCallback,
                      should_cancel: CancelCallback | None) -> tuple[int | None, bool]:
    log = f"{PROJECT_DIR}/../.openmates-bg-{hashlib.sha256(shlex.join(command.argv).encode()).hexdigest()[:12]}.log"
    line = _command_line(command)
    sandbox.commands.run(
        f"nohup bash -lc {shlex.quote(line)} > {shlex.quote(log)} 2>&1 &", timeout=30,
    )
    deadline = time.monotonic() + min(command.timeout_seconds, DEFAULT_READY_TIMEOUT_SECONDS)
    ready = False
    while time.monotonic() < deadline:
        if should_cancel and should_cancel():
            raise CodeRunCancelled("Code run cancelled by user")
        probe = sandbox.commands.run(
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 2 {shlex.quote(str(command.ready_url))} || true",
            timeout=10,
        )
        code = str(getattr(probe, "stdout", "") or "").strip()
        if code and code != "000":
            ready = True
            break
        time.sleep(BACKGROUND_READY_POLL_SECONDS)
    tail = sandbox.commands.run(f"tail -c 16000 {shlex.quote(log)} || true", timeout=10)
    _emit(on_output, "stdout", str(getattr(tail, "stdout", "") or ""))
    _emit(on_output, "status", "Dev server is ready.\n" if ready else "Dev server did not become ready in time.\n")
    return (0 if ready else 1), ready


def run_workspace_command(
    snapshot: dict[str, str],
    state: WorkspaceState | None,
    command: WorkspaceCommand,
    on_output: OutputCallback,
    api_key: str,
    should_cancel: CancelCallback | None = None,
) -> WorkspaceOutcome:
    """Run one command in the Project workspace and detect the files it changed.

    ``snapshot`` maps Project-relative paths to the client's current text. The
    returned state replaces the stored one; ``changes`` are the sync-back entries
    with expected bases taken from the snapshot.
    """
    started = time.monotonic()
    sandbox, reused = _connect_or_create(state, api_key, on_output)
    sandbox_id = str(getattr(sandbox, "sandbox_id", None) or getattr(sandbox, "id", ""))
    current = state if (reused and state is not None) else WorkspaceState(sandbox_id=sandbox_id, created_at=time.time())
    if should_cancel and should_cancel():
        raise CodeRunCancelled("Code run cancelled by user")
    _sync(sandbox, snapshot, current, on_output)
    _emit(on_output, "status", f"Running {shlex.join(command.argv)}...\n")
    ready: bool | None = None
    if command.background:
        exit_code, ready = _start_background(sandbox, command, on_output, should_cancel)
    else:
        exit_code = _run_interruptible_command(
            sandbox, _command_line(command), command.timeout_seconds, lambda kind, text: _emit(on_output, kind, text),
            should_cancel,
        )
    snapshot_shas = dict(current.synced)
    changed, deleted, not_synced, unsynced = detect_changes(_scan(sandbox), snapshot_shas, current.unsynced)
    changes: list[FileChange] = []
    for path, kind in changed:
        if len(changes) >= MAX_SYNC_BACK_FILES:
            not_synced.append({"path": path, "reason": "too_many_changed_files"})
            continue
        text = sandbox.files.read(_project_path(path))
        text = text.decode("utf-8") if isinstance(text, (bytes, bytearray)) else str(text)
        changes.append(FileChange(path=path, kind=kind, expected_base=snapshot_shas.get(path), content=text))
        current.synced[path] = content_sha256(text)
    for path in deleted:
        if len(changes) >= MAX_SYNC_BACK_FILES:
            not_synced.append({"path": path, "reason": "too_many_changed_files"})
            continue
        changes.append(FileChange(path=path, kind="delete", expected_base=snapshot_shas.get(path)))
        current.synced.pop(path, None)
    current.unsynced = unsynced
    sandbox.set_timeout(WORKSPACE_IDLE_TIMEOUT_SECONDS)
    return WorkspaceOutcome(
        exit_code=exit_code, duration_seconds=time.monotonic() - started, sandbox_id=sandbox_id,
        reused=reused, state=current, changes=changes, not_synced=not_synced, ready=ready,
    )
