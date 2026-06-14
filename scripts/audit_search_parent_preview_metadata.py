#!/usr/bin/env python3
"""Audit composite result-list parent embeds for preview metadata contracts.

Parent previews for result-list embeds must be self-contained. Any app-skill-use
embed type with children must either be covered by parent preview metadata
generation or carry an explicit exemption explaining why it is not a result-list
preview. This catches new child/composite embed types before preview renderers
fall back to loading child embeds.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = REPO_ROOT / "backend/apps"

# Covered by EmbedService._build_parent_preview_metadata or a skill-specific
# parent metadata builder. New result-list parent embeds should be added here
# only after tests prove they store enough parent-level preview metadata.
PARENT_PREVIEW_METADATA_COVERAGE: set[str] = {
    "code:search_repos",
    "electronics:search_components",
    "events:search",
    "health:search_appointments",
    "home:search",
    "images:search",
    "maps:search",
    "news:search",
    "nutrition:search_recipes",
    "shopping:search_products",
    "social_media:get-posts",
    "social_media:search",
    "travel:search_connections",
    "travel:search_stays",
    "videos:search",
    "weather:forecast",
    "web:search",
}

# Composite parents that are intentionally not search/result-list previews. New
# exemptions require a non-empty reason so future maintainers understand why the
# parent may remain manifest-only or action-only.
PARENT_PREVIEW_METADATA_EXEMPTIONS: dict[str, str] = {
    "code:create_application": "Application parents store a manifest of file refs; live previews run only on explicit action.",
}


@dataclass(frozen=True)
class AuditIssue:
    path: Path
    app_id: str
    skill_id: str
    message: str

    def format(self, root: Path) -> str:
        try:
            display_path = self.path.relative_to(root)
        except ValueError:
            display_path = self.path
        return f"{display_path}: {self.app_id}:{self.skill_id} - {self.message}"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def app_paths(paths: list[str]) -> list[Path]:
    if not paths:
        return sorted(APPS_DIR.glob("*/app.yml"))

    resolved: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path = path.resolve()
        if path.name == "app.yml":
            resolved.add(path)
    return sorted(resolved)


def iter_child_parent_embed_types(app_data: dict[str, Any]) -> list[dict[str, Any]]:
    embed_types = app_data.get("embed_types") or []
    if not isinstance(embed_types, list):
        return []

    return [
        embed_type
        for embed_type in embed_types
        if isinstance(embed_type, dict)
        and embed_type.get("category") == "app-skill-use"
        and embed_type.get("has_children") is True
        and embed_type.get("skill_id")
    ]


def audit_app_files(
    paths: list[Path],
    *,
    covered: set[str] | None = None,
    exemptions: dict[str, str] | None = None,
) -> list[AuditIssue]:
    covered = PARENT_PREVIEW_METADATA_COVERAGE if covered is None else covered
    exemptions = PARENT_PREVIEW_METADATA_EXEMPTIONS if exemptions is None else exemptions

    issues: list[AuditIssue] = []
    for path in paths:
        app_id = path.parent.name
        app_data = load_yaml(path)
        for embed_type in iter_child_parent_embed_types(app_data):
            skill_id = str(embed_type["skill_id"])
            key = f"{app_id}:{skill_id}"
            if key in covered:
                continue
            if key in exemptions:
                if exemptions[key].strip():
                    continue
                issues.append(
                    AuditIssue(
                        path=path,
                        app_id=app_id,
                        skill_id=skill_id,
                        message="explicit parent preview metadata exemption reason is empty",
                    )
                )
                continue
            issues.append(
                AuditIssue(
                    path=path,
                    app_id=app_id,
                    skill_id=skill_id,
                    message=(
                        "missing parent preview metadata contract. Add metadata builder coverage "
                        "or document a non-result-list exemption in audit_search_parent_preview_metadata.py."
                    ),
                )
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit result-list parent embed preview metadata coverage")
    parser.add_argument("paths", nargs="*", help="Optional app.yml paths to audit")
    args = parser.parse_args()

    paths = app_paths(args.paths)
    if not paths:
        print("No app.yml files to audit.")
        return 0

    issues = audit_app_files(paths)
    if issues:
        print("SEARCH PARENT PREVIEW METADATA ISSUES")
        for issue in issues:
            print(f"- {issue.format(REPO_ROOT)}")
        print(f"Summary: {len(issues)} issue(s).")
        return 1

    print(f"Search parent preview metadata audit passed for {len(paths)} app file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
