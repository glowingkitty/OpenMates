---
description: Testing standards — E2E, unit tests, Playwright patterns
globs:
  - "**/*.spec.ts"
  - "**/*.test.ts"
  - "**/tests/**"
  - "frontend/apps/web_app/tests/**"
  - "backend/tests/**"
---

@docs/contributing/guides/testing.md

## Daily Test Results — Where to Find Them

The daily cron job (`tests.py run --daily`) runs every night through the unified test control plane and saves results locally:

| File | Contents |
|------|----------|
| `test-results/daily-run-YYYY-MM-DD.json` | Full daily run results (all suites, all tests) |
| `test-results/last-failed-tests.json` | Just the failures from the latest daily run |
| `test-results/last-passed-tests.json` | Just the passes from the latest daily run |
| `test-results/reports/failed/*.md` | Per-test MD reports for each failed test |
| `test-results/reports/success/*.md` | Per-test MD reports for each passed test |
| `test-results/last-run.json` | Last individual run (may be a subset — check `run_id`) |

**When asked to fix test failures:** Use `/fix-tests` skill, or start by reading `test-results/last-failed-tests.json` — it has the exact failure count, test names, and error messages. Then read the individual MD reports in `test-results/reports/failed/` for full error context.

**Do NOT** re-download results from GitHub Actions or re-run tests just to see what failed — the results are already local.

## Investigating a Failing E2E Spec

When a specific spec fails and needs deep investigation, use the **`e2e-test-investigator`** subagent. Spawn one per failing spec for parallel investigation.

**Key principle: screenshots are ground truth.** Error messages in failure reports often describe downstream symptoms, not root causes. Always read `test-results/screenshots/current/<spec-folder>/test-failed-*.png` AND the last successful step screenshot.

### Manual investigation checklist (if not using the subagent)

1. **Read the failure report:** `test-results/reports/failed/<spec-name>.md`
2. **Read screenshots:** `test-results/screenshots/current/<spec-folder>/` — compare what the test expected vs. what's actually on screen
3. **Query OpenObserve for client console logs from the test run:**
   ```bash
   docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json \
     '{"stream":"client_console","filters":[{"field":"debugging_id","op":"like","value":"%<spec-name>%"}],"since_minutes":120,"limit":50}'
   ```
4. **Query backend logs for related errors:**
   ```bash
   docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json \
     '{"stream":"default","filters":[{"field":"level","op":"in","value":["ERROR","WARNING"]},{"field":"message","op":"like","value":"%<keyword>%"}],"since_minutes":120,"limit":30}'
   ```
5. **Read the spec code** to understand what step failed and what was expected
6. **Read the frontend component** involved in the failing step
7. **Check for regressions:** `git log -5 --oneline -- <component-file>`

### E2E Debug Log Pipeline

All Playwright specs use `getE2EDebugUrl()` which injects `#e2e-debug={runId}-{specName}&e2e-token={hmac}` into the URL. The frontend detects this at page load and starts forwarding all console logs to OpenObserve via `POST /e2e/client-logs`, tagged with the run ID. This works pre-login, so the full test flow (including login/signup) is captured.

### Common E2E failure patterns

