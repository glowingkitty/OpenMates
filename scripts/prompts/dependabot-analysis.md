Fix the following Dependabot security alerts in the OpenMates GitHub repository.

**Date:** {{DATE}}

## Instructions

For each alert below:

1. **Upgrade the affected package** to the minimum patched version specified (or the latest stable if no minimum is given).
2. **Update all relevant lock files** — `pnpm-lock.yaml` for frontend packages, `requirements.txt` / `pyproject.toml` for backend packages.
3. **Run the relevant tests** to confirm nothing breaks after the upgrade:
   - Frontend: `pnpm --filter @openmates/ui test` (vitest unit tests)
   - Backend: `python -m pytest backend/tests/ -m "not integration" -q`
4. **Include the GHSA ID in your commit title**, e.g.:
   `fix: upgrade jspdf to 4.2.1 (GHSA-wfv2-pwc8-crg5)`
5. **Deploy using `sessions.py deploy`** — see Deploy Instructions below. Do NOT use raw `git commit` or `git push`.

## Constraints

- One deploy per GHSA ID (or one deploy for a batch of related upgrades in the same package).
- If upgrading introduces breaking API changes, note them but still upgrade — security takes priority.
- If no patch version exists yet, skip the upgrade and note it. Do not downgrade.
- Do not change unrelated code.

## Alerts to Fix

{{ALERT_SUMMARY}}
