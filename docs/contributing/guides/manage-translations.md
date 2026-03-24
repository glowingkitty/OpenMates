# Translation Management — Reference

Full command reference, output examples, and detailed workflows.

For rules, see `manage-translations.md` (loaded automatically by tag).

---

# Translation Management (Full Guide)

Load this document when working on translations, finding missing keys, or using the translation management tool.

---

## MANDATORY: Always Use the Script First (CRITICAL)

**Before answering any translation-related question or making any translation change, you MUST run `manage_translations.py` to get live data from the actual YAML files.** Never answer from memory or assumptions — the script is the single source of truth.

| User asks…                                       | Run this first                                                                   |
| ------------------------------------------------ | -------------------------------------------------------------------------------- |
| "Which translations are missing?"                | `python3 scripts/manage_translations.py show-next-missing`                       |
| "How complete is language X?"                    | `python3 scripts/manage_translations.py overview --lang X`                       |
| "What's the overall translation status?"         | `python3 scripts/manage_translations.py overview`                                |
| "Which file contains key Y?"                     | `python3 scripts/manage_translations.py find-key "Y"`                            |
| "Translate the missing keys for language X"      | `python3 scripts/auto_translate.py --lang X --count 20`                          |
| "Are there structural issues in the YAML files?" | `python3 scripts/manage_translations.py validate`                                |
| "Export missing translations for X"              | `python3 scripts/manage_translations.py export-missing --lang X`                 |
| Any translation task involving a specific file   | `python3 scripts/manage_translations.py show-next-missing --file "filename.yml"` |

**Do not skip this step.** Running the script takes under 2 seconds and gives exact file paths, line numbers, and current counts. Answering without it risks operating on stale information.

---

## Overview

`scripts/manage_translations.py` is the primary tool for managing i18n translations. It operates directly on the 186 YAML source files in `frontend/packages/ui/src/i18n/sources/` and reads the language list from `languages.json`.

**Current state (as of last audit — run `overview` for live numbers):**

- ~3,200 total translation keys across 186 YAML files
- 20 supported languages
- `en` and `de` are most complete; `sv` has the most missing

---

## Commands

### `show-next-missing` — Find missing translations

The primary command for LLM-driven translation work. Scans files one by one and shows missing keys with their exact location and context.

```bash
# Next 5 missing keys across all languages (default)
python3 scripts/manage_translations.py show-next-missing

# Next 20 missing keys for Swedish specifically
python3 scripts/manage_translations.py show-next-missing --lang sv --count 20

# Missing keys in a specific file only
python3 scripts/manage_translations.py show-next-missing --file "header.yml" --lang sv

# Missing keys in a directory glob
python3 scripts/manage_translations.py show-next-missing --file "settings/*.yml" --lang de --count 10
```

**Output for each missing key:**

```
frontend/packages/ui/src/i18n/sources/header.yml:1
  Key:     toggle_menu
  Context: Button text for toggling the main menu
  English: Toggle menu
  Missing: sv (and 0 other(s): ...)
```

**How to use the output to translate:**

1. Note the `rel_path:line` — open that exact file at that line
2. `Key` is the YAML entry name to edit
3. `Context` tells you where/how the string is used
4. `English` is the source text to translate
5. Add the translated value under the language code in that YAML entry

---

### `overview` — Statistics dashboard

Shows completion percentages, missing counts, and file counts.

```bash
# Full language table with progress bars
python3 scripts/manage_translations.py overview

# Detail for one language only
python3 scripts/manage_translations.py overview --lang sv

# Include full paths of all 186 source files
python3 scripts/manage_translations.py overview --files
```

Use `overview` first to decide which language to work on and how many keys are missing before running `show-next-missing`.

---

### `validate` — Structural integrity check

Catches structural problems that would silently break the build system or produce wrong output.

```bash
python3 scripts/manage_translations.py validate
```

**What it detects:**

- Accidentally **nested YAML** — violates the flat-key rule (see `docs/contributing/guides/i18n.md`). This breaks the build system silently.
- **Duplicate top-level keys** within the same file (YAML silently overwrites the first one)
- Missing required fields: `context`, `en`, `verified_by_human`
- Empty `en` value (the English source must never be blank)
- YAML parse errors

**Run `validate` after adding new keys** to catch structural mistakes before committing.

---

### `export-missing` — Export missing translations

Exports all missing entries for a language in a ready-to-use format.

```bash
# YAML (pasteable directly into source files, grouped by file)
python3 scripts/manage_translations.py export-missing --lang sv

# JSON array (for scripted/AI-driven translation)
python3 scripts/manage_translations.py export-missing --lang sv --format json

# CSV (for spreadsheet-based review)
python3 scripts/manage_translations.py export-missing --lang sv --format csv

# Write to file instead of stdout
python3 scripts/manage_translations.py export-missing --lang sv --output /tmp/sv_missing.yaml

# Limit to one file
python3 scripts/manage_translations.py export-missing --lang sv --file "settings/*.yml"
```

