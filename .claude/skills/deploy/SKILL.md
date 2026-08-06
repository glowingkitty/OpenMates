---
name: deploy
description: Lint, commit, and push tracked changes via sessions.py deploy
user-invocable: true
---

## Current Session State
!`python3 scripts/sessions.py status --json 2>/dev/null || echo '{"error": "no active session"}'`

## Instructions

You are deploying code changes. Follow this exact sequence:

Scoped `dev` deploys through `sessions.py deploy` are pre-authorized when they
are required to verify the assigned task. Ask first only for production deploys,
raw git commit/push, broad dirty deploys, destructive data/migrations, secrets,
unclear privacy/billing/security scope, unsafe same-file overlap, or
planning/review-only requests.

Agent edits should live in the automatic session worktree, not the repository
root checkout. The root checkout is the control plane for orchestration and the
short `dev` integration window. If the session does not show a worktree, create
or print it with:

```bash
python3 scripts/sessions.py worktree ensure --session <SESSION_ID>
```

1. **Load deployment docs** (commit message format, PR rules):
   ```bash
   python3 scripts/sessions.py deploy-docs
   ```

2. **Preview what will be deployed:**
   ```bash
   python3 scripts/sessions.py prepare-deploy --session <SESSION_ID>
   ```
    Review the file list. Exclude any files that shouldn't be committed with `--exclude`.

   Do not run a separate `wait-lock` before normal deploys. `sessions.py deploy`
   scopes the commit from the session worktree diff, guards root integration and
   commit/push with the short dev deploy push lock, and releases the lock after
   push. If root integration is unsafe, sessions.py records a
   visible blocked-deploy item; resolve the conflict and rerun deploy.

3. **Run spec conformance when applicable:**
   - If this work has a full spec under `docs/specs/<slug>/spec.yml`, run `python3 scripts/spec_verify.py docs/specs/<slug>/spec.yml` before the final deploy.
   - A scoped verification deploy may precede final conformance when live Playwright evidence is required. After that run, complete exact captions, local privacy scanning, frame-only demonstration review, and Discord publication attempt before final completion.
   - If this work used an inline spec, include the scenarios, acceptance criteria, and test evidence in the deploy message.
   - If no spec exists for source changes, confirm the change is trivial/mechanical or include an explicit skip reason.

4. **Deploy** (lint + commit + push):
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
- **Worktree integration blocked:** Resolve the root integration conflict, check `python3 scripts/sessions.py status`, then rerun the same deploy command
- **Never** use raw `git commit` — it bypasses session tracking

### After Deploy
Write the task completion summary with the commit SHA from the deploy output.
For non-trivial work, include `Spec:` and `Tests:` lines in the summary.
