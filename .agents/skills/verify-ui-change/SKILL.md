---
name: verify-ui-change
description: Verify UI and Playwright changes against their exact source in isolated GitHub CI, then deploy and visually smoke the resulting dev revision when needed.
user-invocable: true
argument-hint: "<spec-name>.spec.ts [--account N]"
---

# Verify UI Change

Use this skill when a web UI, Playwright, embed, settings, chat, or Apple/web
parity change needs browser verification. It composes existing OpenMates
guardrails; it does not replace `sessions.py deploy`, `scripts/tests.py`, or
`scripts/verify_parity.py`.

## Policy

Browser E2E and component proof run before deployment against the exact candidate
inside isolated GitHub CI. They never require a Vercel deployment or shared-dev
runtime. Scoped `dev` deploys through `sessions.py deploy` remain pre-authorized
for assigned implementation work and post-deploy visual smoke.

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
   component spec first. It should navigate to
   `/dev/preview/{component-path}?chrome=0`. Isolated CI supplies the runner-local
   base URL. Every
   inspection, test, screenshot, and recording must include `chrome=0` and show
   only the component, never the configuration UI. Use the `.preview.ts` default
   fixture for the standard state and encode every non-default input or
   configuration in URL query parameters such as `variant`, `props`, `theme`,
   `background`, and `width`. Then
   assert meaningful hover, focus, click, expanded/collapsed, and on/off states
   before named proof checkpoints. Broader route or flow specs come after this
   focused component spec.

2. Ensure there is an active session and inspect blockers.
   ```bash
   python3 scripts/sessions.py status
   python3 scripts/sessions.py doctor --session <SESSION_ID>
   ```

3. Publish the immutable source and submit each relevant spec to isolated CI.
   ```bash
   python3 scripts/sessions.py ci-source --session <SESSION_ID>
   python3 scripts/ci_coordinator.py submit \
     --session <SESSION_ID> \
     --source <source-sha> \
     --spec <name>.spec.ts \
     --mode e2e
   python3 scripts/ci_coordinator.py wait <request-id>
   ```
   A multi-spec coordinator submission is split into one GitHub-hosted job per
   spec. Each job has its own disposable backend stack, database, accounts and
   runner-local web process. Never pass `--preview-url` for ordinary E2E.

4. Inspect the source-bound result and component artifact. A queued, running,
   stale, skipped or cleanup-incomplete job is not a pass. Fix objective defects
   and republish the candidate before continuing.

5. After isolated CI is green, perform the scoped deploy for assigned
   implementation work.
   ```bash
   python3 scripts/sessions.py deploy --session <SESSION_ID> \
     --title "type: short description" \
     --message "Why this UI/spec change is needed and isolated CI evidence"
   ```
   Wait for the exact Vercel commit only when the task also needs post-deploy
   readiness, manual confirmation or visual smoke. Deployment is not E2E setup.

6. For larger user-visible web/UI changes, run a deployed Playwright visual smoke
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

7. For cross-client work, prefer the parity wrapper after deploy.
   ```bash
   python3 scripts/verify_parity.py --run --web-spec <name>.spec.ts --apple build
   ```

## Failure Handling

- If `doctor` reports unrelated dirty files, keep the deploy scoped with tracked
  files, `--exclude`, or `--use-staged` for safe same-file hunks.
- If the spec is missing or untracked, include it in the immutable candidate;
  `ci-source` transports dirty candidate bytes without a branch or deploy.
- If candidate E2E fails, do not deploy merely to retry it. Inspect its isolated
  artifact, fix the cause, publish a new candidate and resubmit.
- If Vercel is not Ready after deployment, fix readiness before post-deploy
  visual smoke; this does not invalidate earlier exact-source E2E evidence.
- If the test fails, use `e2e-test-investigator` or `stabilize-e2e-pattern` for
  root-cause work rather than adding one-off waits.
- If visual smoke shows objective visual, error, loading, or responsiveness
  defects, fix them automatically, redeploy, and rerun it before completion.

## Output

Return a concise verification note:

```markdown
Source: <candidate sha>
Spec: <name>.spec.ts
Isolated CI: <request id and GitHub Actions run id>
Deployed commit: <sha or not required>
Visual smoke: <summary path/screenshot paths or skipped reason>
Result: <passed|failed|blocked>
Blocker: <only if blocked>
```
