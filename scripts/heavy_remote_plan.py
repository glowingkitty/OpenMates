#!/usr/bin/env python3
"""Decide whether a heavy_slot command can run in an E2B sandbox, and what to upload.

Standard library only, so `heavy_slot.py` (system python) can plan a remote run
before handing it to `heavy_remote.py` (which needs the E2B SDK venv).

Remote-eligible commands are those whose result is only their output and exit
code: `cargo test|check|clippy` (host target only) and `vitest` runs without
snapshot updates, given directly or as a `bash -c "cd DIR && CMD | tail -N"`
payload. Everything else (builds whose artifacts are used locally, other
targets, Docker, Apple) stays on the local heavy slot.

The sandbox holds the public repository at a baseline commit (the template's
HEAD). A run uploads only the files where the worktree differs from that commit
(tracked changes and untracked files that git does not ignore) and deletes the
files the worktree removed.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REMOTE_ROOT = "/home/user/repo"
CARGO_REMOTE_SUBCOMMANDS = frozenset({"test", "check", "clippy"})
VITEST_UPDATE_FLAGS = frozenset({"-u", "--update"})
PIPE_FILTERS = frozenset({"tail", "head", "grep"})
MAX_SYNC_FILE_BYTES = 20 * 1024 * 1024
DEPENDENCY_MANIFESTS = ("pnpm-lock.yaml", "package.json", "pnpm-workspace.yaml")


@dataclass(frozen=True)
class RemoteCommand:
    """A command accepted for a remote run, already mapped into the sandbox."""

    kind: str  # "cargo" or "vitest"
    shell: str  # bash -c payload run in the sandbox
    cwd: str  # sandbox working directory


@dataclass
class SyncPlan:
    """Files to upload and delete so the sandbox repo matches the worktree."""

    upload: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    skipped_large: list[str] = field(default_factory=list)

    @property
    def dependencies_changed(self) -> bool:
        return any(Path(p).name in DEPENDENCY_MANIFESTS for p in [*self.upload, *self.delete])


def _cargo_kind(argv: list[str]) -> str | None:
    args = argv[1:]
    if args and args[0].startswith("+"):
        return None  # a pinned non-default toolchain is not in the template
    sub = next((a for a in args if not a.startswith("-")), None)
    if sub not in CARGO_REMOTE_SUBCOMMANDS:
        return None
    if any(a == "--target" or a.startswith("--target=") for a in args):
        return None  # only the host target is installed in the sandbox
    return "cargo"


def _vitest_kind(argv: list[str]) -> str | None:
    if "vitest" not in argv or VITEST_UPDATE_FLAGS & set(argv):
        return None
    if any(a.startswith("--update") for a in argv):
        return None
    return "vitest"


def command_kind(argv: list[str]) -> str | None:
    """Return "cargo"/"vitest" when argv alone is remote-eligible, else None."""
    if not argv:
        return None
    tool = os.path.basename(argv[0])
    if tool == "cargo":
        return _cargo_kind(argv)
    if tool in {"npx", "pnpm"}:
        return _vitest_kind(argv)
    return None


def _split_segments(payload: str) -> tuple[list[list[str]], list[str]] | None:
    """Split `a && b 2>&1 | c` into argv segments and their separators.

    Only `&&`, `|` and `2>&1` are understood; any other shell syntax
    (file redirection, `;`, background jobs) returns None so the run stays local.
    """
    try:
        lexer = shlex.shlex(payload, posix=True, punctuation_chars="&|;<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    separators: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in {"&&", "|"}:
            separators.append(tok)
            segments.append([])
        elif tok == ">&" and segments[-1][-1:] == ["2"] and tokens[i + 1:i + 2] == ["1"]:
            segments[-1][-1] = "2>&1"
            i += 1
        elif set(tok) & set("&|;<>"):
            return None
        else:
            segments[-1].append(tok)
        i += 1
    if not all(segments):
        return None
    return segments, separators


def _map_path(value: str, root: Path) -> str:
    root_text = str(root)
    if value == root_text or value.startswith(root_text + "/"):
        return REMOTE_ROOT + value[len(root_text):]
    return value


def _map_argv(argv: list[str], root: Path) -> list[str]:
    mapped = []
    for arg in argv:
        if "=" in arg and arg.startswith("--"):
            key, _, value = arg.partition("=")
            mapped.append(f"{key}={_map_path(value, root)}")
        else:
            mapped.append(_map_path(arg, root))
    return mapped


def remote_cwd(cwd: Path, root: Path) -> str | None:
    try:
        rel = cwd.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return REMOTE_ROOT if str(rel) == "." else f"{REMOTE_ROOT}/{rel.as_posix()}"


def plan_command(argv: list[str], cwd: Path, root: Path) -> RemoteCommand | None:
    """Map a heavy_slot command to a sandbox command, or None to run it locally."""
    sandbox_cwd = remote_cwd(cwd, root)
    if sandbox_cwd is None or not argv:
        return None
    kind = command_kind(argv)
    if kind:
        return RemoteCommand(kind, shlex.join(_map_argv(argv, root)), sandbox_cwd)
    if os.path.basename(argv[0]) not in {"bash", "sh"} or len(argv) != 3 or argv[1] != "-c":
        return None
    split = _split_segments(argv[2])
    if split is None:
        return None
    segments, separators = split
    kinds = []
    for seg in segments:
        words = [w for w in seg if w != "2>&1"]
        head = os.path.basename(words[0]) if words else ""
        if head == "cd":
            if len(words) != 2:
                return None
            target = Path(words[1]) if Path(words[1]).is_absolute() else cwd / words[1]
            if remote_cwd(target, root) is None:
                return None
        elif head in PIPE_FILTERS:
            continue
        else:
            seg_kind = command_kind(words)
            if seg_kind is None:
                return None
            kinds.append(seg_kind)
    if len(set(kinds)) != 1:
        return None
    parts = [" ".join("2>&1" if w == "2>&1" else shlex.quote(w) for w in _map_argv(seg, root))
             for seg in segments]
    shell = parts[0] + "".join(f" {sep} {part}" for sep, part in zip(separators, parts[1:]))
    return RemoteCommand(kinds[0], shell, sandbox_cwd)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout


def has_commit(root: Path, commit: str) -> bool:
    return subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
                          capture_output=True).returncode == 0


def sync_plan(root: Path, base: str) -> SyncPlan:
    """List the worktree files that differ from `base` (the sandbox checkout)."""
    plan = SyncPlan()
    diff = _git(root, "diff", "--name-status", "--no-renames", "-z", base)
    fields = diff.split("\0")
    changed: set[str] = set()
    for status, path in zip(fields[0::2], fields[1::2]):
        if status == "D":
            plan.delete.append(path)
        elif path:
            changed.add(path)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    changed.update(p for p in untracked.split("\0") if p)
    for path in sorted(changed):
        full = root / path
        if not full.exists() and not full.is_symlink():
            plan.delete.append(path)
        elif full.is_file() and not full.is_symlink() and full.stat().st_size > MAX_SYNC_FILE_BYTES:
            plan.skipped_large.append(path)
        else:
            plan.upload.append(path)
    return plan
