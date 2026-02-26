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

### E2E Test Planning (CRITICAL — do this BEFORE writing any code)

**Before writing any Playwright spec file, you MUST use Firecrawl to validate all planned interactions live in a real browser first.** Only once every step works correctly in Firecrawl should you write the Playwright spec.

#### Step 0: Validate with Firecrawl Browser (MANDATORY)

1. **Create a Firecrawl browser session** using `firecrawl_browser_create`
2. **Execute each planned interaction step-by-step** using `firecrawl_browser_execute` with `agent-browser` commands:
   - Navigate to the page
   - Take a `snapshot` to inspect the DOM (use `agent-browser snapshot -i -c` for interactive elements)
   - Perform each click, type, fill, etc. and confirm it works
   - Take screenshots at key steps to verify the UI state
3. **Debug any failures immediately** — fix your understanding of selectors, element refs, or interaction order before writing Playwright code
4. **Only proceed to write the spec once ALL steps complete successfully** in Firecrawl

This prevents wasted iterations from unanticipated interaction side-effects discovered only after writing the full spec.

---

**Before writing any Playwright spec file, you MUST also:**

1. **Write the test plan in natural language first** — describe each user action as a numbered step (e.g., "click the map icon", "type Berlin Hbf", "press send"). Do NOT write code yet.
2. **Get user approval** on the plan before implementing.
3. **Investigate DOM interactions** — for each step that touches a complex component (editor, map, overlay, modal), read the source to understand:
   - What CSS selectors/elements are involved
   - What side effects the interaction triggers (e.g., clicking an embed card opens fullscreen)
   - Where the cursor/focus lands after the action
4. **Read `chat-flow.spec.ts` first** — it is the simplest passing test and defines the proven patterns for login, message sending, and response assertion. Use it as the baseline template. Key patterns to copy:
   - Use `toContainText('expected text', { timeout: 45000 })` to wait for AI responses — do NOT poll for loading indicators to disappear
   - Use `test.setTimeout(120000)` with `test.slow()` (triples timeout to 360s) — not 300s as base
   - Use `page.keyboard.type()` to type into the TipTap editor — never `fill()`

Skipping the planning step leads to failed iterations from unanticipated interaction side-effects (overlays blocking clicks, wrong selectors, etc.) that waste much more time than planning upfront.

---

### TipTap Editor Interaction in Playwright

The message editor uses TipTap (ProseMirror). Key gotchas for E2E tests:

- **Never click the editor content area after inserting an embed** — the click may land on an embed card node, triggering its fullscreen overlay, which then intercepts subsequent clicks (including the send button). Instead, call `page.keyboard.type()` directly — embed insertion helpers like `insertMap()` call `editor.commands.focus("end")` to position the cursor after the embed automatically.
- **Use `page.keyboard.type()`, not `editorContent.fill()`** — TipTap is not a native input; `fill()` does not work. Always type via the keyboard as shown in `chat-flow.spec.ts`.
- **If a fullscreen overlay accidentally opens**, press `await page.keyboard.press('Escape')` before continuing.

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

## Test Runner (`scripts/run-tests.sh`)

A unified test runner that orchestrates vitest, pytest, and Playwright suites,
producing structured JSON results for LLM-readable debugging.

### Quick Reference

```bash
# Run unit tests only (fast — vitest + pytest unit, no live API or Playwright)
./scripts/run-tests.sh --suite vitest
./scripts/run-tests.sh --suite pytest

# Run all suites including Playwright (5 parallel workers)
./scripts/run-tests.sh

# Run all suites including pytest integration tests (hit live API)
./scripts/run-tests.sh --all

# Rerun only tests that failed in the last run
./scripts/run-tests.sh --only-failed

# Run Playwright with fewer workers (e.g. only 2 accounts available)
./scripts/run-tests.sh --suite playwright --workers 2
```

### Multi-Account Parallel Playwright

The runner assigns spec files round-robin to worker slots (1–5). Each slot
uses a separate test account to avoid session collisions. Account credentials
are loaded from numbered env vars in `.env`:

```
OPENMATES_TEST_ACCOUNT_1_EMAIL=...
OPENMATES_TEST_ACCOUNT_1_PASSWORD=...
OPENMATES_TEST_ACCOUNT_1_OTP_KEY=...
OPENMATES_TEST_ACCOUNT_2_EMAIL=...
...
OPENMATES_TEST_ACCOUNT_5_EMAIL=...
```

Spec files call `getTestAccount()` from `signup-flow-helpers.ts`, which reads
`PLAYWRIGHT_WORKER_SLOT` (set by the worker) to pick the right credentials.
Falls back to the base `OPENMATES_TEST_ACCOUNT_*` vars when slots are not set.

### Output Format

Results are written to `test-results/run-<timestamp>.json` and
`test-results/last-run.json`. The JSON schema:

```json
{
  "run_id": "2026-02-25T10:30:00Z",
  "git_sha": "abc1234",
  "git_branch": "dev",
  "flags": { "unit_only": true, "only_failed": false, "suite": "all" },
  "duration_seconds": 847,
  "summary": { "total": 52, "passed": 50, "failed": 2, "skipped": 0 },
  "suites": {
    "vitest": { "status": "passed", "duration_seconds": 8, "tests": [...] },
    "pytest_unit": { "status": "passed", "duration_seconds": 22, "tests": [...] },
    "pytest_integration": { "status": "skipped", "reason": "--unit-only" },
    "playwright": {
      "status": "failed", "duration_seconds": 720, "workers": 5,
      "tests": [
        { "file": "chat-flow.spec.ts", "slot": 2, "status": "failed",
          "duration_seconds": 45, "error": "Expected 'Hello' but got timeout",
          "stdout": "...(truncated to ~5000 chars)..." }
      ]
    }
  }
}
```

