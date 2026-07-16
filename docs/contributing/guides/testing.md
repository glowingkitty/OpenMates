---
status: active
last_verified: 2026-06-11
---

# Testing Reference

Detailed test commands, Playwright Docker setup, test runner reference, and sequential debugging workflow.

---

## Test Commands

### New Functionality Phase Gates

For new shared functionality, implementation and verification must happen in this
order by default:

1. **OpenMates CLI first:** implement and test an OpenMates CLI command, real CLI
   chat, or CLI contract test against the dev server. This must pass on the dev
   server before any SDK, web, or Apple work starts. After the dev-server CLI
   proof is green, move the same coverage into the GitHub Actions test path so it
   runs in daily tests. This catches backend processing, model routing, skill
   invocation, embed resolution, sync, and WebSocket issues before browser state
   is involved.

   The CLI phase-gate proof must use real CLI commands against the real dev API
   and WebSocket services with real auth/test-account state. It must not be a
   mocked `fetch`, mocked SDK client, stubbed local server, direct function call,
   fixture replay, or unit test that bypasses the OpenMates API/WebSocket path.
   Mocked tests are useful as supplemental unit coverage only; they never satisfy
   the CLI-first gate. If an external paid provider would make the real command
   expensive, use a low-cost real request or record an explicit user-approved
   waiver before relying on provider replay for that external call.
2. **SDK parity second:** implement and test npm SDK and pip SDK parity for the
   same behavior when it is exposed programmatically. Run
   `python3 scripts/audit_sdk_cli_parity.py` when CLI or SDK surfaces change.
3. **Web app third:** after CLI and required SDK evidence are green, implement the
   web surface and run the Playwright `*.spec.ts` that verifies the
   browser-specific flow through `python3 scripts/tests.py run --spec
   <name>.spec.ts`. Web specs prove Svelte, TipTap, IndexedDB/localStorage,
   rendering, screenshots, and user interaction behavior.
4. **User confirmation fourth:** for user-visible web UI or behavior, ask the user
   to confirm the deployed dev web app works and looks correct. A passing
   `*.spec.ts` is necessary but not sufficient to start Apple parity.
5. **Apple app last:** after CLI, SDK, web, and required user-confirmation
   evidence are green, run or attempt the Apple app test through
   `scripts/apple_remote.py` when the feature has an Apple counterpart. Use
   `test-ios` for native tests, `build-ios` when no targeted test exists, and
   `cleanup` after simulator verification.

Do not skip directly to Playwright for shared product behavior unless the change
is clearly browser-only, such as selector changes, layout/screenshot diffs,
pointer-event overlays, or Svelte-only rendering. Do not mark Apple
`not affected` unless there is no native counterpart. Do not start a later client
while an earlier phase is unimplemented, untested, or blocked unless the spec or
session contract records an explicit user-approved waiver or accepted external
blocker.

CLI tests are the only phase that must prove the exact behavior on the dev server
before being promoted into GitHub Actions. Do not add or rely on a GitHub Actions
CLI run as the first proof for a new feature; GitHub Actions is the retention and
daily-regression gate after dev-server CLI evidence succeeds.

Do not count a mocked API-call test as dev-server CLI evidence. The acceptance
artifact should show the real command that was executed, the dev API URL or test
environment target, and the observable product result returned by the dev server.

Use the parity verifier when a change spans shared product behavior or multiple
clients:

```bash
python3 scripts/verify_parity.py --run --web-spec <name>.spec.ts --apple build
python3 scripts/verify_parity.py --check --no-skips
```

The verifier runs static CLI/npm SDK/pip SDK parity first, then dispatches CLI
and web checks through `scripts/tests.py`, then runs Apple verification through
`scripts/apple_remote.py`. It writes JSON evidence to `test-results/parity/` and
never runs local Playwright or Vitest directly. It does not replace the required
user confirmation gate for user-visible web behavior. If a phase is not
applicable, record an explicit reason with `--skip-web` or `--apple skip
--skip-apple`.

### Cross-App Parity Order

For chat, AI pipeline, settings-backed chat behavior, app skills, focus modes,
embeds, memory types, provider-backed behavior, sync, billing, notifications,
benchmark behavior, or any feature that exists across clients, implementation and
tests must prove parity in this order: OpenMates CLI first, npm SDK and pip SDK
second, web app third, user confirmation fourth, Apple app last.

1. **CLI contract first:** add or run an OpenMates CLI test against the dev server
   that exercises the backend/API/WebSocket contract without browser UI, TipTap,
   IndexedDB UI state, screenshots, or Svelte rendering. This is the required
   first proof for chat and app-skill behavior because it isolates backend
   correctness. Once it passes on dev, move or wire the coverage into GitHub
   Actions so it becomes part of the daily test set.

   This contract must drive the real CLI binary or compiled CLI entrypoint against
   `https://api.dev.openmates.org` or the approved dev-server target. It must not
   mock the OpenMates API, WebSocket client, SDK facade, route handlers, or backend
   skill execution.
