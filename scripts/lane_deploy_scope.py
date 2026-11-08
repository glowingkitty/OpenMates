"""Deploy/CI scope guards for parallel lanes (``sessions.py deploy --only``, ``ci-source``).

Two failure modes made lanes ship partial work without noticing:

* ``new_untracked_files`` lists files a lane created in its own managed
  worktree that the session never recorded, so ``ci-source`` and
  ``deploy --only`` can track them automatically instead of silently
  publishing a candidate without them.
* ``omitted_only_files`` lists dirty session files that an explicit
  ``--only`` selection leaves out, so deploy can refuse a partial commit and
  name every file it would have dropped. ``--exclude`` leaves one out on purpose.

Generated outputs (``specifications/generated/*``, generated Rust migration
YAML) are never auto-tracked or reported: deploy rebuilds them itself.
See .claude/rules/session-lifecycle.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

try:
    from scripts.lane_ci_source import REGENERABLE_GENERATED_ARTIFACTS
except ModuleNotFoundError:
    from lane_ci_source import REGENERABLE_GENERATED_ARTIFACTS


def _publishable(name: str) -> bool:
    """Return whether ``name`` may enter a CI candidate (no secrets, logs, symlinks)."""
    try:
        from scripts.ci_source import source_path
    except ModuleNotFoundError:
        from ci_source import source_path
    try:
        source_path(name)
    except ValueError:
        return False
    return True


def new_untracked_files(root: Path, tracked: list[str]) -> list[str]:
    """Return Git-untracked, non-ignored files in ``root`` the session does not track yet.

    Only regular files are returned; symlinks, generated artifacts and paths
    ``ci_source`` refuses to publish (env files, logs, credentials) are skipped.
    """
    root = Path(root)
    output = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    known = set(tracked)
    found = []
    for name in sorted(set(output.split("\0")) - {""}):
        path = root / name
        if name in known or name in REGENERABLE_GENERATED_ARTIFACTS:
            continue
        if path.is_symlink() or not path.is_file() or not _publishable(name):
            continue
        found.append(name)
    return found


def omitted_only_files(
    selector: str,
    to_commit: list[str],
    dirty_files: set[str] | list[str],
    tracked: list[str],
    exclude: set[str],
) -> list[str]:
    """Return dirty session-tracked files an ``--only`` selection would leave out.

    Empty for any other selector. Files named with ``--exclude`` and
    regenerable generated artifacts are intentional omissions.
    """
    if selector != "only":
        return []
    selected = set(to_commit)
    dirty = set(dirty_files)
    return sorted(
        path
        for path in set(tracked)
        if path in dirty
        and path not in selected
        and path not in exclude
        and path not in REGENERABLE_GENERATED_ARTIFACTS
    )


def omitted_only_message(sid: str, omitted: list[str]) -> str:
    """Explain a refused partial ``--only`` deploy and how to resolve it."""
    lines = [
        "DEPLOY BLOCKED — --only leaves out dirty files this session tracks "
        "(a partial deploy would silently drop them):",
        *(f"  - {path}" for path in omitted),
        "Add each with another --only <path> (the flag is repeatable), or leave it out "
        "on purpose with --exclude <path>, or untrack it: "
        f"python3 scripts/sessions.py untrack --session {sid} --file <path>",
    ]
    return "\n".join(lines)
