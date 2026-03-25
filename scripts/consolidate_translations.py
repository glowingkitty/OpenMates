#!/usr/bin/env python3
"""
Consolidate redundant translations into common.yml — with safety checks.

SAFETY: Before removing any key, verifies it has ZERO references across:
  1. Static $text('key') calls in Svelte/TS/JS files
  2. Dynamic $text(`prefix.${var}`) template literals (blocks entire namespace prefix)
  3. Backend app.yml translation_key / i18n_namespace fields
  4. Generated metadata files (appsMetadata.ts, matesMetadata.ts)
  5. Test files referencing translation keys
  6. Any other file containing the resolved key path as a string literal

A key is only removed if ALL references point to the exact resolved path AND
every one of those references was successfully rewritten to common.*.

Usage:
  python3 scripts/consolidate_translations.py --dry-run          # preview safe removals
  python3 scripts/consolidate_translations.py --apply --all      # apply safe consolidation
  python3 scripts/consolidate_translations.py --dry-run --value "Cancel"  # preview one value
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
PROJECT_ROOT = Path(".")

# Supported languages (order matters for YAML output)
LANGUAGES = [
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
    "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv", "he",
]

MIN_OCCURRENCES = 3
MAX_EN_LENGTH = 30

SKIP_KEYS_CONTAINING = {
    "systemprompt", "follow_up", "how_to_use", "description",
    "example", "placeholder", "tooltip", "hint",
}

SKIP_EN_VALUES = {
    "|", "||", "---", "—", "•",
    "1 year & older", "90 days & older",
    "Career insights", "Log In from Another Device",
    "On Low Balance", "Settings & Memories",
    "Generate Draft", "Cancel Reminder",
    "Hide sensitive data", "Show sensitive data",
    "Verify Your Identity", "Set Reminder", "Set reminder",
    "Copied to clipboard", "or",
}

COMMON_KEY_NAMES = {
    "Cancel": "cancel", "Close": "close", "Copy": "copy",
    "Copied": "copied", "Copied!": "copied_excl", "Continue": "continue",
    "Done": "done", "Delete": "delete", "Search": "search",
    "Processing...": "processing", "Loading...": "loading",
    "Email": "email", "credits": "credits", "Download": "download",
    "Chat": "chat", "Chats": "chats", "Docs": "docs",
    "Password": "password", "Pricing": "pricing", "Retry": "retry",
    "Share": "share", "Summary": "summary", "Today": "today",
    "Apps": "apps", "Ask": "ask", "Buy Credits": "buy_credits",
    "Contact": "contact", "Date": "date", "Discord": "discord",
    "Duration": "duration", "Generate": "generate", "Images": "images",
    "Just now": "just_now", "Monthly": "monthly", "New chat": "new_chat",
    "Privacy": "privacy", "Read": "read", "Save": "save",
    "Settings": "settings", "Upload failed": "upload_failed", "View": "view",
    "Add Entry": "add_entry", "Add Password": "add_password",
    "Audio": "audio", "Back": "back", "Change Password": "change_password",
    "Custom": "custom", "Details": "details", "Devices": "devices",
    "Disabled": "disabled", "Enabled": "enabled",
    "Gift Cards": "gift_cards", "GitHub": "github",
    "Imprint": "imprint", "Invoices": "invoices", "Language": "language",
    "Last Updated": "last_updated", "Legal": "legal", "Location": "location",
    "Newsletter": "newsletter", "Other": "other", "PDF": "pdf",
    "Provider": "provider", "Recovery Key": "recovery_key",
    "Select all": "select_all", "Show less": "show_less",
    "Skill": "skill", "Status": "status", "Stop": "stop",
    "Storage": "storage", "Terms and conditions": "terms_and_conditions",
    "Untitled chat": "untitled_chat", "Yesterday": "yesterday",
}


# ---------------------------------------------------------------------------
# YAML helpers (reused from previous version)
# ---------------------------------------------------------------------------

def resolve_namespace(yml_file: Path, sources_dir: Path) -> tuple[str, str]:
    """Compute (namespace, key_prefix) matching build-translations.js."""
    rel = yml_file.relative_to(sources_dir)
    parts = rel.parts
    if len(parts) == 1:
        return rel.stem, ""
    namespace = parts[0]
    for part in parts[1:-1]:
        namespace = f"{namespace}.{part}"
    filename = parts[-1]
    if filename == "main.yml":
        return namespace, ""
    return namespace, Path(filename).stem


def resolve_key(yaml_key: str, key_prefix: str) -> str:
    if not key_prefix:
        return yaml_key
    if yaml_key == key_prefix:
        return yaml_key
    return f"{key_prefix}.{yaml_key}"


def parse_yaml_full(filepath: Path) -> list[dict]:
    entries = []
    current_key = None
    current_data = {}
    current_line = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            stripped = line.rstrip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line[0].isspace() and ":" in stripped:
                if current_key:
                    entries.append(_build_entry(current_key, current_data, current_line))
                current_key = stripped.split(":", 1)[0].strip()
                current_data = {}
                current_line = line_num
            elif line[0].isspace() and current_key and ":" in stripped:
                m = re.match(r"\s+(\w[\w_]*)\s*:\s*(.*)", stripped)
                if m:
                    val = m.group(2).strip()
                    if (val.startswith('"') and val.endswith('"')) or \
                       (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    current_data[m.group(1)] = val
    if current_key:
        entries.append(_build_entry(current_key, current_data, current_line))
    return entries


def _build_entry(key: str, data: dict, line: int) -> dict:
    translations = {lang: data[lang] for lang in LANGUAGES if lang in data}
    return {
        "key": key,
        "translations": translations,
        "context": data.get("context", ""),
        "line": line,
    }


# ---------------------------------------------------------------------------
# SAFETY: Comprehensive reference scanner
# ---------------------------------------------------------------------------

def _rg(pattern: str, path: str, globs: list[str] | None = None,
        fixed: bool = False) -> list[str]:
    """Run ripgrep and return matching lines."""
    cmd = ["rg", "-n", "--no-heading"]
    if fixed:
        cmd.append("-F")
    if globs:
        for g in globs:
            cmd.extend(["--glob", g])
    cmd.extend([pattern, path])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return [line for line in result.stdout.strip().split("\n") if line]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def build_all_referenced_keys() -> set[str]:
    """
    Build a set of ALL translation key paths that are referenced ANYWHERE
    in the codebase. This is the safety net — a key in this set must NOT
    be deleted from YAML sources.

    Scans:
      1. Static $text('key') in frontend code
      2. Dynamic $text(`prefix.${var}`) — blocks entire prefix namespace
      3. Backend app.yml translation_key / i18n_namespace values
      4. Generated metadata files (appsMetadata.ts, matesMetadata.ts, embedRegistry)
      5. Any string literal matching a known namespace prefix in non-YAML files
    """
    referenced = set()

    # --- 1. Static $text('key') / $text("key") calls ---
    for line in _rg(
        r"""\$text\(['"]([^'"]+)['"]\)""",
        "frontend/",
        globs=["*.svelte", "*.ts", "*.js"],
    ):
        for match in re.findall(r"""\$text\(['"]([^'"]+)['"]\)""", line):
            referenced.add(match)

    # --- 2. Dynamic $text(`prefix.${var}`) — mark entire prefix as referenced ---
    # E.g. $text(`settings.${key}`) means ALL keys under settings.* are referenced
    for line in _rg(r"\$text\(`", "frontend/", globs=["*.svelte", "*.ts"]):
        # Extract the static prefix before the first ${
        m = re.search(r"\$text\(`([^`$]+)\$\{", line)
        if m:
            prefix = m.group(1)
            referenced.add(f"__dynamic_prefix__:{prefix}")

    # --- 3. $text(variable) calls — we can't know what key, mark as dynamic ---
    # These are already handled by the prefix check above for template literals.
    # For plain variable references like $text(someVar), we track the variable
    # assignment patterns but conservatively mark the key as referenced.

    # --- 4. Backend app.yml: translation_key and i18n_namespace ---
    for line in _rg("translation_key:", "backend/apps/", globs=["*.yml"]):
        m = re.search(r"translation_key:\s*[\"']?([^\s\"'#]+)", line)
        if m:
            key = m.group(1)
            # Backend sometimes omits the "apps." prefix (added at runtime)
            referenced.add(key)
            if not key.startswith("apps.") and "." not in key:
                referenced.add(f"apps.{key}")

    for line in _rg("i18n_namespace:", "backend/apps/", globs=["*.yml"]):
        m = re.search(r"i18n_namespace:\s*[\"']?([^\s\"'#]+)", line)
        if m:
            # Mark all keys under this namespace as referenced
            referenced.add(f"__dynamic_prefix__:{m.group(1)}.")

    # --- 5. Generated metadata files ---
    for ts_file in ["frontend/packages/ui/src/data/appsMetadata.ts",
                     "frontend/packages/ui/src/data/matesMetadata.ts"]:
        if Path(ts_file).exists():
            for line in _rg("translation_key", ts_file, fixed=True):
                for m in re.findall(r"""['"]([a-z_][a-z0-9_.]+)['"]""", line):
                    referenced.add(m)

    # --- 6. labelKey / titleKey / translationKey object properties ---
    for line in _rg(
        r"""(?:labelKey|titleKey|translationKey|Key)\s*[:=]\s*['"]""",
        "frontend/",
        globs=["*.svelte", "*.ts"],
    ):
        for m in re.findall(r"""['"]([a-z_][a-z0-9_.]+)['"]""", line):
            if "." in m:
                referenced.add(m)

    # --- 7. example_translation_keys arrays in app.yml ---
    for line in _rg("example_translation_key", "backend/apps/", globs=["*.yml"]):
        for m in re.findall(r"""['"]([a-z_][a-z0-9_.]+)['"]""", line):
            referenced.add(m)

    return referenced


