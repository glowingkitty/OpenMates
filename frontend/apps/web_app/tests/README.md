# End-to-End Tests (Playwright)

This folder contains Playwright end-to-end tests that exercise the deployed web app
via the Playwright Docker image. The tests are designed to validate real user flows
across signup, 2FA enrollment, and payment.

## Test Inventory

- `signup-flow.spec.ts`
  - Full signup flow: email verification, password setup, 2FA enrollment, credit
    purchase, and entry into the chat experience.
  - Captures step-by-step screenshots in `playwright-artifacts/`.
  - Emits `[SIGNUP_FLOW]` log checkpoints to make test progress obvious in CI logs.

- `signup-flow-passkey.spec.ts`
  - Passkey signup flow: email verification, passkey registration (WebAuthn PRF),
    credit purchase, and entry into the chat experience.
  - Uses Playwright virtual authenticator via CDP to handle WebAuthn prompts.
  - Emits `[SIGNUP_PASSKEY]` log checkpoints.

- `chat-flow.spec.ts`
  - Automated login to an existing account using email/password + 2FA.
  - Validates end-to-end chat functionality by sending a test message and checking for a specific response.
  - Deletes the chat after validation to ensure test cleanup.
  - Emits `[CHAT_FLOW]` log checkpoints and captures screenshots.

## Shared Helpers

Common functionality used across signup tests is extracted into `signup-flow-helpers.ts` to ensure consistency and reduce code duplication. This includes:
- Screenshot and logging helpers
- Mailosaur client for email polling
- Stripe card detail filling
- TOTP generation for 2FA
- Signup domain and email generation logic

## Required Environment Variables

- `SIGNUP_TEST_EMAIL_DOMAINS` (comma-separated list of allowed test domains)
- `MAILOSAUR_API_KEY` (Mailosaur API key for inbox polling)
- `MAILOSAUR_SERVER_ID` (optional if domain is `<server>.mailosaur.net`)
- `OPENMATES_TEST_ACCOUNT_EMAIL` (Email for the automated chat test)
- `OPENMATES_TEST_ACCOUNT_PASSWORD` (Password for the automated chat test)
- `OPENMATES_TEST_ACCOUNT_OTP_KEY` (2FA secret for the automated chat test)
- `PLAYWRIGHT_TEST_BASE_URL` (base URL for the deployed web app under test)

## Run Tests (Docker Playwright Image)

From the repo root:

### Load Secrets from .env

The tests automatically load secrets from the root `.env` file when run via Docker Compose. Ensure the following variables are set in your `.env`:

```env
OPENMATES_TEST_ACCOUNT_EMAIL=...
OPENMATES_TEST_ACCOUNT_PASSWORD=...
OPENMATES_TEST_ACCOUNT_OTP_KEY=...
SIGNUP_TEST_EMAIL_DOMAINS=...
MAILOSAUR_API_KEY=...
```

### Run All Tests

```bash
docker compose -f docker-compose.playwright.yml run --rm playwright
```

### Run a Specific Test File

Provide a test file through `PLAYWRIGHT_TEST_FILE`. Use just the filename (without the `tests/` prefix, since `testDir` is already set to `tests` in the Playwright config):

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_FILE="chat-flow.spec.ts" \
  playwright
```

### Run Tests Matching a Pattern

Use `PLAYWRIGHT_TEST_GREP` to filter tests by name (case-insensitive regex):

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  -e PLAYWRIGHT_TEST_GREP="passkey" \
  playwright
```

## Artifacts

- Current run screenshots: `playwright-artifacts/*.png`
- Previous run screenshots: `playwright-artifacts/previous_run/*.png`
  - On each run, any existing screenshots are moved into `previous_run/`.
  - Existing screenshots inside `previous_run/` are removed first.
