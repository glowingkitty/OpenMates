---
name: verify-ui-change
description: Deploy a scoped UI or Playwright spec change to dev, wait for Vercel, then dispatch the relevant .spec.ts through the GitHub Actions test control plane.
user-invocable: true
argument-hint: "<spec-name>.spec.ts [--account N]"
---

# Verify UI Change

Use this skill when a web UI, Playwright, embed, settings, chat, or Apple/web
parity change needs browser verification. It composes existing OpenMates
guardrails; it does not replace `sessions.py deploy`, `scripts/tests.py`, or
`scripts/verify_parity.py`.

## Policy

Scoped `dev` deploys through `sessions.py deploy` are pre-authorized when they
are required to verify assigned work. Do not ask for permission just because a
Playwright `.spec.ts` must run against deployed `dev` code.

Ask first for production deploys, raw git commit/push, broad or unscoped dirty
deploys, destructive data/migrations, secrets, unclear privacy/billing/security
scope, same-file overlap that cannot be safely staged, or planning/review-only
requests.

Session edits should happen in the automatic worktree returned by
`python3 scripts/sessions.py worktree ensure --session <SESSION_ID>`. The root
checkout remains the orchestration control plane and the short-lived `dev`
integration point only.

## Workflow

1. Identify the exact Playwright spec and any account slot.
   ```bash
   python3 scripts/tests.py run --spec <name>.spec.ts --dry-run
   ```

2. Ensure there is an active session and inspect blockers.
   ```bash
   python3 scripts/sessions.py status
   python3 scripts/sessions.py doctor --session <SESSION_ID>
   ```

3. Preview and perform a scoped deploy.
   ```bash
   python3 scripts/sessions.py deploy-docs
   python3 scripts/sessions.py prepare-deploy --session <SESSION_ID>
   python3 scripts/sessions.py deploy --session <SESSION_ID> \
     --title "type: short description" \
     --message "Why this UI/spec change is needed"
   ```
   `sessions.py deploy` scopes the commit from the session worktree diff,
   integrates it to `dev`, and records verification state for the resulting
   commit; use `wait-lock` only for diagnostics/manual inspection.

4. Capture the deployed commit SHA from the deploy output. Use fast latest-ready
   verification for low-risk checks that do not need an exact deploy proof. Use
   exact-SHA verification for Playwright evidence, release-critical UI checks,
   or any case where a stale Ready deployment would be misleading.
   ```bash
   python3 scripts/tests.py run \
     --spec <name>.spec.ts \
     --gate-deploy \
     --expected-commit <commit-sha>
   ```

   If the spec needs a pinned account, include `--account N`.

5. For cross-client work, prefer the parity wrapper after deploy.
   ```bash
   python3 scripts/verify_parity.py --run --web-spec <name>.spec.ts --apple build
   ```

## Failure Handling

- If `doctor` reports unrelated dirty files, keep the deploy scoped with tracked
  files, `--exclude`, or `--use-staged` for safe same-file hunks.
- If the spec is missing or untracked, track and deploy it before dispatching;
  GitHub Actions cannot run local-only specs.
- If Vercel is not Ready, fix the deployment before rerunning browser evidence.
- If the test fails, use `e2e-test-investigator` or `stabilize-e2e-pattern` for
  root-cause work rather than adding one-off waits.

## Output

Return a concise verification note:

```markdown
Commit: <sha>
Spec: <name>.spec.ts
Run: <GitHub Actions run id or test-results run id>
Result: <passed|failed|blocked>
Blocker: <only if blocked>
```
