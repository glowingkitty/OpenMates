#!/usr/bin/env python3
"""Package OpenCode workflow code without mirroring over tracked source files.

This replaces the startup mirror writer with an immutable release artifact.
The selected package owns hook dependencies, configuration and capabilities.
Canonical Claude sources and parity mirrors remain ordinary source files.
See docs/architecture/agent-workflow-decisions.md for activation and rollback.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HOOK_PATH = Path(".opencode/plugins/openmates-hooks.js")
REQUIRED_TASK_ACTIONS = [
    "context",
    "show",
    "create",
    "start",
    "edit",
    "block",
    "unblock",
    "done",
    "activity_add",
]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_runtime_package(
    runtime_checkout: Path,
    destination: Path,
    *,
    dependency_source: Path,
    control_plane_commit: str,
    runtime_destination: Path | None = None,
) -> dict:
    """Build outside tracked source; failed preparation never changes the live pointer."""
    root = runtime_checkout.resolve()
    destination = destination.resolve()
    if destination.is_relative_to(root):
        raise RuntimeError("workflow package must live outside the source checkout")
    if destination.exists():
        raise RuntimeError("workflow package destination already exists")
    if not (dependency_source / "@opencode-ai/plugin/package.json").is_file():
        raise RuntimeError("workflow plugin dependency is missing")
    runtime_destination = (runtime_destination or root).resolve()
    hook = root / HOOK_PATH
    if not hook.is_file() or b"export const OpenMatesHooks" not in hook.read_bytes():
        raise RuntimeError("workflow hook export is missing")
    config = json.loads((root / "opencode.json").read_text())
    for path in config.get("instructions", []):
        if not (root / path).is_file():
            raise RuntimeError(f"workflow instruction is missing: {path}")
    config["instructions"] = [
        str(runtime_destination / path) if not Path(path).is_absolute() else path
        for path in config.get("instructions", [])
    ]
    config["skills"] = {
        **config.get("skills", {}),
        "paths": [str(runtime_destination / ".agents/skills")],
    }
    destination.mkdir(parents=True)
    try:
        (destination / "plugins").mkdir()
        shutil.copy2(hook, destination / "plugins/openmates-hooks.js")
        agents = root / ".opencode/agents"
        if agents.is_dir():
            shutil.copytree(agents, destination / "agents")
        shutil.copytree(dependency_source, destination / "node_modules", symlinks=False)
        # OpenCode's loader may check/install dependencies; bind the actual installed version.
        version = json.loads(
            (destination / "node_modules/@opencode-ai/plugin/package.json").read_text()
        )["version"]
        (destination / "package.json").write_text(
            json.dumps(
                {"type": "module", "dependencies": {"@opencode-ai/plugin": version}},
                indent=2,
            )
            + "\n"
        )
        (destination / "opencode.json").write_text(json.dumps(config, indent=2) + "\n")
        hashes = {
            str(path.relative_to(destination)): _digest(path.read_bytes())
            for path in sorted(destination.rglob("*"))
            if path.is_file()
        }
        manifest = {
            "version": 1,
            "control_plane_commit": control_plane_commit,
            "runtime_checkout": str(runtime_destination),
            "required_task_actions": REQUIRED_TASK_ACTIONS,
            "plugin_version": version,
            "files": hashes,
        }
        (destination / "workflow-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        return manifest
    except BaseException:
        shutil.rmtree(destination)
        raise


def validate_runtime_package(package: Path) -> dict:
    manifest = json.loads((package / "workflow-manifest.json").read_text())
    if manifest.get("version") != 1 or not manifest.get("files"):
        raise RuntimeError("workflow package manifest is invalid")
    for relative, digest in manifest["files"].items():
        path = (package / relative).resolve()
        if (
            not path.is_relative_to(package.resolve())
            or not path.is_file()
            or _digest(path.read_bytes()) != digest
        ):
            raise RuntimeError(f"workflow package checksum mismatch: {relative}")
    plugins = list((package / "plugins").glob("*"))
    if [p.name for p in plugins] != ["openmates-hooks.js"]:
        raise RuntimeError(
            "workflow package must contain exactly one OpenMates hook loader"
        )
    return manifest


def sync_hook(runtime_checkout: Path, project_root: Path) -> dict:
    """Retired compatibility entry point: never overwrite or delete source files."""
    raise RuntimeError(
        "Tracked runtime mirroring is retired; prepare a workflow release package instead"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-checkout", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.parse_args()
    parser.error(
        "Tracked runtime mirroring is retired; use opencode_runtime_release.py prepare"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
