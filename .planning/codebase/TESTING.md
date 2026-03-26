# Testing Patterns

**Analysis Date:** 2026-03-26

## Test Frameworks Overview

| Layer | Framework | Config File | Location |
|-------|-----------|-------------|----------|
| Backend unit/integration | pytest + pytest-asyncio | `backend/pytest.ini` | `backend/tests/` |
| Frontend unit (web app) | Vitest | `frontend/apps/web_app/vitest.config.ts` | `src/**/*.test.ts` |
| Frontend unit (ui package) | Vitest | `frontend/packages/ui/vitest.config.ts` | `src/**/*.{test,spec}.ts` |
| Frontend E2E | Playwright | `frontend/apps/web_app/playwright.config.ts` | `frontend/apps/web_app/tests/` |
| API smoke tests | Standalone Python scripts | N/A | `scripts/api_tests/` |

---

## Backend — pytest

**Runner:** pytest
**Config:** `backend/pytest.ini`
**Async mode:** `asyncio_mode = auto` — all async tests run automatically

**Run Commands:**
```bash
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_core.py
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/ -k "rest_api"
/OpenMates/.venv/bin/python3 -m pytest -v backend/tests/test_encryption_service.py
```

**Markers (enforced with `--strict-markers`):**
- `integration` — requires external services
- `slow` — long-running tests
- `vault` — requires running Vault instance
- `benchmark` — expensive model comparison/inference (excluded from daily CI)
- `asyncio` — registered by pytest-asyncio

---

## Backend Test File Organization

**Location:** All backend tests live in `backend/tests/`

**Naming:**
- `test_<module>.py` for unit tests (e.g., `test_encryption_service.py`, `test_rate_limiting.py`)
- `test_rest_api_<domain>.py` for integration REST API tests (e.g., `test_rest_api_auth.py`, `test_rest_api_ai.py`)

**Structure:**
```
backend/tests/
├── conftest.py                         # Shared fixtures and HTTP client for REST tests
├── test_encryption_service.py          # Unit tests for EncryptionService
├── test_rate_limiting.py               # Unit tests for rate_limiting module
├── test_rest_api_core.py               # REST API integration: core endpoints
├── test_rest_api_ai.py                 # REST API integration: AI endpoints
├── test_rest_api_auth.py               # REST API integration: auth endpoints
├── test_postprocessor.py               # Unit tests for postprocessor functions
├── test_chat_compressor.py             # Unit tests for chat compression
└── ...
```

---

## Backend Test Structure

**Suite Organization — Nested classes per concern:**
```python
class TestEncryptionService:
    """Test suite for EncryptionService class"""

    @pytest.fixture
    def encryption_service(self, mock_vault_url, mock_vault_token):
        """Create EncryptionService instance with mocked dependencies"""
        ...

    class TestInitialization:
        """Test service initialization and configuration"""
        def test_init_with_env_vars(self, mock_vault_url, mock_vault_token): ...
        def test_init_fallback_to_env_var(self, ...): ...

    class TestEncryptionDecryption:
        """Test encryption and decryption operations"""
        @pytest.mark.asyncio
        async def test_encrypt_success(self, encryption_service, mock_vault_response): ...
```

**Lightweight fake objects (preferred over full mocks for pure logic tests):**
```python
class FakeSkill:
    def __init__(self, id: str, stage: str = "production", internal: bool = False):
        self.id = id
        self.stage = stage
        self.internal = internal

class FakeAppYAML:
    def __init__(self, skills=None):
        self.skills = skills or []
```
See `backend/tests/test_postprocessor.py` for the full pattern.

**Import guard — skip when backend deps missing:**
```python
try:
    from backend.apps.ai.processing.rate_limiting import (
        check_rate_limit,
        RateLimitScheduledException,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")
```

---

## Backend Mocking

**Framework:** `unittest.mock` (`AsyncMock`, `MagicMock`, `patch`, `mock_open`)