---

## Sequential Test Debugging Workflow (`scripts/run-tests-sequential.sh`)

**CRITICAL: When the user asks to "run the E2E tests", "start end-to-end testing", or "work through
the Playwright specs", use THIS workflow — not `run-tests.sh`.** The sequential runner processes
one spec at a time, automatically debugging failures with Firecrawl before moving on.

A lightweight script for running Playwright specs **one at a time** with progress tracking.
Designed for iterative debugging: run a test, if it passes continue, if it fails debug with
Firecrawl browser, fix, re-run, repeat.

### Quick Reference

```bash
# Check progress (how many passed/failed/remaining)
./scripts/run-tests-sequential.sh --status

# Run the next unprocessed spec
./scripts/run-tests-sequential.sh --next

# Run a specific spec (shorthand without .spec.ts works too)
./scripts/run-tests-sequential.sh --spec chat-flow
./scripts/run-tests-sequential.sh --spec chat-flow.spec.ts

# Use a specific test account slot (default: 1)
./scripts/run-tests-sequential.sh --next --slot 2

# Manually mark a spec (passed/failed/skipped)
./scripts/run-tests-sequential.sh --mark chat-flow passed
./scripts/run-tests-sequential.sh --mark signup-flow skipped

# Start over
./scripts/run-tests-sequential.sh --reset
```

### Progress Tracking

Results are tracked in `test-results/progress.txt` (gitignored). Format:

```
PASSED chat-flow.spec.ts
FAILED signup-flow.spec.ts
SKIPPED dev-preview.spec.ts
```

- **`--next`** picks the first spec (alphabetically) not yet in the progress file
- When a spec **passes**, it is auto-recorded as `PASSED` and `--next` advances
- When a spec **fails**, it is recorded as `FAILED` and the script stops with debug instructions
- Re-running a spec (via `--spec` or `--mark`) **overwrites** its previous entry

### Debug Workflow (When a Spec Fails)

**CRITICAL: Follow this exact sequence. Do NOT just edit the spec blindly.**

1. **Reproduce in Firecrawl browser** — create a browser session and manually walk through the
   user flow that the spec tests. This reveals what the actual app state looks like:

   ```
   → firecrawl_browser_create
   → agent-browser open https://app.dev.openmates.org
   → agent-browser snapshot -i -c    (inspect interactive elements)
   → Walk through each test step manually (login, navigate, click, type, etc.)
   → agent-browser screenshot         (capture what you see)
   ```

2. **Identify the root cause** — common causes of spec failures:
   - **Selector changed**: A CSS class, `data-testid`, or DOM structure was modified
   - **Timing issue**: An element takes longer to appear than the test expects
   - **Backend change**: An API response format changed or a new field is required
   - **UI flow changed**: A new modal, redirect, or step was added to the user flow
   - **Environment issue**: Test credentials expired, deployment not ready, etc.

3. **Fix the root cause** — either:
   - Fix the **app code** if the spec is testing correct behavior that broke
   - Fix the **spec file** if the app behavior is correct but the test is stale

4. **Verify the fix in Firecrawl first** — re-walk the flow to confirm it works before
   running the full Playwright spec (which takes longer due to Docker overhead)

5. **Re-run the spec**:

   ```bash
   ./scripts/run-tests-sequential.sh --spec <failed-spec-name>
   ```

6. **Continue to next** once it passes:
   ```bash
   ./scripts/run-tests-sequential.sh --next
   ```

### When to Use `--mark`

- **`--mark <spec> skipped`**: Skip a spec that's known-broken for reasons outside your scope
  (e.g., depends on a third-party service that's down). Come back to it later.
- **`--mark <spec> passed`**: Manually mark as passed if you've verified it works outside the
  script (e.g., ran it via `docker compose` directly).
- **`--mark <spec> failed`**: Record a failure without re-running (e.g., you know it's broken
  from a previous session).

### Relationship to `run-tests.sh`

|                 | `run-tests.sh`                      | `run-tests-sequential.sh`               |
| --------------- | ----------------------------------- | --------------------------------------- |
| **Purpose**     | Full suite run (CI/pre-PR gate)     | One-at-a-time debug workflow            |
| **Parallelism** | Up to 5 workers                     | Single spec, single slot                |
| **Output**      | `test-results/last-run.json` (JSON) | `test-results/progress.txt` (text)      |
| **Best for**    | Final validation                    | Iterative debugging and fixing          |
| **On failure**  | Records all results, exits          | Stops with Firecrawl debug instructions |

---

## Pre-PR Test Checklist (CRITICAL — before any dev → main PR)

Before creating a PR from `dev` to `main`, you **MUST**:

1. Run: `./scripts/run-tests.sh --all`
2. Read `test-results/last-run.json`
3. Verify ALL suites show `"status": "passed"`
4. Verify `run_id` timestamp is within the last 30 minutes
5. If any test failed, fix it or get explicit user approval before proceeding
6. Do NOT create the PR if tests have not been run recently or have failures

---

## Pre-Commit Test Checklist (When Tests Exist)

- [ ] Tests actually fail when the code is broken (not just passing trivially)
- [ ] Tests cover the happy path AND at least one error path
- [ ] Tests don't depend on external services (mock them)
- [ ] Test names describe the scenario being tested
- [ ] No `time.sleep()` or arbitrary waits (use proper async/await)
