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

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  playwright
```

## Artifacts

- Current run screenshots: `frontend/apps/web_app/tests/artifacts/*.png`
- Previous run screenshots: `frontend/apps/web_app/tests/artifacts/previous_run/*.png`
  - On each run, any existing screenshots are moved into `previous_run/`.
  - Existing screenshots inside `previous_run/` are removed first.
