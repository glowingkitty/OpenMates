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
2. Read `chat-flow.spec.ts` as the baseline template
3. Investigate DOM interactions for complex components
4. If a spec fails and you need to debug interactively, use Firecrawl browser to investigate

Key Playwright patterns:

- Use `toContainText('text', { timeout: 45000 })` for AI responses — never poll loading indicators
- Use `test.setTimeout(120000)` with `test.slow()`
- Use `page.keyboard.type()` for TipTap editor — never `fill()`
- Never click editor content area after inserting an embed (triggers fullscreen)
- ALL specs MUST run via Docker — never `npx playwright test` locally

## Rule 4: Wait for Vercel Before E2E

After pushing frontend changes, wait ~150s for Vercel deployment. Verify with `vercel ls open-mates-webapp` — must show "Ready". Never use `curl` to check.

## Rule 5: Unexpected Screen? Ask the User

If a Playwright test encounters a completely unexpected screen, stop and ask the user how to proceed instead of guessing.

## Rule 6: Pre-PR Test Gate

Before any `dev` → `main` PR: run `./scripts/run-tests.sh --all`, verify `test-results/last-run.json` shows all passed within last 30 minutes.

## Test Locations

| Type            | Location                                               | Naming               |
| --------------- | ------------------------------------------------------ | -------------------- |
| Python unit     | `backend/apps/<app>/tests/` or `backend/core/*/tests/` | `test_*.py`          |
| TypeScript unit | `frontend/packages/ui/src/**/__tests__/`               | `*.test.ts`          |
| Playwright E2E  | `frontend/apps/web_app/tests/`                         | `*.spec.ts`          |
| REST API        | `backend/tests/`                                       | `test_rest_api_*.py` |

## Rule 7: New Features Require E2E Test Proposal (CRITICAL)

After implementing any new **auth flow, payment flow, or user-facing feature**, you MUST propose an E2E test plan. See CLAUDE.md "New Features Require E2E Test Proposal" for the full rule.

## Rule 8: Prefer Playwright Specs Over Firecrawl for Verification

For feature/fix verification, prefer writing or extending Playwright `*.spec.ts` tests over one-off Firecrawl browser sessions. Specs are repeatable, automated, and don't consume Firecrawl API quota. Reserve Firecrawl for **debugging** when a spec fails and you need to manually investigate the deployed app.

## Rule 9: Sidebar-Closed Default & Cold-Boot Verification

- **Sidebar-closed**: Always test chat-related features with sidebar defaulting to closed (<=1440px viewport). Five bugs were caused by stores assuming the sidebar component was mounted.
- **Cold boot**: After fixing chat/navigation/sync bugs, verify by clearing IndexedDB and localStorage, then reloading. Five bugs only manifested on cold boot.

## What to Run After Changes

| Change Type            | Tests                                                                     |
| ---------------------- | ------------------------------------------------------------------------- |
| Backend API endpoint   | `pytest -s backend/tests/test_rest_api_external.py`                       |
| Backend auth changes   | `pytest backend/tests/test_auth_endpoints.py -v`                          |
| Backend business logic | `pytest backend/apps/<app>/tests/`                                        |
| Frontend component     | `npm run test:unit -- <component>.test.ts`                                |
| Full user flow         | Playwright E2E via Docker                                                 |
| Any push to dev        | GitHub Actions CI runs automatically (vitest, pytest, svelte-check, i18n) |
