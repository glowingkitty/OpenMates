#!/usr/bin/env python3
"""Decide whether a heavy_slot command runs in an E2B sandbox, and what moves in and out.

Standard library only, so `heavy_slot.py` (system python) can plan a remote run
before handing it to `heavy_remote.py` (which needs the E2B SDK venv).

Remote kinds (everything else stays on the local heavy slot):
- cargo: `cargo test|check|clippy|build` for the host target. `cargo build`
  copies the top-level files of `target/{debug,release}` it produced back.
- vitest: `vitest` without snapshot updates.
- node: the translation build (`build:translations`, `build-translations.js`),
  `svelte-check` and `svelte-kit sync`.
- playwright: `playwright test` / `@playwright/test/cli.js test`. Its config and
  output may live in a folder under /tmp (the real-run proof folders); that
  folder is copied in before and its new files are copied back after the run.

Every remote run copies back the repository files the command created or
changed (generated locale JSON, snapshots, Cargo.lock), so its result matches a
local run. A command may be given directly or as a `bash -c` payload made of
`cd`, `export VAR=value`, `echo`, output filters (`tail`, `grep`, ...) and the
commands above, joined by `&&`, `||`, `;` or `|`, with `2>&1` and `>/dev/null`.
Any other shell syntax (file redirection, background jobs, substitution) stays
local.

The sandbox holds the public repository at a baseline commit (the template's
HEAD). A run uploads only the files where the worktree differs from that commit
(tracked changes and untracked files that git does not ignore) and deletes the
files the worktree removed. The worktree's absolute path is linked to the
sandbox checkout, so absolute paths in configs keep working.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REMOTE_ROOT = "/home/user/repo"
CARGO_REMOTE_SUBCOMMANDS = frozenset({"test", "check", "clippy", "build"})
VITEST_UPDATE_FLAGS = frozenset({"-u", "--update"})
PIPE_FILTERS = frozenset({"tail", "head", "grep", "wc", "cut", "sort", "uniq", "tr"})
NOOP_COMMANDS = frozenset({"echo", "true", "date"})
NODE_SCRIPTS = frozenset({"build:translations"})
NODE_TOOLS = frozenset({"svelte-check", "svelte-kit"})
SHELL_OPERATORS = frozenset({"&&", "||", ";", "|"})
MAX_SYNC_FILE_BYTES = 20 * 1024 * 1024
# A /tmp folder copied into the sandbox (playwright proof folders) must stay small.
EXTERNAL_ROOTS = ("/tmp/",)
MAX_EXTERNAL_DIR_BYTES = 50 * 1024 * 1024
MAX_EXTERNAL_DIR_FILES = 2000
DEPENDENCY_MANIFESTS = ("pnpm-lock.yaml", "package.json", "pnpm-workspace.yaml")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class RemoteCommand:
    """A command accepted for a remote run, already mapped into the sandbox."""

    kind: str  # "cargo", "vitest", "node" or "playwright"
    shell: str  # bash -c payload run in the sandbox
    cwd: str  # sandbox working directory
    external_dirs: tuple[str, ...] = ()  # /tmp folders mirrored in and copied back
    cargo_build: bool = False  # copy target/{debug,release} outputs back


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
    if VITEST_UPDATE_FLAGS & set(argv) or any(a.startswith("--update") for a in argv):
        return None
    return "vitest"


def _is_playwright_test(argv: list[str]) -> bool:
    words = [os.path.basename(a) for a in argv]
    if "test" not in argv:
        return False
    if "playwright" in words:
        return True
    return any(a.endswith("@playwright/test/cli.js") for a in argv)


def command_kind(argv: list[str]) -> str | None:
    """Return the remote kind when argv alone is remote-eligible, else None."""
    if not argv:
        return None
    tool = os.path.basename(argv[0])
    if tool == "cargo":
        return _cargo_kind(argv)
    if tool in {"npx", "pnpm", "npm", "node", "vitest", "svelte-check"}:
        if "vitest" in argv or tool == "vitest":
            return _vitest_kind(argv)
        if _is_playwright_test(argv):
            return "playwright"
        if tool in {"npm", "pnpm"} and NODE_SCRIPTS & set(argv):
            return "node"
        if tool == "node" and len(argv) >= 2 and os.path.basename(argv[1]) == "build-translations.js":
            return "node"
        if NODE_TOOLS & {os.path.basename(a) for a in argv}:
            return "node"
    return None


def _tokens(payload: str) -> list[str] | None:
    try:
        lexer = shlex.shlex(payload, posix=True, punctuation_chars="&|;<>()")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def _is_operator(token: str) -> bool:
    # punctuation_chars splits unquoted operators into tokens made only of
    # operator characters; a quoted `grep -E 'a|b'` pattern keeps other characters.
    return bool(token) and set(token) <= set("&|;<>()")


def _split_segments(payload: str) -> tuple[list[list[str]], list[str]] | None:
    """Split `a && b 2>&1 | c; d` into argv segments and their separators.

    Understood: `&&`, `||`, `;`, `|`, `2>&1`, `>/dev/null`, `2>/dev/null`.
    Anything else (file redirection, `&`, subshells) returns None (run locally).
    """
    tokens = _tokens(payload)
    if tokens is None:
        return None
    segments: list[list[str]] = [[]]
    separators: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not _is_operator(tok):
            segments[-1].append(tok)
        elif tok in SHELL_OPERATORS:
            separators.append(tok)
            segments.append([])
        elif tok == ">&" and segments[-1][-1:] == ["2"] and tokens[i + 1:i + 2] == ["1"]:
            segments[-1][-1] = "2>&1"
            i += 1
        elif tok == ">" and tokens[i + 1:i + 2] == ["/dev/null"]:
            if segments[-1][-1:] == ["2"]:
                segments[-1][-1] = "2>/dev/null"
            else:
                segments[-1].append(">/dev/null")
            i += 1
        else:
            return None
        i += 1
    if separators and separators[-1] == ";" and not segments[-1]:
        separators.pop()
        segments.pop()
    if not all(segments):
        return None
    return segments, separators


REDIRECTS = frozenset({"2>&1", "2>/dev/null", ">/dev/null"})


def _map_path(value: str, roots: tuple[Path, ...]) -> str:
    for root in roots:  # the worktree first: it may sit inside the canonical checkout
        root_text = str(root)
        if value == root_text or value.startswith(root_text + "/"):
            return REMOTE_ROOT + value[len(root_text):]
    return value


def _map_argv(argv: list[str], roots: tuple[Path, ...]) -> list[str]:
    mapped = []
    for arg in argv:
        if "=" in arg and arg.startswith("--"):
            key, _, value = arg.partition("=")
            mapped.append(f"{key}={_map_path(value, roots)}")
        else:
            mapped.append(_map_path(arg, roots))
    return mapped


def remote_cwd(cwd: Path, root: Path) -> str | None:
    try:
        rel = cwd.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return REMOTE_ROOT if str(rel) == "." else f"{REMOTE_ROOT}/{rel.as_posix()}"


def external_dir(path: Path) -> Path | None:
    """The /tmp folder to mirror for `path`: itself when a folder, else its parent."""
    text = str(path)
    if not text.startswith(EXTERNAL_ROOTS):
        return None
    folder = path if path.is_dir() else path.parent
    if not folder.is_dir() or str(folder).rstrip("/") in {r.rstrip("/") for r in EXTERNAL_ROOTS}:
        return None
    return folder


def external_dir_fits(folder: Path) -> bool:
    total = files = 0
    for dirpath, _dirs, names in os.walk(folder):
        for name in names:
            files += 1
            full = Path(dirpath) / name
            if not full.is_symlink():
                total += full.stat().st_size
            if files > MAX_EXTERNAL_DIR_FILES or total > MAX_EXTERNAL_DIR_BYTES:
                return False
    return True


def _outside_paths(words: list[str], roots: tuple[Path, ...]) -> list[Path] | None:
    """Absolute or cwd-relative paths in a playwright command that are outside the worktree.

    Returns None when one points outside the worktree and outside /tmp (stay local).
    """
    found = []
    for word in words:
        value = word.partition("=")[2] if word.startswith("--") and "=" in word else word
        if not value.startswith("/"):
            continue
        path = Path(value)
        if any(remote_cwd(path, r) is not None for r in roots):
            continue
        if not path.exists():
            continue
        folder = external_dir(path)
        if folder is None:
            return None
        found.append(folder)
    return found


def _segment_kinds(segments: list[list[str]], cwd: Path, root: Path) -> list[str] | None:
    kinds = []
    for seg in segments:
        words = [w for w in seg if w not in REDIRECTS]
        head = os.path.basename(words[0]) if words else ""
        if head == "cd":
            if len(words) != 2:
                return None
            target = Path(words[1]) if Path(words[1]).is_absolute() else cwd / words[1]
            if remote_cwd(target, root) is None:
                return None
            cwd = target
        elif head == "export":
            if not all(ENV_NAME.match(w.partition("=")[0]) for w in words[1:]):
                return None
        elif head in PIPE_FILTERS or head in NOOP_COMMANDS:
            continue
        else:
            seg_kind = command_kind(words)
            if seg_kind is None:
                return None
            kinds.append(seg_kind)
    return kinds


def _join(segments: list[list[str]], separators: list[str], roots: tuple[Path, ...]) -> str:
    parts = [" ".join(w if w in REDIRECTS else shlex.quote(w) for w in _map_argv(seg, roots))
             for seg in segments]
    return parts[0] + "".join(f" {sep} {part}" for sep, part in zip(separators, parts[1:]))


def plan_command(argv: list[str], cwd: Path, root: Path,
                 canonical: Path | None = None) -> RemoteCommand | None:
    """Map a heavy_slot command to a sandbox command, or None to run it locally.

    `canonical` is the main checkout; paths into it (its installed node_modules)
    map to the sandbox checkout too.
    """
    if not argv:
        return None
    roots = (root,) if canonical is None or canonical == root else (root, canonical)
    sandbox_cwd = remote_cwd(cwd, root)
    if command_kind(argv):
        segments, separators = [argv], []
    elif os.path.basename(argv[0]) in {"bash", "sh"} and len(argv) == 3 and argv[1] == "-c":
        split = _split_segments(argv[2])
        if split is None:
            return None
        segments, separators = split
    else:
        return None
    kinds = _segment_kinds(segments, cwd, root)
    if not kinds or len(set(kinds)) != 1:
        return None
    kind = kinds[0]
    external: list[Path] = []
    if kind == "playwright":
        words = [w for seg in segments for w in seg]
        outside = _outside_paths(words, roots)
        if outside is None:
            return None
        external.extend(outside)
        if sandbox_cwd is None:
            folder = external_dir(cwd)
            if folder is None:
                return None
            external.append(folder)
            sandbox_cwd = str(cwd)
    if sandbox_cwd is None:
        return None
    unique = sorted({str(p) for p in external})
    # Nested folders: keep only the outermost one.
    unique = [p for p in unique if not any(p != q and p.startswith(q + "/") for q in unique)]
    if not all(external_dir_fits(Path(p)) for p in unique):
        return None
    cargo_build = kind == "cargo" and any(
        next((a for a in seg[1:] if not a.startswith("-")), None) == "build"
        for seg in segments if seg and os.path.basename(seg[0]) == "cargo")
    return RemoteCommand(kind, _join(segments, separators, roots), sandbox_cwd, tuple(unique), cargo_build)


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
