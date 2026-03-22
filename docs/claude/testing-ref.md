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

## Test Runner (`scripts/run_tests.py`)

```bash
python3 scripts/run_tests.py --suite vitest           # Unit tests only (local)
python3 scripts/run_tests.py --suite pytest            # Pytest only (local)
python3 scripts/run_tests.py                           # Full suite (local + GitHub Actions)
python3 scripts/run_tests.py --only-failed             # Rerun failures
python3 scripts/run_tests.py --spec chat-flow.spec.ts  # Single Playwright spec
python3 scripts/run_tests.py --suite playwright        # All E2E specs via GitHub Actions
python3 scripts/run_tests.py --daily                   # Cron mode (commit gate, emails)
python3 scripts/run_tests.py --daily --force           # Skip commit check
python3 scripts/run_tests.py --max-concurrent 10       # Override batch size (default: 20)
python3 scripts/run_tests.py --no-fail-fast            # Run all batches even on failure
python3 scripts/run_tests.py --dry-run                 # Show what would run
```

Playwright specs are dispatched to GitHub Actions (`playwright-spec.yml`) in batches of 20 concurrent runners, each with a separate test account (`OPENMATES_TEST_ACCOUNT_1_EMAIL` through `20`). Batch-level fail-fast: current batch finishes, then stops if any failures.

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

## Unified Skill Spec Architecture

Each app skill has a single `skill-{app}-{skill}.spec.ts` file that validates the complete lifecycle in 4 sequential phases:

### The 4-Phase Pattern

```
Phase 1: Embed preview     → /dev/preview/embeds/{app} renders (no login, static mock data)
Phase 2: CLI direct command → openmates apps {app} {skill} --json returns results
Phase 3: CLI chat send      → openmates chats new "message" triggers the skill
Phase 4: Web UI chat        → login → send → verify embed → fullscreen → cleanup
```

### Existing Skill Specs

| Spec File | App | Skill | Has CLI Phase? |
|-----------|-----|-------|:-:|
| `skill-web-search.spec.ts` | web | search | Yes |
| `skill-web-read.spec.ts` | web | read | Yes |
| `skill-videos-search.spec.ts` | videos | search | Yes |
| `skill-videos-transcript.spec.ts` | videos | get_transcript | Yes |
| `skill-images-search.spec.ts` | images | search | Yes |
| `skill-news-search.spec.ts` | news | search | Yes |
| `skill-travel-connections.spec.ts` | travel | search_connections | Yes |
| `skill-travel-stays.spec.ts` | travel | search_stays | Yes |
| `skill-maps-search.spec.ts` | maps | search | Yes |
| `skill-math-calculate.spec.ts` | math | calculate | Yes |
| `skill-events-search.spec.ts` | events | search | Yes |
| `skill-shopping-search.spec.ts` | shopping | search_products | Yes |
| `skill-health-appointments.spec.ts` | health | search_appointments | Yes |
| `skill-code-docs.spec.ts` | code | get_docs | Yes |
| `skill-reminder-set.spec.ts` | reminder | set-reminder | No (stateful) |

### Shared Test Helpers

Located in `tests/helpers/`. All parameters are optional with sensible defaults.

**`chat-test-helpers.ts`** — Chat interaction helpers:
- `loginToTestAccount(page, logCheckpoint?, takeStepScreenshot?)` — email/password/OTP login with retry
- `startNewChat(page, logCheckpoint?)` — click new chat button (handles sidebar-closed)
- `sendMessage(page, message, logCheckpoint?, takeStepScreenshot?, stepLabel?)` — type + send
- `deleteActiveChat(page, logCheckpoint?, takeStepScreenshot?, stepLabel?)` — context menu delete

**`cli-test-helpers.ts`** — CLI process helpers:
- `runCli(apiUrl, args, timeoutMs?)` — spawn CLI, capture stdout/stderr
- `deriveApiUrl(baseUrl)` — convert Playwright base URL to API URL
- `parseCliJson(result)` — parse and validate CLI JSON output

**`embed-test-helpers.ts`** — Embed assertion helpers:
- `verifyEmbedPreviewPage(page, app, logCheckpoint)` — Phase 1 full check
- `waitForEmbedFinished(page, appId, skillId, timeout?)` — wait for `data-status="finished"`
- `openFullscreen(page, embedLocator)` — click → overlay visible
- `verifySearchGrid(overlay, minResults?)` — `.search-template-grid` has N+ cards
- `closeFullscreen(page, overlay)` — minimize button → verify hidden

---

## Live Mock System (LLM & HTTP Caching)

