#!/usr/bin/env python3
"""Prepare and validate immutable OpenCode backend releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_runtime_package(package: Path, runtime_checkout: Path) -> dict:
    """Inspect actual instantiated hook/tool schemas without live chats or state."""
    try:
        from sync_opencode_runtime_hook import validate_runtime_package
    except ImportError:
        from scripts.sync_opencode_runtime_hook import validate_runtime_package
    manifest = validate_runtime_package(package)
    with tempfile.TemporaryDirectory(prefix="opencode-workflow-probe-") as temporary:
        env = os.environ.copy()
        env.update(
            OPENMATES_PROJECT_ROOT=temporary,
            OPENMATES_CONTROL_PLANE_RUNTIME=str(runtime_checkout),
            OPENMATES_REQUIRE_PLUGIN="1",
            OPENMATES_OPENCODE_RESPONSE_MEDIA_AUTOMATION="0",
        )
        result = subprocess.run(
            [
                "node",
                str(runtime_checkout / "scripts/probe_opencode_workflow.mjs"),
                str(package),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            raise RuntimeError(
                "workflow capability/guard probe failed: " + result.stderr[-2000:]
            )
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        if set(observed.get("actions", [])) != set(manifest["required_task_actions"]):
            raise RuntimeError(
                "workflow advertised actions do not match the effective tool schema"
            )
        for command in ("decision", "continuation", "worktree"):
            check = subprocess.run(
                [
                    "python3",
                    str(runtime_checkout / "scripts/sessions.py"),
                    command,
                    "--help",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check.returncode:
                raise RuntimeError(f"workflow helper capability is missing: {command}")
        return observed


def validate_release(
    release: Path,
    *,
    control_plane_commit: str = "",
    require_workflow: bool = False,
    runtime_checkout_override: Path | None = None,
) -> dict[str, str]:
    release = release.resolve()
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    binary = release / "opencode"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"release binary is missing or not executable: {binary}")
    if _file_hash(binary) != manifest.get("binary_sha256"):
        raise RuntimeError("release binary checksum does not match manifest")
    if (
        control_plane_commit
        and manifest.get("control_plane_commit") != control_plane_commit
    ):
        raise RuntimeError(
            "runtime control-plane commit does not match release manifest"
        )
    with tempfile.TemporaryDirectory(prefix="opencode-release-storage-") as data_home:
        environment = os.environ.copy()
        environment["XDG_DATA_HOME"] = data_home
        try:
            result = subprocess.run(
                [str(binary), "db", "path"],
                capture_output=True,
                text=True,
                timeout=30,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"release binary database-path probe failed: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[:300]
            raise RuntimeError(
                f"release binary database-path probe failed: {detail or result.returncode}"
            )
        database_path = Path(result.stdout.strip()).resolve()
        expected_database_path = (
            Path(data_home) / "opencode" / "opencode.db"
        ).resolve()
        if database_path != expected_database_path:
            raise RuntimeError(
                "release binary must use the production opencode.db storage path; "
                f"reported {database_path.name or '<empty>'}"
            )
    if require_workflow or manifest.get("workflow_manifest_sha256"):
        package = release / "workflow"
        if not (package / "workflow-manifest.json").is_file() or _file_hash(
            package / "workflow-manifest.json"
        ) != manifest.get("workflow_manifest_sha256"):
            raise RuntimeError(
                "release workflow package is missing or does not match manifest"
            )
        workflow = json.loads((package / "workflow-manifest.json").read_text())
        if workflow.get("control_plane_commit") != manifest.get("control_plane_commit"):
            raise RuntimeError("workflow package coordinator revision mismatch")
        runtime = runtime_checkout_override or Path(workflow["runtime_checkout"])
        actual = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=runtime,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if actual != manifest["control_plane_commit"]:
            raise RuntimeError(
                "workflow helper checkout has a different coordinator revision"
            )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=runtime,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if dirty:
            raise RuntimeError(
                "workflow helper checkout must be clean before activation"
            )
        probe_runtime_package(package, runtime)
    return {str(key): str(value) for key, value in manifest.items()}


def prepare_release(
    binary: Path,
    releases: Path,
    *,
    opencode_commit: str,
    control_plane_commit: str,
    version: str,
    runtime_checkout: Path | None = None,
    dependency_source: Path | None = None,
    active_runtime_checkout: Path | None = None,
    activate: bool = True,
) -> dict[str, str]:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(
            f"built OpenCode binary is missing or not executable: {binary}"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", control_plane_commit):
        raise RuntimeError(
            "control-plane commit must be a full 40-character lowercase Git SHA"
        )
    release_id = f"{opencode_commit[:12]}-{control_plane_commit[:12]}"
    releases.mkdir(parents=True, exist_ok=True)
    destination = releases / release_id
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix=f".{release_id}-", dir=releases))
        try:
            shutil.copy2(binary, temporary / "opencode")
            (temporary / "opencode").chmod(0o755)
            manifest = {
                "binary_sha256": _file_hash(temporary / "opencode"),
                "control_plane_commit": control_plane_commit,
                "opencode_commit": opencode_commit,
                "release_id": release_id,
                "version": version,
            }
            if runtime_checkout is not None:
                try:
                    from sync_opencode_runtime_hook import prepare_runtime_package
                except ImportError:
                    from scripts.sync_opencode_runtime_hook import (
                        prepare_runtime_package,
                    )
                if dependency_source is None:
                    raise RuntimeError(
                        "workflow package requires pinned plugin dependencies"
                    )
                prepare_runtime_package(
                    runtime_checkout,
                    temporary / "workflow",
                    dependency_source=dependency_source,
                    control_plane_commit=control_plane_commit,
                    runtime_destination=active_runtime_checkout,
                )
                manifest["workflow_manifest_sha256"] = _file_hash(
                    temporary / "workflow/workflow-manifest.json"
                )
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    manifest = validate_release(destination, runtime_checkout_override=runtime_checkout)
    if not activate:
        return manifest
    link = releases / "current"
    temporary_link = releases / ".current-new"
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(destination.name)
    os.replace(temporary_link, link)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--binary", required=True, type=Path)
    prepare.add_argument("--releases", required=True, type=Path)
    prepare.add_argument("--opencode-commit", required=True)
    prepare.add_argument("--control-plane-commit", required=True)
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--runtime-checkout", type=Path)
    prepare.add_argument("--dependency-source", type=Path)
    prepare.add_argument("--active-runtime-checkout", type=Path)
    prepare.add_argument("--no-activate", action="store_true")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--release", required=True, type=Path)
    validate.add_argument("--control-plane-commit", default="")
    validate.add_argument("--require-workflow", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_release(
            args.binary,
            args.releases,
            opencode_commit=args.opencode_commit,
            control_plane_commit=args.control_plane_commit,
            version=args.version,
            runtime_checkout=args.runtime_checkout,
            dependency_source=args.dependency_source,
            active_runtime_checkout=args.active_runtime_checkout,
            activate=not args.no_activate,
        )
    else:
        result = validate_release(
            args.release,
            control_plane_commit=args.control_plane_commit,
            require_workflow=args.require_workflow,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
