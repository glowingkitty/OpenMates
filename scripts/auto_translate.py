#!/usr/bin/env python3
# scripts/auto_translate.py
#
# AI-powered translation tool for OpenMates i18n YAML source files.
#
# Translates missing keys for a given language (and optional file scope) using
# the Google AI Studio (Gemini) API, then writes the results directly back into
# the YAML source files. Designed for targeted, step-by-step use by Claude or
# a human — not a bulk "translate everything" script.
#
# Prerequisites:
#   pip install httpx pyyaml          (both are already available in this repo)
#   SECRET__GOOGLE_AI_STUDIO__API_KEY or GEMINI_API_KEY set in .env (repo root)
#
# Usage:
#   # Translate all missing Swedish keys in settings files
#   python3 scripts/auto_translate.py --lang sv --file "settings/*.yml"
#
#   # Translate next 20 missing Hebrew keys across all files
#   python3 scripts/auto_translate.py --lang he --count 20
#
#   # Translate all missing French keys in a single file
#   python3 scripts/auto_translate.py --lang fr --file "common.yml"
#
#   # Dry run: show what would be translated without writing files
#   python3 scripts/auto_translate.py --lang de --file "common.yml" --dry-run
#
# How it works:
#   1. Calls manage_translations.py export-missing --format json to get the list
#      of keys that need translating (scoped to --lang and --file).
#   2. Batches the keys by file and sends them to Gemini Flash for translation.
#      Each batch stays under the token budget (short UI labels grouped together,
#      long system prompts sent individually).
#   3. Writes each translated value back into the YAML source file using targeted
#      line-level insertion — preserving all existing structure and comments.
#   4. Runs manage_translations.py validate before exiting to catch any issues.
#
# Notes:
#   - Reads GEMINI_API_KEY / SECRET__GOOGLE_AI_STUDIO__API_KEY from .env
#   - Writes directly to frontend/packages/ui/src/i18n/sources/ YAML files
#   - Does NOT touch compiled locale JSON files (those are build artifacts)
#   - Run `cd frontend/packages/ui && npm run build:translations` after this

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
I18N_SOURCES_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n" / "sources"
ENV_FILE = REPO_ROOT / ".env"

# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------

RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------


def load_api_key() -> Optional[str]:
    """
    Load the Gemini / Google AI Studio API key.

    Priority:
    1. GEMINI_API_KEY / SECRET__GOOGLE_AI_STUDIO__API_KEY env var
    2. Same keys in the repo-root .env file (if not marked IMPORTED_TO_VAULT)
    3. Docker Vault via `docker compose exec api` (for dev servers that store the
       key in Vault rather than plaintext in .env)
    """
    for var in ("GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"):
        val = os.environ.get(var, "").strip()
        if val and val != "IMPORTED_TO_VAULT":
            return val

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, val = line.partition("=")
            k = k.strip()
            val = val.strip().strip('"').strip("'")
            if k in ("GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"):
                if val and val != "IMPORTED_TO_VAULT":
                    return val

    # Fallback: fetch from Vault via Docker (dev server setup)
    return _load_api_key_from_vault()


