Fix the following security vulnerabilities detected by EU and international vulnerability sources (OSV, NVD).

These are vulnerabilities that GitHub Dependabot did NOT flag — they were detected by cross-referencing our dependencies against the OSV database (which aggregates EU-contributed advisories, PyPI, npm, and NIST/NVD data).

**Date:** {{DATE}}
**Total findings:** {{TOTAL_FINDINGS}}

## Instructions

For each alert below:

1. **Upgrade the affected package** to the minimum patched version specified (or the latest stable if no minimum is given).
2. **Update all relevant lock files** — `pnpm-lock.yaml` for frontend (npm) packages, `requirements.txt` for backend (PyPI) packages.
3. **Run the relevant tests** to confirm nothing breaks after the upgrade:
   - Frontend: `pnpm --filter @openmates/ui test` (vitest unit tests)
   - Backend: `python -m pytest backend/tests/ -m "not integration" -q`
4. **Include the vulnerability ID in your commit title**, e.g.:
   `fix: upgrade lodash to 4.17.22 (GHSA-xxxx-yyyy-zzzz / CVE-2026-12345)`
5. **Deploy using `sessions.py deploy`** — see Deploy Instructions below. Do NOT use raw `git commit` or `git push`.

## Constraints

- One deploy per vulnerability ID (or one deploy for a batch of related upgrades in the same package).
- If upgrading introduces breaking API changes, note them but still upgrade — security takes priority.
- If no patch version exists yet, skip the upgrade and note it. Do not downgrade.
- Do not change unrelated code.

## Alerts to Fix

{{ALERT_SUMMARY}}

## User Disclosure Assessment

The following packages handle sensitive user data. If a vulnerability in these packages could have been exploited before the fix, a user disclosure notice may be needed:

{{DISCLOSURE_SUMMARY}}

For each disclosure-relevant package above, assess:
- Was the vulnerability realistically exploitable in our specific usage?
- Could user data (encrypted chats, auth tokens, payment info) have been compromised?
- Recommend: "no disclosure needed" (if not exploitable in our context) or "disclosure recommended" (if there's any realistic risk).

Include your disclosure assessment in the commit message body.
