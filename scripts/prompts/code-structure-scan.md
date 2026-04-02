You are scanning the OpenMates codebase for code structure and repository hygiene issues. You are looking for organizational problems, misplaced files, gitignore gaps, and open-source readiness issues. You do NOT make code changes — suggestions only.

**Date:** {{DATE}} | **HEAD:** {{GIT_SHA}} | **Day:** {{DAY_OF_WEEK}}

## Architecture context

This is an open-source project. SvelteKit frontend (`frontend/`), Python/FastAPI backend (`backend/`), Docker microservices, PostgreSQL via Directus CMS. Monorepo with `frontend/apps/web_app/` and `frontend/packages/ui/`. Backend has `core/` (API gateway), `apps/` (microservices), `shared/` (utilities, schemas, providers).

Naming conventions:
- Python: `snake_case.py`
- TypeScript services: `camelCase.ts`
- Svelte components: `PascalCase.svelte`
- TypeScript types: `camelCase.ts` in `types/` directory
- Test files (Python): `test_<module>.py`
- Test files (TS): `<module>.test.ts` in `__tests__/`

## Scope

### Priority 1 — Files changed in the last 7 days (ALWAYS scan these first)

```
{{RECENT_CHANGES}}
```

### Priority 2 — Rotating sector ({{SECTOR_NAME}})

```
{{SECTOR_PATHS}}
```

## Previous findings (carry forward any that are still unresolved)

{{PREVIOUS_FINDINGS}}

## Categories to scan for

1. **Gitignore gaps** — files tracked in git that should NOT be: log files, temp/cache directories, local config overrides, build artifacts, IDE/editor files (`.idea/`, `.vscode/settings.json`), OS files (`.DS_Store`, `Thumbs.db`), compiled output, `node_modules`, `__pycache__`, `.env` files with real values, coverage reports, test screenshots
2. **Open-source hygiene** — files that leak internal infrastructure: real IP addresses, internal domain names, server hostnames, deployment configs with production values (should use `<PLACEHOLDER>`), SSH keys, API keys or tokens (even expired ones), internal URLs, email addresses of team members
3. **Folder organization** — files in the wrong directory (e.g., utility in an app-specific folder when it belongs in `shared/`), inconsistent nesting depth between similar modules, orphaned directories with no code, files that should be colocated (e.g., a component and its test in different trees)
4. **File consolidation** — very small files (<20 lines) that export a single constant/type and could be merged into a parent module, duplicate functionality split across multiple files, config files that could be consolidated
5. **Naming inconsistencies** — files that break the project's naming conventions listed above, inconsistent casing within the same directory, ambiguous names that don't describe the file's purpose
6. **Stale artifacts** — old migration scripts no longer needed, outdated config files superseded by newer ones, leftover experiment/prototype code, commented-out code blocks in config files, empty `__init__.py` files that serve no purpose, unused fixture files

## Output format

**Write your findings directly to `logs/nightly-reports/code-structure.json`** using the Write tool. Use this exact JSON structure:

```json
{
  "job": "code-structure",
  "ran_at": "{{DATE}}T{{TIME}}Z",
  "status": "ok",
  "summary": "Code structure scan completed (HEAD {{GIT_SHA}}, sector: {{SECTOR_NAME}}). N item(s) found.",
  "details": {
    "date": "{{DATE}}",
    "head_sha": "{{GIT_SHA}}",
    "sector_scanned": "{{SECTOR_NAME}}",
    "items": [
      {
        "category": "gitignore-gaps|open-source-hygiene|folder-organization|file-consolidation|naming-inconsistencies|stale-artifacts",
        "severity": "high|medium|low",
        "path": "path/to/file/or/directory",
        "issue": "1-2 sentence description of the problem",
        "suggestion": "1-2 sentence recommended fix"
      }
    ]
  }
}
```

## Rules

- **Suggestions only.** Do NOT edit, move, rename, or delete any files.
- **Top 10 items max.** Rank by severity (high first), then by impact.
- **Be specific.** Include exact file paths, not vague descriptions.
- **Skip known patterns.** Don't flag `scripts/.tmp/` (intentionally gitignored already), `logs/` (gitignored), or `test-results/` (gitignored). Check `.gitignore` before flagging gitignore gaps.
- **Carry forward** any unresolved items from previous findings.
- **Write the JSON file early** (even with partial results) so a hard kill still produces output.
- **Time limit:** You have 25 minutes. If you're running low, wrap up with what you have.
