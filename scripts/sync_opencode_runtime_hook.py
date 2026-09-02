#!/usr/bin/env python3
"""Atomically mirror the deployed OpenCode hook into the shared project.

Existing OpenCode sessions are permanently associated with their original
project directory. OpenCode therefore discovers plugins from the shared
checkout even when the server process runs from a clean runtime worktree. The
shared hook is a runtime mirror, not an authoring location; this command makes
its bytes match the clean deployed checkout before server startup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


HOOK_PATH = Path(".opencode/plugins/openmates-hooks.js")
RUNTIME_MIRRORS = (
    HOOK_PATH,
    Path("opencode.json"),
    Path(".agents/skills/define-specification/SKILL.md"),
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync_hook(runtime_checkout: Path, project_root: Path) -> dict[str, object]:
    runtime_checkout = runtime_checkout.resolve()
    project_root = project_root.resolve()
    if runtime_checkout == project_root:
        raise ValueError("runtime checkout and shared project root must differ")
    files = []
    for relative in RUNTIME_MIRRORS:
        source = runtime_checkout / relative
        target = project_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"deployed runtime file is missing: {source}")
        source_data = source.read_bytes()
        if relative == HOOK_PATH and (not source_data or b"export const OpenMatesHooks" not in source_data):
            raise ValueError(f"deployed hook does not export OpenMatesHooks: {source}")
        previous_data = target.read_bytes() if target.is_file() else b""
        changed = previous_data != source_data
        if changed:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(source_data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                temporary.chmod(source.stat().st_mode & 0o777)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        files.append(
            {
                "changed": changed,
                "path": str(relative),
                "previous_hash": _digest(previous_data) if previous_data else "",
                "source_hash": _digest(source_data),
                "target": str(target),
            }
        )
    return {
        "changed": any(item["changed"] for item in files),
        "files": files,
        "runtime_checkout": str(runtime_checkout),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-checkout", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(sync_hook(args.runtime_checkout, args.project_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
