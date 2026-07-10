#!/usr/bin/env python3
"""Deterministic changed-path classification for CI and Vercel.

Defines the canonical package and web build inputs. GitHub Actions still needs
declarative path filters, so focused tests keep workflow YAML in parity with
these sets. The classifier fails open when a caller cannot obtain changed paths.
"""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CLI_PATH_PATTERNS = (
    ".github/workflows/publish-cli.yml",
    "backend/apps/**/app.yml",
    "frontend/packages/openmates-cli/**",
    "frontend/packages/ui/src/demo_chats/**",
    "frontend/packages/ui/src/i18n/locales/en.json",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "scripts/ci_impact.py",
    "scripts/generate_sdk_app_skills.py",
    "scripts/prepare_cli_publish_version.mjs",
    "scripts/tests/test_ci_impact.py",
    "scripts/tests/test_ci_workflow_scope.py",
    "scripts/tests/test_prepare_cli_publish_version.mjs",
    "shared/config/product_version.json",
)
PYTHON_PATH_PATTERNS = (
    ".github/workflows/publish-python-sdk.yml",
    "backend/apps/**/app.yml",
    "packages/openmates-python/**",
    "scripts/ci_impact.py",
    "scripts/generate_sdk_app_skills.py",
    "scripts/prepare_python_publish_version.py",
    "scripts/tests/test_ci_impact.py",
    "scripts/tests/test_ci_workflow_scope.py",
    "scripts/tests/test_prepare_python_publish_version.py",
    "shared/config/product_version.json",
)
WEB_PATH_PATTERNS = (
    "backend/apps/**/app.yml",
    "docs/**",
    "frontend/apps/web_app/**",
    "frontend/packages/ui/**",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "scripts/ci_impact.py",
    "scripts/vercel_ignore_build.py",
    "shared/docs/**",
    "vercel.json",
)


@dataclass(frozen=True)
class CIImpact:
    cli_package: bool
    python_package: bool
    web: bool


def normalize_paths(paths: Iterable[str]) -> tuple[str, ...]:
    """Return unique repository-relative paths without traversal components."""
    normalized = {
        path.replace("\\", "/").removeprefix("./")
        for raw_path in paths
        if (path := str(raw_path).strip()) and not path.startswith("../") and "/../" not in path
    }
    return tuple(sorted(normalized))


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_paths(paths: Iterable[str]) -> CIImpact:
    normalized = normalize_paths(paths)
    return CIImpact(
        cli_package=any(_matches_any(path, CLI_PATH_PATTERNS) for path in normalized),
        python_package=any(_matches_any(path, PYTHON_PATH_PATTERNS) for path in normalized),
        web=any(_matches_any(path, WEB_PATH_PATTERNS) for path in normalized),
    )


def workflow_path_patterns(target: str) -> tuple[str, ...]:
    if target == "cli":
        return CLI_PATH_PATTERNS
    if target == "python":
        return PYTHON_PATH_PATTERNS
    raise ValueError(f"Unknown CI workflow target: {target}")


def changed_paths_since(base_sha: str, head_sha: str, repo_root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return normalize_paths(result.stdout.splitlines())