**Async HTTP mocking (httpx):**
```python
with patch('httpx.AsyncClient') as mock_client:
    mock_response_obj = MagicMock()
    mock_response_obj.status_code = 200
    mock_response_obj.json.return_value = {"data": {"policies": ["default"]}}
    mock_client.return_value.__aenter__.return_value.get = AsyncMock(
        return_value=mock_response_obj
    )
    result = await service._validate_token()
    assert result is True
```

**Patching object methods directly:**
```python
with patch.object(encryption_service, '_vault_request', return_value=mock_vault_response):
    ciphertext, key_version = await encryption_service.encrypt(plaintext, key_name)
```

**monkeypatch for module-level dependencies:**
```python
def test_returns_none_when_no_config(self, monkeypatch):
    mock_cm = MagicMock()
    mock_cm.get_provider_config.return_value = None
    monkeypatch.setattr(
        "backend.apps.ai.processing.rate_limiting.ConfigManager",
        lambda: mock_cm,
    )
```

**What to Mock:**
- External HTTP clients (httpx, requests)
- Database/cache services (`CacheService`, `DirectusService`)
- Vault API requests
- Environment variables (`patch.dict(os.environ, {...})`)

**What NOT to Mock:**
- Pure function logic under test
- Python standard library functions unless necessary

---

## Backend Integration Tests (REST API)

The shared `backend/tests/conftest.py` provides:
- `api_client` fixture: authenticated `httpx.Client` against `https://api.dev.openmates.org`; auto-skips if `OPENMATES_TEST_ACCOUNT_API_KEY` is unset
- `poll_task_until_complete()`: polls `/v1/tasks/{task_id}` until complete or failed (max 60 retries, 2s interval)
- `verify_image_metadata()`: checks XMP + C2PA metadata on generated images

Integration tests require the dev server to be running and `OPENMATES_TEST_ACCOUNT_API_KEY` env var to be set.

---

## Frontend Unit Tests — Vitest

**Runner:** Vitest
**Config (web app):** `frontend/apps/web_app/vitest.config.ts` — includes `src/**/*.test.{js,ts}`, excludes `tests/**`
**Config (ui package):** `frontend/packages/ui/vitest.config.ts` — includes `src/**/*.{test,spec}.ts`, environment `jsdom`, globals `true`

**Setup File:** `frontend/packages/ui/src/test-setup.ts` — stubs browser APIs not available in jsdom:
- `window` object with `btoa`, `atob`, `sessionStorage`, `localStorage`, `navigator`, `matchMedia`
- `crypto.subtle`, `crypto.randomUUID`
- `indexedDB`

**Run Commands:**
```bash
cd frontend/apps/web_app && npm run test:unit
npm run test:unit -- --coverage
```

---

## Frontend Unit Test File Organization

**Location:** Co-located in `__tests__/` subdirectory alongside source files.

**Naming:**
- `<ServiceName>.test.ts` (e.g., `chatListCache.test.ts`, `ChatKeyManager.test.ts`)
- `<feature>.test.ts` (e.g., `serializers.test.ts`, `deriveEmbedKey.test.ts`)

**Structure:**
```
frontend/packages/ui/src/
├── services/
│   ├── chatListCache.ts
│   ├── __tests__/
│   │   ├── chatListCache.test.ts
│   │   ├── embedStore.test.ts
│   │   └── chatMetadataCache.test.ts
│   ├── encryption/
│   │   ├── ChatKeyManager.ts
│   │   └── __tests__/
│   │       ├── ChatKeyManager.test.ts
│   │       └── shareEncryption.test.ts
│   └── drafts/
│       └── __tests__/
│           └── draftSave.test.ts
├── stores/
│   └── __tests__/
│       ├── activeChatStore.test.ts
│       └── phasedSyncState.test.ts
└── message_parsing/
    └── __tests__/
        ├── serializers.test.ts
        └── parse_message_large_promotion.test.ts
```

