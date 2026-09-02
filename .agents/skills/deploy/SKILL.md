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
    - Run `python3 scripts/specifications.py check-changed <changed paths> --session <SESSION_ID>` for Specification-governed work. Specification edits require an exact-hash approval receipt; changed behavioral tests cannot remain unmapped.
    - Run `python3 scripts/specifications.py check-generated`; stale registries, assertion indexes, coverage, or evidence fingerprints block deploy.
    - If this work has a full Plan under `docs/plans/<slug>/plan.yml`, run `python3 scripts/plan_verify.py docs/plans/<slug>/plan.yml` before the final deploy.
   - A scoped verification deploy may precede final conformance when live Playwright evidence is required. After that run, complete exact captions, frame-only demonstration review, and OpenCode response-media embedding before final completion; do not run proof-video-specific PII/sensitive-data detection or replacement.
    - If this work used an inline Plan, include the scenarios, acceptance criteria, and test evidence in the deploy message.
    - If no Plan exists for source changes, confirm the change is trivial/mechanical or include an explicit skip reason.

4. **Deploy** (lint + commit + push):
   ```bash
   python3 scripts/sessions.py deploy --session <SESSION_ID> \
     --title "type: short description" \
     --message "Longer explanation of why"
   ```

   For larger user-visible web/UI changes, do not include `--end` on the deploy
   command yet. After Vercel is Ready and Playwright evidence is green, run a
   Playwright visual smoke on the deployed route(s) in both laptop and mobile
   viewports, checking obvious rendering defects, implementation-related error
   text, long loading/spinner states, and basic primary-control responsiveness
   where practical. Prefer:
   ```bash
   node frontend/apps/web_app/scripts/visual-smoke.mjs \
     --url https://app.dev.openmates.org/<route> \
     --session <SESSION_ID>
   ```
   If you use a different Playwright screenshot/report artifact, record it:
   ```bash
    python3 scripts/sessions.py visual-smoke --session <SESSION_ID> \
      --url https://app.dev.openmates.org/<route> \
      --viewport laptop \
      --viewport mobile \
      --result passed \
      --method playwright \
      --run-id <playwright-artifact> \
      --summary "Checked laptop and mobile rendering, implementation error text, loading states, and responsiveness smoke."
   ```
   Use Firecrawl only as an explicit fallback when Playwright is impractical or
   blocked; keep calls minimal and record why. Fix objective issues, redeploy,
   and rerun the smoke.
   End only after that record exists:
   ```bash
   python3 scripts/sessions.py end --session <SESSION_ID>
   ```
   Use `--skip-visual-smoke "reason"` only for Tier 0/non-visual work.

### Commit Message Format
- Prefix: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`, `style:`, `perf:`, `ci:`, `revert:`
- Imperative present tense: "change" not "changed"
- For bug fixes, use structured format: `Symptom:`, `Cause:`, `Fix:`
- Contract-governed commits include `Contracts:`, `Assertions:`, `Spec:`, and `Contract-Impact:` trailers. Releases aggregate these trailers.

### If Deploy Fails
- **Lint errors:** Fix them first, then retry
- **Pre-existing hook bug** (unrelated to your changes): Use `--no-verify` and add a backlog entry
- **Worktree integration blocked:** Resolve the root integration conflict, check `python3 scripts/sessions.py status`, then rerun the same deploy command
- **Never** use raw `git commit` — it bypasses session tracking

### After Deploy
Write the task completion summary with the commit SHA from the deploy output.
For non-trivial work, include `Spec:`, `Tests:`, and for larger UI work
`Visual smoke:` lines in the summary.
