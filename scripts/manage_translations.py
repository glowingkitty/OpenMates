#!/usr/bin/env python3
"""
manage_translations.py — Translation management tool for OpenMates i18n YAML files.

Source files live in: frontend/packages/ui/src/i18n/sources/
Language list from:   frontend/packages/ui/src/i18n/languages.json

Commands:
  show-next-missing   Find translation keys with missing values (LLM-friendly output)
  overview            Statistics dashboard: languages, counts, completeness, files
  validate            Structural integrity check (nesting, missing fields, duplicates)
  export-missing      Export missing translations as pasteable YAML/JSON/CSV
  find-key            Search for a key by name, English text, or context string

Usage examples:
  python scripts/manage_translations.py show-next-missing
  python scripts/manage_translations.py show-next-missing --lang sv --count 10
  python scripts/manage_translations.py show-next-missing --file "settings/*.yml"
  python scripts/manage_translations.py overview
  python scripts/manage_translations.py overview --files
  python scripts/manage_translations.py overview --lang sv
  python scripts/manage_translations.py validate
  python scripts/manage_translations.py export-missing --lang sv
  python scripts/manage_translations.py export-missing --lang sv --format json --output /tmp/sv_missing.json
  python scripts/manage_translations.py find-key "toggle menu"
  python scripts/manage_translations.py find-key "open_settings"
"""

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
I18N_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n"
SOURCES_DIR = I18N_DIR / "sources"
LANGUAGES_JSON = I18N_DIR / "languages.json"

# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------

RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Core data loading
# ---------------------------------------------------------------------------


