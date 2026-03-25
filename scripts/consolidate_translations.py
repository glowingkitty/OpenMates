#!/usr/bin/env python3
"""
Consolidate redundant translations into common.yml.

Finds duplicate English values across YAML translation files and migrates them
to common.yml, updating all $text() references in Svelte/TS components.

Usage:
  # Preview all consolidatable keys
  python3 scripts/consolidate_translations.py --dry-run

  # Preview a specific English value
  python3 scripts/consolidate_translations.py --dry-run --value "Cancel"

  # Apply consolidation for a specific value
  python3 scripts/consolidate_translations.py --apply --value "Cancel"

  # Apply all consolidatable values at once
  python3 scripts/consolidate_translations.py --apply --all

  # Show only the consolidation plan as JSON
  python3 scripts/consolidate_translations.py --plan --json
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

SOURCES_DIR = Path("frontend/packages/ui/src/i18n/sources")
COMMON_YML = SOURCES_DIR / "common.yml"
FRONTEND_DIR = Path("frontend")

# Supported languages (order matters for YAML output)
LANGUAGES = [
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
    "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv", "he"
]

# Minimum occurrences to consider for consolidation
MIN_OCCURRENCES = 3

# Maximum English text length to consider (longer strings are context-specific)
MAX_EN_LENGTH = 30

# Keys that should NOT be consolidated (context-specific even if short)
SKIP_KEYS_CONTAINING = {
    "systemprompt", "follow_up", "how_to_use", "description",
    "example", "placeholder", "tooltip", "hint",
}

# English values that should NOT be consolidated (not generic UI strings)
SKIP_EN_VALUES = {
    "|", "||", "---", "—", "•",  # Formatting characters
    "1 year & older", "90 days & older",  # Domain-specific retention settings
    "Career insights",  # Feature-specific
    "Log In from Another Device",  # Feature-specific, too long
    "On Low Balance",  # Feature-specific notification setting
    "Settings & Memories",  # Feature-specific section name
    "Generate Draft",  # Feature-specific action
    "Cancel Reminder",  # Feature-specific action
    "Hide sensitive data", "Show sensitive data",  # Feature-specific PII toggles
    "Verify Your Identity",  # Feature-specific auth dialog
    "Set Reminder", "Set reminder",  # Feature-specific (case variants too)
    "Copied to clipboard",  # Feedback message, not a button label
    "or",  # Already in common as nested key not_found.or_separator, skip
}

# Manual key name overrides for common keys (en_text -> common_key_name)
COMMON_KEY_NAMES = {
    "Cancel": "cancel",
    "Close": "close",
    "Copy": "copy",
    "Copied": "copied",
    "Copied!": "copied_excl",
    "Continue": "continue",
    "Done": "done",
    "Delete": "delete",
    "Search": "search",
    "Processing...": "processing",
    "Loading...": "loading",
    "Email": "email",
    "credits": "credits",
    "Download": "download",
    "Chat": "chat",
    "Chats": "chats",
    "Docs": "docs",
    "Password": "password",
    "Pricing": "pricing",
    "Retry": "retry",
    "Share": "share",
    "Summary": "summary",
    "Today": "today",
    "Apps": "apps",
    "Ask": "ask",
    "Buy Credits": "buy_credits",
    "Contact": "contact",
    "Date": "date",
    "Discord": "discord",
    "Duration": "duration",
    "Generate": "generate",
    "Images": "images",
    "Just now": "just_now",
    "Monthly": "monthly",
    "New chat": "new_chat",
    "Privacy": "privacy",
    "Read": "read",
    "Save": "save",
    "Settings": "settings",
    "Settings & Memories": "settings_and_memories",
    "Upload failed": "upload_failed",
    "View": "view",
    "Add Entry": "add_entry",
    "Add Password": "add_password",
    "Audio": "audio",
    "Back": "back",
    "Cancel Reminder": "cancel_reminder",
    # "Career insights" — too context-specific, skip
    "Change Password": "change_password",
    "Copied to clipboard": "copied_to_clipboard",
    "Custom": "custom",
    "Details": "details",
    "Devices": "devices",
    "Disabled": "disabled",
    "Enabled": "enabled",
    "Generate Draft": "generate_draft",
    "Gift Cards": "gift_cards",
    "GitHub": "github",
    "Hide sensitive data": "hide_sensitive_data",
    "Imprint": "imprint",
    "Invoices": "invoices",
    "Language": "language",
    "Last Updated": "last_updated",
    "Legal": "legal",
    "Location": "location",
    "Log In from Another Device": "log_in_from_another_device",
    "Newsletter": "newsletter",
    "On Low Balance": "on_low_balance",
    "Other": "other",
    "PDF": "pdf",
    "Provider": "provider",
    "Recovery Key": "recovery_key",
    "Select all": "select_all",
    "Set Reminder": "set_reminder",
    "Set reminder": "set_reminder_lower",
    "Show less": "show_less",
    "Show sensitive data": "show_sensitive_data",
    "Skill": "skill",
    "Status": "status",
    "Stop": "stop",
    "Storage": "storage",
    "Terms and conditions": "terms_and_conditions",
    "Untitled chat": "untitled_chat",
    "Verify Your Identity": "verify_your_identity",
    "Yesterday": "yesterday",
    "or": "or_separator",
}


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
        # Subdirectory file: namespace = parent dir(s), prefix depends on filename
        namespace = parts[0]
        # Handle nested subdirs (e.g., settings/subsection/)
        for part in parts[1:-1]:
            namespace = f"{namespace}.{part}"

        filename = parts[-1]
        if filename == "main.yml":
            return namespace, ""
        else:
            return namespace, Path(filename).stem


def parse_yaml_full(filepath: Path) -> list[dict]:
    """
    Parse a flat-key YAML translation file.
    Returns list of {key, translations: {lang: text}, context, line} dicts.
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

            # Top-level key
            if not line[0].isspace() and ":" in stripped:
                if current_key:
                    entries.append(_build_entry(current_key, current_data, current_line))

                key_part = stripped.split(":", 1)[0].strip()
                current_key = key_part
                current_data = {}
                current_line = line_num

            # Sub-field
            elif line[0].isspace() and current_key and ":" in stripped:
                field_match = re.match(r"\s+(\w[\w_]*)\s*:\s*(.*)", stripped)
                if field_match:
                    field_name = field_match.group(1)
                    field_value = field_match.group(2).strip()
                    if (field_value.startswith('"') and field_value.endswith('"')) or \
                       (field_value.startswith("'") and field_value.endswith("'")):
                        field_value = field_value[1:-1]
                    current_data[field_name] = field_value

    if current_key:
        entries.append(_build_entry(current_key, current_data, current_line))

    return entries


