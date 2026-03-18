Remove the dead code listed below from the OpenMates codebase.

**Date:** {{DATE}}
**Total findings this run:** {{TOTAL_FINDINGS}}
**Categories:** {{CATEGORIES}}

## Critical rules — read before touching anything

1. **One commit per category** (python / typescript / svelte / css). Do not mix categories in a single commit.
2. **Never delete a file that is part of a SvelteKit route** (`+page.svelte`, `+layout.svelte`, `+error.svelte`).
3. **Python auto-fixable items** (marked `[auto-fix]`): run `ruff check --select F401,F841 --fix <file>` instead of editing by hand. Always verify the file still passes `ruff check` after fixing.
4. **TypeScript unused exports**: remove only the `export` keyword — do NOT delete the function body unless the function is also confirmed unused within the file.
5. **Svelte unused components**: delete the entire `.svelte` file AND remove its export from `frontend/packages/ui/index.ts` if present. Check that no other file references the component name before deleting.
6. **CSS unused classes**: delete the entire rule block (selector + all properties + closing `}`). Include any matching `@media` overrides of the same class. Do NOT delete CSS custom property definitions (`--var-name`).
7. **Do not remove code marked `# noqa`, `// eslint-disable`, or `/* svelte-ignore */`** — those suppressions indicate intentional exceptions.
8. **Do not touch deprecated shims** — items with `DEPRECATED` in their docstring are kept for backwards compatibility unless explicitly listed below.
9. After all changes, run the following to verify no regressions:
   - Python: `ruff check --select F401,F841 backend/ --exclude "*.ipynb"`
   - Frontend: `cd frontend && pnpm --filter @openmates/web_app exec svelte-check --threshold warning 2>&1 | tail -5`
10. **Commit each category** using `python3 scripts/sessions.py deploy` with title `chore: remove dead <category> code (automated)` — do NOT push to main.

## Dead code to remove

{{FINDINGS_BODY}}

## Completion

After removing all items and committing:

- Confirm total items removed vs skipped (with reasons for any skips).
- If any item looked risky or had unexpected callers, note it.
