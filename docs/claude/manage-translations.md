# Translation Management — Rules

Rules for using the translation management tools. For full command reference and workflow details, run:
`python3 scripts/sessions.py context --doc manage-translations-ref`

---

## Rule 1: Always Run the Script First

Before answering any translation question or making changes, run `manage_translations.py` for live data. Never answer from memory.

| User asks | Run first |
|---|---|
| Which translations are missing? | `python3 scripts/manage_translations.py show-next-missing` |
| How complete is language X? | `python3 scripts/manage_translations.py overview --lang X` |
| Overall status? | `python3 scripts/manage_translations.py overview` |
| Which file has key Y? | `python3 scripts/manage_translations.py find-key "Y"` |
| Translate missing keys for X | `python3 scripts/auto_translate.py --lang X --count 20` |
| Structural issues? | `python3 scripts/manage_translations.py validate` |

## Rule 2: Always Use auto_translate.py

Never translate YAML strings manually yourself. Always use:
```bash
python3 scripts/auto_translate.py --lang <code> [--file <pattern>] [--count N]
```

## Rule 3: Translate in Scoped Runs

Use `--file` or `--count` to limit each run. Never translate all missing keys at once. Review diffs after each batch.

## Rule 4: Workflow Loop

1. `overview --lang <code>` — check current state
2. `auto_translate.py --lang <code> --file "settings/*.yml"` — translate a scope
3. `git diff` — review
4. Repeat until 0 missing
5. `cd frontend/packages/ui && npm run build:translations` — rebuild

## Rule 5: Never Edit Compiled JSON

The `locales/*.json` files are generated and gitignored. Only edit source `.yml` files.

## Rule 6: Validate Before Committing

Always run `python3 scripts/manage_translations.py validate` after batch YAML changes.
