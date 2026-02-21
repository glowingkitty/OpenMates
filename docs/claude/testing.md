# Testing Policy

Load this document when creating or running tests.

---

## Test Creation Consent Requirements

**NEVER create test files without the user's explicit consent.** This applies to:

- Unit tests (pytest, vitest)
- Integration tests
- End-to-end tests (Playwright)
- Test fixtures or mocks

**What to do instead:**

1. When you identify a situation where tests might be valuable, make a **brief natural-language suggestion** describing what the tests could cover
2. Do NOT include code examples in test suggestions
3. Wait for the user to explicitly ask you to create the tests before writing any test code
4. If the user says "yes" or "go ahead", only then create the test files

**Exception - When user explicitly requests TDD:**
If the user says "use TDD" or explicitly asks to write tests first, follow the full TDD cycle:

1. 🔴 **Red**: Write a failing test that describes the desired behavior
2. 🟢 **Green**: Write the minimal code to make the test pass
3. 🔵 **Refactor**: Improve the code while keeping tests green

---

## What Makes Tests Actually Useful

When creating tests (with consent), ensure they meet these criteria:

### Good Tests Should:

- **Test behavior, not implementation**: Verify _what_ happens, not _how_
- **Be independent**: Each test runs in isolation, no shared state
- **Cover edge cases**: Empty inputs, null values, boundary conditions, error paths
- **Use descriptive names**: `test_encrypt_message_with_empty_content_returns_empty_encrypted_blob`
- **Follow AAA pattern**: Arrange → Act → Assert (clearly separated)
- **Be fast**: Unit tests should run quickly (< 100ms each)
- **Use meaningful assertions**: Verify the specific behavior you care about

### Tests to AVOID (Low Value):

- Testing private implementation details that may change
- Tests that duplicate framework/library tests
- Mocking so heavily that nothing real is tested
- Tests that pass with any implementation (too loose assertions)
- Trivial getter/setter tests with no logic

### End-to-End Tests Should:

- **Test user journeys**, not individual components
- **Use stable selectors**: `data-testid` attributes, not CSS classes
- **Be deterministic**: No flaky timing-dependent assertions
- **Cover critical paths**: Signup, login, payment, core features
- **Account for Vercel deployment delay**: After pushing frontend changes, Vercel takes up to **200 seconds** to deploy. Before running E2E tests, **wait ~150 seconds then verify the deployment status** with `vercel ls open-mates-webapp` — the latest entry must show "● Ready". Never use `curl` to check readiness; use the Vercel CLI.
- **Ask the user on unexpected screens**: If a Playwright test encounters a completely unexpected screen (e.g., a different page/layout than anticipated after an action), **stop and ask the user how to proceed** instead of guessing or failing silently.

---

## Test Location Standards

| Test Type               | Location                                               | Naming               |
| ----------------------- | ------------------------------------------------------ | -------------------- |
| Python unit tests       | `backend/apps/<app>/tests/` or `backend/core/*/tests/` | `test_*.py`          |
| TypeScript unit tests   | `frontend/packages/ui/src/**/__tests__/`               | `*.test.ts`          |
| Playwright E2E tests    | `frontend/apps/web_app/tests/`                         | `*.spec.ts`          |
| REST API external tests | `backend/tests/`                                       | `test_rest_api_*.py` |

---

## Running Tests After Changes

| Change Type            | Run These Tests                                     |
| ---------------------- | --------------------------------------------------- |
| Backend API endpoint   | `pytest -s backend/tests/test_rest_api_external.py` |
| Backend business logic | `pytest backend/apps/<app>/tests/`                  |
| Frontend component     | `npm run test:unit -- <component>.test.ts`          |
| Full user flow         | Playwright E2E via Docker (see E2E section below)   |

---

## Test Commands

### Backend

```bash
# Run all external REST API tests
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py

# Run specific skill tests
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py -k ask
```

### Frontend

```bash
# Run frontend unit tests
cd frontend/apps/web_app && npm run test:unit

# Run with coverage
npm run test:unit -- --coverage
```

### End-to-End (Playwright)

**CRITICAL: ALL `spec.ts` Playwright tests MUST be run via Docker.** Do NOT run `npx playwright test` locally — the local environment does not have the required browsers/dependencies and local runs are unreliable. Always use `docker-compose.playwright.yml`.

**CRITICAL: Always verify deployment before running E2E tests.** Playwright tests run against the deployed dev server (`https://app.dev.openmates.org`), NOT a local dev server. After pushing frontend changes, you MUST wait for the Vercel deployment to complete before running tests.

```bash
# 1. Wait for deployment (~150 seconds after push)
sleep 150

# 2. Verify deployment status — must show "● Ready"
vercel ls open-mates-webapp 2>&1 | head -5

# 3. Only then run the tests via Docker:

# Run a specific test file:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_FILE="<test-file>.spec.ts" \
  playwright

# Run tests matching a pattern (grep by test title):
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_GREP="<regex-pattern>" \
  playwright

# Run all tests:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm playwright

# Run signup/auth flows (needs extra env vars):
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_FILE="signup-flow.spec.ts" \
  playwright
```

**Environment variables:**

- `PLAYWRIGHT_TEST_FILE` — target a specific test file (e.g., `"login.spec.ts"`)
- `PLAYWRIGHT_TEST_GREP` — filter tests by title regex (e.g., `"should redirect"`)
- `PLAYWRIGHT_TEST_BASE_URL` — override the target URL (defaults to `https://app.dev.openmates.org`)
- Test credentials (`OPENMATES_TEST_ACCOUNT_EMAIL`, etc.) are loaded from `.env` via `--env-file`

**Why Docker only:**

- The dev server does not have Playwright browsers installed locally
- Local `npx playwright test` runs fail with missing browser errors
- The Docker image (`mcr.microsoft.com/playwright`) includes all required browsers and dependencies
- Docker ensures consistent, reproducible test runs across all sessions

**Artifacts:** Test screenshots and other artifacts are written to `./playwright-artifacts/` on the host (mounted into the container).

---

## Pre-Commit Test Checklist (When Tests Exist)

- [ ] Tests actually fail when the code is broken (not just passing trivially)
- [ ] Tests cover the happy path AND at least one error path
- [ ] Tests don't depend on external services (mock them)
- [ ] Test names describe the scenario being tested
- [ ] No `time.sleep()` or arbitrary waits (use proper async/await)
