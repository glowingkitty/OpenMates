#!/usr/bin/env python3
"""Audit backend app skills against app-skill-use embed registrations.

Every executable app skill can surface as an `app_skill_use` embed in chat. If a
skill is missing from `embed_types`, the frontend falls through to an unknown
skill path and example chats can silently render poor placeholders. This script
keeps the backend skill registry and frontend embed routing contract in sync.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = REPO_ROOT / "backend/apps"

# These skills are intentionally internal orchestration or memory operations and
# do not create user-visible app_skill_use embeds. New entries require a reason.
SKILL_EMBED_EXCEPTIONS: dict[str, str] = {
    "ai:ask": "Core chat entrypoint invoked implicitly for every request, not a tool-call embed.",
}


def load_app(path: Path) -> dict[str, Any]:
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
        if path.name == "app.yml" and APPS_DIR in path.parents:
            resolved.add(path)
    return sorted(resolved)


def skill_ids(app_data: dict[str, Any]) -> set[str]:
    skills = app_data.get("skills") or []
    if not isinstance(skills, list):
        return set()
    return {skill.get("id") for skill in skills if isinstance(skill, dict) and skill.get("id")}


def embed_skill_ids(app_data: dict[str, Any]) -> set[str]:
    embed_types = app_data.get("embed_types") or []
    if not isinstance(embed_types, list):
        return set()
    return {
        embed.get("skill_id")
        for embed in embed_types
        if isinstance(embed, dict)
        and embed.get("category") == "app-skill-use"
        and embed.get("skill_id")
    }


def audit(paths: list[Path]) -> list[str]:
    issues: list[str] = []
    for path in paths:
        app_id = path.parent.name
        app_data = load_app(path)
        for skill_id in sorted(skill_ids(app_data) - embed_skill_ids(app_data)):
            key = f"{app_id}:{skill_id}"
            if key in SKILL_EMBED_EXCEPTIONS:
                continue
            issues.append(
                f"{path.relative_to(REPO_ROOT)}: skill {skill_id!r} is missing an app-skill-use "
                f"embed_types entry. Add one or document an exception in {Path(__file__).name}."
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit app skills against app-skill-use embed registrations")
    parser.add_argument("paths", nargs="*", help="Optional app.yml paths to audit")
    args = parser.parse_args()

    paths = app_paths(args.paths)
    if not paths:
        print("No app.yml files to audit.")
        return 0

    issues = audit(paths)
    if issues:
        print("SKILL EMBED REGISTRY ISSUES")
        for issue in issues:
            print(f"- {issue}")
        print(f"Summary: {len(issues)} issue(s).")
        return 1

    print(f"Skill embed registry audit passed for {len(paths)} app file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