2. **SDK parity second:** after the CLI contract is green, add or run npm SDK and
   pip SDK parity checks for exposed programmatic behavior.
3. **Web app E2E third:** after CLI and required SDK parity are green, add or run the
   Playwright spec that verifies the browser-specific flow, including composer
   behavior, draft/autosave state, settings UI, embeds, rendering, and user
   interactions. If the CLI contract passes but Playwright fails, debug the web
   app path instead of the backend pipeline first.
4. **User confirmation fourth:** for user-visible web changes, ask the user to
   confirm the deployed dev web app works and looks correct. Automated specs are
   not enough to begin Apple parity.
5. **Apple parity last:** when the product surface has an Apple counterpart,
   run or attempt the relevant iOS/macOS verification through
   `scripts/apple_remote.py` after CLI, SDK, web, and required user-confirmation
   evidence are green. Record Mac/Xcode evidence or a sanitized failure class per
   the Apple App section below.

Do not clone every Playwright spec into a CLI test. Prefer small reusable real
CLI contract tests for shared invariants such as message send, default-model
routing, skill invocation, embed resolution, sub-chat behavior, and sync
lifecycle. SDK tests remain responsible for programmatic parity. Playwright
remains responsible for browser UI and local web state; user confirmation remains
responsible for deployed web feel and visual correctness; Apple tests remain
responsible for native UI parity.

When fixing a failing chat-related Playwright spec, first check whether a
matching CLI contract exists. If not, write or propose the minimal CLI contract
before editing the web spec. The exception is a clearly browser-only failure,
such as a selector, layout, screenshot, pointer-event overlay, or Svelte-only
rendering regression; document that exception in the test plan or summary.

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

### Apple App

Apple verification is required when a change affects a product surface that also
exists in `apple/OpenMates/`, including chat, sync, auth, settings, embeds,
billing, shared UI primitives, app chrome, or provider result rendering.

Use XcodeBuildMCP on a Mac when available. If the active OpenCode session runs
on Linux/dev server, you MUST attempt the remote Mac Xcode CLI flow through the
redacted wrapper in `scripts/apple_remote.py` before marking Apple verification
unavailable. Use only operator-provided local runtime configuration, such as
`~/.config/openmates/apple-remote.json`, `~/.ssh/config`, current environment
variables, or explicit details from the user. The minimum acceptable attempt is
`python3 scripts/apple_remote.py status` plus `python3 scripts/apple_remote.py
build-ios`; for native test coverage use `python3 scripts/apple_remote.py
test-ios --only-testing <target/test>`. A stronger verification is a full build,
simulator launch, and screenshot parity check with `simctl`. Use the remote Mac
flow in `apple/AGENTS.md`: verify SSH access, protect local Mac checkout changes,
run `xcodebuild`, use `xcrun simctl` for simulator launch/screenshot checks when
needed, and shut down any simulator booted by the session after verification.

Remote Xcode CLI probe pattern, with all private connection details kept local:

```bash
python3 scripts/apple_remote.py status
python3 scripts/apple_remote.py build-ios --simulator "iPhone 17"
python3 scripts/apple_remote.py test-ios --simulator "iPhone 17" --only-testing "OpenMatesUITests/<testName>"
python3 scripts/apple_remote.py cleanup
```

If the Mac is reachable but the checkout cannot be found, or if key-based SSH is
not available, record the sanitized failure class, such as `ssh_failed`,
`project_not_found`, or `xcode_build_failed`, and ask the user for the missing
access/path instead of silently skipping Apple verification. This Tailscale/SSH
route was validated on 2026-06-08 with `xcodebuild -version`,
`xcodebuild -showBuildSettings`, and a generic iOS Simulator build.

Do not record private hostnames, IP addresses, usernames, SSH aliases, tailnet
names, auth keys, device names, or personal local paths in tests, specs, docs,
or final summaries. Use generic evidence such as scheme, simulator family, build
status, screenshot path, and whether manual parity checks passed.

### Playwright E2E (GitHub Actions — NOT local)

> **Claude: NEVER run these docker compose commands directly.** Use `python3 scripts/tests.py run --spec <name>.spec.ts` instead — it dispatches to GitHub Actions with proper test accounts and records status/history. The commands below document what the CI runner executes internally.

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

## Test Control Plane (`scripts/tests.py`)

