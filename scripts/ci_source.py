"""Publish an immutable CI candidate through the managed session command.

A temporary Git index preserves the user's branch and staging area. Only tracked
changes and explicitly session-tracked new files enter the candidate. Publication
uses a private expiring patch artifact; it never creates a Git ref, integrates
into dev, or restarts services.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

try:
    from scripts.ci_candidate_artifact import upload_patch
except ModuleNotFoundError:
    from ci_candidate_artifact import upload_patch

DISK_RESERVE = 30 * 1024**3
MAX_CHANGED_BYTES = 100 * 1024**2


def _specifications_module():
    try:
        from scripts import specifications
    except ModuleNotFoundError:
        import specifications
    return specifications


def _specification_governed(paths: list[str]) -> bool:
    specifications = _specifications_module()

    return any(
        specifications._is_test_file(path)
        or path.startswith("specifications/")
        or (path.startswith("docs/plans/") and Path(path).name == "plan.yml")
        for path in paths
    )


def candidate_preflight(
    root: Path,
    paths: list[str],
    *,
    session_id: str,
    materialized: bool = True,
) -> dict:
    """Run only cheap checks whose inputs are present in the candidate worktree."""
    checks: list[dict[str, object]] = []
    deferred: list[str] = []
    governed = _specification_governed(paths)
    if not materialized:
        deferred.append(
            "Resolved patch candidate syntax and Specification metadata were not "
            "checked because the patch is not materialized in this worktree; "
            "existing deployment validation must validate the materialized source"
        )
    else:
        if governed:
            specifications = _specifications_module()

            approvals = (
                specifications._control_plane_root(root)
                / "scripts/.specifications-approvals-state.json"
            )
            errors = specifications.check_changed_files(
                root,
                paths,
                session_id=session_id,
                approvals_path=approvals,
            )
            if errors:
                raise ValueError("Candidate Specification preflight failed:\n" + "\n".join(errors))
            checks.append({"check": "specifications-check-changed", "paths": paths})

        python_paths = [
            path for path in paths if path.endswith(".py") and (root / path).is_file()
        ]
        for path in python_paths:
            source = (root / path).read_bytes()
            try:
                compile(source, path, "exec")
            except SyntaxError as exc:
                raise ValueError(f"Candidate Python syntax preflight failed: {exc}") from exc
        if python_paths:
            checks.append({"check": "python-compile", "paths": python_paths})

        svelte_paths = [
            path for path in paths if path.endswith(".svelte") and (root / path).is_file()
        ]
        if svelte_paths:
            web = root / "frontend/apps/web_app"
            if (web / "node_modules/svelte").exists():
                program = (
                    "import fs from 'node:fs'; import {compile} from 'svelte/compiler';"
                    "for (const path of process.argv.slice(1)) compile(fs.readFileSync(path, 'utf8'),"
                    "{filename:path, generate:false});"
                )
                result = subprocess.run(
                    [
                        "node",
                        "--input-type=module",
                        "-e",
                        program,
                        *(str(root / path) for path in svelte_paths),
                    ],
                    cwd=web,
                    capture_output=True,
                    text=True,
                )
                if result.returncode:
                    detail = (result.stderr or result.stdout).strip()
                    raise ValueError("Candidate Svelte syntax preflight failed: " + detail)
                checks.append({"check": "svelte-compile", "paths": svelte_paths})
            else:
                deferred.append(
                    "Touched Svelte files require compiler validation in isolated CI "
                    "because frontend/apps/web_app/node_modules/svelte is unavailable"
                )

    deploy_requirements = []
    if governed:
        deploy_requirements = [
            "Specifications: trailer",
            "Assertions: trailer",
            "Plan: trailer",
            "Specification-Impact: trailer",
        ]
    return {
        "status": (
            "deferred"
            if not materialized
            else "passed" if not deferred else "passed_with_deferred_checks"
        ),
        "checks": checks,
        "deferred_checks": deferred,
        "future_deploy_requirements": deploy_requirements,
    }


def git(root, *args, env=None, input=None):
    return subprocess.check_output(
        ["git", *args], cwd=root, env=env, input=input, text=True
    ).strip()


def git_bytes(root, *args, env=None) -> bytes:
    """Return byte-exact Git output for patches and other framed content."""
    return subprocess.check_output(["git", *args], cwd=root, env=env)


def reviewed_paths(root: Path, session_files: list[str]) -> list[str]:
    changed = set(git(root, "diff", "HEAD", "--name-only", "-z").split("\0")) - {""}
    tracked = set(git(root, "ls-files", "-z").split("\0"))
    changed.update(
        name
        for name in session_files
        if name not in tracked and (root / name).is_file()
    )
    safe = []
    for name in sorted(changed):
        path = source_path(name)
        if any(
            parent.is_symlink()
            for parent in [root / path, *(root / path).parents]
            if parent != root.parent
        ):
            raise ValueError("CI snapshot does not follow symlinks")
        if (root / path).exists() or name in changed:
            safe.append(name)
    return safe


def source_path(name: str) -> Path:
    path = Path(name)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or any(char in name for char in ("\n", "\r", "\t", '"', "\\"))
        or path.parts[0] in {"logs", "test-results", "vaults", ".git"}
    ):
        raise ValueError("CI snapshot contains a non-source path")
    if path.name.startswith(".env") and path.name != ".env.example":
        raise ValueError("CI snapshot cannot publish environment files")
    if any(part.lower() in {"credentials", "secrets"} for part in path.parts):
        raise ValueError("CI snapshot cannot publish credential directories")
    return path


def fingerprint(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    total = 0
    for name in paths:
        path = root / name
        data = path.read_bytes() if path.exists() else b"<deleted>"
        total += len(data)
        if total > MAX_CHANGED_BYTES:
            raise ValueError("CI source changes exceed the 100 MiB publication limit")
        digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def publish(
    root: Path,
    session_id: str,
    session_files: list[str],
    *,
    base: str = "",
    resolved_patch: Path | None = None,
    patch_sha256: str = "",
    artifact_uploader=upload_patch,
) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", session_id):
        raise ValueError("Invalid session identity")
    if shutil.disk_usage(root).free < DISK_RESERVE + MAX_CHANGED_BYTES:
        raise RuntimeError("CI snapshot would risk the 30 GiB dev-server disk reserve")
    patch = None
    original_head = git(root, "rev-parse", "HEAD")
    if resolved_patch:
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            raise ValueError(
                "Resolved patches require their exact reviewed base commit"
            )
        patch = resolved_patch.read_text()
        if hashlib.sha256(patch.encode()).hexdigest() != patch_sha256:
            raise ValueError("Resolved patch does not match the reviewed SHA-256")
        if len(patch.encode()) > MAX_CHANGED_BYTES:
            raise ValueError("Resolved patch exceeds the source publication limit")
        paths = [
            line.split("\t", 2)[2]
            for line in git(root, "apply", "--numstat", input=patch).splitlines()
        ]
        for name in paths:
            source_path(name)
        parent = base
    else:
        if base or patch_sha256:
            raise ValueError("Base and patch hash require --resolved-patch")
        paths = reviewed_paths(root, session_files)
        parent = git(root, "rev-parse", "HEAD")
    preflight = candidate_preflight(
        root, paths, session_id=session_id, materialized=patch is None
    )
    before = fingerprint(root, paths) if patch is None else patch_sha256
    with tempfile.TemporaryDirectory(prefix="openmates-ci-index-") as directory:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        git(root, "read-tree", parent, env=env)
        if patch is not None:
            git(root, "apply", "--cached", "--check", env=env, input=patch)
            git(root, "apply", "--cached", env=env, input=patch)
            for entry in git(
                root, "ls-files", "--stage", "--", *paths, env=env
            ).splitlines():
                if entry.startswith(("120000 ", "160000 ")):
                    raise ValueError("CI patches cannot publish symlinks or submodules")
        elif paths:
            git(root, "add", "-A", "--", *paths, env=env)
        tree = git(root, "write-tree", env=env)
        if git(root, "rev-parse", "HEAD") != original_head or (
            patch is None and fingerprint(root, paths) != before
        ):
            raise RuntimeError("Source changed during capture; request a new snapshot")
        if tree == git(root, "rev-parse", parent + "^{tree}"):
            return {
                "source": parent,
                "tree": tree,
                "session": session_id,
                "changed_paths": [],
                "base": parent,
                "unchanged": True,
                "preflight": preflight,
            }
        timestamp = git(root, "show", "-s", "--format=%cI", parent)
        env.update(
            GIT_AUTHOR_NAME="OpenMates CI",
            GIT_AUTHOR_EMAIL="ci@example.com",
            GIT_COMMITTER_NAME="OpenMates CI",
            GIT_COMMITTER_EMAIL="ci@example.com",
            GIT_AUTHOR_DATE=timestamp,
            GIT_COMMITTER_DATE=timestamp,
        )
        source = git(
            root,
            "commit-tree",
            tree,
            "-p",
            parent,
            env=env,
            input=f"CI candidate for session {session_id}\n",
        )
    candidate_bytes = git_bytes(root, "diff", "--binary", "--no-renames", parent, source)
    if len(candidate_bytes) > MAX_CHANGED_BYTES:
        raise ValueError("CI candidate patch exceeds the source publication limit")
    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    common_dir = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    canonical = common_dir.resolve().parent
    candidate_dir = canonical / "logs/ci-candidates" / source
    candidate_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    local_patch = candidate_dir / "candidate.patch"
    temporary_patch = candidate_dir / ".candidate.patch.tmp"
    temporary_patch.write_bytes(candidate_bytes)
    temporary_patch.chmod(0o600)
    temporary_patch.replace(local_patch)
    artifact = artifact_uploader(
        local_patch,
        source=source,
        sha256=candidate_sha256,
    )
    result = {
        "source": source,
        "tree": tree,
        "session": session_id,
        "changed_paths": paths,
        "base": parent,
        "resolved_patch_sha256": patch_sha256,
        "patch_sha256": candidate_sha256,
        "patch_url": artifact["url"],
        "artifact_bucket": artifact["bucket"],
        "artifact_key": artifact["key"],
        "artifact_expires_at": artifact["expires_at"],
        "local_patch": str(local_patch),
        "preflight": preflight,
    }
    manifest = candidate_dir / "manifest.json"
    temporary_manifest = candidate_dir / ".manifest.json.tmp"
    temporary_manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary_manifest.chmod(0o600)
    temporary_manifest.replace(manifest)
    result["manifest"] = str(manifest)
    return result
