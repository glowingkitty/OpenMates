# Testing Rules

Rules for creating and running tests. For detailed commands, Playwright patterns, and test runner reference, run:
`python3 scripts/sessions.py context --doc testing-ref`

---

## Rule 1: Never Create Tests Without Consent

Never create test files without the user's explicit consent. When you see a testing opportunity, make a brief natural-language suggestion. Wait for explicit approval before writing any test code.

**Exception:** If the user says "use TDD", follow the red/green/refactor cycle.

## Rule 2: Test Behavior, Not Implementation

- Verify _what_ happens, not _how_
- Each test runs in isolation, no shared state
- Cover edge cases: empty inputs, null values, boundaries, error paths
- Use descriptive names: `test_encrypt_message_with_empty_content_returns_empty_encrypted_blob`
- Follow AAA pattern: Arrange → Act → Assert

## Rule 3: E2E Tests — Plan Before Code (CRITICAL)

Before writing any Playwright spec:

1. Write the test plan in natural language, get user approval
2. Read a `skill-*.spec.ts` file as the baseline template for skill tests, or `chat-flow.spec.ts` for general chat tests
3. Investigate DOM interactions for complex components
4. If a spec fails and you need to debug interactively, use Firecrawl browser to investigate

Key Playwright patterns:

- Use `toContainText('text', { timeout: 45000 })` for AI responses — never poll loading indicators
- Use `test.setTimeout(120000)` with `test.slow()`
- Use `page.keyboard.type()` for TipTap editor — never `fill()`
- Never click editor content area after inserting an embed (triggers fullscreen)
- ALL specs MUST run via Docker — never `npx playwright test` locally

### Unified Skill Spec Structure

Each app skill has a single `skill-{app}-{skill}.spec.ts` file with 4 sequential test phases:

1. **Embed preview** — verifies `/dev/preview/embeds/{app}` renders correctly (no login needed)
2. **CLI direct command** — `openmates apps {app} {skill} --json` returns valid results
3. **CLI chat send** — `openmates chats new "message"` triggers the skill via chat
4. **Web UI chat** — login → send message → verify embed renders → open fullscreen → cleanup

All chat phases use `withLiveMockMarker()` — the full backend pipeline always runs, only external API calls (LLM + HTTP) are cached. **Never use `withMockMarker()` which skips the pipeline.**

### Shared Test Helpers

Use the shared helpers in `tests/helpers/` — **never** copy-paste login/chat functions into individual specs:

```typescript
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { runCli, deriveApiUrl, parseCliJson } = require('./helpers/cli-test-helpers');
const { verifyEmbedPreviewPage, waitForEmbedFinished, openFullscreen, verifySearchGrid, closeFullscreen } = require('./helpers/embed-test-helpers');
```

All parameters in chat helpers are optional with defaults — `loginToTestAccount(page)` works for simple cases.

## Rule 4: Wait for Vercel Before E2E

After pushing frontend changes, wait ~150s for Vercel deployment. Verify with `vercel ls open-mates-webapp` — must show "Ready". Never use `curl` to check.

## Rule 5: Unexpected Screen? Ask the User

If a Playwright test encounters a completely unexpected screen, stop and ask the user how to proceed instead of guessing.

## Rule 6: Pre-PR Test Gate

Before any `dev` → `main` PR: run `python3 scripts/run_tests.py`, verify `test-results/last-run.json` shows all passed within last 30 minutes.

## Test Locations

| Type            | Location                                               | Naming                         |
| --------------- | ------------------------------------------------------ | ------------------------------ |
| Python unit     | `backend/apps/<app>/tests/` or `backend/core/*/tests/` | `test_*.py`                    |
| TypeScript unit | `frontend/packages/ui/src/**/__tests__/`               | `*.test.ts`                    |
| Playwright E2E  | `frontend/apps/web_app/tests/`                         | `*.spec.ts`                    |
| Skill E2E       | `frontend/apps/web_app/tests/`                         | `skill-{app}-{skill}.spec.ts`  |
| Test helpers    | `frontend/apps/web_app/tests/helpers/`                 | `*-test-helpers.ts`            |
| REST API        | `backend/tests/`                                       | `test_rest_api_*.py`           |

## Rule 7: New Features Require E2E Test Proposal (CRITICAL)

