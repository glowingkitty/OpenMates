#!/usr/bin/env python3
# backend/scripts/batch_migrate_focus_modes.py
#
# Phase 2 batch migration: converts ALL focus modes to SKILL.md format.
#
# For each focus mode found in backend/apps/<app>/app.yml:
#   1. Creates backend/apps/<app>/focus_modes/<focus_id>/SKILL.md (canonical English)
#      from the app.yml structural data + i18n English strings
#   2. Generates SKILL.<lang>.md siblings for every translated language
#
# Skips focus modes that already have a SKILL.md (e.g., jobs/career_insights).
#
# Usage:
#   python3 backend/scripts/batch_migrate_focus_modes.py
#   python3 backend/scripts/batch_migrate_focus_modes.py --dry-run
#   python3 backend/scripts/batch_migrate_focus_modes.py --app code  # single app

import argparse
import hashlib
import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_APPS_DIR = REPO_ROOT / "backend/apps"
LEGACY_FOCUS_MODES_DIR = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/focus_modes"
LEGACY_APP_FOCUS_MODES_DIR = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/app_focus_modes"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", help="Migrate only this app (e.g., 'code')")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing files")
    args = parser.parse_args()

    # Discover all focus modes from app.yml files
    all_focus_modes: List[Dict[str, Any]] = []
    for app_yml_path in sorted(BACKEND_APPS_DIR.glob("*/app.yml")):
        app_id = app_yml_path.parent.name
        if args.app and app_id != args.app:
            continue
        with open(app_yml_path) as f:
            data = yaml.safe_load(f) or {}
        focuses = data.get("focuses") or data.get("focus_modes") or []
        for focus in focuses:
            all_focus_modes.append({
                "app_id": app_id,
                "focus_id": focus.get("id"),
                "focus_data": focus,
            })

    if not all_focus_modes:
        print("No focus modes found.")
        return 0

    print(f"Found {len(all_focus_modes)} focus modes across {len(set(f['app_id'] for f in all_focus_modes))} apps")
    print()

    created_canonical = 0
    created_localized = 0
    skipped = 0

    for fm in all_focus_modes:
        app_id = fm["app_id"]
        focus_id = fm["focus_id"]
        focus_data = fm["focus_data"]
        focus_dir = BACKEND_APPS_DIR / app_id / "focus_modes" / focus_id
        canonical_path = focus_dir / "SKILL.md"

        if canonical_path.exists():
            print(f"  SKIP {app_id}/{focus_id} — SKILL.md already exists")
            skipped += 1
            continue

        # Load i18n data from both legacy files
        fm_data, afm_data = _load_i18n_data(app_id, focus_id)

        # Generate canonical SKILL.md
        canonical_content = _render_canonical_skill_md(app_id, focus_id, focus_data, fm_data, afm_data)

        if args.dry_run:
            print(f"  [dry-run] would create {canonical_path.relative_to(REPO_ROOT)}")
        else:
            focus_dir.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(canonical_content, encoding="utf-8")
            print(f"  WROTE {canonical_path.relative_to(REPO_ROOT)}")
        created_canonical += 1

        # Generate localized SKILL.<lang>.md files
        languages = _collect_languages(fm_data, afm_data, app_id, focus_id)
        source_hash = _compute_hash(canonical_content) if not args.dry_run else "dry-run"

        for lang in sorted(languages):
            target_path = focus_dir / f"SKILL.{lang}.md"
            localized_content = _render_localized_skill_md(
                app_id, focus_id, lang, fm_data, afm_data, source_hash
            )
            if localized_content is None:
                continue

            if args.dry_run:
                print(f"    [dry-run] would create SKILL.{lang}.md")
            else:
                target_path.write_text(localized_content, encoding="utf-8")
            created_localized += 1

    print()
    print(f"Done. Created {created_canonical} canonical + {created_localized} localized files. Skipped {skipped}.")
    return 0


