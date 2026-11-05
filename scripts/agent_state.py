"""Shared repository-state helpers for agent tooling scripts.

Provides the canonical checkout root and an atomic, file-locked JSON state
transaction used by CI evidence, the daily meeting and the CLI Codex adapter's
cached-context migration.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile


def canonical_root(root):
    """Return the canonical (non-worktree) checkout for ``root``."""
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=root,
        text=True,
    ).strip()
    return Path(common).parent


@contextmanager
def transaction(path):
    """Lock ``path``, yield its JSON state and atomically write it back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = (
            json.loads(path.read_text())
            if path.exists()
            else {"workers": {}, "outbox": {}, "enabled": False}
        )
        yield state
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".state-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