After implementing any new **auth flow, payment flow, or user-facing feature**, you MUST propose an E2E test plan. See CLAUDE.md "New Features Require E2E Test Proposal" for the full rule.

## Rule 8: Prefer Playwright Specs Over Firecrawl for Verification

For feature/fix verification, prefer writing or extending Playwright `*.spec.ts` tests over one-off Firecrawl browser sessions. Specs are repeatable, automated, and don't consume Firecrawl API quota. Reserve Firecrawl for **debugging** when a spec fails and you need to manually investigate the deployed app.

## Rule 9: Sidebar-Closed Default & Cold-Boot Verification

- **Sidebar-closed**: Always test chat-related features with sidebar defaulting to closed (<=1440px viewport). Five bugs were caused by stores assuming the sidebar component was mounted.
- **Cold boot**: After fixing chat/navigation/sync bugs, verify by clearing IndexedDB and localStorage, then reloading. Five bugs only manifested on cold boot.

## Rule 10: Use Shared Console Monitor (CRITICAL)

All E2E spec files MUST use the shared console monitor (`tests/console-monitor.ts`) instead of inline console log boilerplate:

```typescript
// ✅ CORRECT — use shared console monitor
const {
  test,
  expect,
  consoleLogs,
  networkActivities,
  attachConsoleListeners,
  attachNetworkListeners,
} = require("./console-monitor");

// Inside your test:
attachConsoleListeners(page);
attachNetworkListeners(page);
```

```typescript
// ❌ WRONG — DO NOT copy-paste console boilerplate into individual spec files
const consoleLogs: string[] = [];
page.on('console', (msg) => { ... });
```

**What the console monitor provides:**

- Auto-captures all console messages and page errors
- **Auto-fails tests** on unexpected console.error messages (with a configurable allowlist for known benign errors like favicon 404s, CSP violations, service worker noise)
- Aggregates repeating log messages (grouped by text, sorted by frequency)
- Forwards log summaries to OpenObserve via the api-reporter for observability
- Populates `console_logs` in failure notification emails (previously always null)
- Provides `saveWarnErrorLogs(id, phase)` for multi-phase tests like `chat-flow.spec.ts`

**Allowlisted benign error patterns** (see `BENIGN_ERROR_PATTERNS` in console-monitor.ts):

- `favicon.ico`, `net::ERR_*`, `Failed to load resource: the server responded`, `Content Security Policy`, `[ChatDatabase]`, `service worker`, `workbox`, `DevTools`, `chrome-extension://`, `js.stripe.com`, `ResizeObserver loop`

## Rule 11: Use `data-testid` for E2E Selectors

New E2E test selectors MUST use `data-testid` attributes on Svelte components:

```svelte
<!-- In component -->
<button data-testid="chat-send-button" on:click={send}>Send</button>
```

```typescript
// In spec file
page.getByTestId("chat-send-button");
// or: page.locator('[data-testid="chat-send-button"]')
```

**Naming convention:** `{domain}-{element}[-{variant}]`

- Examples: `chat-send-button`, `settings-menu-toggle`, `sidebar-new-chat`, `message-user`, `message-assistant`

**Why:** CSS class selectors (`.send-button`) break when classes are renamed for styling. `data-testid` attributes are stable, explicit test contracts.

**Keep `getByRole`** for accessibility-semantic locators (buttons, links, menu items) where the role+name is stable.

## Rule 12: Check Test Coverage with sessions.py

Use `check-tests` to discover existing tests and get instructions on what to create/update:

```bash
# Check tests for all files in current session
python3 scripts/sessions.py check-tests --session <ID>

# Check tests for a specific file
python3 scripts/sessions.py check-tests --file path/to/component.svelte
```

## What to Run After Changes

| Change Type            | Tests                                                                     |
| ---------------------- | ------------------------------------------------------------------------- |
| Backend API endpoint   | `pytest -s backend/tests/test_rest_api_external.py`                       |
| Backend auth changes   | `pytest backend/tests/test_auth_endpoints.py -v`                          |
| Backend business logic | `pytest backend/apps/<app>/tests/`                                        |
| Frontend component     | `npm run test:unit -- <component>.test.ts`                                |
| Full user flow         | Playwright E2E via Docker                                                 |
| Any push to dev        | Daily test runner (`scripts/run-tests-daily.sh`) covers all suites        |
