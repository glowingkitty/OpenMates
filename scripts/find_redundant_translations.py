#!/usr/bin/env python3
"""
Find redundant translations across i18n YAML source files.

Namespace-aware: resolves YAML keys to their final JSON paths
(matching build-translations.js logic) to avoid false positives.

Detects:
  1. Duplicate resolved paths — same final JSON key from multiple YAML files
  2. Duplicate English values — different resolved keys that share the same `en` text
  3. Near-duplicate English values — keys with very similar `en` text (case/punctuation diffs)

Usage:
  python3 scripts/find_redundant_translations.py              # full report
  python3 scripts/find_redundant_translations.py --json       # machine-readable output
  python3 scripts/find_redundant_translations.py --summary    # counts only
  python3 scripts/find_redundant_translations.py --consolidatable  # show keys eligible for common.yml
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SOURCES_DIR = Path("frontend/packages/ui/src/i18n/sources")


def resolve_namespace(yml_file: Path, sources_dir: Path) -> tuple[str, str]:
    """
    Compute the namespace and key prefix for a YAML file,
    matching the logic in build-translations.js (lines 154-192).

    Returns (namespace, key_prefix).
    """
    rel = yml_file.relative_to(sources_dir)
    parts = rel.parts

    if len(parts) == 1:
        # Top-level file: namespace = filename without .yml, no prefix
        return rel.stem, ""
    else:
        # Subdirectory file: namespace = first parent dir
        namespace = parts[0]

        filename = parts[-1]
        if filename == "main.yml":
            return namespace, ""
        else:
            return namespace, Path(filename).stem


def resolve_key(yaml_key: str, namespace: str, key_prefix: str) -> str:
    """Compute the final resolved JSON path for a YAML key."""
    if not key_prefix:
        return f"{namespace}.{yaml_key}"
    if yaml_key == key_prefix:
        # Key matches filename — don't prefix
        return f"{namespace}.{yaml_key}"
    return f"{namespace}.{key_prefix}.{yaml_key}"


def parse_yaml_keys(filepath: Path) -> list[dict]:
    """
    Parse a flat-key YAML translation file without a YAML library.
    Returns list of {key, en, context, line} dicts.
    """
    entries = []
    current_key = None
    current_data = {}
    current_line = 0

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            stripped = line.rstrip()

            if not stripped or stripped.startswith("#"):
                continue

            # Top-level key (no leading whitespace, ends with colon)
            if not line[0].isspace() and ":" in stripped:
                if current_key and "en" in current_data:
                    entries.append({
                        "key": current_key,
                        "en": current_data.get("en", ""),
                        "context": current_data.get("context", ""),
                        "line": current_line,
                    })

                key_part = stripped.split(":", 1)[0].strip()
                current_key = key_part
                current_data = {}
                current_line = line_num

            elif line[0].isspace() and current_key and ":" in stripped:
                field_match = re.match(r"\s+(\w[\w_]*)\s*:\s*(.*)", stripped)
                if field_match:
                    field_name = field_match.group(1)
                    field_value = field_match.group(2).strip()
                    if (field_value.startswith('"') and field_value.endswith('"')) or \
                       (field_value.startswith("'") and field_value.endswith("'")):
                        field_value = field_value[1:-1]
                    current_data[field_name] = field_value

    if current_key and "en" in current_data:
        entries.append({
            "key": current_key,
            "en": current_data.get("en", ""),
            "context": current_data.get("context", ""),
            "line": current_line,
        })

    return entries


def normalize(text: str) -> str:
    """Normalize text for near-duplicate comparison."""
    t = text.lower().strip()
    # Normalize unicode ellipsis to ASCII
    t = t.replace("…", "...")
    # Remove trailing punctuation
    t = re.sub(r"[.!?:…]+$", "", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t)
    return t


def find_redundancies(sources_dir: Path, consolidatable_mode: bool = False) -> dict:
    """Scan all YAML files and find redundancies using resolved namespace paths."""
    yml_files = sorted(sources_dir.rglob("*.yml"))

    # resolved_path -> [(file, line, yaml_key, en, context)]
    resolved_locations = defaultdict(list)
    # en_text -> [(resolved_path, yaml_key, file, line, context)]
    en_exact = defaultdict(list)
    # normalized_en -> [(resolved_path, yaml_key, file, line, en_original, context)]
    en_normalized = defaultdict(list)

    for yml_file in yml_files:
        namespace, key_prefix = resolve_namespace(yml_file, sources_dir)
        rel_path = str(yml_file)
        entries = parse_yaml_keys(yml_file)

        for entry in entries:
            yaml_key = entry["key"]
            en = entry["en"]
            ctx = entry["context"]
            line = entry["line"]
            resolved = resolve_key(yaml_key, namespace, key_prefix)

            resolved_locations[resolved].append({
                "file": rel_path,
                "line": line,
                "yaml_key": yaml_key,
                "en": en,
                "context": ctx,
            })

            if en:
                en_exact[en].append({
                    "resolved_path": resolved,
                    "yaml_key": yaml_key,
                    "file": rel_path,
                    "line": line,
                    "context": ctx,
                })

                norm = normalize(en)
                if norm:
                    en_normalized[norm].append({
                        "resolved_path": resolved,
                        "yaml_key": yaml_key,
                        "file": rel_path,
                        "line": line,
                        "en": en,
                        "context": ctx,
                    })

    # 1. True duplicate resolved paths (same JSON key from multiple source files)
    duplicate_paths = {
        k: v for k, v in resolved_locations.items() if len(v) > 1
    }

    # 2. Exact duplicate English values (different resolved paths, same en text)
    GENERIC_THRESHOLD = 2
    duplicate_en_exact = {}
    for en_text, locations in en_exact.items():
        if len(locations) > 1 and len(en_text) > GENERIC_THRESHOLD:
            unique_paths = set(loc["resolved_path"] for loc in locations)
            if len(unique_paths) > 1:
                duplicate_en_exact[en_text] = locations

    # 3. Near-duplicate English values
    near_duplicates = {}
    for norm, locations in en_normalized.items():
        if len(locations) > 1 and len(norm) > 3:
            unique_paths = set(loc["resolved_path"] for loc in locations)
            unique_en = set(loc["en"] for loc in locations)
            if len(unique_paths) > 1 and len(unique_en) > 1:
                near_duplicates[norm] = locations

    # 4. Consolidatable: duplicate en values eligible for common.yml
    consolidatable = {}
    if consolidatable_mode:
        for en_text, locations in en_exact.items():
            unique_paths = set(loc["resolved_path"] for loc in locations)
            if len(unique_paths) >= 3 and len(en_text) <= 30 and len(en_text) > 2:
                # Exclude if already all in common
                non_common = [loc for loc in locations if not loc["resolved_path"].startswith("common.")]
                if non_common:
                    consolidatable[en_text] = locations

    return {
        "duplicate_paths": duplicate_paths,
        "duplicate_en_exact": duplicate_en_exact,
        "near_duplicates": near_duplicates,
        "consolidatable": consolidatable,
        "stats": {
            "total_files": len(yml_files),
            "total_entries": sum(len(v) for v in resolved_locations.values()),
            "unique_resolved_paths": len(resolved_locations),
        },
    }


def print_report(results: dict, summary_only: bool = False, consolidatable_mode: bool = False):
    """Print a human-readable report."""
    stats = results["stats"]
    dup_paths = results["duplicate_paths"]
    dup_en = results["duplicate_en_exact"]
    near_dupes = results["near_duplicates"]

    print("=" * 70)
    print("REDUNDANT TRANSLATION REPORT (namespace-aware)")
    print("=" * 70)
    print(f"\nScanned: {stats['total_files']} YAML files, "
          f"{stats['unique_resolved_paths']} unique resolved paths, "
          f"{stats['total_entries']} total entries")
    print()

    # Section 1: True duplicate resolved paths
    print(f"── 1. TRUE DUPLICATE PATHS (same JSON key from multiple files): {len(dup_paths)} found")
    if not summary_only and dup_paths:
        for path, locations in sorted(dup_paths.items()):
            en_values = set(loc["en"] for loc in locations)
            conflict = " ⚠ CONFLICT" if len(en_values) > 1 else ""
            print(f"\n  Path: {path}{conflict}")
            for loc in locations:
                print(f"    {loc['file']}:{loc['line']}  yaml_key: {loc['yaml_key']}  en: \"{loc['en']}\"")
    elif dup_paths:
        conflicts = sum(1 for v in dup_paths.values() if len(set(entry["en"] for entry in v)) > 1)
        print(f"   {conflicts} conflicts (different en values), {len(dup_paths) - conflicts} identical duplicates")
        print("   Run without --summary to see details.")
    else:
        print("   None found.")
    print()

    # Section 2: Exact duplicate English values
    print(f"── 2. DUPLICATE ENGLISH VALUES (different paths, same en text): {len(dup_en)} found")
    if not summary_only and dup_en:
        for en_text, locations in sorted(dup_en.items(), key=lambda x: (-len(x[1]), x[0])):
            print(f"\n  en: \"{en_text}\"  ({len(locations)} occurrences)")
            for loc in locations:
                print(f"    {loc['resolved_path']}  [{loc['file']}:{loc['line']}]")
    elif dup_en:
        print("   Run without --summary to see details.")
    else:
        print("   None found.")
    print()

    # Section 3: Near-duplicates
    print(f"── 3. NEAR-DUPLICATE ENGLISH VALUES (case/punctuation diffs): {len(near_dupes)} found")
    if not summary_only and near_dupes:
        for norm, locations in sorted(near_dupes.items(), key=lambda x: (-len(x[1]), x[0])):
            print(f"\n  Normalized: \"{norm}\"  ({len(locations)} variants)")
            for loc in locations:
                print(f"    {loc['resolved_path']}  en: \"{loc['en']}\"  [{loc['file']}:{loc['line']}]")
    elif near_dupes:
        print("   Run without --summary to see details.")
    else:
        print("   None found.")
    print()

    # Section 4: Consolidatable (if requested)
    if consolidatable_mode:
        consol = results.get("consolidatable", {})
        print(f"── 4. CONSOLIDATABLE TO common.yml (≥3 occurrences, ≤30 chars): {len(consol)} found")
        if not summary_only and consol:
            for en_text, locations in sorted(consol.items(), key=lambda x: (-len(x[1]), x[0])):
                print(f"\n  en: \"{en_text}\"  ({len(locations)} occurrences)")
                for loc in locations:
                    print(f"    {loc['resolved_path']}  [{loc['file']}:{loc['line']}]")
        print()

    # Summary
    total_issues = len(dup_paths) + len(dup_en) + len(near_dupes)
    print("=" * 70)
    print(f"TOTAL: {total_issues} redundancy groups found")
    if dup_paths:
        conflicts = sum(1 for v in dup_paths.values() if len(set(entry["en"] for entry in v)) > 1)
        print(f"  ⚠  {len(dup_paths)} duplicate paths ({conflicts} conflicts, {len(dup_paths) - conflicts} identical)")
    if dup_en:
        print(f"  📋 {len(dup_en)} shared English values — consider consolidating into common keys")
    if near_dupes:
        print(f"  🔍 {len(near_dupes)} near-duplicates — review for possible unification")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Find redundant translations in i18n YAML files")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--summary", action="store_true", help="Show counts only")
    parser.add_argument("--consolidatable", action="store_true",
                        help="Also show keys eligible for common.yml consolidation")
    args = parser.parse_args()

    if not SOURCES_DIR.exists():
        print(f"Error: Sources directory not found: {SOURCES_DIR}", file=sys.stderr)
        sys.exit(1)

    results = find_redundancies(SOURCES_DIR, consolidatable_mode=args.consolidatable)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_report(results, summary_only=args.summary, consolidatable_mode=args.consolidatable)


if __name__ == "__main__":
    main()
