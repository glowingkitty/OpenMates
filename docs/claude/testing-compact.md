# Testing Rules (Compact)

Full reference: `sessions.py context --doc testing`

## Rules

- **R1** Never create tests without user consent. Suggest first, wait for approval
- **R2** Test behavior, not implementation. AAA pattern. Descriptive names
- **R3** E2E: plan in natural language first, get approval, then code. Read `chat-flow.spec.ts` as template
- **R4** Wait ~150s for Vercel after push. Check with `vercel ls` — must show "Ready"
- **R5** Unexpected screen in Playwright? Stop and ask user
- **R6** Pre-PR: run `./scripts/run-tests.sh --all`, verify last-run.json all passed
- **R7** New auth/payment/user features MUST have E2E test proposal
- **R8** Prefer Playwright specs over Firecrawl for verification
- **R9** Test with sidebar closed (<=1440px). Cold-boot verify (clear IndexedDB+localStorage)
- **R10** Use shared console monitor (`tests/console-monitor.ts`). Never inline console boilerplate
- **R11** Use `data-testid` for E2E selectors. Format: `{domain}-{element}[-{variant}]`
- **R12** Use `sessions.py check-tests --session <ID>` to discover existing tests

## Test Locations

| Type            | Location                        | Naming               |
| --------------- | ------------------------------- | -------------------- |
| Python unit     | `backend/apps/<app>/tests/`     | `test_*.py`          |
| TypeScript unit | `frontend/**/src/**/__tests__/` | `*.test.ts`          |
| Playwright E2E  | `frontend/apps/web_app/tests/`  | `*.spec.ts`          |
| REST API        | `backend/tests/`                | `test_rest_api_*.py` |

## What to Run After Changes

| Change             | Command                                             |
| ------------------ | --------------------------------------------------- |
| Backend API        | `pytest -s backend/tests/test_rest_api_external.py` |
| Backend auth       | `pytest backend/tests/test_auth_endpoints.py -v`    |
| Backend logic      | `pytest backend/apps/<app>/tests/`                  |
| Frontend component | `npm run test:unit -- <component>.test.ts`          |
| Full user flow     | Playwright E2E via Docker                           |
| Any push to dev    | GitHub Actions CI runs automatically                |