def _build_entry(key: str, data: dict, line: int) -> dict:
    translations = {}
    for lang in LANGUAGES:
        if lang in data:
            translations[lang] = data[lang]
    return {
        "key": key,
        "translations": translations,
        "context": data.get("context", ""),
        "verified_by_human": data.get("verified_by_human", "[]"),
        "line": line,
    }


def resolve_key(yaml_key: str, key_prefix: str) -> str:
    """Apply the key prefix, matching build-translations.js logic."""
    if not key_prefix:
        return yaml_key
    if yaml_key == key_prefix:
        # Key matches filename — don't prefix
        return yaml_key
    return f"{key_prefix}.{yaml_key}"


def find_text_references(resolved_path: str) -> list[dict]:
    """
    Find all $text('resolved_path') references in Svelte/TS files.
    Returns list of {file, line, match} dicts.
    """
    refs = []
    # Search for $text('namespace.key') or $text("namespace.key")
    pattern = re.escape(resolved_path)

    try:
        result = subprocess.run(
            ["rg", "-n", "--no-heading",
             "--glob", "*.svelte", "--glob", "*.ts", "--glob", "*.js",
             f"\\$text\\(['\"]({pattern})['\"]", str(FRONTEND_DIR)],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            # Format: file:line:match
            parts = line.split(":", 2)
            if len(parts) >= 3:
                refs.append({
                    "file": parts[0],
                    "line_num": int(parts[1]),
                    "content": parts[2].strip(),
                })
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return refs


def find_consolidatable(sources_dir: Path, min_occurrences: int = MIN_OCCURRENCES,
                        max_en_length: int = MAX_EN_LENGTH) -> list[dict]:
    """
    Find all English values that appear in multiple resolved paths
    and are candidates for common.yml consolidation.
    """
    yml_files = sorted(sources_dir.rglob("*.yml"))

    # en_text -> [{resolved_path, yaml_key, file, line, namespace, key_prefix, translations, context}]
    en_to_locations = defaultdict(list)

    # Track what's already in common.yml
    common_keys = {}  # en_text -> yaml_key

    for yml_file in yml_files:
        namespace, key_prefix = resolve_namespace(yml_file, sources_dir)
        entries = parse_yaml_full(yml_file)
        rel_path = str(yml_file)

        for entry in entries:
            yaml_key = entry["key"]
            resolved = resolve_key(yaml_key, key_prefix)
            resolved_path = f"{namespace}.{resolved}"
            en = entry["translations"].get("en", "")

            if not en:
                continue

            loc = {
                "resolved_path": resolved_path,
                "yaml_key": yaml_key,
                "file": rel_path,
                "line": entry["line"],
                "namespace": namespace,
                "key_prefix": key_prefix,
                "translations": entry["translations"],
                "context": entry["context"],
                "verified_by_human": entry["verified_by_human"],
            }

            en_to_locations[en].append(loc)

            if yml_file == COMMON_YML:
                common_keys[en] = yaml_key

    # Filter to consolidatable groups
    consolidatable = []
    for en_text, locations in sorted(en_to_locations.items(), key=lambda x: (-len(x[1]), x[0])):
        # Must appear in multiple distinct resolved paths
        unique_paths = set(loc["resolved_path"] for loc in locations)
        if len(unique_paths) < min_occurrences:
            continue

        # Must be short enough to be generic
        if len(en_text) > max_en_length:
            continue

        # Skip non-UI values
        if en_text in SKIP_EN_VALUES:
            continue

        # Skip context-specific keys
        if any(skip in en_text.lower() for skip in {"http", "www", "openmates"}):
            continue

        # Skip values that start with quotes or special chars (likely content, not UI)
        if en_text.startswith(('"', "'", "(")):
            continue

        # Check if any location key contains skip patterns
        all_contextual = all(
            any(skip in loc["yaml_key"].lower() for skip in SKIP_KEYS_CONTAINING)
            for loc in locations
        )
        if all_contextual:
            continue

        # Filter OUT locations that are already in common.yml
        common_locs = [loc for loc in locations if loc["namespace"] == "common"]
        other_locs = [loc for loc in locations if loc["namespace"] != "common"]

        if not other_locs:
            continue  # Already fully consolidated

        # Determine the common key name
        if common_locs:
            common_key = common_locs[0]["yaml_key"]
            already_in_common = True
        else:
            # Use manual override if available, otherwise derive from en text
            if en_text in COMMON_KEY_NAMES:
                common_key = COMMON_KEY_NAMES[en_text]
            else:
                # Derive from English text: lowercase, replace spaces with underscores
                common_key = re.sub(r"[^a-z0-9]+", "_", en_text.lower()).strip("_")
                if not common_key:
                    continue
            already_in_common = False

        # Get the best translations (prefer locations with most languages filled)
        best_translations = {}
        for loc in locations:
            for lang, text in loc["translations"].items():
                if lang not in best_translations or not best_translations[lang]:
                    best_translations[lang] = text

        consolidatable.append({
            "en_text": en_text,
            "common_key": common_key,
            "common_resolved_path": f"common.{common_key}",
            "already_in_common": already_in_common,
            "occurrences": len(unique_paths),
            "locations_to_remove": other_locs,
            "best_translations": best_translations,
            "best_context": f"Generic UI text: {en_text}",
        })

    return consolidatable


def format_yaml_entry(key: str, translations: dict, context: str,
                      verified_by_human: str = "[]") -> str:
    """Format a single YAML translation entry."""
    lines = [f"{key}:"]
    # Always quote context values since they may contain colons
    context_escaped = context.replace('"', '\\"')
    lines.append(f'  context: "{context_escaped}"')
    for lang in LANGUAGES:
        val = translations.get(lang, "")
        if val:
            # Quote values that contain special YAML characters
            if any(c in val for c in ":{}'\"#[]") or val.startswith(("'", '"', "-", " ")):
                # Use double quotes, escaping internal double quotes
                val_escaped = val.replace('"', '\\"')
                lines.append(f'  {lang}: "{val_escaped}"')
            else:
                lines.append(f"  {lang}: {val}")
    lines.append("  verified_by_human: []")
    return "\n".join(lines)


def remove_key_from_yaml(filepath: str, yaml_key: str, line_start: int) -> bool:
    """
    Remove a translation key block from a YAML file.
    Returns True if successful.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the key block
    start_idx = line_start - 1  # 0-indexed

    # Verify this is the right key
    if start_idx >= len(lines):
        return False

    line_content = lines[start_idx].rstrip()
    if not line_content.startswith(f"{yaml_key}:"):
        # Line number may have shifted — search nearby
        for offset in range(-5, 6):
            idx = start_idx + offset
            if 0 <= idx < len(lines) and lines[idx].rstrip().startswith(f"{yaml_key}:"):
                start_idx = idx
                break
        else:
            # Search the whole file
            for idx, ln in enumerate(lines):
                if ln.rstrip().startswith(f"{yaml_key}:") and not ln[0].isspace():
                    start_idx = idx
                    break
            else:
                print(f"  WARNING: Could not find key '{yaml_key}' in {filepath}", file=sys.stderr)
                return False

    # Find the end of this key block (next top-level key or EOF)
    end_idx = start_idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        # Next top-level key or comment before next key
        if line.strip() and not line[0].isspace() and not line.startswith("#"):
            break
        # Blank line followed by a top-level key
        if not line.strip():
            # Check if next non-blank line is a top-level key
            next_non_blank = end_idx + 1
            while next_non_blank < len(lines) and not lines[next_non_blank].strip():
                next_non_blank += 1
            if next_non_blank < len(lines) and lines[next_non_blank].strip() and \
               not lines[next_non_blank][0].isspace():
                end_idx += 1  # Include the blank line in removal
                break
        end_idx += 1

    # Remove the block
    del lines[start_idx:end_idx]

    # Clean up multiple consecutive blank lines
    cleaned = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(cleaned)

    return True


def update_text_references(old_path: str, new_path: str) -> int:
    """
    Update all $text('old_path') references to $text('new_path') in Svelte/TS files.
    Returns number of files changed.
    """
    refs = find_text_references(old_path)
    changed_files = set()

    for ref in refs:
        filepath = ref["file"]
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Replace both single and double quote variants
        new_content = content.replace(f"$text('{old_path}')", f"$text('{new_path}')")
        new_content = new_content.replace(f'$text("{old_path}")', f"$text('{new_path}')")

        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed_files.add(filepath)

    return len(changed_files)


def add_to_common_yml(key: str, translations: dict, context: str) -> bool:
    """Add a new key to common.yml."""
    entry = format_yaml_entry(key, translations, context)

    with open(COMMON_YML, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if key already exists
    if re.search(rf"^{re.escape(key)}:", content, re.MULTILINE):
        return False  # Already exists

    # Append to end of file
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{entry}\n"

    with open(COMMON_YML, "w", encoding="utf-8") as f:
        f.write(content)

    return True


def apply_consolidation(item: dict) -> dict:
    """
    Apply a single consolidation: add to common.yml, remove from sources, update refs.
    Returns a summary dict.
    """
    en_text = item["en_text"]
    common_key = item["common_key"]
    common_path = item["common_resolved_path"]
    summary = {
        "en_text": en_text,
        "common_key": common_key,
        "added_to_common": False,
        "removed_from": [],
        "refs_updated": 0,
        "files_with_updated_refs": 0,
    }

    # Step 1: Add to common.yml if not already there
    if not item["already_in_common"]:
        added = add_to_common_yml(
            common_key,
            item["best_translations"],
            item["best_context"],
        )
        summary["added_to_common"] = added

    # Step 2: For each duplicate location, update $text() refs then remove from YAML
    for loc in item["locations_to_remove"]:
        old_path = loc["resolved_path"]

        # Update component references
        num_changed = update_text_references(old_path, common_path)
        summary["refs_updated"] += num_changed
        summary["files_with_updated_refs"] += num_changed

        # Remove the key from the source YAML
        removed = remove_key_from_yaml(loc["file"], loc["yaml_key"], loc["line"])
        if removed:
            summary["removed_from"].append(loc["file"])

    return summary


def print_plan(consolidatable: list, json_output: bool = False):
    """Print the consolidation plan."""
    if json_output:
        output = []
        for item in consolidatable:
            output.append({
                "en_text": item["en_text"],
                "common_key": item["common_key"],
                "common_resolved_path": item["common_resolved_path"],
                "already_in_common": item["already_in_common"],
                "occurrences": item["occurrences"],
                "locations_to_remove": [
                    {"resolved_path": loc["resolved_path"], "file": loc["file"], "line": loc["line"]}
                    for loc in item["locations_to_remove"]
                ],
            })
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    total_removals = 0
    total_ref_updates = 0

    print("=" * 70)
    print("TRANSLATION CONSOLIDATION PLAN")
    print("=" * 70)
    print(f"\nFound {len(consolidatable)} English values to consolidate to common.yml\n")

    for item in consolidatable:
        en_text = item["en_text"]
        common_key = item["common_key"]
        already = "EXISTS" if item["already_in_common"] else "NEW"
        locs = item["locations_to_remove"]

        print(f"  [{already}] common.{common_key}  en: \"{en_text}\"  ({item['occurrences']} occurrences)")

        # Find $text() references for each location
        ref_count = 0
        for loc in locs:
            refs = find_text_references(loc["resolved_path"])
            ref_count += len(refs)
            ref_str = f"  ({len(refs)} refs)" if refs else "  (0 refs — possibly unused)"
            print(f"         - {loc['resolved_path']}  [{loc['file']}:{loc['line']}]{ref_str}")

        total_removals += len(locs)
        total_ref_updates += ref_count
        print()

    print("=" * 70)
    print(f"SUMMARY: {len(consolidatable)} values → common.yml")
    print(f"  Keys to remove from source files: {total_removals}")
    print(f"  $text() references to update: {total_ref_updates}")
    print(f"  Translation entries saved: ~{total_removals * 21} (across 21 languages)")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Consolidate redundant translations into common.yml")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--apply", action="store_true", help="Apply the consolidation")
    parser.add_argument("--plan", action="store_true", help="Show consolidation plan only")
    parser.add_argument("--value", type=str, help="Only process a specific English value")
    parser.add_argument("--all", action="store_true", help="Process all consolidatable values")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--min-occurrences", type=int, default=MIN_OCCURRENCES,
                        help=f"Minimum occurrences to consider (default: {MIN_OCCURRENCES})")
    parser.add_argument("--max-length", type=int, default=MAX_EN_LENGTH,
                        help=f"Maximum English text length (default: {MAX_EN_LENGTH})")
    args = parser.parse_args()

    if not SOURCES_DIR.exists():
        print(f"Error: Sources directory not found: {SOURCES_DIR}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and not args.apply and not args.plan:
        args.dry_run = True  # Default to dry-run

    print("Scanning translation files...", file=sys.stderr)
    # Pass custom thresholds
    consolidatable = find_consolidatable(
        SOURCES_DIR,
        min_occurrences=args.min_occurrences,
        max_en_length=args.max_length,
    )

    if args.value:
        consolidatable = [c for c in consolidatable if c["en_text"] == args.value]
        if not consolidatable:
            print(f"No consolidatable entries found for en: \"{args.value}\"", file=sys.stderr)
            print(f"Try: --min-occurrences 2 or --max-length 50", file=sys.stderr)
            sys.exit(1)

    if args.dry_run or args.plan:
        print_plan(consolidatable, json_output=args.json)
    elif args.apply:
        if not args.value and not args.all:
            print("Error: --apply requires either --value \"...\" or --all", file=sys.stderr)
            sys.exit(1)

        print(f"Applying consolidation for {len(consolidatable)} values...\n")
        total_summary = {
            "values_processed": 0,
            "keys_added_to_common": 0,
            "keys_removed": 0,
            "component_files_updated": 0,
        }

        for item in consolidatable:
            print(f"  Consolidating: \"{item['en_text']}\" → common.{item['common_key']}")
            summary = apply_consolidation(item)

            if summary["added_to_common"]:
                total_summary["keys_added_to_common"] += 1
            total_summary["keys_removed"] += len(summary["removed_from"])
            total_summary["component_files_updated"] += summary["files_with_updated_refs"]
            total_summary["values_processed"] += 1

            if summary["removed_from"]:
                print(f"    Removed from {len(summary['removed_from'])} files")
            if summary["files_with_updated_refs"]:
                print(f"    Updated refs in {summary['files_with_updated_refs']} component files")

        print(f"\n{'=' * 70}")
        print(f"DONE: {total_summary['values_processed']} values consolidated")
        print(f"  New common.yml keys: {total_summary['keys_added_to_common']}")
        print(f"  Keys removed from source files: {total_summary['keys_removed']}")
        print(f"  Component files updated: {total_summary['component_files_updated']}")
        print(f"\nNext steps:")
        print(f"  1. cd frontend/packages/ui && npm run build:translations")
        print(f"  2. node frontend/packages/ui/scripts/validate-locales.js")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