**YAML output** looks like this — each block is pasteable directly into the source file:

```yaml
# ── frontend/packages/ui/src/i18n/sources/header.yml ──

toggle_menu: # line 1
  context: Button text for toggling the main menu
  en: Toggle menu
  sv: "" # ← translate here
```

**Note:** Do NOT use `export-missing` as the primary translation workflow. The correct approach is to run `auto_translate.py` (see the "Translating a specific language" section below), which handles finding missing keys, calling the Gemini API, and writing results back automatically.

---

### `find-key` — Search for a key

Finds a key by partial key name, English text, or context description. Useful when you know what a string says but not which file it's in.

```bash
# Search by key name fragment
python3 scripts/manage_translations.py find-key "toggle_menu"

# Search by English text
python3 scripts/manage_translations.py find-key "Sign In"

# Search by context description
python3 scripts/manage_translations.py find-key "header button"
```

**Output includes:**

- Full file path and line number
- Key name, context, English value
- Per-language completion (how many languages have it translated, which are missing)
- Which field matched (key / english / context)

Use `find-key` before adding a new translation key to check if it already exists under a different name.

---

## Typical Workflows

### Translating a specific language (e.g. adding Swedish) — MANDATORY PROCEDURE (CRITICAL)

**Always use `auto_translate.py` to perform the actual translation — never translate YAML strings manually yourself.** The script calls the Gemini API, writes results directly into the YAML source files, and runs validation automatically.

**The correct loop (repeat until no missing keys remain):**

**Step 1 — Check current state**

```bash
python3 scripts/manage_translations.py overview --lang sv
```

Note the total number of missing keys. This is your progress baseline.

**Step 2 — Run auto_translate.py for the target scope**

Pick a focused scope (a file pattern or a reasonable `--count`) rather than translating everything at once. This keeps each step fast, validates early, and lets the user see progress.

```bash
# Translate missing keys in a specific file or directory
python3 scripts/auto_translate.py --lang sv --file "settings/*.yml"

# Translate the next N missing keys across all files
python3 scripts/auto_translate.py --lang sv --count 20

# Translate all missing keys in a single file
python3 scripts/auto_translate.py --lang sv --file "common.yml"
```

The script will:

1. Find all missing keys for the given scope
2. Batch and send them to the Gemini API
3. Write the translated values directly into the YAML source files
4. Run `validate` and show any issues

**Step 3 — Review the diff**

```bash
git diff frontend/packages/ui/src/i18n/sources/
```

Spot-check a few translations for accuracy. If any look wrong, use the Edit tool to correct them directly in the YAML file, then re-run validate.

**Step 4 — Loop back to Step 2**

Run `auto_translate.py` again with the same or next scope until `overview --lang sv` shows 0 missing keys.

**Step 5 — Rebuild compiled locales (once all missing keys are done)**

```bash
cd frontend/packages/ui && npm run build:translations
```

---

**Why scoped runs and not all at once?**

- Early validation: catching a structural error after one file is far cheaper than after all 186
- Progress visibility: the user can verify each batch before continuing
- API reliability: very large batches risk timeout or truncated responses from Gemini

### Adding a new translation key

```bash
# 1. Check if the key already exists
python3 scripts/manage_translations.py find-key "your key name or text"

# 2. Add the key to the appropriate YAML file (see docs/contributing/guides/i18n.md for format)

# 3. Validate structure
python3 scripts/manage_translations.py validate

# 4. Check the key appears correctly
python3 scripts/manage_translations.py find-key "your_key_name"
```

### Identifying the worst-covered files for a language

```bash
# Show the most missing (file-by-file order, increase count to see more)
python3 scripts/manage_translations.py show-next-missing --lang pt --count 50 2>&1 | grep "^frontend/"
```

### Validating after bulk edits

```bash
python3 scripts/manage_translations.py validate 2>&1 | grep -A3 "✗"
```

---

## Important Rules

- **Always use `auto_translate.py` for translation** — never produce translations yourself and never write them manually into YAML files. Run `python3 scripts/auto_translate.py --lang <code> [--file <pattern>] [--count N]` and let the script handle the API calls and file writes. Use `--dry-run` first if you want to preview what will be translated.
- **Translate in scoped runs, not all at once** — use `--file` to restrict to a directory or single file, or use `--count` to limit the number of keys per run. Never attempt to translate all missing keys for all files in a single command.
- **Never edit the compiled JSON files** in `frontend/packages/ui/src/i18n/locales/` — they are generated build artifacts and are gitignored. Edit only the YAML source files.
- **Use flat keys only** — see `docs/contributing/guides/i18n.md`. Nested YAML breaks the build silently. `validate` will catch it.
- **English (`en`) must never be empty** — it is the source of truth for all other translations.
- **After adding or modifying YAML files**, always run `npm run build:translations` in `frontend/packages/ui/` before testing in the browser.
- **Run `validate` before committing** any batch of YAML changes.
