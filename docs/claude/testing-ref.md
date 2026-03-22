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

## E2E Mock/Replay System (LLM & App Skills)

Many E2E specs trigger real LLM inference and external API calls (web search, travel, etc.), which cost money per run. The mock/replay system lets tests use pre-recorded responses instead, controlled by the `E2E_USE_MOCKS` env var.

### How It Works

1. **Marker in message text**: When `E2E_USE_MOCKS=1`, the `withMockMarker()` helper appends a `<<<TEST_MOCK:fixture_id>>>` marker to the chat message
2. **Backend detects marker**: In `ask_skill_task.py`, the marker is detected and stripped before processing
3. **Fixture replay**: Instead of calling the real LLM/skill APIs, pre-recorded events are published to the same Redis channels
4. **Everything else is real**: WebSocket, encryption, billing preflight, postprocessing, persistence, frontend rendering — all unchanged

### What's Mocked vs Real

| Layer | Mock Mode | Real Mode |
|-------|-----------|-----------|
| WebSocket, encryption, IndexedDB | **Real** | Real |
| Preprocessing LLM call (title, category, model) | Mocked (fixture data) | Real |
| Credit check & billing preflight | **Real** (validates fixture's model ID) | Real |
| **LLM provider API call** | **Mocked** — fixture stream chunks | Real |
| **Skill external APIs** (Brave, YouTube, etc.) | **Mocked** — fixture skill results | Real |
| Postprocessing (suggestions, persistence) | **Real** | Real |

### Running Tests in Mock Mode

```bash
# With mocks (zero API cost):
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e E2E_USE_MOCKS=1 \
  -e PLAYWRIGHT_TEST_FILE="chat-flow.spec.ts" playwright

# Without mocks (real APIs, full integration):
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_FILE="chat-flow.spec.ts" playwright
```

### Multi-Turn Conversations

Each message in a multi-turn chat gets its own fixture ID. Each turn maps to a separate Celery task, so each needs its own recorded response:

```typescript
await page.keyboard.type(withMockMarker('Write a function', 'code_gen_turn1'));
// ... wait for response ...
await page.keyboard.type(withMockMarker('Add error handling', 'code_gen_turn2'));
// ... wait for response ...
await page.keyboard.type(withMockMarker('Refactor to class', 'code_gen_turn3'));
```

### Speed Profiles

Fixtures include a `speed_profile` that controls simulated streaming speed. Override per-test via the marker:

| Profile | Delay | Use case |
|---------|-------|----------|
| `instant` | 0ms | CI (default) — fastest execution |
| `fast` | 5ms/chunk | Simulates ~500 tps (Cerebras, Groq) |
| `medium` | 20ms/chunk | Simulates ~150 tps (GPT-4o, Sonnet) |
| `slow` | 50ms/chunk | Simulates ~60 tps — for streaming UX tests |

```typescript
// Override speed for streaming behavior tests:
withMockMarker('Explain gravity', 'chat_scroll_test', 'slow')
// → appends <<<TEST_MOCK:chat_scroll_test:slow>>>
```

### Recording New Fixtures

To record a real response as a fixture:

1. Use `withRecordMarker()` in the spec (or manually add `<<<TEST_RECORD:fixture_id>>>` to the message)
2. Run the test against real APIs — the backend captures all events and saves to `backend/apps/ai/testing/fixtures/{fixture_id}.json`
3. Switch back to `withMockMarker()` for subsequent runs

```typescript
// One-time recording:
await page.keyboard.type(withRecordMarker('Capital of Germany?', 'chat_flow_capital'));
// → runs real LLM, saves fixture to backend/apps/ai/testing/fixtures/chat_flow_capital.json

// Then switch to mock for all future runs:
await page.keyboard.type(withMockMarker('Capital of Germany?', 'chat_flow_capital'));
```

### Fixture File Format

Fixtures are JSON files in `backend/apps/ai/testing/fixtures/`:

```json
{
  "fixture_id": "chat_flow_capital",
  "speed_profile": "instant",
  "preprocessing": {
    "can_proceed": true,
    "category": "general_knowledge",
    "title": "Capital of Germany",
    "selected_model_id": "anthropic/claude-sonnet-4-20250514",
    "steps": [...]
  },
  "response": "The capital of Germany is Berlin.",
  "skill_executions": [],
  "usage": { "prompt_tokens": 150, "completion_tokens": 12 }
}
```

Fixtures store only the full `response` text. Stream chunks are generated at replay time by splitting at sentence/paragraph boundaries. This keeps fixtures small and human-editable.

### Security

- Mock markers are **ignored in production** (`SERVER_ENVIRONMENT == "production"`)
- The testing module is never imported in production environments
- Fixture files contain only recorded AI responses, no secrets

### Key Files

| File | Purpose |
|------|---------|
| `backend/apps/ai/testing/mock_replay.py` | Marker detection, fixture loading, Redis replay |
| `backend/apps/ai/testing/fixture_recorder.py` | Records real responses as fixture files |
| `backend/apps/ai/testing/fixtures/` | Fixture JSON files |
| `backend/apps/ai/tasks/ask_skill_task.py` | Interception point (~40 lines) |
| `frontend/apps/web_app/tests/signup-flow-helpers.ts` | `withMockMarker()`, `withRecordMarker()` |

### Instrumented Specs

All specs that send chat messages are instrumented with `withMockMarker()`. Fixtures must be recorded before mock mode works for each spec. See the fixture ID in each spec's `withMockMarker()` call.

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
