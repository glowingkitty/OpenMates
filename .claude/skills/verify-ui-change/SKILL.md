---
name: verify-ui-change
description: Deploy a scoped UI or Playwright spec change to dev, wait for Vercel, dispatch the relevant .spec.ts, then run reviewed Playwright visual smoke for larger UI work.
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
   For UI elements, components, and screens, identify or create the focused
   component spec first. It should target
   `https://app.dev.openmates.org/dev/preview/{component-path}`, render one
   semantically valid default state from `.preview.ts` data when needed, and
   assert meaningful hover, focus, click, expanded/collapsed, and on/off states
   before named proof checkpoints. Broader route or flow specs come after this
   focused component spec.

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
   guards root integration and commit/push with the dev deploy verification
   lock, and records verification state for the resulting commit; use
   `wait-lock` only for diagnostics/manual inspection.

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

   For every modified UI component, publish the focused component proof video in
   the OpenCode response. Use separate phone and laptop proof profiles only when
   responsive behavior differs. Derive still frames from the completed video only
   for failures, explicit requests, or ambiguous visual-intent inspection; do not
   add screenshot galleries or browser-side screenshot calls for component proof.

5. For larger user-visible web/UI changes, run a deployed Playwright visual smoke
   against the affected `app.dev.openmates.org` route(s) after Playwright and
   before user confirmation or session completion. The helper captures laptop and
   mobile screenshots and hard-fails console/page/network/layout problems; it
   intentionally records `blocked` until the screenshots are reviewed:
   ```bash
   node frontend/apps/web_app/scripts/visual-smoke.mjs \
     --url https://app.dev.openmates.org/<route> \
     --session <SESSION_ID>
   ```

   Open the generated laptop and mobile PNGs. If objective visual defects appear
   (clipping, overlap, overflow, hidden controls, broken media, error text, long
   loading, or unresponsive primary controls), fix, redeploy, rerun Playwright if
   affected, and rerun visual smoke. If the screenshots are acceptable, record the
   pass explicitly:
   ```bash
   python3 scripts/sessions.py visual-smoke --session <SESSION_ID> \
     --url https://app.dev.openmates.org/<route> \
     --viewport laptop \
     --viewport mobile \
     --result passed \
     --method playwright \
     --run-id test-results/visual-smoke/<run>/summary.json \
     --summary "Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none."
   ```

   Use Firecrawl only as an explicit fallback when Playwright is impractical or
   blocked; keep calls minimal and record why. Skip only for Tier 0/non-visual
   work with `--skip-visual-smoke "reason"`.

6. For cross-client work, prefer the parity wrapper after deploy.
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
- If visual smoke shows objective visual, error, loading, or responsiveness
  defects, fix them automatically, redeploy, and rerun it before completion.

## Output

Return a concise verification note:

```markdown
Commit: <sha>
Spec: <name>.spec.ts
Run: <GitHub Actions run id or test-results run id>
Visual smoke: <summary path/screenshot paths or skipped reason>
Result: <passed|failed|blocked>
Blocker: <only if blocked>
```
