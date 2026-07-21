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

- **New functionality phase gates:** Implement and test new shared functionality against the direct REST API/WebSocket contract first, OpenMates CLI against the dev server second, npm SDK and pip SDK locally against the dev server third, web app fourth, user confirmation fifth, and Apple app last when there is a native counterpart. Direct API evidence must classify endpoint access as unauthenticated public REST API, developer API-key REST API, first-party client surface only, or internal-only, and must state auth, rate limits, credit/budget limits, and whether client-side encrypted data or decrypted plaintext is handled. Endpoints that accept or return client-side encrypted chat, memory, file, key, sync, or share material must default to first-party or internal-only access unless a spec explicitly approves a narrower public/developer contract that preserves encryption boundaries. Dev-server REST/API evidence must pass before CLI, SDK, web, or Apple work starts; dev-server CLI evidence must pass before SDK, web, or Apple work starts; local dev-server SDK evidence must pass before web or Apple work starts when the behavior is exposed programmatically. Only after local REST/API, CLI, and SDK tests pass should the same coverage be reproduced or wired into GitHub Actions for CI/daily tests. REST/API, CLI, and SDK gates must use real requests/commands/SDK calls against the real dev API/WebSocket path with real auth/test-account state; mocked `fetch`, mocked SDK clients, stubbed local servers, direct function calls, and fixture replay are supplemental only and never satisfy these gates. Do not start a later client while an earlier phase is unimplemented, untested, or blocked unless the spec or session contract records an explicit user-approved waiver or accepted external blocker.
- **Dev server API updates:** On this dev machine, `https://api.dev.openmates.org` points at the local Docker-backed dev API. If direct REST/API, CLI, or SDK proof needs newly changed backend code, restart the relevant local Docker service, usually `api`, under the Docker lock before probing the dev URL. Do not wait for GitHub self-host image publishes to update `api.dev.openmates.org`; image publishes are for released/self-host artifacts, not the live dev API process.
- **Cross-app parity order:** For chat, AI pipeline, settings-backed chat behavior, app skills, focus modes, embeds, memory types, provider-backed behavior, sync, billing, notifications, benchmark behavior, or any feature that exists across clients, the same REST/API → CLI → SDK → web → user confirmation → Apple order is mandatory. Direct REST/API evidence is the cheapest proof of backend/API/WebSocket contract, access model, auth, rate-limit, and encryption-boundary correctness and must be run locally against `https://api.dev.openmates.org` before CLI, SDK, GitHub Actions CI reproduction, or Playwright; Playwright proves browser-specific Svelte/TipTap/IndexedDB/user-interaction behavior; user confirmation proves the deployed web behavior works and looks correct; Apple verification proves native parity. Run `python3 scripts/audit_sdk_cli_parity.py` when the CLI or SDK surface changes. If a chat-related Playwright spec fails and no matching REST/API plus CLI/SDK contract exists, write or propose the minimal contract before changing the web spec, unless the failure is clearly browser-only (selector, layout, screenshot, pointer-event overlay, or Svelte-only rendering).
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

1. **Plan the phase ladder:** identify the direct REST API/WebSocket contract, endpoint access model, auth/rate-limit/credit budget requirements, encryption-boundary constraints, CLI command/contract, npm SDK contract, pip SDK contract, web `*.spec.ts`, required user confirmation, and Apple `scripts/apple_remote.py test-ios` or `build-ios` evidence required for the feature. If no Apple counterpart exists, record `Apple not affected`.
2. **REST/API first:** implement the backend contract and add or run direct REST/WebSocket proof against the dev server before CLI, SDK, web, or Apple work. The proof must hit the real dev API/WebSocket path, must not mock OpenMates API calls, and must verify expected 401/403/429 or budget errors for the endpoint access model when relevant.
3. **CLI second:** implement the CLI path and add or run the real CLI proof against the dev server before SDK, web, or Apple work. The proof must hit the real dev API/WebSocket path and must not mock OpenMates API calls.
4. **SDK parity third:** implement and test npm SDK and pip SDK parity locally against the dev server for the same behavior when it is exposed programmatically. Run `python3 scripts/audit_sdk_cli_parity.py` when the CLI or SDK surface changes. After local REST/API, CLI, and SDK evidence is green, reproduce or wire the same coverage into GitHub Actions for CI/daily tests.
5. **Web fourth:** check for an existing web spec with `sessions.py check-tests --session <id>`, then extend or propose the needed Playwright spec. Run it only after deploy through `python3 scripts/tests.py run --spec <name>.spec.ts`.
6. **User confirmation fifth:** for user-visible web UI or behavior, ask the user to confirm the deployed dev web app works and looks correct. A passing `*.spec.ts` is not enough to start Apple parity.
7. **Apple last:** after REST/API, CLI, SDK, web, and required user-confirmation evidence are complete, run or attempt Apple verification with `scripts/apple_remote.py` when the feature has an Apple counterpart.
8. **Run related specs:** Ensure no regressions in adjacent functionality.

### Exempt Changes (no spec required)

- Documentation-only changes (`.md` files, comments, docstrings)
- i18n/translation updates (`.yml` source files only)
- Config/infra changes (`Caddyfile`, `docker-compose`, CI workflows)
- Purely cosmetic CSS changes with no behavior change

### Deploy Gate

`sessions.py deploy` will warn when source files have related specs that weren't run during the session. Use `--skip-tests "reason"` to bypass with an explicit justification logged to the commit.
