# End-to-End Tests (Playwright)

This folder contains Playwright end-to-end tests that exercise the deployed web app
via the Playwright Docker image. The tests are designed to validate real user flows
across signup, 2FA enrollment, and payment.

## Test Inventory

- `signup-flow.spec.ts`
  - Full signup flow: email verification, password setup, 2FA enrollment, credit
    purchase, and entry into the chat experience.
  - Captures step-by-step screenshots in `frontend/apps/web_app/tests/artifacts/`.
  - Emits `[SIGNUP_FLOW]` log checkpoints to make test progress obvious in CI logs.

## Required Environment Variables

- `SIGNUP_TEST_EMAIL_DOMAINS` (comma-separated list of allowed test domains)
- `MAILOSAUR_API_KEY` (Mailosaur API key for inbox polling)
- `MAILOSAUR_SERVER_ID` (optional if domain is `<server>.mailosaur.net`)
- `PLAYWRIGHT_TEST_BASE_URL` (base URL for the deployed web app under test)

## Run Tests (Docker Playwright Image)

From the repo root:

### Run All Tests

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  playwright
```

### Run a Specific Test File

Provide a test file through `PLAYWRIGHT_TEST_FILE` to avoid overriding the
container command:

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  -e PLAYWRIGHT_TEST_FILE="tests/signup-flow.spec.ts" \
  playwright
```

### Run Tests Matching a Pattern

Use `PLAYWRIGHT_TEST_GREP` to filter tests by name (case-insensitive regex):

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  -e PLAYWRIGHT_TEST_GREP="signup" \
  playwright
```

### Run a Single Test by Title

For an exact test match, provide the full test title:

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  -e PLAYWRIGHT_TEST_GREP="full signup flow" \
  playwright
```

## Artifacts

- Current run screenshots: `frontend/apps/web_app/tests/artifacts/*.png`
- Previous run screenshots: `frontend/apps/web_app/tests/artifacts/previous_run/*.png`
  - On each run, any existing screenshots are moved into `previous_run/`.
  - Existing screenshots inside `previous_run/` are removed first.