---

## Frontend Unit Test Structure

**Suite Organization:**
```typescript
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

// Bug history block at top of file (links commits to fixed bugs)
// Bug history this test suite guards against:
//  - 861d8edca: sidebar remount served stale cache after destroy/recreate
//  - 780b871e7: stale decrypted metadata after logout → "Untitled chat"

describe("ChatListCache", () => {
  beforeEach(() => {
    chatListCache.clear();  // Reset singleton state
  });

  describe("basic cache operations", () => {
    it("returns null when cache is not ready", () => {
      expect(chatListCache.getCache()).toBeNull();
    });
  });

  describe("updateInProgress", () => {
    it("waitForUpdate resolves immediately when no update in progress", async () => {
      let resolved = false;
      await chatListCache.waitForUpdate().then(() => { resolved = true; });
      expect(resolved).toBe(true);
    });
  });
});
```

**Key patterns:**
- `describe` blocks are nested two levels deep: outer = class/module, inner = method/behavior group
- `beforeEach` resets singleton state to prevent test cross-contamination
- Helper factory functions create minimal test fixtures: `function makeChat(id, extras = {}) { ... }`
- Use `as any` for minimal fake objects that only implement the fields under test

---

## Frontend Mocking

**Framework:** Vitest `vi` object

**Mocking modules before import:**
```typescript
// Mock $app/environment and $app/navigation BEFORE importing the store
vi.mock("$app/environment", () => ({ browser: true }));
vi.mock("$app/navigation", () => ({ replaceState: vi.fn() }));
```

**Mocking heavy dependencies for a service:**
```typescript
const mockDelete = vi.fn().mockResolvedValue(undefined);
const mockPut = vi.fn().mockResolvedValue(undefined);
vi.mock("../../db", () => ({
  chatDB: {
    chats: {
      delete: (...args: unknown[]) => mockDelete(...args),
      put: (...args: unknown[]) => mockPut(...args),
    },
  },
}));
```

**Stubbing globals (for crypto, IndexedDB, etc.):**
```typescript
vi.stubGlobal("crypto", {
  getRandomValues: (buf: Uint8Array) => { buf.fill(_counter++ % 256); return buf; },
  subtle: {},
} as unknown as Crypto);
```

**Using `vi.hoisted` for pre-import patches:**
```typescript
const locationMock = vi.hoisted(() => {
  const loc = { hash: "", pathname: "/", search: "" };
  (globalThis as Record<string, unknown>).window = {
    ...(globalThis as Record<string, unknown>).window as object,
    location: loc,
  };
  return loc;
});
```

---

## Frontend E2E Tests — Playwright

**Runner:** Playwright
**Config:** `frontend/apps/web_app/playwright.config.ts`
**Test directory:** `frontend/apps/web_app/tests/`
**Pattern:** `(.+\.)?(test|spec)\.[jt]s`

**Key config:**
- No local dev server — tests always run against an already-deployed instance
- `PLAYWRIGHT_TEST_BASE_URL` must be set explicitly; missing var throws immediately (no silent misconfiguration)
- `screenshot: 'only-on-failure'`, `trace: 'retain-on-failure'`
- `retries: 1` — retries once for flaky timing on dev server

**Run Commands:**
```bash
# Single spec via Docker:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_FILE="chat-management-flow.spec.ts" playwright

# With grep filter:
docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
  -e PLAYWRIGHT_TEST_GREP="pins a chat" playwright

# Via test runner (dispatches to GitHub Actions):
python3 scripts/run_tests.py --spec signup-flow.spec.ts
python3 scripts/run_tests.py --suite playwright
```

---

## E2E Test File Organization

**Location:** `frontend/apps/web_app/tests/`

