---
name: deploy
description: Lint, commit, and push tracked changes via sessions.py deploy
user-invocable: true
---

## Current Session State
!`python3 scripts/sessions.py status --json 2>/dev/null || echo '{"error": "no active session"}'`

## Instructions

You are deploying code changes. Follow this exact sequence:

1. **Load deployment docs** (commit message format, PR rules):
   ```bash
   python3 scripts/sessions.py deploy-docs
   ```

2. **Preview what will be deployed:**
   ```bash
   python3 scripts/sessions.py prepare-deploy --session <SESSION_ID>
   ```
   Review the file list. Exclude any files that shouldn't be committed with `--exclude`.

3. **Deploy** (lint + commit + push):
   ```bash
   python3 scripts/sessions.py deploy --session <SESSION_ID> \
     --title "type: short description" \
     --message "Longer explanation of why" \
     --end
   ```

### Commit Message Format
- Prefix: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`, `style:`, `perf:`, `ci:`, `revert:`
- Imperative present tense: "change" not "changed"
- For bug fixes, use structured format: `Symptom:`, `Cause:`, `Fix:`

### If Deploy Fails
- **Lint errors:** Fix them first, then retry
- **Pre-existing hook bug** (unrelated to your changes): Use `--no-verify` and add a backlog entry
- **Never** use raw `git commit` — it bypasses session tracking

### After Deploy
Write the task completion summary with the commit SHA from the deploy output.