def load_languages() -> list[dict]:
    """Load supported language definitions from languages.json (single source of truth)."""
    if not LANGUAGES_JSON.exists():
        print(f"{RED}Error: languages.json not found at {LANGUAGES_JSON}{RESET}")
        sys.exit(1)
    with open(LANGUAGES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return data["languages"]


def load_yaml_file(filepath: Path) -> dict:
    """Load a YAML file. Returns empty dict on parse error (error is printed)."""
    try:
        with open(filepath, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print(f"{RED}YAML parse error in {filepath}: {e}{RESET}", file=sys.stderr)
        return {}


def get_relative_path(filepath: Path) -> str:
    """Return filepath relative to REPO_ROOT for display, falling back to absolute."""
    try:
        return str(filepath.relative_to(REPO_ROOT))
    except ValueError:
        return str(filepath)


def get_all_source_files(file_filter: Optional[str] = None) -> list[Path]:
    """
    Return all .yml files under SOURCES_DIR, sorted by (directory, filename).

    If file_filter is provided (e.g. "header.yml" or "settings/*.yml"), only
    files whose path relative to SOURCES_DIR matches that glob pattern are
    returned.
    """
    all_files = sorted(SOURCES_DIR.rglob("*.yml"))

    if file_filter:
        # Normalise separator so globs work on all platforms
        filtered = []
        for f in all_files:
            rel = str(f.relative_to(SOURCES_DIR))
            if fnmatch.fnmatch(rel, file_filter) or fnmatch.fnmatch(f.name, file_filter):
                filtered.append(f)
        return filtered

    return all_files


def is_missing(value) -> bool:
    """Return True if a translation value counts as missing (absent, empty, or None)."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def is_valid_entry(entry) -> bool:
    """Return True if entry looks like a translation entry (dict with 'en' key)."""
    return isinstance(entry, dict) and "en" in entry


# ---------------------------------------------------------------------------
# Build in-memory index
# ---------------------------------------------------------------------------


def build_index(file_filter: Optional[str] = None) -> list[dict]:
    """
    Scan all source YAML files and return a flat list of entry records.

    Each record:
      {
        "file":     Path (absolute),
        "rel_path": str (relative to REPO_ROOT),
        "src_rel":  str (relative to SOURCES_DIR, e.g. "settings/main.yml"),
        "line":     int (1-based line number of the key in the file),
        "key":      str,
        "entry":    dict (the raw YAML entry with context, en, de, …),
      }

    Line numbers are computed by scanning the raw file text for the key
    as a YAML mapping key (i.e. "^key_name:" or "^'key_name':").
    """
    files = get_all_source_files(file_filter)
    records = []

    for filepath in files:
        raw_text = ""
        try:
            with open(filepath, encoding="utf-8") as f:
                raw_text = f.read()
        except OSError as e:
            print(f"{RED}Cannot read {filepath}: {e}{RESET}", file=sys.stderr)
            continue

        data = {}
        try:
            data = yaml.safe_load(raw_text) or {}
        except yaml.YAMLError as e:
            print(f"{RED}YAML parse error in {filepath}: {e}{RESET}", file=sys.stderr)
            continue

        # Build a line-number lookup: key_name → 1-based line number
        line_map: dict[str, int] = {}
        lines = raw_text.splitlines()
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Match bare key: "key_name:" or quoted "'key.name':"
            if ":" in stripped and not stripped.startswith("#"):
                candidate = stripped.split(":")[0].strip().strip("'\"")
                if candidate and " " not in candidate and candidate not in line_map:
                    line_map[candidate] = lineno

        rel_path = get_relative_path(filepath)
        src_rel = str(filepath.relative_to(SOURCES_DIR))

        for key, entry in data.items():
            if not is_valid_entry(entry):
                # Could be a structural issue — captured by validate command
                continue
            records.append(
                {
                    "file": filepath,
                    "rel_path": rel_path,
                    "src_rel": src_rel,
                    "line": line_map.get(str(key), 0),
                    "key": str(key),
                    "entry": entry,
                }
            )

    return records


# ---------------------------------------------------------------------------
# Command: show-next-missing
# ---------------------------------------------------------------------------


def cmd_show_next_missing(args):
    """
    Print the next N missing translation entries, grouped by file then by language.

    If --lang is given: show missing entries for that one language only.
    If not:            iterate file-by-file across all languages.

    Output is designed to be LLM-friendly: full file path, exact line number,
    context description, and English original text.
    """
    languages = load_languages()
    all_lang_codes = [lang["code"] for lang in languages]

    # Resolve which languages to check
    if args.lang:
        # Could be a new language not in languages.json — allow it
        target_langs = [args.lang]
        if args.lang not in all_lang_codes:
            print(
                f"{YELLOW}Note: '{args.lang}' is not in languages.json — "
                f"checking it as a new/unsupported language.{RESET}\n"
            )
    else:
        # All languages except English (English is always the source)
        target_langs = [c for c in all_lang_codes if c != "en"]

    records = build_index(getattr(args, "file", None))

    if not records:
        print(f"{YELLOW}No translation files found.{RESET}")
        return

    count_limit = args.count
    found = 0

    if args.lang:
        # Single language: iterate file by file, show missing for that lang
        lang_code = args.lang
        current_file = None

        for record in records:
            if found >= count_limit:
                break

            entry = record["entry"]
            value = entry.get(lang_code)

            if not is_missing(value):
                continue

            if record["rel_path"] != current_file:
                current_file = record["rel_path"]
                print(f"\n{BOLD}{BLUE}{current_file}{RESET}")

            _print_missing_entry(record, lang_code, [lang_code])
            found += 1
    else:
        # All languages: go file by file, collect all missing (lang, record) pairs
        # Emit up to count_limit entries total, ordered by file then language order
        current_file = None

        for record in records:
            if found >= count_limit:
                break

            entry = record["entry"]
            missing_langs = [lc for lc in target_langs if is_missing(entry.get(lc))]

            if not missing_langs:
                continue

            if record["rel_path"] != current_file:
                current_file = record["rel_path"]
                print(f"\n{BOLD}{BLUE}{current_file}{RESET}")

            _print_missing_entry(record, missing_langs[0], missing_langs)
            found += 1

    if found == 0:
        if args.lang:
            print(f"{GREEN}No missing translations for '{args.lang}'. All complete!{RESET}")
        else:
            print(f"{GREEN}No missing translations found. Everything is complete!{RESET}")
    else:
        remaining = _count_total_missing(records, target_langs) - found
        if remaining > 0:
            print(
                f"\n{DIM}… and {remaining:,} more missing translation(s) not shown. "
                f"Use --count to see more.{RESET}"
            )


def _print_missing_entry(record: dict, primary_lang: str, all_missing_langs: list[str]):
    """Print a single missing-translation entry in LLM-friendly format."""
    entry = record["entry"]
    en_text = entry.get("en", "")
    context = entry.get("context", "(no context)")
    line_str = f":{record['line']}" if record["line"] else ""

    print(f"  {BOLD}{record['rel_path']}{line_str}{RESET}")
    print(f"  Key:     {CYAN}{record['key']}{RESET}")
    print(f"  Context: {context}")
    print(f"  English: {en_text}")

    if len(all_missing_langs) == 1:
        print(f"  Missing: {YELLOW}{primary_lang}{RESET}")
    else:
        others = all_missing_langs[1:]
        others_str = ", ".join(others[:5])
        if len(others) > 5:
            others_str += f" (+{len(others) - 5} more)"
        print(
            f"  Missing: {YELLOW}{primary_lang}{RESET}"
            f"{DIM} (and {len(others)} other(s): {others_str}){RESET}"
        )
    print()


def _count_total_missing(records: list[dict], target_langs: list[str]) -> int:
    """Count total number of (record, lang) missing pairs."""
    total = 0
    for record in records:
        entry = record["entry"]
        for lc in target_langs:
            if is_missing(entry.get(lc)):
                total += 1
                break  # Count each record once (we show file-by-file, 1 per record)
    return total


# ---------------------------------------------------------------------------
# Command: overview
# ---------------------------------------------------------------------------


def cmd_overview(args):
    """
    Print a statistics dashboard:
    - Total supported languages with completion percentages
    - Total key count
    - Source file count (and optionally full paths)
    - Per-language breakdown (optional via --lang)
    """
    languages = load_languages()

    target_lang = getattr(args, "lang", None)
    show_files = getattr(args, "files", False)

    records = build_index()
    source_files = get_all_source_files()
    total_keys = len(records)
    total_files = len(source_files)

    # Compute per-language stats
    lang_stats = {}
    for lang in languages:
        code = lang["code"]
        if code == "en":
            # English is always the source — count non-missing en values
            present = sum(1 for r in records if not is_missing(r["entry"].get("en")))
            lang_stats[code] = {"present": present, "missing": total_keys - present}
        else:
            missing = sum(1 for r in records if is_missing(r["entry"].get(code)))
            lang_stats[code] = {"present": total_keys - missing, "missing": missing}

    print(f"\n{BOLD}Translation Overview{RESET}")
    print("=" * 60)

    if target_lang:
        # Detailed view for one language
        lang_info = next((lang for lang in languages if lang["code"] == target_lang), None)
        if not lang_info:
            print(f"{YELLOW}Language '{target_lang}' not found in languages.json.{RESET}")
            return
        stats = lang_stats[target_lang]
        pct = (stats["present"] / total_keys * 100) if total_keys else 0
        print(f"\n{BOLD}{lang_info['name']} ({target_lang}){RESET}")
        print(f"  Total keys:  {total_keys:,}")
        print(f"  Translated:  {stats['present']:,}  ({pct:.1f}%)")
        print(f"  Missing:     {RED}{stats['missing']:,}{RESET}")
        print()
    else:
        # Full language table
        print(f"\n{BOLD}Languages ({len(languages)} supported):{RESET}\n")

        # Header
        print(f"  {'Code':<5} {'Name':<20} {'Translated':>10} {'Missing':>8}  Completion")
        print(f"  {'─'*4:<5} {'─'*19:<20} {'─'*10:>10} {'─'*8:>8}  {'─'*30}")

        for lang in languages:
            code = lang["code"]
            stats = lang_stats[code]
            pct = (stats["present"] / total_keys * 100) if total_keys else 0
            bar_len = int(pct / 100 * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)

            if pct >= 99.9:
                pct_color = GREEN
                bar_color = GREEN
                suffix = " ✓"
            elif pct >= 80:
                pct_color = YELLOW
                bar_color = YELLOW
                suffix = ""
            else:
                pct_color = RED
                bar_color = RED
                suffix = ""

            missing_str = f"{stats['missing']:,}" if stats["missing"] > 0 else ""
            missing_display = f"{RED}{missing_str}{RESET}" if stats["missing"] > 0 else f"{DIM}—{RESET}"

            print(
                f"  {code:<5} {lang['name']:<20} "
                f"{stats['present']:>10,} {missing_display:>18}  "
                f"{bar_color}{bar}{RESET} {pct_color}{pct:5.1f}%{RESET}{suffix}"
            )

    # Summary
    print(f"\n{BOLD}Source files:{RESET} {total_files} YAML files")
    print(f"{BOLD}Total keys:{RESET}   {total_keys:,}")

    if show_files:
        print(f"\n{BOLD}All source files:{RESET}")
        for f in source_files:
            print(f"  {get_relative_path(f)}")

    print()


# ---------------------------------------------------------------------------
# Command: validate
# ---------------------------------------------------------------------------


def cmd_validate(_args):
    """
    Check structural integrity of all source YAML files.

    Detects:
    - YAML parse errors
    - Accidentally nested YAML (entries whose value is a dict without 'en')
    - Missing required fields: context, en, verified_by_human
    - Entries where 'en' is empty/missing
    - Duplicate keys within the same file
    """
    files = get_all_source_files()
    total_issues = 0
    files_with_issues = 0

    print(f"\n{BOLD}Validating {len(files)} translation files…{RESET}\n")

    for filepath in files:
        file_issues = []
        rel_path = get_relative_path(filepath)

        # 1. Parse YAML
        try:
            with open(filepath, encoding="utf-8") as f:
                raw_text = f.read()
        except OSError as e:
            file_issues.append(f"Cannot read file: {e}")
            _print_file_issues(rel_path, file_issues)
            total_issues += len(file_issues)
            files_with_issues += 1
            continue

        try:
            data = yaml.safe_load(raw_text) or {}
        except yaml.YAMLError as e:
            file_issues.append(f"YAML parse error: {e}")
            _print_file_issues(rel_path, file_issues)
            total_issues += len(file_issues)
            files_with_issues += 1
            continue

        # 2. Build line number map
        lines = raw_text.splitlines()
        line_map: dict[str, int] = {}
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith("#"):
                candidate = stripped.split(":")[0].strip().strip("'\"")
                if candidate and " " not in candidate and candidate not in line_map:
                    line_map[candidate] = lineno

        # 3. Duplicate key detection (YAML silently overrides — check via raw text).
        #    Only check TOP-LEVEL keys: lines that start without any leading whitespace.
        seen_keys: dict[str, int] = {}
        for lineno, line in enumerate(lines, start=1):
            # Skip indented lines (sub-keys like context:, en:, de:) and comments
            if not line or line[0] == " " or line[0] == "\t" or line[0] == "#":
                continue
            stripped = line.strip()
            if ":" not in stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            candidate = stripped.split(":")[0].strip().strip("'\"")
            if candidate and " " not in candidate:
                if candidate in seen_keys:
                    file_issues.append(
                        f"Line {lineno}: Duplicate top-level key '{candidate}' "
                        f"(first at line {seen_keys[candidate]})"
                    )
                else:
                    seen_keys[candidate] = lineno

        # 4. Per-entry checks
        for key, entry in data.items():
            line_ref = f"line {line_map.get(str(key), '?')}"

            if not isinstance(entry, dict):
                file_issues.append(
                    f"{line_ref}: Key '{key}' has a scalar value — "
                    f"should be a dict with context, en, etc."
                )
                continue

            # Nested YAML check: if entry has no 'en' but has sub-dicts, it's likely nested
            has_en = "en" in entry
            sub_dicts = {k: v for k, v in entry.items() if isinstance(v, dict)}
            if not has_en and sub_dicts:
                file_issues.append(
                    f"{line_ref}: Key '{key}' appears to be NESTED YAML "
                    f"(sub-keys: {list(sub_dicts.keys())[:3]}). "
                    f"Use flat dot-notation keys instead."
                )
                continue

            # Missing required fields
            if "context" not in entry:
                file_issues.append(f"{line_ref}: Key '{key}' is missing 'context' field")
            if "en" not in entry:
                file_issues.append(f"{line_ref}: Key '{key}' is missing 'en' field")
            elif is_missing(entry.get("en")):
                file_issues.append(f"{line_ref}: Key '{key}' has empty 'en' (English source must not be empty)")
            if "verified_by_human" not in entry:
                file_issues.append(f"{line_ref}: Key '{key}' is missing 'verified_by_human' field")

        if file_issues:
            _print_file_issues(rel_path, file_issues)
            total_issues += len(file_issues)
            files_with_issues += 1

    if total_issues == 0:
        print(f"{GREEN}✓ All {len(files)} files passed validation — no issues found.{RESET}\n")
    else:
        print(
            f"\n{RED}{BOLD}Found {total_issues} issue(s) across "
            f"{files_with_issues} file(s).{RESET}\n"
        )


def _print_file_issues(rel_path: str, issues: list[str]):
    """Print issues for one file."""
    print(f"{BOLD}{YELLOW}{rel_path}{RESET}")
    for issue in issues:
        print(f"  {RED}✗{RESET} {issue}")
    print()


# ---------------------------------------------------------------------------
# Command: export-missing
# ---------------------------------------------------------------------------


def cmd_export_missing(args):
    """
    Export all missing translation entries for a given language as YAML, JSON, or CSV.

    The YAML format is pasteable directly into the source files.
    """
    languages = load_languages()
    all_lang_codes = [lang["code"] for lang in languages]
    lang_code = args.lang

    if not lang_code:
        print(f"{RED}Error: --lang is required for export-missing.{RESET}")
        sys.exit(1)

    if lang_code not in all_lang_codes:
        print(
            f"{YELLOW}Note: '{lang_code}' is not in languages.json — "
            f"treating as new language.{RESET}\n"
        )

    records = build_index(getattr(args, "file", None))
    missing_records = [r for r in records if is_missing(r["entry"].get(lang_code))]

    if not missing_records:
        print(f"{GREEN}No missing translations for '{lang_code}'. Nothing to export.{RESET}")
        return

    fmt = getattr(args, "format", "yaml")
    output_path = getattr(args, "output", None)

    if fmt == "yaml":
        content = _export_yaml(missing_records, lang_code)
    elif fmt == "json":
        content = _export_json(missing_records, lang_code)
    elif fmt == "csv":
        content = _export_csv(missing_records, lang_code)
    else:
        print(f"{RED}Unknown format: {fmt}. Use yaml, json, or csv.{RESET}")
        sys.exit(1)

    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
        print(f"{GREEN}Exported {len(missing_records)} missing '{lang_code}' "
              f"translations to {output_path}{RESET}")
    else:
        print(content)
        print(
            f"\n{DIM}# {len(missing_records)} missing '{lang_code}' translations above.{RESET}"
        )


def _export_yaml(records: list[dict], lang_code: str) -> str:
    """
    Generate pasteable YAML with one entry per missing key.

    Groups by source file with a comment header so the LLM knows which file to edit.
    Each entry shows context, en, and an empty placeholder for the target language.
    """
    lines = [f"# Missing '{lang_code}' translations — {len(records)} keys\n"]
    current_src = None

    for record in records:
        if record["src_rel"] != current_src:
            current_src = record["src_rel"]
            full_path = get_relative_path(record["file"])
            lines.append(f"\n# ── {full_path} ──")

        entry = record["entry"]
        context = entry.get("context", "")
        en_text = entry.get("en", "")
        key = record["key"]
        line_num = record["line"]

        lines.append(f"\n{key}:  # line {line_num}")
        lines.append(f"  context: {context}")
        lines.append(f"  en: {_yaml_scalar(en_text)}")
        lines.append(f"  {lang_code}: \"\"  # ← translate here")

    return "\n".join(lines) + "\n"


def _export_json(records: list[dict], lang_code: str) -> str:
    """Generate a JSON array of missing entries — suitable for scripted translation."""
    output = []
    for record in records:
        entry = record["entry"]
        output.append(
            {
                "file": get_relative_path(record["file"]),
                "line": record["line"],
                "key": record["key"],
                "context": entry.get("context", ""),
                "en": entry.get("en", ""),
                lang_code: "",
            }
        )
    return json.dumps(output, ensure_ascii=False, indent=2)


def _export_csv(records: list[dict], lang_code: str) -> str:
    """Generate a CSV of missing entries."""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["file", "line", "key", "context", "en", lang_code])
    for record in records:
        entry = record["entry"]
        writer.writerow(
            [
                get_relative_path(record["file"]),
                record["line"],
                record["key"],
                entry.get("context", ""),
                entry.get("en", ""),
                "",
            ]
        )
    return buf.getvalue()


def _yaml_scalar(text: str) -> str:
    """Return a YAML-safe scalar representation of a string."""
    if not text:
        return '""'
    if any(c in text for c in ('"', "'", ":", "{", "}", "[", "]", "#", "&", "*", "!", "|", ">", "?", "-")):
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


# ---------------------------------------------------------------------------
# Command: find-key
# ---------------------------------------------------------------------------


def cmd_find_key(args):
    """
    Search for translation keys by key name, English text, or context string.

    Performs case-insensitive substring matching across all three fields.
    """
    query = args.query.lower()
    languages = load_languages()
    all_lang_codes = [lang["code"] for lang in languages]

    records = build_index()
    matches = []

    for record in records:
        entry = record["entry"]
        key_match = query in record["key"].lower()
        en_match = query in str(entry.get("en", "")).lower()
        ctx_match = query in str(entry.get("context", "")).lower()

        if key_match or en_match or ctx_match:
            matches.append((record, key_match, en_match, ctx_match))

    if not matches:
        print(f"{YELLOW}No keys found matching '{args.query}'.{RESET}")
        return

    print(f"\n{BOLD}Found {len(matches)} match(es) for '{args.query}':{RESET}\n")

    for record, key_match, en_match, ctx_match in matches:
        entry = record["entry"]
        line_str = f":{record['line']}" if record["line"] else ""

        # Match type indicator
        match_types = []
        if key_match:
            match_types.append("key")
        if en_match:
            match_types.append("english")
        if ctx_match:
            match_types.append("context")

        print(f"{BOLD}{BLUE}{record['rel_path']}{line_str}{RESET}  {DIM}[{', '.join(match_types)}]{RESET}")
        print(f"  Key:     {CYAN}{record['key']}{RESET}")
        print(f"  Context: {entry.get('context', '(no context)')}")
        print(f"  English: {entry.get('en', '')}")

        # Show per-language completion
        completed = []
        missing = []
        for code in all_lang_codes:
            if code == "en":
                continue
            val = entry.get(code)
            if is_missing(val):
                missing.append(code)
            else:
                completed.append(code)

        total_non_en = len(all_lang_codes) - 1
        pct = (len(completed) / total_non_en * 100) if total_non_en else 0

        print(f"  Completion: {GREEN}{len(completed)}{RESET}/{total_non_en} languages ({pct:.0f}%)")

        if missing:
            missing_str = ", ".join(missing[:10])
            if len(missing) > 10:
                missing_str += f" (+{len(missing) - 10} more)"
            print(f"  Missing:    {YELLOW}{missing_str}{RESET}")

        print()


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_translations.py",
        description="OpenMates translation management tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  show-next-missing   Find keys with missing translations (LLM-friendly output)
  overview            Statistics dashboard
  validate            Structural integrity checks
  export-missing      Export missing translations as YAML/JSON/CSV
  find-key            Search for a key by name, English text, or context

Examples:
  python scripts/manage_translations.py show-next-missing
  python scripts/manage_translations.py show-next-missing --lang sv --count 20
  python scripts/manage_translations.py show-next-missing --file "settings/*.yml"
  python scripts/manage_translations.py overview
  python scripts/manage_translations.py overview --files --lang sv
  python scripts/manage_translations.py validate
  python scripts/manage_translations.py export-missing --lang sv
  python scripts/manage_translations.py export-missing --lang sv --format json
  python scripts/manage_translations.py find-key "toggle menu"
""",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ── show-next-missing ──
    p_missing = subparsers.add_parser(
        "show-next-missing",
        help="Find the next N missing translations (LLM-friendly output)",
    )
    p_missing.add_argument(
        "--lang",
        metavar="CODE",
        default=None,
        help="Language code to check (default: all languages)",
    )
    p_missing.add_argument(
        "--count",
        metavar="N",
        type=int,
        default=5,
        help="Number of missing entries to show (default: 5)",
    )
    p_missing.add_argument(
        "--file",
        metavar="GLOB",
        default=None,
        help='Filter to specific file(s), e.g. "header.yml" or "settings/*.yml"',
    )

    # ── overview ──
    p_overview = subparsers.add_parser(
        "overview",
        help="Show statistics: languages, translation counts, file list",
    )
    p_overview.add_argument(
        "--files",
        action="store_true",
        help="Include full paths of all source files",
    )
    p_overview.add_argument(
        "--lang",
        metavar="CODE",
        default=None,
        help="Show detailed breakdown for one language",
    )

    # ── validate ──
    subparsers.add_parser(
        "validate",
        help="Check structural integrity of all source YAML files",
    )

    # ── export-missing ──
    p_export = subparsers.add_parser(
        "export-missing",
        help="Export missing translations as YAML, JSON, or CSV",
    )
    p_export.add_argument(
        "--lang",
        metavar="CODE",
        required=True,
        help="Language code to export missing translations for",
    )
    p_export.add_argument(
        "--format",
        choices=["yaml", "json", "csv"],
        default="yaml",
        help="Output format (default: yaml)",
    )
    p_export.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write output to file instead of stdout",
    )
    p_export.add_argument(
        "--file",
        metavar="GLOB",
        default=None,
        help='Filter to specific file(s), e.g. "settings/*.yml"',
    )

    # ── find-key ──
    p_find = subparsers.add_parser(
        "find-key",
        help="Search for a key by name, English text, or context string",
    )
    p_find.add_argument(
        "query",
        help="Search query (case-insensitive substring match)",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    if not SOURCES_DIR.exists():
        print(
            f"{RED}Error: sources directory not found at {SOURCES_DIR}\n"
            f"Run this script from the repo root or scripts/ directory.{RESET}"
        )
        sys.exit(1)

    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "show-next-missing": cmd_show_next_missing,
        "overview": cmd_overview,
        "validate": cmd_validate,
        "export-missing": cmd_export_missing,
        "find-key": cmd_find_key,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
