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

The daily cron job (`run_tests.py --daily`) runs every night and saves results locally:

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

## Additional Test Rules

- **NEVER run vitest, pnpm test, or npx vitest locally.** It crashes the server. Always use `python3 scripts/run_tests.py --suite vitest` which dispatches to GitHub Actions.
- **NEVER run Playwright specs locally or via docker compose.** Always use `python3 scripts/run_tests.py --spec <name>.spec.ts` or `python3 scripts/run_tests.py --suite playwright`. This dispatches specs to GitHub Actions where they run with proper test accounts and infrastructure. The docker compose commands in the testing doc are reference only — they describe what the CI runner executes, not what you should run.
- **New features require E2E test proposal:** After implementing any auth flow, payment flow, or user-facing feature, propose an E2E test plan (user flow, assertions, which spec to extend). Wait for user confirmation before writing test code.
- **Sidebar-closed as default:** Always test chat features with sidebar closed (default <=1440px).
- **Cold-boot verification:** After fixing chat/nav/sync bugs, verify by clearing IndexedDB + localStorage, then reload.
- **Use Playwright specs for verification, not Firecrawl.** Specs are repeatable and don't consume API quota. Reserve Firecrawl for debugging when a spec fails.

## Test-First Enforcement (Mandatory)

Every bug fix and feature MUST follow this test-first workflow. No exceptions unless `--skip-tests` is used at deploy time with an explicit reason.

### Bug Fixes

1. **Check for existing spec:** Run `sessions.py check-tests --session <id>` immediately after reading the issue.
2. **Spec exists → run it first:** Run `python3 scripts/run_tests.py --spec <name>.spec.ts` to confirm the spec reproduces the bug (expect red/failure). If the spec passes, the bug may not be covered — extend the spec or create a targeted one.
3. **No spec exists → propose a test plan:** Before writing any fix code, propose a minimal E2E test that would reproduce the bug (user flow, assertions, which spec to create or extend). Wait for user confirmation.
4. **Fix the bug.**
5. **Run the spec again:** Confirm it passes (green). This is the proof the fix works.

### Features

1. **Implement the feature.**
2. **Check for existing spec:** Run `sessions.py check-tests --session <id>`.
3. **Spec exists → extend it:** Add assertions for the new behavior. Run to confirm green.
4. **No spec exists → propose a test plan:** For user-facing features, propose an E2E test (user flow, assertions, which spec to create or extend). Wait for user confirmation, then write and run.
5. **Run related specs:** Ensure no regressions in adjacent functionality.

### Exempt Changes (no spec required)

- Documentation-only changes (`.md` files, comments, docstrings)
- i18n/translation updates (`.yml` source files only)
- Config/infra changes (`Caddyfile`, `docker-compose`, CI workflows)
- Purely cosmetic CSS changes with no behavior change

### Deploy Gate

`sessions.py deploy` will warn when source files have related specs that weren't run during the session. Use `--skip-tests "reason"` to bypass with an explicit justification logged to the commit.