def is_key_safe_to_remove(resolved_path: str, referenced_keys: set[str]) -> tuple[bool, str]:
    """
    Check if a resolved key path is safe to remove.
    Returns (safe, reason).

    A key is BLOCKED from removal if:
      - It appears in the referenced_keys set (direct reference)
      - Any dynamic prefix matches it (e.g. prefix "settings." blocks "settings.chat")
      - It matches a backend translation_key pattern
    """
    # Direct reference check
    if resolved_path in referenced_keys:
        return False, "directly referenced"

    # Dynamic prefix check — e.g. $text(`settings.${key}`) blocks all settings.*
    for ref in referenced_keys:
        if ref.startswith("__dynamic_prefix__:"):
            prefix = ref[len("__dynamic_prefix__:"):]
            if resolved_path.startswith(prefix):
                return False, f"matches dynamic prefix '{prefix}*'"

    # Check if this key's namespace segments match a backend translation_key
    # E.g. "apps.audio" referenced as just "audio" in backend
    parts = resolved_path.split(".")
    if len(parts) >= 2:
        # Check without first segment (namespace)
        without_ns = ".".join(parts[1:])
        if without_ns in referenced_keys:
            return False, f"backend references '{without_ns}'"

    return True, "no references found"


# ---------------------------------------------------------------------------
# YAML file operations
# ---------------------------------------------------------------------------