```bash
python3 scripts/tests.py run --suite vitest           # Unit tests via GitHub Actions
python3 scripts/tests.py run --suite pytest            # Pytest via GitHub Actions
python3 scripts/tests.py run                           # Full suite (local orchestration + GitHub Actions)
python3 scripts/tests.py run --only-failed             # Rerun failures
python3 scripts/tests.py run --spec chat-flow.spec.ts  # Single Playwright spec
python3 scripts/tests.py run --suite playwright        # All E2E specs via GitHub Actions
python3 scripts/tests.py run --daily                   # Cron mode (commit gate, emails)
python3 scripts/tests.py run --daily --force           # Skip commit check
python3 scripts/tests.py run --hourly-dev              # Hourly dev smoke (4 specs)
python3 scripts/tests.py run --hourly-prod             # Free hourly prod smoke (legacy alias)
python3 scripts/tests.py run --prod-paid-chat          # Paid prod CLI chat smoke (scheduled slots)
python3 scripts/tests.py run --prod-app-skill          # Prod CLI app-skill smoke (daily slot)
python3 scripts/tests.py run --hourly-dev --dry-run-notify  # Test Discord wiring only
python3 scripts/tests.py run --max-concurrent 10       # Override batch size (default: 20)
python3 scripts/tests.py run --no-fail-fast            # Run all batches even on failure
python3 scripts/tests.py run --dry-run                 # Show what would run

`scripts/run_tests.py` remains the underlying execution engine. Agents and humans
should use `scripts/tests.py run` so current state, history, and failure leases
stay consistent.
```

### Hourly smoke modes (OPE-349)

Thin "is the core flow alive?" runners are triggered by the dev server's local
crontab. They are intentionally separate from `--daily` because the goal is
"catch urgent production breakage quickly", not full coverage.

| Mode | What it runs | Notification | Schedule |
| --- | --- | --- | --- |
| `--hourly-dev` | reachability + Stripe + chat (see `frontend/apps/web_app/tests/dev-smoke/README.md`) | Discord | local cron, 08–18 UTC |
| `--hourly-prod` / `--prod-free-hourly` | production logged-out reachability only | Discord + email on failure | hourly, 06:00–23:59 Europe/Berlin |
| `--prod-paid-chat` | production CLI `chats new` with one tiny paid `PONG` prompt | Discord + email on failure | 07:00, 13:00, 19:00 Europe/Berlin |
| `--prod-app-skill` | production CLI `apps web search` direct typed app-skill command | Discord + email on failure | 09:00 Europe/Berlin |
| `--daily` | full pytest + vitest + all E2E | Discord + email | local cron, 03 UTC weekdays |

**Why local cron, not GitHub Actions `schedule:`** — the GH-Actions cron silently
skips runs under load, which lost us prod outage alerts. The local crontab on
the dev server triggers `gh workflow run` so the actual specs still execute on
GH Actions runners; only the trigger moves. See OPE-349 for the full rationale.

**Discord noise control** — production smoke posts on FAILURE only. The dev
hourly mode can still post a single daily green heartbeat; the nightly mode
posts every run. Each webhook lives in its own Discord channel so noise from
one cron never drowns out alerts from another.

To verify a webhook without dispatching specs:

```bash
python3 scripts/tests.py run --hourly-dev --dry-run-notify
python3 scripts/tests.py run --hourly-prod --dry-run-notify
python3 scripts/tests.py run --daily --dry-run-notify
```

Hourly/prod archives: `test-results/hourly-dev/run-*.json`, `test-results/hourly-prod/run-*.json`, `test-results/prod-paid-chat/run-*.json`, and `test-results/prod-app-skill/run-*.json` (rotated to last 7 days).

Playwright specs are dispatched to GitHub Actions (`playwright-spec.yml`) in batches of concurrent runners, each with a separate test account (`OPENMATES_TEST_ACCOUNT_1_EMAIL` through `20`). Batch-level fail-fast: current batch finishes, then stops if any failures.

Development dispatches pin the checked-out source to the commit whose Vercel deployment passed the readiness gate, so a moving `dev` branch cannot change the test implementation after dispatch.

### Reserved E2E Credential Accounts

Most specs use the normal account pool. Specs that rotate, reset, or delete persistent auth credentials use reserved account slots and must call `getIsolatedTestAccount(<spec filename>)` instead of `getTestAccount()`.

| Slot | Spec | Why reserved |
|------|------|--------------|
| 14 | `account-recovery-flow.spec.ts` | Account reset can delete encrypted account state and may require fresh 2FA setup. |
| 15 | `backup-code-login-flow.spec.ts` | The Change App flow rotates the TOTP secret. |
| 16 | `backup-codes-settings.spec.ts` | Backup code reset mutates login recovery material. |
| 17 | `recovery-key-login-flow.spec.ts` | Recovery key regeneration mutates login recovery material. |
| 17 | `cli-created-account-login.spec.ts` | Verifies the CLI-provisioned password/TOTP account can log in through the web app without mutating recovery material. |
| 18 | `recovery-key-settings.spec.ts` | Recovery key regeneration mutates login recovery material. |
| 19 | `settings-change-email.spec.ts` | Email roundtrip mutates the account login identifier. |
| 20 | `api-keys-flow.spec.ts` | API-key lifecycle tests create/delete developer credentials. |

