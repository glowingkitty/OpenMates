"""Validate locally retained CI candidate manifests and patch bytes."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re

try:
    from scripts.ci_candidate_artifact import validate_url
    from scripts.ci_source import git
except ModuleNotFoundError:
    from ci_candidate_artifact import validate_url
    from ci_source import git


SHA = re.compile(r"[0-9a-f]{40}")


def canonical_root(root: Path) -> Path:
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common.resolve().parent


def manifest_path(root: Path, source: str) -> Path:
    if not SHA.fullmatch(source):
        raise ValueError("CI candidate source must be a full commit SHA")
    return canonical_root(root) / "logs/ci-candidates" / source / "manifest.json"


def load(root: Path, source: str, *, required: bool = False, require_fresh: bool = False) -> dict:
    path = manifest_path(root, source)
    if not path.is_file():
        if required:
            raise RuntimeError("Retained CI candidate manifest is unavailable")
        return {}
    data = json.loads(path.read_text())
    for field in ("source", "base", "tree"):
        if not SHA.fullmatch(str(data.get(field, ""))):
            raise RuntimeError(f"CI candidate manifest has invalid {field}")
    if data["source"] != source:
        raise RuntimeError("CI candidate manifest source mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("patch_sha256", ""))):
        raise RuntimeError("CI candidate manifest has invalid patch digest")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(data.get("session", ""))):
        raise RuntimeError("CI candidate manifest has invalid owner")
    validate_url(str(data.get("patch_url", "")))
    expires = dt.datetime.fromisoformat(str(data.get("artifact_expires_at", "")))
    if expires.tzinfo is None:
        raise RuntimeError("CI candidate artifact expiry must include a timezone")
    if require_fresh and expires <= dt.datetime.now(dt.timezone.utc):
        raise RuntimeError("CI candidate artifact expired; publish a fresh candidate")
    patch = Path(str(data.get("local_patch", ""))).resolve()
    expected_dir = path.parent.resolve()
    if patch.parent != expected_dir or not patch.is_file():
        raise RuntimeError("Retained CI candidate patch is unavailable")
    if hashlib.sha256(patch.read_bytes()).hexdigest() != data["patch_sha256"]:
        raise RuntimeError("Retained CI candidate patch digest mismatch")
    if git(root, "rev-parse", source + "^{commit}") != source:
        raise RuntimeError("Retained CI candidate commit is unavailable")
    if git(root, "rev-parse", source + "^{tree}") != data["tree"]:
        raise RuntimeError("Retained CI candidate tree mismatch")
    if git(root, "show", "-s", "--format=%P", source).split() != [data["base"]]:
        raise RuntimeError("Retained CI candidate parent mismatch")
    return data