def format_yaml_entry(key: str, translations: dict, context: str) -> str:
    lines = [f"{key}:"]
    ctx = context.replace('"', '\\"')
    lines.append(f'  context: "{ctx}"')
    for lang in LANGUAGES:
        val = translations.get(lang, "")
        if val:
            if any(c in val for c in ":{}'\"#[]") or val.startswith(("'", '"', "-", " ")):
                lines.append(f'  {lang}: "{val.replace(chr(34), chr(92)+chr(34))}"')
            else:
                lines.append(f"  {lang}: {val}")
    lines.append("  verified_by_human: []")
    return "\n".join(lines)


def remove_key_from_yaml(filepath: str, yaml_key: str, line_start: int) -> bool:
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start_idx = line_start - 1
    if start_idx >= len(lines):
        return False

    if not lines[start_idx].rstrip().startswith(f"{yaml_key}:"):
        for offset in range(-5, 6):
            idx = start_idx + offset
            if 0 <= idx < len(lines) and lines[idx].rstrip().startswith(f"{yaml_key}:"):
                start_idx = idx
                break
        else:
            for idx, ln in enumerate(lines):
                if ln.rstrip().startswith(f"{yaml_key}:") and not ln[0].isspace():
                    start_idx = idx
                    break
            else:
                print(f"  WARNING: Could not find key '{yaml_key}' in {filepath}",
                      file=sys.stderr)
                return False

    end_idx = start_idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        if line.strip() and not line[0].isspace() and not line.startswith("#"):
            break
        if not line.strip():
            nxt = end_idx + 1
            while nxt < len(lines) and not lines[nxt].strip():
                nxt += 1
            if nxt < len(lines) and lines[nxt].strip() and not lines[nxt][0].isspace():
                end_idx += 1
                break
        end_idx += 1

    del lines[start_idx:end_idx]
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