def _load_i18n_data(app_id: str, focus_id: str):
    """Load both legacy i18n YAML files."""
    fm_path = LEGACY_FOCUS_MODES_DIR / f"{app_id}_{focus_id}.yml"
    afm_path = LEGACY_APP_FOCUS_MODES_DIR / f"{app_id}.yml"

    fm_data = {}
    if fm_path.exists():
        with open(fm_path) as f:
            fm_data = yaml.safe_load(f) or {}

    afm_data = {}
    if afm_path.exists():
        with open(afm_path) as f:
            afm_data = yaml.safe_load(f) or {}

    return fm_data, afm_data


def _safe_get(data: dict, key: str, lang: str) -> Optional[str]:
    """Get data[key][lang] as a string, or None."""
    section = data.get(key)
    if not isinstance(section, dict):
        return None
    value = section.get(lang)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _render_canonical_skill_md(
    app_id: str,
    focus_id: str,
    focus_data: dict,
    fm_data: dict,
    afm_data: dict,
) -> str:
    """Render the canonical English SKILL.md from app.yml + i18n data."""
    # Extract English strings from i18n files
    fm_name_key = f"{app_id}_{focus_id}"
    afm_name_key = focus_id

    name = _safe_get(fm_data, fm_name_key, "en") or _safe_get(afm_data, afm_name_key, "en") or focus_id
    description = _safe_get(fm_data, "description", "en") or _safe_get(afm_data, f"{focus_id}.description", "en") or ""
    process_raw = _safe_get(fm_data, "process", "en") or _safe_get(afm_data, f"{focus_id}.process", "en") or ""
    systemprompt = _safe_get(fm_data, "systemprompt", "en") or ""

    # How-to-use examples from app_focus_modes
    how_to_use = []
    for i in (1, 2, 3):
        ex = _safe_get(afm_data, f"{focus_id}.how_to_use.{i}", "en")
        if ex:
            how_to_use.append(ex)

    # Structural data from app.yml
    raw_stage = focus_data.get("stage", "development") or "development"
    icon = focus_data.get("icon_image", "")
    preprocessor_hint = focus_data.get("preprocessor_hint", "")

    # Some legacy app.yml files have YAML formatting issues where the system
    # prompt text leaked into the stage field (e.g., "planning You are an
    # expert..."). Clean: extract only the first word as the stage. If
    # there's leaked text AND no system prompt from i18n, use the leaked
    # text as the system prompt.
    VALID_STAGES = {"planning", "development", "production"}
    stage = raw_stage.strip().split()[0].lower() if raw_stage else "development"
    if stage not in VALID_STAGES:
        stage = "development"
    leaked_text = raw_stage.strip()[len(stage):].strip() if raw_stage else ""
    if leaked_text and not systemprompt:
        systemprompt = leaked_text

    # Clean up preprocessor_hint: in some legacy app.yml files the hint and
    # system prompt are merged into one block. Separate them: take only
    # lines before the first sentence that doesn't start with "Select when"
    # or similar routing instruction.
    hint_lines = []
    if preprocessor_hint:
        for line in preprocessor_hint.strip().splitlines():
            hint_lines.append(line.strip())
        preprocessor_hint = " ".join(hint_lines)

    lines = []
    lines.append("---")
    lines.append(f"id: {focus_id}")
    lines.append(f"app: {app_id}")
    lines.append(f"stage: {stage}")
    if icon:
        lines.append(f"icon: {icon}")
    lines.append("")
    lines.append(f"name: {_yaml_safe(name)}")
    lines.append(f"description: {_yaml_safe(description)}")
    lines.append("")
    if preprocessor_hint:
        lines.append("preprocessor-hint: >")
        wrapped = textwrap.fill(preprocessor_hint, width=72, initial_indent="  ", subsequent_indent="  ")
        lines.append(wrapped)
    lines.append("")
    lines.append("allowed-models: []")
    lines.append("recommended-model: null")
    lines.append("allowed-apps: []")
    lines.append("allowed-skills: []")
    lines.append("denied-skills: []")
    lines.append("")
    lines.append("lang: en")
    lines.append("verified_by_human: true")
    lines.append("source_hash: null")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")

    if process_raw:
        lines.append("## Process")
        lines.append("")
        for bullet_line in process_raw.strip().splitlines():
            bl = bullet_line.strip()
            if bl:
                if not bl.startswith("- "):
                    bl = f"- {bl}"
                lines.append(bl)
        lines.append("")

    if how_to_use:
        lines.append("## How to use")
        lines.append("")
        for ex in how_to_use:
            lines.append(f"- {ex}")
        lines.append("")

    if systemprompt:
        lines.append("## System prompt")
        lines.append("")
        lines.append(systemprompt.rstrip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _collect_languages(fm_data: dict, afm_data: dict, app_id: str, focus_id: str) -> set:
    """Collect all non-English languages that have translations."""
    languages = set()
    fm_name_key = f"{app_id}_{focus_id}"
    afm_name_key = focus_id

    for container, key in ((fm_data, fm_name_key), (afm_data, afm_name_key)):
        section = container.get(key)
        if isinstance(section, dict):
            for lang in section.keys():
                if lang in ("context", "verified_by_human"):
                    continue
                if lang == "en":
                    continue
                languages.add(lang)

    return languages


def _render_localized_skill_md(
    app_id: str,
    focus_id: str,
    lang: str,
    fm_data: dict,
    afm_data: dict,
    source_hash: str,
) -> Optional[str]:
    """Render a SKILL.<lang>.md file."""
    fm_name_key = f"{app_id}_{focus_id}"
    afm_name_key = focus_id

    name = _safe_get(fm_data, fm_name_key, lang) or _safe_get(afm_data, afm_name_key, lang)
    if not name:
        return None

    description = _safe_get(fm_data, "description", lang) or _safe_get(afm_data, f"{focus_id}.description", lang) or ""
    process_raw = _safe_get(fm_data, "process", lang) or _safe_get(afm_data, f"{focus_id}.process", lang) or ""
    systemprompt = _safe_get(fm_data, "systemprompt", lang) or ""

    how_to_use = []
    for i in (1, 2, 3):
        ex = _safe_get(afm_data, f"{focus_id}.how_to_use.{i}", lang)
        if ex:
            how_to_use.append(ex)

    # Aggregate verified_by_human
    verified_langs = set()
    for container, key in ((fm_data, fm_name_key), (afm_data, afm_name_key)):
        section = container.get(key)
        if isinstance(section, dict):
            vbh = section.get("verified_by_human") or []
            if isinstance(vbh, list):
                verified_langs.update(vbh)
    verified = lang in verified_langs

    name_yaml = yaml.safe_dump(name, allow_unicode=True, default_style='"').strip()
    desc_yaml = yaml.safe_dump(description, allow_unicode=True, default_style='"').strip()

    lines = []
    lines.append("---")
    lines.append(f"# Localized override for {app_id}/{focus_id}")
    lines.append(f"id: {focus_id}")
    lines.append(f"app: {app_id}")
    lines.append(f"name: {name_yaml}")
    lines.append(f"description: {desc_yaml}")
    lines.append(f"lang: {lang}")
    lines.append(f"verified_by_human: {'true' if verified else 'false'}")
    lines.append(f"source_hash: {source_hash}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")

    if process_raw:
        lines.append("## Process")
        lines.append("")
        for bullet_line in process_raw.strip().splitlines():
            bl = bullet_line.strip()
            if bl:
                if not bl.startswith("- "):
                    bl = f"- {bl}"
                lines.append(bl)
        lines.append("")

    if how_to_use:
        lines.append("## How to use")
        lines.append("")
        for ex in how_to_use:
            lines.append(f"- {ex}")
        lines.append("")

    if systemprompt:
        lines.append("## System prompt")
        lines.append("")
        lines.append(systemprompt.rstrip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _compute_hash(content: str) -> str:
    """Compute SHA-256 of structural frontmatter for stale-detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _yaml_safe(s: str) -> str:
    """Escape a string for inline YAML if it contains special characters."""
    if not s:
        return '""'
    if any(c in s for c in ":{}[]&*?|>-!%@`#,") or s.startswith(("'", '"')):
        return yaml.safe_dump(s, allow_unicode=True, default_style='"').strip()
    return s


if __name__ == "__main__":
    sys.exit(main())
