"""Validate reviewed CI candidates for the ordinary scoped deploy pipeline.

An immutable candidate supplies the intended edit relative to its reviewed base.
The original session worktree and index remain untouched, even after deployment.
Normal integration, deletion, lint and short push-lock gates remain authoritative.
See docs/architecture/isolated-github-tests.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

try:
    from scripts.ci_source import git, source_path, fingerprint, MAX_CHANGED_BYTES
except ModuleNotFoundError:
    from ci_source import git, source_path, fingerprint, MAX_CHANGED_BYTES


def source_identity(root: Path, paths: list[str]) -> dict:
    index = Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    return {
        "head": git(root, "rev-parse", "HEAD"),
        "index": hashlib.sha256(index.read_bytes() if index.exists() else b"").hexdigest(),
        "files": fingerprint(root, paths),
    }


def validate(root: Path, session: str, candidate: str, base: str, selected: list[str]) -> dict:
    for value in (candidate, base):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise RuntimeError("Reviewed deployment requires full candidate and base SHAs")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", session):
        raise RuntimeError("Invalid reviewed deployment session")
    retained = f"refs/remotes/origin/codex/ci/{session}/{candidate}"
    if git(root, "rev-parse", retained) != candidate:
        raise RuntimeError("Reviewed candidate is not retained for this session")
    parents = git(root, "show", "-s", "--format=%P", candidate).split()
    if parents != [base]:
        raise RuntimeError("Reviewed candidate must have exactly the reviewed base as parent")
    paths = git(root, "diff", "--no-renames", "--name-only", "-z", base, candidate).split("\0")
    paths = sorted(path for path in paths if path)
    if not paths or paths != sorted(set(selected)):
        raise RuntimeError("--only must exactly match every changed reviewed candidate path")
    for path in paths:
        source_path(path)
    entries = git(root, "ls-tree", "-r", candidate, "--", *paths).splitlines()
    if any(entry.startswith(("120000 ", "160000 ")) for entry in entries):
        raise RuntimeError("Reviewed deployment cannot introduce symlinks or submodules")
    patch = git(root, "diff", "--binary", "--no-renames", base, candidate, "--", *paths)
    if len(patch.encode()) > MAX_CHANGED_BYTES:
        raise RuntimeError("Reviewed deployment exceeds the source publication limit")
    deletions = {}
    for line in git(root, "diff", "--no-renames", "--numstat", base, candidate).splitlines():
        _, removed, path = line.split("\t", 2)
        deletions[path] = None if removed == "-" else int(removed)
    return {
        "candidate": candidate,
        "base": base,
        "paths": paths,
        "patch_id": hashlib.sha256(patch.encode()).hexdigest(),
        "deletions": deletions,
        "source_identity": source_identity(root, paths),
    }


def verify_current_base(root: Path, review: dict, current: str) -> None:
    # Unrelated upstream changes may advance; selected paths require a new review.
    if git(root, "merge-base", review["base"], current) != review["base"]:
        raise RuntimeError("Reviewed base is not an ancestor of current dev")
    changed = git(root, "diff", "--name-only", review["base"], current, "--", *review["paths"])
    if changed:
        raise RuntimeError("Reviewed candidate paths changed upstream; reconcile and publish a new candidate")


def verify_source(root: Path, review: dict) -> None:
    if source_identity(root, review["paths"]) != review["source_identity"]:
        raise RuntimeError("Original worktree HEAD, index or selected files changed during reviewed deployment")


def verify_staged(root: Path, review: dict) -> None:
    changed = git(root, "diff", "--cached", "--name-only", review["candidate"], "--", *review["paths"])
    if changed:
        raise RuntimeError("Integrated selected files differ from the exact reviewed candidate")