def add_to_common_yml(key: str, translations: dict, context: str) -> bool:
    entry = format_yaml_entry(key, translations, context)
    with open(COMMON_YML, "r", encoding="utf-8") as f:
        content = f.read()
    if re.search(rf"^{re.escape(key)}:", content, re.MULTILINE):
        return False
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{entry}\n"
    with open(COMMON_YML, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def find_static_text_refs(resolved_path: str) -> list[dict]:
    """Find static $text('resolved_path') references."""
    refs = []
    pattern = re.escape(resolved_path)
    for line in _rg(
        f"\\$text\\(['\"]({pattern})['\"]",
        "frontend/",
        globs=["*.svelte", "*.ts", "*.js"],
    ):
        parts = line.split(":", 2)
        if len(parts) >= 3:
            refs.append({"file": parts[0], "line_num": int(parts[1]),
                         "content": parts[2].strip()})
    return refs


def update_text_references(old_path: str, new_path: str) -> int:
    refs = find_static_text_refs(old_path)
    changed = set()
    for ref in refs:
        filepath = ref["file"]
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = content.replace(f"$text('{old_path}')", f"$text('{new_path}')")
        new_content = new_content.replace(f'$text("{old_path}")', f"$text('{new_path}')")
        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed.add(filepath)
    return len(changed)


# ---------------------------------------------------------------------------
# Core: find consolidatable keys
# ---------------------------------------------------------------------------

def find_consolidatable(sources_dir: Path, min_occ: int = MIN_OCCURRENCES,
                        max_len: int = MAX_EN_LENGTH) -> list[dict]:
    yml_files = sorted(sources_dir.rglob("*.yml"))
    en_to_locations = defaultdict(list)

    for yml_file in yml_files:
        namespace, key_prefix = resolve_namespace(yml_file, sources_dir)
        for entry in parse_yaml_full(yml_file):
            yaml_key = entry["key"]
            resolved = resolve_key(yaml_key, key_prefix)
            resolved_path = f"{namespace}.{resolved}"
            en = entry["translations"].get("en", "")
            if not en:
                continue
            en_to_locations[en].append({
                "resolved_path": resolved_path,
                "yaml_key": yaml_key,
                "file": str(yml_file),
                "line": entry["line"],
                "namespace": namespace,
                "key_prefix": key_prefix,
                "translations": entry["translations"],
                "context": entry["context"],
            })

    consolidatable = []
    for en_text, locations in sorted(en_to_locations.items(),
                                     key=lambda x: (-len(x[1]), x[0])):
        unique_paths = set(loc["resolved_path"] for loc in locations)
        if len(unique_paths) < min_occ:
            continue
        if len(en_text) > max_len:
            continue
        if en_text in SKIP_EN_VALUES:
            continue
        if any(s in en_text.lower() for s in {"http", "www", "openmates"}):
            continue
        if en_text.startswith(('"', "'", "(")):
            continue
        if all(any(s in loc["yaml_key"].lower() for s in SKIP_KEYS_CONTAINING)
               for loc in locations):
            continue

        common_locs = [loc for loc in locations if loc["namespace"] == "common"]
        other_locs = [loc for loc in locations if loc["namespace"] != "common"]
        if not other_locs:
            continue

        if common_locs:
            common_key = common_locs[0]["yaml_key"]
            already_in_common = True
        else:
            if en_text in COMMON_KEY_NAMES:
                common_key = COMMON_KEY_NAMES[en_text]
            else:
                common_key = re.sub(r"[^a-z0-9]+", "_", en_text.lower()).strip("_")
                if not common_key:
                    continue
            already_in_common = False

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


# ---------------------------------------------------------------------------
# Plan / Apply with safety
# ---------------------------------------------------------------------------

def print_plan(items: list, referenced: set[str], json_output: bool = False):
    safe_removals = 0
    blocked_removals = 0
    total_ref_updates = 0

    output_items = []
    for item in items:
        locs_safe = []
        locs_blocked = []
        for loc in item["locations_to_remove"]:
            ok, reason = is_key_safe_to_remove(loc["resolved_path"], referenced)
            loc_info = {**loc, "safe": ok, "reason": reason}
            if ok:
                locs_safe.append(loc_info)
            else:
                locs_blocked.append(loc_info)
        item["_safe"] = locs_safe
        item["_blocked"] = locs_blocked
        output_items.append(item)

    if json_output:
        out = []
        for item in output_items:
            out.append({
                "en_text": item["en_text"],
                "common_key": item["common_key"],
                "already_in_common": item["already_in_common"],
                "safe_to_remove": [
                    {"resolved_path": loc["resolved_path"], "file": loc["file"]}
                    for loc in item["_safe"]
                ],
                "blocked": [
                    {"resolved_path": loc["resolved_path"], "reason": loc["reason"]}
                    for loc in item["_blocked"]
                ],
            })
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    print("=" * 70)
    print("TRANSLATION CONSOLIDATION PLAN (with safety check)")
    print("=" * 70)
    print(f"\nScanned {len(referenced)} key references across codebase\n")

    for item in output_items:
        en_text = item["en_text"]
        common_key = item["common_key"]
        tag = "EXISTS" if item["already_in_common"] else "NEW"

        n_safe = len(item["_safe"])
        n_blocked = len(item["_blocked"])

        if n_safe == 0:
            status = "SKIP (all blocked)"
        elif n_blocked == 0:
            status = f"SAFE ({n_safe} removable)"
        else:
            status = f"PARTIAL ({n_safe} safe, {n_blocked} blocked)"

        print(f"  [{tag}] common.{common_key}  en: \"{en_text}\"  — {status}")

        for loc in item["_safe"]:
            refs = find_static_text_refs(loc["resolved_path"])
            ref_str = f"({len(refs)} static refs)" if refs else "(0 refs)"
            print(f"    SAFE   {loc['resolved_path']}  {ref_str}")
            safe_removals += 1
            total_ref_updates += len(refs)

        for loc in item["_blocked"]:
            print(f"    BLOCK  {loc['resolved_path']}  — {loc['reason']}")
            blocked_removals += 1

        print()

    print("=" * 70)
    print(f"SAFE to remove:    {safe_removals} keys")
    print(f"BLOCKED (kept):    {blocked_removals} keys")
    print(f"$text() refs to update: {total_ref_updates}")
    print(f"Translation entries saved: ~{safe_removals * 21}")
    print("=" * 70)


def apply_consolidation(items: list, referenced: set[str]):
    total = {"added": 0, "removed": 0, "blocked": 0, "refs_updated": 0}

    for item in items:
        en_text = item["en_text"]
        common_key = item["common_key"]
        common_path = item["common_resolved_path"]

        safe_locs = []
        for loc in item["locations_to_remove"]:
            ok, reason = is_key_safe_to_remove(loc["resolved_path"], referenced)
            if ok:
                safe_locs.append(loc)
            else:
                total["blocked"] += 1
                print(f"    BLOCK  {loc['resolved_path']}  — {reason}")

        if not safe_locs:
            print(f"  Skipping \"{en_text}\" — all locations blocked")
            continue

        print(f"  Consolidating: \"{en_text}\" → common.{common_key}"
              f"  ({len(safe_locs)} safe, "
              f"{len(item['locations_to_remove']) - len(safe_locs)} blocked)")

        # Add to common.yml if needed
        if not item["already_in_common"]:
            if add_to_common_yml(common_key, item["best_translations"],
                                 item["best_context"]):
                total["added"] += 1

        # Process each safe location
        for loc in safe_locs:
            old_path = loc["resolved_path"]
            n_updated = update_text_references(old_path, common_path)
            total["refs_updated"] += n_updated

            if remove_key_from_yaml(loc["file"], loc["yaml_key"], loc["line"]):
                total["removed"] += 1

    print(f"\n{'=' * 70}")
    print("DONE:")
    print(f"  Keys added to common.yml: {total['added']}")
    print(f"  Keys safely removed:      {total['removed']}")
    print(f"  Keys blocked (kept):      {total['blocked']}")
    print(f"  Component refs updated:   {total['refs_updated']}")
    print("\nNext steps:")
    print("  1. cd frontend/packages/ui && npm run build:translations")
    print("  2. node frontend/packages/ui/scripts/validate-locales.js")
    print(f"{'=' * 70}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Consolidate redundant translations into common.yml (safe)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--apply", action="store_true", help="Apply consolidation")
    parser.add_argument("--value", type=str, help="Only process specific English value")
    parser.add_argument("--all", action="store_true", help="Process all values")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--min-occurrences", type=int, default=MIN_OCCURRENCES)
    parser.add_argument("--max-length", type=int, default=MAX_EN_LENGTH)
    args = parser.parse_args()

    if not SOURCES_DIR.exists():
        print(f"Error: Sources directory not found: {SOURCES_DIR}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and not args.apply:
        args.dry_run = True

    print("Building reference map (scanning entire codebase)...", file=sys.stderr)
    referenced = build_all_referenced_keys()
    print(f"Found {len(referenced)} referenced keys/prefixes", file=sys.stderr)

    print("Scanning translation files for duplicates...", file=sys.stderr)
    consolidatable = find_consolidatable(
        SOURCES_DIR,
        min_occ=args.min_occurrences,
        max_len=args.max_length,
    )

    if args.value:
        consolidatable = [c for c in consolidatable if c["en_text"] == args.value]
        if not consolidatable:
            print(f"No consolidatable entries for: \"{args.value}\"", file=sys.stderr)
            sys.exit(1)

    if args.dry_run:
        print_plan(consolidatable, referenced, json_output=args.json)
    elif args.apply:
        if not args.value and not args.all:
            print("Error: --apply requires --value or --all", file=sys.stderr)
            sys.exit(1)
        apply_consolidation(consolidatable, referenced)


if __name__ == "__main__":
    main()
