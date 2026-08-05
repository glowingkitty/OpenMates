---
name: remove-stale-code
description: Safely remove deletion-ready findings from logs/nightly-reports/stale-code.json. Use when asked to clean stale code, dead code, unused imports, variables, functions, classes, exports, components, or selectors from the deterministic daily report.
user-invocable: true
argument-hint: "[fingerprint, path, or maximum candidate count]"
---

# Remove Stale Code

Use the deterministic report as a lead, never as authorization by itself. This
workflow handles only `deletion_ready` findings and revalidates every guard
against the current checkout before editing.

## Workflow

1. Start or resume a `sessions.py` maintenance session before edits.
2. Read `logs/nightly-reports/stale-code.json`. Stop if it is missing, malformed,
   has `status != "ok"`, or contains no `deletion_ready` findings.
3. Compare `subject_commit` with `git rev-parse HEAD`. If they differ, run
   `python3 scripts/stale_code_daily.py --dry-run-notify` and reread the report.
4. Select only findings whose `classification` is exactly `deletion_ready`.
   Apply a user-provided fingerprint/path filter when present. Otherwise process
   at most five findings from one category in one run.
5. For every selected finding, recompute its SHA-256 fingerprint from
   `category`, `subcategory`, repository-relative `file`, numeric `line` (or
   zero), and `code`, joined with NUL bytes. Skip it if the fingerprint differs.
6. Reread the target and search the repository for the symbol and its dynamic
   forms. Skip it if references, metadata registration, glob loading,
   decorators, reflection, public exports, generated paths, migrations,
   fixtures, route conventions, or compatibility markers make usage ambiguous.
7. Apply only the smallest finding-specific change. For Ruff F401 imports,
   reread and remove only the selected import statement or selected imported
   name from a multi-name statement with `apply_patch`; never run a file-wide
   autofix. Then run `ruff check --select F401 <file>` and inspect the diff. For
   an unsupported finding kind, stop rather than inventing a deletion strategy.
8. Rerun `python3 scripts/find_dead_code.py --json --all` and confirm each
   selected fingerprint disappeared without creating detector errors.
9. Run the smallest targeted lint/test command for every changed file. Do not
   treat the detector rerun as a substitute for product tests.
10. Review the final diff. Use `python3 scripts/sessions.py deploy` only after all
    selected candidates and targeted checks pass. Never commit or deploy skipped
    candidates as if they were removed.

## Refusal Rules

- Never edit `review_only` or `suppressed` findings.
- Never trust a report from another commit.
- Never bulk-remove more than five findings or mix categories in one run.
- Never delete a Svelte component or CSS selector solely from zero literal references.
- Never delete compatibility, public API, framework registration, generated,
  migration, fixture, or route code without a separately approved contract.
- Never continue when a required analyzer, reference search, or targeted test fails.

## Output

Report selected fingerprints, removed findings, skipped findings with reasons,
changed files, detector rerun result, targeted verification commands, and deploy
commit when applicable.