**Naming conventions:**
- `<feature>-flow.spec.ts` — user journey flows (e.g., `signup-flow.spec.ts`, `chat-management-flow.spec.ts`, `buy-credits-flow.spec.ts`)
- `skill-<app>-<skill>.spec.ts` — skill lifecycle tests (e.g., `skill-web-read.spec.ts`, `skill-news-search.spec.ts`)
- `<topic>.spec.ts` — targeted feature tests (e.g., `incognito-mode.spec.ts`, `a11y-pages.spec.ts`)
- `signup-flow-helpers.ts` — shared E2E utilities (TOTP generation, Mailosaur client, screenshot helpers)

**Shared helpers in `tests/helpers/`:**
- `chat-test-helpers.ts` — `loginToTestAccount`, `startNewChat`, `sendMessage`, `deleteActiveChat`
- `cli-test-helpers.ts` — `runCli`, `deriveApiUrl`, `parseCliJson`
- `embed-test-helpers.ts` — `verifyEmbedPreviewPage`, `waitForEmbedFinished`, `openFullscreen`, `verifySearchGrid`
- `env-guard.ts` — `skipWithoutCredentials` guard

---

## E2E Test Structure

**Suite structure (single test per flow, internally logged with checkpoints):**
```typescript
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('@playwright/test');
const { createSignupLogger, createStepScreenshotter, ... } = require('./signup-flow-helpers');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
  consoleLogs.length = 0;
  networkActivities.length = 0;
});

// Dump debug info on failure
test.afterEach(async ({}, testInfo: any) => {
  if (testInfo.status !== 'passed') {
    console.log('\n--- DEBUG INFO ON FAILURE ---');
    consoleLogs.slice(-20).forEach((log) => console.log(log));
    networkActivities.slice(-20).forEach((activity) => console.log(activity));
  }
});

test('full feature test name', async ({ page, context }) => {
  test.slow();
  test.setTimeout(300000);  // Long E2E flows get 5 minute timeout

  const log = createSignupLogger('FEATURE_NAME');
  const screenshot = createStepScreenshotter(log);

  // Skip guards for missing credentials
  skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

  // Step-by-step with checkpoints
  await loginToTestAccount(page, log, screenshot);
  log('Reached target state.');

  await assertNoMissingTranslations(page);  // Check i18n on every major step
  await deleteActiveChat(page, log, screenshot, 'cleanup');  // Always clean up
});
```

---

## E2E Skill Spec — 4-Phase Pattern

Each app skill spec validates the complete lifecycle in 4 sequential phases:

```
Phase 1: Embed preview     → /dev/preview/embeds/{app} renders (no login, static mock)
Phase 2: CLI direct command → openmates apps {app} {skill} --json returns results
Phase 3: CLI chat send      → openmates chats new "message" triggers the skill
Phase 4: Web UI chat        → login → send → verify embed → fullscreen → cleanup
```

---

## Live Mock System (LLM & HTTP Caching)

**Purpose:** Run the full backend pipeline without external API costs.

**How to use in tests:**
```typescript
// In message text — appends cache marker
withLiveMockMarker('Search for AI news', 'news_search_web')
// group_id convention: {app}_{skill}_{context} (web/cli/descriptive)
```

**Run commands:**
```bash
# Record (first run — hits real APIs):
E2E_RECORD_LIVE_FIXTURES=1 npx playwright test skill-web-search.spec.ts

# Replay (CI runs — zero cost):
E2E_USE_LIVE_MOCKS=1 npx playwright test skill-web-search.spec.ts
```

**Cache storage:** `backend/apps/ai/testing/api_cache/{group_id}/`

**Key files:**
- `backend/shared/testing/api_response_cache.py` — cache storage and fingerprinting
- `backend/shared/testing/mock_context.py` — marker detection
- `backend/shared/testing/caching_http_transport.py` — httpx transport wrapper
- `backend/apps/ai/testing/caching_llm_wrapper.py` — LLM provider wrapper

---

## Coverage

**Requirements:** No enforced coverage target detected.

