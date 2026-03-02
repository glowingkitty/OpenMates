#!/usr/bin/env python3
"""
Apply missing Arabic translations to settings YAML files.

Uses docker cp to copy a batch script into the api container, runs it there,
then copies the output back and applies to YAML source files.

Usage: python3 scripts/apply_ar_translations.py [--file "settings/*.yml"]
"""

import json
import subprocess
import sys
import re
import os
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "_ar_translate_batch.py")
CONTAINER = "api"
INPUT_REMOTE = "/tmp/ar_input.json"
OUTPUT_REMOTE = "/tmp/ar_output.json"
INPUT_LOCAL = "/tmp/ar_input_local.json"
OUTPUT_LOCAL = "/tmp/ar_output_local.json"


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


def translate_batch_via_docker(items: list) -> dict:
    """Translate all items via docker cp + exec approach. Returns dict key -> ar."""
    # 1. Write input JSON to host temp file
    input_data = [{"key": item["key"], "en": item["en"]} for item in items]
    with open(INPUT_LOCAL, "w", encoding="utf-8") as f:
        json.dump(input_data, f, ensure_ascii=False)

    print(f"Copied {len(items)} keys to input file. docker cp-ing to container...", flush=True)

    # 2. docker cp input + batch script into container
    run(["docker", "cp", INPUT_LOCAL, f"{CONTAINER}:{INPUT_REMOTE}"])
    run(["docker", "cp", BATCH_SCRIPT, f"{CONTAINER}:/tmp/_ar_translate_batch.py"])

    # 3. exec the batch script inside the container
    print(f"Running translation script inside container (this may take a minute)...", flush=True)
    result = subprocess.run(
        ["docker", "exec", "-e", "PYTHONPATH=/app", CONTAINER,
         "python", "/tmp/_ar_translate_batch.py"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=600,
    )
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        print(f"WARNING: batch script exited {result.returncode} — will try to use partial output", file=sys.stderr)

    # 4. docker cp output back (may exist even on failure if partial results were written)
    cp_result = subprocess.run(
        ["docker", "cp", f"{CONTAINER}:{OUTPUT_REMOTE}", OUTPUT_LOCAL],
        capture_output=True, text=True,
    )
    if cp_result.returncode != 0:
        print(f"ERROR copying output from container:\n{cp_result.stderr}", file=sys.stderr)
        return {}

    try:
        with open(OUTPUT_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Read {len(data)} translations from output file.", flush=True)
        return data
    except Exception as e:
        print(f"ERROR reading output JSON: {e}", file=sys.stderr)
        return {}


def apply_translation_to_yaml(filepath: str, key: str, translation: str) -> bool:
    """
    Inject `ar: <translation>` into the YAML entry for the given key.

    Uses a line-scanning approach rather than regex block matching, so it
    correctly handles keys whose sibling values span multiple lines (e.g. a
    quoted multi-line `en:` string with blank lines inside it).

    Algorithm:
    1. Find the line that starts the key block (top-level key, no indent).
    2. Scan forward line-by-line to find the end of the block:
       - A line starting with `  ar:` means ar is already present → stop.
       - A line starting with `  verified_by_human:` is the preferred
         insertion point.
       - A new top-level key (no leading spaces, contains `:`) ends the block.
    3. Insert or replace the ar: line at the found position.
    """
    # Escape for YAML: quote if contains special characters
    needs_quoting = any(c in translation for c in [':', '#', '\n', '"', "'", '[', ']', '{', '}', '\\'])
    if needs_quoting:
        safe = translation.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        ar_line = f'  ar: "{safe}"\n'
    else:
        ar_line = f"  ar: {translation}\n"

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the line index of the key definition
    key_line_idx = None
    key_re = re.compile(r'^' + re.escape(key) + r'\s*:')
    for i, line in enumerate(lines):
        if key_re.match(line):
            key_line_idx = i
            break

    if key_line_idx is None:
        print(f"  WARNING: Could not find key '{key}' in {filepath}", file=sys.stderr)
        return False

    # Scan the block body (lines after the key header that are indented)
    ar_line_idx = None       # existing ar: line (to replace if empty)
    vbh_line_idx = None      # verified_by_human: line
    block_end_idx = None     # first line of the next top-level key

    i = key_line_idx + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Empty line — could be inside a multi-line value, keep going
        if stripped == '':
            i += 1
            continue

        # Indented line (part of this block)
        if line.startswith('  ') or line.startswith('\t'):
            if line.startswith('  ar:'):
                ar_line_idx = i
            elif line.startswith('  verified_by_human:'):
                vbh_line_idx = i
            i += 1
            continue

        # Non-indented, non-empty → start of a new top-level key
        block_end_idx = i
        break

    # If ar: already exists
    if ar_line_idx is not None:
        existing = lines[ar_line_idx].strip()
        if existing == 'ar: ""' or existing == 'ar:':
            # Replace empty value
            lines[ar_line_idx] = ar_line
        else:
            # Already has a real value — skip
            return False
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True

    # Insert ar: before verified_by_human: or before the next top-level key
    if vbh_line_idx is not None:
        insert_at = vbh_line_idx
    elif block_end_idx is not None:
        insert_at = block_end_idx
    else:
        insert_at = len(lines)

    lines.insert(insert_at, ar_line)
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="settings/*.yml",
                        help="Glob pattern for files to process (default: settings/*.yml)")
    args = parser.parse_args()

    # Export current missing keys
    missing_json = "/tmp/ar_settings_remaining.json"
    export_result = subprocess.run(
        ["python3", "scripts/manage_translations.py", "export-missing",
         "--lang", "ar", "--file", args.file, "--format", "json",
         "--output", missing_json],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    if export_result.returncode != 0:
        print(f"ERROR exporting missing: {export_result.stderr}", file=sys.stderr)
        sys.exit(1)

    with open(missing_json, "r", encoding="utf-8") as f:
        missing = json.load(f)

    if not missing:
        print("No missing Arabic translations found!")
        return

    total = len(missing)
    print(f"Found {total} missing Arabic keys. Translating via Docker...\n")

    translations = translate_batch_via_docker(missing)

    if not translations:
        print("ERROR: Got no translations back. Aborting.")
        sys.exit(1)

    print(f"\nGot {len(translations)} translations (out of {total} needed). Applying to YAML files...\n")

    success = 0
    failed = 0
    missing_tr = []

    for item in missing:
        filepath = os.path.join(PROJECT_ROOT, item["file"])
        key = item["key"]
        translation = translations.get(key, "")

        if not translation:
            missing_tr.append(key)
            failed += 1
            continue

        applied = apply_translation_to_yaml(filepath, key, translation)
        if applied:
            print(f"  OK  {item['file'].split('/')[-1]} :: {key}")
            print(f"      AR: {translation[:80]}{'...' if len(translation) > 80 else ''}")
            success += 1
        else:
            print(f"  FAIL {item['file'].split('/')[-1]} :: {key}")
            failed += 1

    if missing_tr:
        print(f"\nKeys with no translation returned ({len(missing_tr)}):")
        for k in missing_tr:
            print(f"  - {k}")

    print(f"\nDone. Applied: {success}, Failed: {failed}")


if __name__ == "__main__":
    main()