`scripts/run_tests.py` applies this mapping for full-suite, only-failed, and single-spec dispatches. Normal specs are assigned only from slots 1-13. If you add a spec that changes password, email, 2FA, recovery keys, backup codes, API keys, passkeys, or account data destructively, first add it to the reserved policy and document the slot here.

Use `cli-provision-auth-accounts.spec.ts` with `CREATE_ACCOUNT_SLOT` to provision reserved auth-test accounts for slots 14-20 when a slot secret is missing or intentionally rotated. The workflow reads the reusable dev-only invite from the `E2E_SIGNUP_INVITE_CODE` repository secret and exposes it to the CLI only through `OPENMATES_CLI_SIGNUP_INVITE_CODE`. The utility writes credential artifacts to the GitHub Actions artifact bundle; copy them into the matching `OPENMATES_TEST_ACCOUNT_<slot>_*` repository secrets and never commit generated credentials.

Apple XCUITests that mutate sensitive account state use the same reserved slot variables through `RealAccountUITestSupport.fromReservedSlot(<slot>)`; tests must skip when a required reserved slot is absent rather than falling back to the normal account pool. Static sensitive-settings parity smokes can use narrow fixture launch arguments when they do not call live account APIs.

API-key cleanup must only delete keys created by E2E specs, currently names starting with `E2E-Test-Key`, `E2E-RestAPI`, or `E2E-Limit-Key`. Never delete arbitrary existing keys to make room at the 5-key limit.

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

Live mock mode is supplemental coverage. It does not satisfy the new-feature CLI
phase gate, which requires real CLI commands against the dev server with no
mocked OpenMates API/WebSocket calls. Use live mock mode for repeatable CI and
cost control after the real dev CLI proof exists, or when a spec records an
explicit user-approved external-provider waiver.

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

## Production Smoke Suite (OPE-76 / OPE-349)

Production smoke is deliberately smaller than dev coverage. The dev server
dispatches `.github/workflows/prod-smoke.yml` with a `suite` input, polls the
GitHub Actions run, parses the uploaded artifact, and sends Discord + email on
failure. The workflow itself does not send notifications.

| Suite | Command | What it verifies | Cost |
|------|---------|------------------|------|
| `free-hourly` | `python3 scripts/tests.py run --prod-free-hourly` | `prod-smoke-reachability.spec.ts`: logged-out production web shell loads and login/signup renders. | Free |
| `paid-chat` | `python3 scripts/tests.py run --prod-paid-chat` | `openmates chats new "Reply with exactly: PONG"` against production API using the prod smoke API key. | One tiny paid LLM turn |
| `app-skill-web-search` | `python3 scripts/tests.py run --prod-app-skill` | `openmates apps web search "OpenMates official website"` direct typed app-skill command against production API. | Provider/API cost only |

### Required configuration

- GitHub Actions: `PROD_BASE_URL`, `OPENMATES_TEST_ACCOUNT_API_KEY`.
- Dev server notifications: `DISCORD_WEBHOOK_PROD_SMOKE` and either Brevo
  (`BREVO_API_KEY` + `ADMIN_NOTIFY_EMAIL`) or the internal email API
  (`INTERNAL_API_SHARED_TOKEN` + `ADMIN_NOTIFY_EMAIL`).
- `--force` bypasses Berlin-time schedule gates for manual verification.
- `--dry-run` prints the GitHub workflow dispatch that would happen without
  running production tests.

### Manual dispatch

```bash
gh workflow run prod-smoke.yml
gh workflow run prod-smoke.yml -f suite=paid-chat
gh run watch
```

---

## TipTap Editor Interaction in Playwright

- Never click editor after inserting embed — triggers fullscreen overlay
- Use `page.keyboard.type()`, not `fill()` — TipTap is not a native input
- If fullscreen opens accidentally: `page.keyboard.press('Escape')`

---

## Pre-Commit Test Checklist

- [ ] Tests actually fail when code is broken
- [ ] Tests cover happy path AND at least one error path
- [ ] Unit tests mock external services when appropriate, but CLI phase-gate evidence uses real dev-server commands and does not mock OpenMates API/WebSocket calls
- [ ] No `time.sleep()` or arbitrary waits
- [ ] Apple impact was checked for shared product surfaces, and Mac verification or an explicit `not affected` note was recorded
