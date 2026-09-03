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
DEPRECATED_RUNTIME_PATHS = (Path(".agents/skills/define-contract/SKILL.md"),)
RECOVERY_DIR_NAME = ".openmates-runtime-mirror-recovery"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _preserve_previous(project_root: Path, relative: Path, data: bytes) -> Path | None:
    """Preserve displaced runtime-mirror bytes outside the shared checkout."""
    if not data:
        return None
    configured = os.environ.get("OPENMATES_RUNTIME_MIRROR_RECOVERY")
    recovery_root = Path(configured).expanduser() if configured else project_root.parent / RECOVERY_DIR_NAME
    project_id = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:12]
    destination = recovery_root / project_id / _digest(data) / relative
    if destination.is_file():
        if destination.read_bytes() != data:
            raise RuntimeError(f"runtime mirror recovery hash collision: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


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
        recovery_path = _preserve_previous(project_root, relative, previous_data) if changed else None
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
                "recovery_path": str(recovery_path) if recovery_path else "",
                "source_hash": _digest(source_data),
                "target": str(target),
            }
        )
    for relative in DEPRECATED_RUNTIME_PATHS:
        target = project_root / relative
        if target.is_dir():
            raise IsADirectoryError(f"deprecated runtime file is unexpectedly a directory: {target}")
        previous_data = target.read_bytes() if target.is_file() else b""
        changed = target.is_file() or target.is_symlink()
        recovery_path = _preserve_previous(project_root, relative, previous_data) if changed else None
        if changed:
            target.unlink()
        files.append(
            {
                "changed": changed,
                "path": str(relative),
                "previous_hash": _digest(previous_data) if previous_data else "",
                "recovery_path": str(recovery_path) if recovery_path else "",
                "source_hash": "",
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