**View Coverage:**
```bash
cd frontend/apps/web_app && npm run test:unit -- --coverage
```

---

## Test Types

**Backend Unit Tests (`backend/tests/test_*.py`):**
- Pure logic: isolated via `unittest.mock`, no external services
- Crypto/encryption: uses mock Vault responses
- Rate limiting: uses mock CacheService
- Postprocessor: uses lightweight fake objects, zero mocks

**Backend Integration Tests (`backend/tests/test_rest_api_*.py`):**
- Full HTTP stack against `https://api.dev.openmates.org`
- Require `OPENMATES_TEST_ACCOUNT_API_KEY` env var
- Test auth, AI, media, apps, events, status endpoints

**API Feasibility Scripts (`scripts/api_tests/test_*.py`):**
- Standalone scripts, NOT pytest-based
- Call internal Docker container endpoints directly
- Manual verification only — not run in CI

**Frontend Unit Tests (`*.test.ts`):**
- In-memory only, no DOM for service/store tests (jsdom for component tests)
- Mock all browser APIs, IndexedDB, crypto
- Guard against specific historical bugs (commit SHA referenced in header)

**Frontend E2E Tests (`*.spec.ts`):**
- Full browser automation against deployed instance
- Cover auth flows, skill execution, payment, settings
- Screenshot on failure, trace on failure
- Run via GitHub Actions with 20 concurrent test accounts

---

## Common Patterns

**Async Testing (Python):**
```python
@pytest.mark.asyncio
async def test_encrypt_success(self, encryption_service, mock_vault_response):
    """Test successful encryption"""
    with patch.object(encryption_service, '_vault_request', return_value=mock_vault_response):
        ciphertext, key_version = await encryption_service.encrypt(plaintext, key_name)
        assert ciphertext == "vault:v1:test-ciphertext"
        assert key_version == "v1"
```

**Async Testing (TypeScript):**
```typescript
it("resolves any waiting callers when cleared during update", async () => {
  chatListCache.setUpdateInProgress(true);
  let resolved = false;
  const waitPromise = chatListCache.waitForUpdate().then(() => { resolved = true; });
  chatListCache.clear();
  await waitPromise;
  expect(resolved).toBe(true);
});
```

**Error Path Testing (Python):**
```python
async def test_vault_request_permission_denied(self, encryption_service):
    with patch('httpx.AsyncClient') as mock_client:
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 403
        mock_response_obj.text = "Permission denied"
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response_obj
        with patch.object(encryption_service, '_validate_token', return_value=True):
            with pytest.raises(Exception, match="Permission denied"):
                await encryption_service._vault_request("get", "test/path")
```

**Conditional skip (Python — integration tests):**
```python
@pytest.mark.skipif(
    not os.environ.get('VAULT_TOKEN'),
    reason="Integration tests require VAULT_TOKEN environment variable"
)
```

**Conditional skip (Playwright E2E):**
```typescript
test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required for email validation.');
skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
```

**Retry flaky assertions (Playwright):**
```typescript
await expect(async () => {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  await activeChatItem.click({ button: 'right' });
  const pinButton = page.locator('.menu-item.pin');
  await expect(pinButton).toBeVisible({ timeout: 3000 });
  await pinButton.click();
}).toPass({ timeout: 20000 });
```

---

## Test Pre-Commit Checklist

From `docs/contributing/guides/testing.md`:
- Tests actually fail when code is broken
- Tests cover happy path AND at least one error path
- Tests don't depend on external services (mock them)
- No `time.sleep()` or arbitrary waits (E2E: use `waitForTimeout` sparingly)
- New auth/payment/user-facing features need E2E test proposal before implementation
- Test chat features with sidebar closed (default for viewports ≤1440px)
- After fixing chat/nav/sync bugs, verify by clearing IndexedDB + localStorage then reload

---

*Testing analysis: 2026-03-26*
