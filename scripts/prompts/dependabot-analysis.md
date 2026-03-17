# Dependabot Security Alert Fix Prompt

#

# Placeholders replaced by scripts/check-dependabot-daily.sh before passing to opencode:

# {{DATE}} — UTC date of the check (YYYY-MM-DD)

# {{ALERT_SUMMARY}} — human-readable grouped alert list (replaced inline by the shell script)

#

# NOTE: This file provides the static preamble and instructions.

# The actual per-alert details are appended by the shell script at runtime.

Fix the following Dependabot security alerts in the OpenMates GitHub repository.

**Date:** {{DATE}}

## Instructions

For each alert below:

1. **Upgrade the affected package** to the minimum patched version specified (or the latest stable if no minimum is given).
2. **Update all relevant lock files** — `pnpm-lock.yaml` for frontend packages, `requirements.txt` / `pyproject.toml` for backend packages.
3. **Run the relevant tests** to confirm nothing breaks after the upgrade:
   - Frontend: `pnpm --filter @openmates/ui test` (vitest unit tests)
   - Backend: `python -m pytest backend/tests/ -m "not integration" -q`
4. **Include the GHSA ID in your commit message**, e.g.:
   `fix: upgrade jspdf to 4.2.1 (GHSA-wfv2-pwc8-crg5)`
5. **Commit to the `dev` branch** — do NOT open a PR to main.

## Important Constraints

- Make one commit per GHSA ID (or one commit for a batch of related upgrades in the same package).
- If upgrading a package introduces breaking API changes, note them explicitly but still make the upgrade — security takes priority.
- If a patch version is not yet available (no fix exists), note this and skip the upgrade. Do not downgrade.
- Do not change unrelated code.

## Alerts to Fix

{{ALERT_SUMMARY}}