def _load_api_key_from_vault() -> Optional[str]:
    """
    Retrieve the Google AI Studio API key from Vault via `docker compose exec api`.
    Used when the key is stored in Vault and not available as a plaintext env var.
    Returns None if Docker is unavailable or the key cannot be retrieved.
    """
    docker_compose_file = REPO_ROOT / "backend" / "core" / "docker-compose.yml"
    if not docker_compose_file.exists():
        return None

    fetch_script = (
        "import asyncio\n"
        "from backend.core.api.app.utils.secrets_manager import SecretsManager\n"
        "from backend.apps.ai.llm_providers.google_client import _get_google_ai_studio_api_key\n"
        "async def main():\n"
        "    sm = SecretsManager()\n"
        "    await sm.initialize()\n"
        "    key = await _get_google_ai_studio_api_key(sm)\n"
        "    print(key or '', end='')\n"
        "asyncio.run(main())\n"
    )

    try:
        result = subprocess.run(
            [
                "docker", "compose",
                "--env-file", str(ENV_FILE),
                "-f", str(docker_compose_file),
                "exec", "-T", "api",
                "python3", "-c", fetch_script,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        key = result.stdout.strip()
        if key:
            return key
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------


def call_gemini(api_key: str, system_prompt: str, user_message: str, lang: str, keys: list[str]) -> dict[str, str]:
    """
    Call the Gemini Flash API with a function-calling tool to return translations.

    Returns a dict mapping key name → translated value string.
    Empty string for any key that failed to translate (caller will skip it).
    """
    # Build the function schema: one output field per key
    properties = {}
    for k in keys:
        properties[k] = {
            "type": "string",
            "description": f"Translation of '{k}' into {lang}",
        }

    tool = {
        "function_declarations": [
            {
                "name": "return_translations",
                "description": (
                    "Return the translated values for all requested UI string keys. "
                    "Each value must be a natural translation of the English source "
                    "into the target language. Preserve all formatting markers, "
                    "newlines, and placeholder syntax exactly."
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": keys,
                },
            }
        ]
    }

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "tools": [tool],
        "tool_config": {"function_calling_config": {"mode": "ANY"}},
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
        },
    }

    model = "gemini-3-flash-preview"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    try:
        resp = httpx.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        print(f"{RED}Gemini API error {e.response.status_code}: {e.response.text[:300]}{RESET}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"{RED}Gemini request failed: {e}{RESET}", file=sys.stderr)
        return {}

    # Extract function call arguments
    try:
        candidates = data.get("candidates", [])
        if not candidates:
            print(f"{RED}No candidates in Gemini response{RESET}", file=sys.stderr)
            return {}
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            fc = part.get("functionCall")
            if fc and fc.get("name") == "return_translations":
                return fc.get("args", {})
        print(f"{YELLOW}No function call found in response parts{RESET}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"{RED}Failed to parse Gemini response: {e}{RESET}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Batch building
# ---------------------------------------------------------------------------

# Keys whose English value is longer than this are sent one at a time
LONG_TEXT_THRESHOLD = 1500
# Maximum total English chars in a single batch (for normal keys)
BATCH_CHAR_LIMIT = 6000
# Maximum number of keys per batch
BATCH_KEY_LIMIT = 30


def build_batches(records: list[dict]) -> list[list[dict]]:
    """
    Split a list of missing-key records into batches for Gemini.

    Long texts (system prompts, process descriptions) are sent one at a time
    so the model can produce accurate multi-line output without truncation.
    Short UI labels are grouped into batches of up to BATCH_KEY_LIMIT keys or
    BATCH_CHAR_LIMIT total English chars, whichever is reached first.
    """
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars = 0

    for record in records:
        en_text = record.get("en", "")
        en_len = len(en_text)

        # Long texts always get their own batch
        if en_len >= LONG_TEXT_THRESHOLD:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            batches.append([record])
            continue

        # Would adding this record exceed batch limits? Flush if so.
        if current_batch and (
            current_chars + en_len > BATCH_CHAR_LIMIT
            or len(current_batch) >= BATCH_KEY_LIMIT
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(record)
        current_chars += en_len

    if current_batch:
        batches.append(current_batch)

    return batches


# ---------------------------------------------------------------------------
# YAML write-back
# ---------------------------------------------------------------------------


def _yaml_value_lines(lang: str, value: str, indent: str = "  ") -> list[str]:
    """
    Produce the line(s) to insert for a translated value.

    - Single-line values with no special chars: plain scalar
    - Values containing newlines: literal block scalar (|)
    - Values with leading/trailing whitespace or special chars: quoted scalar
    """
    if "\n" in value:
        # Literal block scalar: first line is "  lang: |" then indented content
        content_indent = indent + "  "
        lines = [f"{indent}{lang}: |\n"]
        for ln in value.splitlines():
            lines.append(f"{content_indent}{ln}\n")
        # Ensure a trailing newline after the last content line
        # (block scalars include a final newline by default)
        return lines

    # Check if quoting is needed
    needs_quoting = (
        value != value.strip()
        or any(c in value for c in ('"', "'", ":", "{", "}", "[", "]", "#", "&", "*", "!", "|", ">", "?"))
        or value.lower() in ("true", "false", "null", "yes", "no", "on", "off")
        or (value and value[0] in "-@`")
    )

    if needs_quoting:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return [f'{indent}{lang}: "{escaped}"\n']

    return [f"{indent}{lang}: {value}\n"]


def write_translation_to_file(file_path: Path, key: str, lang: str, value: str) -> bool:
    """
    Insert a translated value for `key` + `lang` into the YAML source file.

    Strategy:
    - Find the line where the key entry starts (e.g. "cancel:")
    - Scan forward to find the `verified_by_human:` line that closes this entry
    - Insert the new language line immediately before `verified_by_human:`

    Returns True if the insertion was made, False if the key was not found.
    """
    if not file_path.exists():
        print(f"{RED}File not found: {file_path}{RESET}", file=sys.stderr)
        return False

    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)

    # Find the line that starts this key's entry.
    # Keys may contain dots (e.g. "career_insights.process") — they are literal
    # top-level YAML keys, not nested paths. We match the exact key followed by ":"
    key_pattern = re.compile(r"^(" + re.escape(key) + r"):\s*$")
    key_line_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if key_pattern.match(line):
            key_line_idx = i
            break

    if key_line_idx is None:
        print(f"{YELLOW}  Key not found in file: {key}{RESET}", file=sys.stderr)
        return False

    # Determine the indentation used inside this entry (look at the next non-blank line)
    entry_indent = "  "
    for j in range(key_line_idx + 1, min(key_line_idx + 5, len(lines))):
        stripped = lines[j].lstrip()
        if stripped:
            entry_indent = lines[j][: len(lines[j]) - len(stripped)]
            break

    # Scan forward from the key line to find `verified_by_human:` within this entry.
    # We stop if we hit another top-level key (no indentation) — that means we
    # reached the next entry without finding verified_by_human.
    insert_idx: Optional[int] = None
    for j in range(key_line_idx + 1, len(lines)):
        line = lines[j]
        stripped = line.strip()

        # Top-level key (no indentation, non-blank, not a comment) → end of entry
        if stripped and not line.startswith(" ") and not line.startswith("\t") and not stripped.startswith("#"):
            # Didn't find verified_by_human — insert just before this next key
            insert_idx = j
            break

        if stripped.startswith("verified_by_human:"):
            insert_idx = j
            break

    if insert_idx is None:
        # End of file — insert at end
        insert_idx = len(lines)

    # Check if the language key already exists between key_line_idx and insert_idx
    lang_pattern = re.compile(r"^\s+" + re.escape(lang) + r":\s")
    for j in range(key_line_idx + 1, insert_idx):
        if lang_pattern.match(lines[j]):
            # Already exists — skip (don't overwrite)
            return False

    # Build the lines to insert
    new_lines = _yaml_value_lines(lang, value, indent=entry_indent)

    # Insert
    for offset, new_line in enumerate(new_lines):
        lines.insert(insert_idx + offset, new_line)

    file_path.write_text("".join(lines), encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main translation loop
# ---------------------------------------------------------------------------


def translate_missing(lang: str, file_pattern: Optional[str], count: Optional[int], dry_run: bool) -> int:
    """
    Find missing translations, call Gemini, write results back.

    Returns the number of keys successfully translated.
    """
    api_key = load_api_key()
    if not api_key:
        print(
            f"{RED}No Gemini API key found.{RESET}\n"
            "Set GEMINI_API_KEY or SECRET__GOOGLE_AI_STUDIO__API_KEY in your environment or .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Step 1: Get list of missing keys via manage_translations.py ---
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "manage_translations.py"),
        "export-missing",
        "--lang", lang,
        "--format", "json",
    ]
    if file_pattern:
        cmd += ["--file", file_pattern]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    except Exception as e:
        print(f"{RED}Failed to run manage_translations.py: {e}{RESET}", file=sys.stderr)
        sys.exit(1)

    # manage_translations.py prints the JSON array followed by a trailing summary
    # comment line (e.g. "# 7 missing 'sv' translations above.") — extract only
    # the JSON array by finding everything between the first "[" and the last "]".
    raw = result.stdout.strip()
    if not raw:
        print(f"{GREEN}No missing translations for '{lang}'" + (f" in '{file_pattern}'" if file_pattern else "") + f".{RESET}")
        return 0

    # Strip ANSI colour codes before parsing
    raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)

    # Extract the JSON array portion only
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        print(f"{GREEN}No missing translations for '{lang}'" + (f" in '{file_pattern}'" if file_pattern else "") + f".{RESET}")
        return 0
    raw = raw[start : end + 1]

    try:
        records = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"{RED}Could not parse export-missing output: {e}{RESET}", file=sys.stderr)
        print(f"Raw output (first 500 chars):\n{raw[:500]}", file=sys.stderr)
        sys.exit(1)

    if not records:
        print(f"{GREEN}No missing translations for '{lang}'" + (f" in '{file_pattern}'" if file_pattern else "") + f".{RESET}")
        return 0

    # Apply --count limit
    if count and count > 0:
        records = records[:count]

    total = len(records)
    print(f"\n{BOLD}Translating {total} missing '{lang}' key(s)" + (f" in '{file_pattern}'" if file_pattern else "") + f"...{RESET}\n")

    # --- Step 2: Build system prompt ---
    system_prompt = (
        f"You are a professional translator producing UI translations for a web application. "
        f"Translate each provided English string into {lang}. "
        f"Rules:\n"
        f"- Match the tone and length of the English source (UI labels must be concise)\n"
        f"- Preserve all newlines, markdown formatting, placeholder syntax ({{variable}}), and bullet markers exactly\n"
        f"- Do NOT add explanations, notes, or commentary\n"
        f"- For languages with formal/informal 'you' (e.g. German, French, Spanish), use the informal register "
        f"(du/tu/tú) unless the source is explicitly formal\n"
        f"- Return exactly one translation per key — no empty strings"
    )

    # --- Step 3: Batch and translate ---
    batches = build_batches(records)
    translated: dict[str, str] = {}  # key → translated value

    for batch_num, batch in enumerate(batches, 1):
        keys = [r["key"] for r in batch]
        print(f"  Batch {batch_num}/{len(batches)}: {len(keys)} key(s)  [{', '.join(keys[:3])}{'...' if len(keys) > 3 else ''}]")

        # Build a clear user message listing each key with its context and English value
        items = []
        for r in batch:
            items.append(
                f"Key: {r['key']}\n"
                f"Context: {r['context']}\n"
                f"English: {r['en']}"
            )
        user_message = (
            f"Translate the following {len(batch)} UI string(s) into {lang}.\n\n"
            + "\n\n---\n\n".join(items)
        )

        if dry_run:
            print(f"  {DIM}[dry-run] Would call Gemini for batch {batch_num}{RESET}")
            continue

        result_map = call_gemini(api_key, system_prompt, user_message, lang, keys)

        for key in keys:
            val = result_map.get(key, "").strip()
            if val:
                translated[key] = val
                print(f"    {GREEN}✓{RESET} {key}: {val[:60]}{'...' if len(val) > 60 else ''}")
            else:
                print(f"    {YELLOW}⚠{RESET} {key}: no translation returned — skipping")

    if dry_run:
        print(f"\n{DIM}[dry-run] No files written.{RESET}")
        return 0

    # --- Step 4: Write translations back into YAML files ---
    print(f"\n{BOLD}Writing to YAML files...{RESET}")
    written = 0
    skipped = 0

    # Build a map from key → file path
    key_to_file: dict[str, Path] = {}
    for r in records:
        key_to_file[r["key"]] = REPO_ROOT / r["file"]

    for key, value in translated.items():
        file_path = key_to_file.get(key)
        if not file_path:
            continue
        if write_translation_to_file(file_path, key, lang, value):
            written += 1
        else:
            skipped += 1
            print(f"  {YELLOW}⚠{RESET} Skipped write for {key} (already exists or key not found)")

    print(f"\n  {GREEN}✓ Wrote {written} translation(s){RESET}" + (f", skipped {skipped}" if skipped else ""))

    # --- Step 5: Validate ---
    print(f"\n{BOLD}Running validate...{RESET}")
    val_result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "manage_translations.py"), "validate"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if val_result.returncode != 0 or "✗" in val_result.stdout:
        print(f"{YELLOW}Validation warnings/errors:{RESET}")
        print(val_result.stdout[:1000])
    else:
        print(f"  {GREEN}✓ Validation passed{RESET}")

    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Translate missing i18n YAML keys using the Gemini API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          # Translate all missing Swedish keys in settings files
          python3 scripts/auto_translate.py --lang sv --file "settings/*.yml"

          # Translate next 20 missing Hebrew keys across all files
          python3 scripts/auto_translate.py --lang he --count 20

          # Translate all missing French keys in a single file
          python3 scripts/auto_translate.py --lang fr --file "common.yml"

          # Dry run: show what would be translated without writing
          python3 scripts/auto_translate.py --lang de --file "common.yml" --dry-run
        """),
    )
    parser.add_argument("--lang", required=True, help="Target language code (e.g. sv, he, fr)")
    parser.add_argument(
        "--file",
        default=None,
        help='Glob pattern to restrict scope (e.g. "settings/*.yml" or "common.yml")',
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Maximum number of keys to translate in this run (default: all missing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be translated without calling the API or writing files",
    )

    args = parser.parse_args()
    n = translate_missing(args.lang, args.file, args.count, args.dry_run)

    if n > 0:
        print(
            f"\n{DIM}Next steps:{RESET}\n"
            f"  1. Review the changes: git diff frontend/packages/ui/src/i18n/sources/\n"
            f"  2. Rebuild compiled locales: cd frontend/packages/ui && npm run build:translations\n"
            f"  3. Check remaining: python3 scripts/manage_translations.py overview --lang {args.lang}\n"
        )


if __name__ == "__main__":
    main()
