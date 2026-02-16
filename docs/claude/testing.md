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
- **Account for Vercel deployment delay**: After pushing frontend changes, Vercel takes up to **200 seconds** to deploy. E2E tests must wait for the deployment to complete before running against the live URL (e.g., poll the site or add an explicit delay).
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
| Full user flow         | Playwright E2E for that flow                        |

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

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  -e PLAYWRIGHT_TEST_FILE="signup-flow.spec.ts" \
  playwright
```

---

## Pre-Commit Test Checklist (When Tests Exist)

- [ ] Tests actually fail when the code is broken (not just passing trivially)
- [ ] Tests cover the happy path AND at least one error path
- [ ] Tests don't depend on external services (mock them)
- [ ] Test names describe the scenario being tested
- [ ] No `time.sleep()` or arbitrary waits (use proper async/await)