"""Deterministic file-risk classification for Project remote writes.

Remote Project edits use this classifier before any later-phase write can be
auto-approved. The list intentionally stays narrow: it protects secrets,
deployment, dependency execution, auth/security/privacy/compliance, schema, CI,
and filesystem-boundary risks without turning normal source edits into noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath


HIGH_RISK_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".ssh/**",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".github/workflows/**",
    "Caddyfile",
    "nginx.conf",
    "Dockerfile",
    "docker-compose*.yml",
    "k8s/**",
    "helm/**",
    "terraform/**",
    "*.tf",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "migrations/**",
    "schema.sql",
    "backend/core/directus/schemas/**",
)

HIGH_RISK_KEYWORDS = (
    "auth",
    "billing",
    "compliance",
    "encryption",
    "permission",
    "privacy",
    "security",
)


@dataclass(frozen=True)
class ProjectFileRisk:
    is_high_risk: bool
    reasons: list[str]


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized)) if normalized else ""


def _matches_pattern(path: str, pattern: str) -> bool:
    basename = PurePosixPath(path).name
    return fnmatch(path, pattern) or fnmatch(basename, pattern)


def classify_project_file_risk(
    path: str,
    *,
    user_protected_patterns: list[str] | None = None,
    is_gitignored: bool = False,
    is_binary: bool = False,
    operation: str = "edit",
) -> ProjectFileRisk:
    """Return whether a Project file operation should always ask by default."""
    normalized_path = _normalize_path(path)
    reasons: list[str] = []

    if not normalized_path or normalized_path.startswith("../"):
        reasons.append("outside_source_root")

    for pattern in HIGH_RISK_PATTERNS:
        if _matches_pattern(normalized_path, pattern):
            reasons.append("built_in_pattern")
            break

    path_parts = {part.lower() for part in PurePosixPath(normalized_path).parts}
    if any(keyword in path_parts for keyword in HIGH_RISK_KEYWORDS):
        reasons.append("sensitive_path_keyword")

    for pattern in user_protected_patterns or []:
        if _matches_pattern(normalized_path, pattern):
            reasons.append("user_protected_pattern")
            break

    if is_gitignored:
        reasons.append("gitignored")
    if is_binary:
        reasons.append("binary")
    if operation in {"delete", "rename", "chmod", "binary_edit", "symlink_edit"}:
        reasons.append(operation)

    return ProjectFileRisk(is_high_risk=bool(reasons), reasons=reasons)