The live mock system runs the **full backend pipeline** (preprocessing, inference, skill execution, postprocessing, billing) but intercepts external API calls with cached record-and-replay responses. This tests everything except the parts that cost money.

**Important:** Always use `withLiveMockMarker()`. Never use the old `withMockMarker()` which skips the entire pipeline.

### How It Works

1. **Marker in message text**: `withLiveMockMarker()` appends `<<<TEST_LIVE_MOCK:group_id>>>` or `<<<TEST_LIVE_RECORD:group_id>>>` to the message
2. **Backend detects marker**: `mock_context.py` sets per-request context vars (`mock_mode_var`, `mock_group_var`)
3. **LLM calls intercepted**: `caching_llm_wrapper.py` wraps provider functions — cache hit returns stored response, cache miss in record mode calls real API and saves
4. **HTTP calls intercepted**: `caching_http_transport.py` wraps httpx — same cache-or-record pattern
5. **Everything else is real**: WebSocket, encryption, preprocessing, postprocessing, billing, persistence, frontend rendering — all unchanged

### What's Cached vs Real

| Layer | Live Mock Mode | Real Mode |
|-------|----------------|-----------|
| WebSocket, encryption, IndexedDB | **Real** | Real |
| Preprocessing (title, category, model selection) | **Real** | Real |
| Credit check & billing | **Real** | Real |
| **LLM provider API call** | **Cached** — replay from `api_cache/` | Real |
| **Skill HTTP requests** (Brave, Doctolib, REWE, etc.) | **Cached** — replay from `api_cache/` | Real |
| Postprocessing (suggestions, persistence) | **Real** | Real |

### Running Tests

```bash
# Record cached responses (first run per skill — hits real APIs):
E2E_RECORD_LIVE_FIXTURES=1 npx playwright test skill-web-search.spec.ts

# Replay cached responses (subsequent runs / CI — zero API cost):
E2E_USE_LIVE_MOCKS=1 npx playwright test skill-web-search.spec.ts

# Real APIs (full integration, real costs):
npx playwright test skill-web-search.spec.ts
```

### Cache Storage

Cached responses are stored in `backend/apps/ai/testing/api_cache/`:

```
api_cache/
├── {group_id}/
│   ├── llm__openai/
│   │   └── {fingerprint}.json
│   ├── llm__claude/
│   │   └── {fingerprint}.json
│   └── brave__search/
│       └── {fingerprint}.json
```

Each cache file contains:
```json
{
  "fingerprint": "abc123def456",
  "category": "llm/openai",
  "group_id": "web_search_cli",
  "recorded_at": "2026-03-22T12:00:00Z",
  "request": { "model": "...", "messages_count": 5, "last_message_preview": {...} },
  "response": { "type": "stream", "body": "Full response text...", "chunk_count": 42 }
}
```

### Fingerprinting

Request fingerprinting ensures deterministic cache hits. Volatile fields (API keys, timestamps, request IDs) are excluded from the hash.

**LLM calls**: Hash of model + messages + tools + temperature + tool_choice
**HTTP calls**: Hash of method + host + path + sorted query params + normalized body

### Group IDs

Each test uses a unique `group_id` to namespace cached responses:

```typescript
withLiveMockMarker('Search for AI news', 'news_search_web')  // group_id = "news_search_web"
withLiveMockMarker('Search for AI news', 'news_search_cli')  // group_id = "news_search_cli"
```

Convention: `{app}_{skill}_{context}` where context is `web`, `cli`, or a descriptive name.

### Security

- Live mock mode requires `MOCK_EXTERNAL_APIS=true` env var
- Mock markers are **ignored in production** (`SERVER_ENVIRONMENT == "production"`)
- The testing modules are never imported in production environments
- Cache files contain only recorded API responses, no secrets

### Key Files

| File | Purpose |
|------|---------|
| `backend/shared/testing/api_response_cache.py` | Cache storage, fingerprinting, load/save |
| `backend/shared/testing/mock_context.py` | Marker detection, per-request context vars |
| `backend/shared/testing/caching_http_transport.py` | httpx transport wrapper for HTTP caching |
| `backend/apps/ai/testing/caching_llm_wrapper.py` | LLM provider wrapper for response caching |
| `backend/apps/ai/testing/api_cache/` | Cached response JSON files |
| `frontend/apps/web_app/tests/signup-flow-helpers.ts` | `withLiveMockMarker()`, `withLiveRecordMarker()` |

### Legacy Fixture System

The old `withMockMarker()` / fixture replay system still exists in `backend/apps/ai/testing/mock_replay.py` and `fixtures/` for backward compatibility. It skips the entire pipeline and replays pre-recorded Redis events. **Do not use it for new tests** — use `withLiveMockMarker()` instead.

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
