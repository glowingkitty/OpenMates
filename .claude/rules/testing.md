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

## Additional Test Rules

- **NEVER run vitest, pnpm test, or npx vitest locally.** It crashes the server. Always use `python3 scripts/run_tests.py --suite vitest` which dispatches to GitHub Actions.
- **NEVER run Playwright specs locally or via docker compose.** Always use `python3 scripts/run_tests.py --spec <name>.spec.ts` or `python3 scripts/run_tests.py --suite playwright`. This dispatches specs to GitHub Actions where they run with proper test accounts and infrastructure. The docker compose commands in the testing doc are reference only — they describe what the CI runner executes, not what you should run.
- **New features require E2E test proposal:** After implementing any auth flow, payment flow, or user-facing feature, propose an E2E test plan (user flow, assertions, which spec to extend). Wait for user confirmation before writing test code.
- **Sidebar-closed as default:** Always test chat features with sidebar closed (default <=1440px).
- **Cold-boot verification:** After fixing chat/nav/sync bugs, verify by clearing IndexedDB + localStorage, then reload.
- **Use Playwright specs for verification, not Firecrawl.** Specs are repeatable and don't consume API quota. Reserve Firecrawl for debugging when a spec fails.
