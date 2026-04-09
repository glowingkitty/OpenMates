#!/usr/bin/env python3
# backend/scripts/migrate_focus_mode_to_skill_md.py
#
# One-shot migration helper that converts a legacy focus mode (defined
# in backend/apps/<app>/app.yml + frontend i18n YAML files) into the new
# SKILL.md directory layout described in
# docs/architecture/apps/focus-modes.md.
#
# Phase 1 of the migration uses this script manually against a single
# focus mode (jobs/career_insights). Phase 2 will extend it to batch-
# migrate all 34 focus modes.
#
# Usage:
#   python3 backend/scripts/migrate_focus_mode_to_skill_md.py \
#     --app jobs --focus career_insights --canonical-exists
#
# With --canonical-exists, the canonical SKILL.md (English) must already
# exist; the script only generates SKILL.<lang>.md siblings for every
# other language that has translations in the legacy i18n YAML. This is
# the safe default — the canonical file is hand-authored so the system
# prompt + structural frontmatter can be reviewed before localized
# files are generated from it.

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]

# Legacy data lives in TWO sibling directories with partially overlapping content:
#   focus_modes/<app>_<focus>.yml   → name (as <app>_<focus>), description, process, systemprompt
#   app_focus_modes/<app>.yml       → name (as <focus>), <focus>.description, <focus>.process,
#                                     <focus>.how_to_use.1/2/3
# The migration reads both and prefers focus_modes/ for fields they both carry,
# falling back to app_focus_modes/ only for how_to_use examples.
LEGACY_FOCUS_MODES_DIR = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/focus_modes"
LEGACY_APP_FOCUS_MODES_DIR = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/app_focus_modes"

# Languages we intentionally skip because they're not used in the app.
# Leave empty — every language with actual translations is migrated.
SKIP_LANGS: set = set()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="App id (e.g., 'jobs')")
    parser.add_argument("--focus", required=True, help="Focus mode id (e.g., 'career_insights')")
    parser.add_argument(
        "--canonical-exists",
        action="store_true",
        help="Require canonical SKILL.md to already exist (recommended).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written, don't touch the filesystem.",
    )
    args = parser.parse_args()

    app_id: str = args.app
    focus_id: str = args.focus
    focus_dir = REPO_ROOT / f"backend/apps/{app_id}/focus_modes/{focus_id}"
    canonical_path = focus_dir / "SKILL.md"

    if args.canonical_exists and not canonical_path.exists():
        print(f"ERROR: canonical SKILL.md does not exist at {canonical_path}", file=sys.stderr)
        print("Create it by hand first, then re-run this script.", file=sys.stderr)
        return 1

    # Load BOTH legacy i18n YAML files for this focus mode.
    focus_modes_path = LEGACY_FOCUS_MODES_DIR / f"{app_id}_{focus_id}.yml"
    app_focus_modes_path = LEGACY_APP_FOCUS_MODES_DIR / f"{app_id}.yml"

    if not focus_modes_path.exists():
        print(f"ERROR: legacy i18n file not found: {focus_modes_path}", file=sys.stderr)
        return 1
    if not app_focus_modes_path.exists():
        print(f"ERROR: legacy i18n file not found: {app_focus_modes_path}", file=sys.stderr)
        return 1

    with open(focus_modes_path, "r", encoding="utf-8") as f:
        fm_data = yaml.safe_load(f) or {}
    with open(app_focus_modes_path, "r", encoding="utf-8") as f:
        afm_data = yaml.safe_load(f) or {}

    # Keys in focus_modes/<app>_<focus>.yml (no focus_id prefix — the filename is the scope)
    fm_name_key = f"{app_id}_{focus_id}"
    fm_process_key = "process"
    fm_description_key = "description"
    fm_systemprompt_key = "systemprompt"

    # Keys in app_focus_modes/<app>.yml (focus_id is the scope)
    afm_name_key = focus_id
    afm_how_to_use_keys = [f"{focus_id}.how_to_use.{i}" for i in (1, 2, 3)]

    # Collect every language that has at least a translated name in either file.
    languages: List[str] = set()
    for container, key in ((fm_data, fm_name_key), (afm_data, afm_name_key)):
        section = container.get(key)
        if isinstance(section, dict):
            for lang in section.keys():
                if lang in ("context", "verified_by_human") or lang in SKIP_LANGS:
                    continue
                if lang == "en":  # canonical file handles English
                    continue
                languages.add(lang)

    print(f"Found {len(languages)} non-English languages: {', '.join(sorted(languages))}")

    # Compute canonical source hash for stale-detection.
    source_hash = _compute_canonical_hash(canonical_path)
    print(f"Canonical source hash: {source_hash[:16]}…")

    # Generate one SKILL.<lang>.md per language.
    for lang in sorted(languages):
        target_path = focus_dir / f"SKILL.{lang}.md"

        # Prefer focus_modes/ for fields both files carry, fall back to app_focus_modes/.
        name = (
            _safe_get(fm_data, fm_name_key, lang)
            or _safe_get(afm_data, afm_name_key, lang)
        )
        description = (
            _safe_get(fm_data, fm_description_key, lang)
            or _safe_get(afm_data, f"{focus_id}.description", lang)
        )
        process_raw = (
            _safe_get(fm_data, fm_process_key, lang)
            or _safe_get(afm_data, f"{focus_id}.process", lang)
        )
        systemprompt = _safe_get(fm_data, fm_systemprompt_key, lang)
        how_to_use = [
            _safe_get(afm_data, k, lang)
            for k in afm_how_to_use_keys
        ]
        how_to_use = [h for h in how_to_use if h]

        if not name:
            print(f"  SKIP {lang}: no translated name", file=sys.stderr)
            continue

        # Aggregate verified_by_human from both files — if either marks the
        # language as verified, we carry that through. (Localized SKILL.md
        # holds the strictest flag; reviewers re-verify in Phase 2.)
        verified_langs: set = set()
        for container, key in ((fm_data, fm_name_key), (afm_data, afm_name_key)):
            section = container.get(key)
            if isinstance(section, dict):
                vbh = section.get("verified_by_human") or []
                if isinstance(vbh, list):
                    verified_langs.update(vbh)
        verified = lang in verified_langs

        content = _render_localized_skill_md(
            app_id=app_id,
            focus_id=focus_id,
            lang=lang,
            name=name,
            description=description or "",
            process_raw=process_raw or "",
            how_to_use=how_to_use,
            systemprompt=systemprompt,
            verified=verified,
            source_hash=source_hash,
        )

        if args.dry_run:
            print(f"  [dry-run] would write {target_path} ({len(content)} bytes)")
        else:
            target_path.write_text(content, encoding="utf-8")
            print(f"  WROTE {target_path.relative_to(REPO_ROOT)}")

    print("Done.")
    return 0


