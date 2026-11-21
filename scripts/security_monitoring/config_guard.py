"""Guard that flags changes to hook, settings and automation config files.

Background: malware once added command hooks to `.claude/settings.json`. This
module walks the git history of the repo for paths that can execute commands
(Claude settings and hooks, VS Code tasks, git hooks, husky, MCP config, CI
workflows, package.json lifecycle scripts) and classifies each change:

- `command_hook_added` (urgent): a parsed JSON diff that adds or changes a hook
  `command`, an `mcpServers` entry, a broadened `permissions.allow` entry or an
  `env` value; a package.json lifecycle script added or changed; a new or
  changed executable in a hooks directory; a new or changed file in the real
  `.git/hooks` directory or a changed `core.hooksPath`; an unparseable JSON
  settings file.
- `config_changed` (low): everything else that matches, for example Markdown
  edits under `.claude/skills|rules|agents|commands`, workflows, deletions.

State (cursor = last scanned commit, git hooks baseline) lives in
`logs/security-monitoring/config-guard.json` (gitignored). The first run
baselines the cursor to the current head without reporting history, but does
report the existing git hooks state once.

CLI: `config_guard.py scan [--json] [--since <sha>]` and `config_guard.py baseline`.
`--since` is a read-only scan: it does not move the cursor or the baseline.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any

COMMAND_HOOK_ADDED = "command_hook_added"
CONFIG_CHANGED = "config_changed"
STATE_RELATIVE = Path("logs/security-monitoring/config-guard.json")
LIFECYCLE_KEYS = ("preinstall", "install", "postinstall", "prepare")
SCRIPT_SUFFIXES = {".sh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".bash", ".zsh", ".ps1"}
CLAUDE_DOC_DIRS = ("skills", "rules", "agents", "commands")
GIT_HOOKS_PREFIX = "git-hooks/"


@dataclass(frozen=True)
class ConfigChange:
    """One flagged change to a hook or settings file."""

    commit: str
    author: str
    date: str
    path: str
    status: str
    risk: str
    reason: str


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=root, capture_output=True, text=True, check=check,
    )


def _head_ref(root: Path) -> str:
    """Prefer origin/dev when it exists, else HEAD."""
    probe = _git(root, "rev-parse", "--verify", "--quiet", "origin/dev", check=False)
    return "origin/dev" if probe.returncode == 0 else "HEAD"


def head_commit(root: Path) -> str:
    return _git(root, "rev-parse", _head_ref(root)).stdout.strip()


# ---------------------------------------------------------------- path rules

def matches(path: str) -> bool:
    """True when the path is a hook, settings or automation config file."""
    p = PurePosixPath(path)
    parts = p.parts
    if "node_modules" in parts:
        return False
    name = p.name
    if parts[0] == ".claude":
        return True
    if path in (".vscode/tasks.json", ".vscode/settings.json"):
        return True
    if parts[0] in (".githooks", ".husky"):
        return True
    if parts[:2] in ((".github", "workflows"), (".github", "actions")):
        return True
    if name == ".mcp.json" or name == "mcp.json" or name.endswith(".mcp.json"):
        return True
    return name == "package.json"


def _is_json_settings(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    if p.parts[0] == ".claude":
        return len(p.parts) == 2 and name.startswith("settings") and name.endswith(".json")
    return path in (".vscode/tasks.json", ".vscode/settings.json") or name.endswith("mcp.json")


def _is_executable_dir(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if parts[0] in (".githooks", ".husky"):
        return True
    if parts[:2] == (".claude", "hooks"):
        return PurePosixPath(path).suffix != ".md"
    if parts[0] == ".claude" and len(parts) > 2 and parts[1] in CLAUDE_DOC_DIRS:
        return PurePosixPath(path).suffix in SCRIPT_SUFFIXES
    return False


# -------------------------------------------------------------- JSON diffing

def _hook_commands(doc: Any) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            command = node.get("command")
            if isinstance(command, str):
                found.add(command)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    if isinstance(doc, dict):
        walk(doc.get("hooks"))
    return found


def _allow_entries(doc: Any) -> set[str]:
    perms = doc.get("permissions") if isinstance(doc, dict) else None
    allow = perms.get("allow") if isinstance(perms, dict) else None
    return {a for a in allow if isinstance(a, str)} if isinstance(allow, list) else set()


def _is_broad_allow(entry: str) -> bool:
    return "*" in entry or "(" not in entry


def diff_settings(before: Any, after: Any) -> list[str]:
    """Return reasons a parsed settings change is urgent; empty when benign."""
    reasons: list[str] = []
    if _hook_commands(after) - _hook_commands(before):
        reasons.append("hook command added or changed")
    b_mcp = before.get("mcpServers", {}) if isinstance(before, dict) else {}
    a_mcp = after.get("mcpServers", {}) if isinstance(after, dict) else {}
    if any(b_mcp.get(k) != v for k, v in a_mcp.items()) if isinstance(a_mcp, dict) and isinstance(b_mcp, dict) else a_mcp != b_mcp:
        reasons.append("mcpServers entry added or changed")
    if any(_is_broad_allow(e) for e in _allow_entries(after) - _allow_entries(before)):
        reasons.append("permissions.allow broadened")
    b_env = before.get("env") if isinstance(before, dict) else None
    a_env = after.get("env") if isinstance(after, dict) else None
    if a_env != b_env:
        reasons.append("env changed")
    return reasons


def _lifecycle(doc: Any) -> dict[str, Any]:
    scripts = doc.get("scripts") if isinstance(doc, dict) else None
    return {k: scripts[k] for k in LIFECYCLE_KEYS if k in scripts} if isinstance(scripts, dict) else {}


def _show(root: Path, rev: str, path: str) -> str | None:
    res = _git(root, "show", f"{rev}:{path}", check=False)
    return res.stdout if res.returncode == 0 else None


def _parse(text: str | None) -> tuple[Any, bool]:
    """Return (document, ok). Missing file parses as an empty document."""
    if text is None:
        return {}, True
    try:
        return json.loads(text), True
    except json.JSONDecodeError:
        return None, False


def classify(root: Path, sha: str, path: str, status: str) -> tuple[str, str]:
    """Classify one changed path of a commit into (risk, reason)."""
    if status.startswith("D"):
        return CONFIG_CHANGED, "file deleted"
    name = PurePosixPath(path).name
    if name == "package.json":
        before, ok_b = _parse(_show(root, f"{sha}^", path))
        after, ok_a = _parse(_show(root, sha, path))
        if not (ok_a and ok_b):
            return CONFIG_CHANGED, "package.json not parseable"
        if _lifecycle(after) != _lifecycle(before):
            return COMMAND_HOOK_ADDED, "package.json lifecycle script added or changed"
        return CONFIG_CHANGED, "package.json changed"
    if _is_json_settings(path):
        before, ok_b = _parse(_show(root, f"{sha}^", path))
        after, ok_a = _parse(_show(root, sha, path))
        if not ok_a:
            return COMMAND_HOOK_ADDED, "settings file not parseable as JSON (review by hand)"
        reasons = diff_settings(before if ok_b else {}, after)
        if path in (".vscode/tasks.json",) and not reasons and before != after:
            reasons.append("task definition changed")
        if reasons:
            return COMMAND_HOOK_ADDED, "; ".join(reasons)
        return CONFIG_CHANGED, "settings changed without command surface"
    if _is_executable_dir(path):
        return COMMAND_HOOK_ADDED, "executable in a hooks directory added or changed"
    return CONFIG_CHANGED, "config file changed"


# ------------------------------------------------------------------ scanning

def scan(root: Path, since_commit: str) -> list[ConfigChange]:
    """List flagged changes in `since_commit..origin/dev` (or HEAD), oldest first."""
    root = Path(root)
    ref = _head_ref(root)
    log = _git(
        root, "log", "--reverse", "--no-renames", "--name-status",
        "--format=%x01%H%x02%an%x02%aI", f"{since_commit}..{ref}",
    ).stdout
    changes: list[ConfigChange] = []
    for block in log.split("\x01")[1:]:
        header, _, rest = block.partition("\n")
        sha, author, date = header.split("\x02")
        for line in rest.splitlines():
            if not line.strip():
                continue
            status, _, path = line.partition("\t")
            if not matches(path):
                continue
            risk, reason = classify(root, sha, path, status)
            changes.append(ConfigChange(sha, author, date, path, status, risk, reason))
    return changes


# --------------------------------------------------------------- git hooks

def _hooks_paths(root: Path) -> tuple[Path, str]:
    """Real hooks dir (shared by all worktrees) and the core.hooksPath value."""
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    configured = _git(root, "config", "--get", "core.hooksPath", check=False).stdout.strip()
    return Path(common) / "hooks", configured


def git_hooks_state(root: Path) -> dict[str, Any]:
    """Checksums of non-sample git hook files plus core.hooksPath."""
    root = Path(root)
    hooks_dir, configured = _hooks_paths(root)
    files: dict[str, str] = {}
    dirs = [("", hooks_dir)]
    if configured:
        target = Path(configured)
        resolved = (target if target.is_absolute() else root / target).resolve()
        if resolved != hooks_dir.resolve():
            dirs.append(("hooksPath/", resolved))
    for prefix, directory in dirs:
        if not directory.is_dir():
            continue
        for item in sorted(directory.iterdir()):
            if item.is_file() and not item.name.endswith(".sample"):
                files[prefix + item.name] = hashlib.sha256(item.read_bytes()).hexdigest()
    return {"hooks_path": configured, "files": files}


def compare_hooks(baseline: dict[str, Any] | None, current: dict[str, Any], now: str) -> list[ConfigChange]:
    """Diff the git hooks state against a baseline (None = nothing known)."""
    old_files = (baseline or {}).get("files", {})
    out: list[ConfigChange] = []

    def make(path: str, status: str, risk: str, reason: str) -> ConfigChange:
        return ConfigChange("", "", now, GIT_HOOKS_PREFIX + path, status, risk, reason)

    for name, digest in current["files"].items():
        if name not in old_files:
            out.append(make(name, "A", COMMAND_HOOK_ADDED, "git hook file present, not in baseline"))
        elif old_files[name] != digest:
            out.append(make(name, "M", COMMAND_HOOK_ADDED, "git hook file content changed"))
    for name in old_files:
        if name not in current["files"]:
            out.append(make(name, "D", CONFIG_CHANGED, "git hook file removed"))
    if current["hooks_path"] != (baseline or {}).get("hooks_path", ""):
        out.append(make("core.hooksPath", "M", COMMAND_HOOK_ADDED,
                        f"core.hooksPath set to {current['hooks_path']!r}"))
    return out


# -------------------------------------------------------------------- state

def _state_path(root: Path) -> Path:
    return Path(root) / STATE_RELATIVE


def load_state(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_scan(root: Path, since: str | None = None, now: str = "") -> list[ConfigChange]:
    """Full scan: commits since the cursor plus git hooks; advances the state.

    With `since` given the scan is read-only (state is not written).
    """
    root = Path(root)
    state = load_state(root)
    head = head_commit(root)
    current_hooks = git_hooks_state(root)
    changes: list[ConfigChange] = []
    start = since or state.get("cursor")
    if start:
        changes.extend(scan(root, start))
    changes.extend(compare_hooks(state.get("git_hooks"), current_hooks, now))
    if since is None:
        save_state(root, {"cursor": head, "git_hooks": current_hooks})
    return changes


def baseline(root: Path) -> dict[str, Any]:
    """Record the current head and git hooks state without reporting."""
    state = {"cursor": head_commit(root), "git_hooks": git_hooks_state(root)}
    save_state(root, state)
    return state


# ---------------------------------------------------------------------- CLI

def _summary(changes: list[ConfigChange]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in changes:
        counts[c.risk] = counts.get(c.risk, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    scan_p = sub.add_parser("scan", help="report new hook/settings changes")
    scan_p.add_argument("--json", action="store_true")
    scan_p.add_argument("--since", help="read-only scan from this commit")
    scan_p.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    base_p = sub.add_parser("baseline", help="record current head and git hooks state")
    base_p.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.cmd == "baseline":
        state = baseline(root)
        print(f"baselined at {state['cursor']}")
        return 0
    from datetime import datetime, timezone
    changes = run_scan(root, args.since, datetime.now(timezone.utc).isoformat())
    if args.json:
        print(json.dumps({"summary": _summary(changes), "changes": [asdict(c) for c in changes]}, indent=2))
    else:
        for c in changes:
            print(f"[{c.risk}] {c.commit[:10]} {c.author} {c.status} {c.path}: {c.reason}")
        print(f"{len(changes)} change(s): {_summary(changes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
