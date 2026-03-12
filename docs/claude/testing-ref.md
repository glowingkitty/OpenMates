# Testing Reference

Detailed test commands, Playwright Docker setup, test runner reference, and sequential debugging workflow.
Load on demand: `python3 scripts/sessions.py context --doc testing-ref`

---

## Test Commands

### Backend

```bash
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py -k ask
```

### Frontend

```bash
cd frontend/apps/web_app && npm run test:unit
npm run test:unit -- --coverage
```

### Playwright E2E (Docker Only)

```bash
# Wait for deployment
sleep 150
vercel ls open-mates-webapp 2>&1 | head -5

# Run specific test:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_FILE="<test-file>.spec.ts" playwright

# Run with grep:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_GREP="<regex>" playwright

# Run all:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm playwright

# Signup flows:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL="${E2E_DEV_TEST_BASE_URL:-https://app.dev.openmates.org}" \
  -e PLAYWRIGHT_TEST_FILE="signup-flow.spec.ts" playwright 2>&1 | tail -200
```

**Env vars:** `PLAYWRIGHT_TEST_FILE`, `PLAYWRIGHT_TEST_GREP`, `PLAYWRIGHT_TEST_BASE_URL`
**Artifacts:** `./playwright-artifacts/`

---

## Test Runner (`scripts/run-tests.sh`)

```bash
./scripts/run-tests.sh --suite vitest          # Unit tests only
./scripts/run-tests.sh --suite pytest           # Pytest only
./scripts/run-tests.sh                          # All suites (5 parallel workers)
./scripts/run-tests.sh --all                    # Including pytest integration
./scripts/run-tests.sh --only-failed            # Rerun failures
./scripts/run-tests.sh --suite playwright --workers 2
```

Multi-account parallel Playwright: assigns specs round-robin to 5 worker slots with separate test accounts (`OPENMATES_TEST_ACCOUNT_1_EMAIL` through `5`).

Output: `test-results/run-<timestamp>.json` and `test-results/last-run.json`

---

## Sequential Test Debugging (`scripts/run-tests-sequential.sh`)

Use THIS workflow when asked to "run E2E tests" or "work through Playwright specs":

```bash
./scripts/run-tests-sequential.sh --status          # Progress
./scripts/run-tests-sequential.sh --next            # Next unprocessed spec
./scripts/run-tests-sequential.sh --spec chat-flow  # Specific spec
./scripts/run-tests-sequential.sh --mark chat-flow passed
./scripts/run-tests-sequential.sh --reset           # Start over
```

Progress tracked in `test-results/progress.txt`.

### Debug Workflow (When a Spec Fails)

1. Reproduce in Firecrawl browser — walk through user flow manually
2. Identify root cause (selector changed, timing, backend change, env issue)
3. Fix app code or spec file
4. Verify fix in Firecrawl first
5. Re-run: `./scripts/run-tests-sequential.sh --spec <name>`
6. Continue: `./scripts/run-tests-sequential.sh --next`

---

## TipTap Editor Interaction in Playwright

- Never click editor after inserting embed — triggers fullscreen overlay
- Use `page.keyboard.type()`, not `fill()` — TipTap is not a native input
- If fullscreen opens accidentally: `page.keyboard.press('Escape')`

---

## Pre-Commit Test Checklist

- [ ] Tests actually fail when code is broken
- [ ] Tests cover happy path AND at least one error path
- [ ] Tests don't depend on external services (mock them)
- [ ] No `time.sleep()` or arbitrary waits