def _safe_get(legacy: Dict[str, Any], section_key: str, lang: str) -> Optional[str]:
    """Return legacy[section_key][lang] as a string, or None."""
    section = legacy.get(section_key)
    if not isinstance(section, dict):
        return None
    value = section.get(lang)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _compute_canonical_hash(canonical_path: Path) -> str:
    """
    Hash the canonical SKILL.md's structural frontmatter (excluding localized
    string fields) so we can detect drift against localized siblings.
    """
    raw = canonical_path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return "unknown"
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return "unknown"
    frontmatter = yaml.safe_load(parts[1]) or {}
    EXCLUDE = {
        "name",
        "description",
        "preprocessor-hint",
        "lang",
        "verified_by_human",
        "source_hash",
    }
    structural = {k: v for k, v in frontmatter.items() if k not in EXCLUDE}
    canonical = yaml.safe_dump(structural, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _render_localized_skill_md(
    *,
    app_id: str,
    focus_id: str,
    lang: str,
    name: str,
    description: str,
    process_raw: str,
    how_to_use: List[str],
    systemprompt: Optional[str],
    verified: bool,
    source_hash: str,
) -> str:
    """
    Render a minimal SKILL.<lang>.md with only the localized fields.

    Structural frontmatter is omitted (enforced by the parity lint in
    Phase 2 — in Phase 1 the loader reads structural fields from the
    canonical file only). The body contains localized Process, How-to-use,
    and System prompt sections when translations exist. If the system
    prompt isn't translated for this language, runtime falls back to the
    canonical English system prompt.
    """
    # Escape YAML special chars in localized strings.
    name_yaml = yaml.safe_dump(name, allow_unicode=True, default_style='"').strip()
    desc_yaml = yaml.safe_dump(description, allow_unicode=True, default_style='"').strip()

    lines: List[str] = []
    lines.append("---")
    lines.append(f"# Localized override for {app_id}/{focus_id} — generated by migrate_focus_mode_to_skill_md.py")
    lines.append("# Structural frontmatter (id, app, stage, gating, …) lives in the canonical SKILL.md.")
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
        # process_raw from legacy YAML is already in "- bullet" form.
        for bullet_line in process_raw.splitlines():
            bl = bullet_line.strip()
            if bl.startswith("- "):
                lines.append(bl)
            elif bl:
                lines.append(f"- {bl}")
        lines.append("")

    if how_to_use:
        lines.append("## How to use")
        lines.append("")
        for example in how_to_use:
            lines.append(f"- {example}")
        lines.append("")

    if systemprompt:
        lines.append("## System prompt")
        lines.append("")
        lines.append(systemprompt.rstrip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(main())