| Pattern | Symptom | Typical Cause |
|---------|---------|---------------|
| Element not found, screenshot shows different page | Session lost, user redirected | Auth token expired, refresh token revoked |
| "No verification code" error | Email code rejected | Cache miss race (Celery hasn't written code yet) or email collision between batched tests |
| Timeout on iframe/overlay | Spinner or empty area visible | Provider iframe failed to load, CSP block, nesting issue |
| Element visible but click times out | Overlay blocking pointer events | Consent/modal overlay with `pointer-events: all` on top |
| Spec passes alone, fails in batch | Intermittent/flaky | Shared state: email collision, test account reuse, DB conflict |

## Additional Test Rules

- **New functionality verification order:** Test new functionality in OpenMates CLI first, web app `*.spec.ts` second, and Apple app third when there is a native counterpart. CLI evidence is the cheapest and fastest proof of backend/API/WebSocket correctness; Playwright proves browser-specific Svelte/TipTap/IndexedDB/user-interaction behavior; Apple verification proves native parity. Do not skip directly to Playwright for shared product behavior unless the change is clearly browser-only.
- **Cross-app parity order:** For chat, AI pipeline, settings-backed chat behavior, app skills, embeds, sync, or any feature that exists across clients, the same CLI → web → Apple order is mandatory. If a chat-related Playwright spec fails and no matching CLI contract exists, write or propose the minimal CLI contract before changing the web spec, unless the failure is clearly browser-only (selector, layout, screenshot, pointer-event overlay, or Svelte-only rendering).
- When a spec failure points to a repeated flaky pattern, first look for a
  deterministic helper or audit improvement that would prevent the class of
  failure across specs. Prefer shared helpers and `scripts/audit_*` checks over
  one-off sleeps or per-spec workarounds.
- **NEVER use CSS class selectors in tests.** All element targeting MUST use `data-testid` attributes with `page.getByTestId('name')`. CSS classes are styling concerns and break when CSS changes.
  - Bad: `page.locator('.send-button')`, `page.locator('.chat-title')`
  - Good: `page.getByTestId('send-button')`, `page.getByTestId('chat-title')`
  - For scoped queries: `container.getByTestId('name')` or `page.getByTestId('parent').getByTestId('child')`
  - For elements with state: `page.locator('[data-testid="chat-item-wrapper"].active')` or use data attributes
  - For elements with data attributes: `page.locator('[data-testid="embed-preview"][data-status="finished"]')`
  - When adding `data-testid` to components, use kebab-case matching the element's purpose
  - Acceptable non-class selectors: `#id`, `[data-action="..."]`, `[data-authenticated="..."]`, `getByRole()`, `getByText()`
- **NEVER run vitest, pnpm test, or npx vitest locally.** It crashes the server. Always use `python3 scripts/tests.py run --suite vitest` which dispatches to GitHub Actions and records status/history.
- **NEVER run Playwright specs locally or via docker compose.** Always use `python3 scripts/tests.py run --spec <name>.spec.ts` or `python3 scripts/tests.py run --suite playwright`. This dispatches specs to GitHub Actions where they run with proper test accounts and infrastructure, and records status/history through the unified control plane. The docker compose commands in the testing doc are reference only — they describe what the CI runner executes, not what you should run.
- **New features require E2E test proposal:** After implementing any auth flow, payment flow, or user-facing feature, propose an E2E test plan (user flow, assertions, which spec to extend). Wait for user confirmation before writing test code.
- **Sidebar-closed as default:** Always test chat features with sidebar closed (default <=1440px).
- **Cold-boot verification:** After fixing chat/nav/sync bugs, verify by clearing IndexedDB + localStorage, then reload.
- **Use Playwright specs for verification, not Firecrawl.** Specs are repeatable and don't consume API quota. Reserve Firecrawl for debugging when a spec fails.
- **Apple impact check:** For changes to chat, sync, auth, settings, embeds, billing, shared UI, app chrome, or provider result rendering, check whether the Apple app has a counterpart. If affected and the session runs on Linux, you MUST attempt the redacted remote Mac wrapper `python3 scripts/apple_remote.py status` followed by `build-ios` or `test-ios` from `docs/contributing/guides/testing.md` / `apple/AGENTS.md` before saying Apple verification is unavailable. Record Mac/Xcode evidence or a sanitized failure class such as `ssh_failed`, `project_not_found`, or `xcode_build_failed`. Use `Apple not affected` only when there is no Apple counterpart.

## Test-First Enforcement (Mandatory)

Every bug fix and feature MUST follow this test-first workflow. No exceptions unless `--skip-tests` is used at deploy time with an explicit reason.

### Bug Fixes

1. **Check for existing spec:** Run `sessions.py check-tests --session <id>` immediately after reading the issue.
2. **Spec exists → run it first:** Run `python3 scripts/tests.py run --spec <name>.spec.ts` to confirm the spec reproduces the bug (expect red/failure). If the spec passes, the bug may not be covered — extend the spec or create a targeted one.
3. **No spec exists → propose a test plan:** Before writing any fix code, propose a minimal E2E test that would reproduce the bug (user flow, assertions, which spec to create or extend). Wait for user confirmation.
4. **Fix the bug.**
5. **Run the spec again:** Confirm it passes (green). This is the proof the fix works.

### Features

1. **Plan the verification ladder:** identify the CLI command/contract, web `*.spec.ts`, and Apple `scripts/apple_remote.py test-ios` or `build-ios` evidence required for the feature. If no Apple counterpart exists, record `Apple not affected`.
2. **Implement the feature.**
3. **CLI first:** add or run the OpenMates CLI proof before Playwright for shared product behavior.
4. **Check for existing web spec:** Run `sessions.py check-tests --session <id>`.
5. **Spec exists → extend it:** Add assertions for the new behavior. Run to confirm green.
6. **No spec exists → propose a test plan:** For user-facing features, propose an E2E test (user flow, assertions, which spec to create or extend). Wait for user confirmation, then write and run.
7. **Apple third:** after CLI and web evidence are green, run or attempt Apple verification with `scripts/apple_remote.py` when the feature has an Apple counterpart.
8. **Run related specs:** Ensure no regressions in adjacent functionality.

### Exempt Changes (no spec required)

- Documentation-only changes (`.md` files, comments, docstrings)
- i18n/translation updates (`.yml` source files only)
- Config/infra changes (`Caddyfile`, `docker-compose`, CI workflows)
- Purely cosmetic CSS changes with no behavior change

### Deploy Gate

`sessions.py deploy` will warn when source files have related specs that weren't run during the session. Use `--skip-tests "reason"` to bypass with an explicit justification logged to the commit.
