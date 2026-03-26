# Phase 5: Testing & Documentation - Research

**Researched:** 2026-03-26
**Domain:** Playwright E2E multi-tab testing, Vitest performance benchmarks, encryption architecture documentation, file-size monitoring
**Confidence:** HIGH

## Summary

Phase 5 is a validation and documentation phase -- no encryption or sync code changes. It requires: (1) two new Playwright E2E specs testing multi-tab encryption scenarios, (2) a Vitest performance benchmark for 100-message encrypt/decrypt, (3) verification that existing regression fixtures still pass, (4) a new end-to-end architecture document with Mermaid diagrams, (5) updates to four Phase 1 docs reflecting the post-rebuild state, and (6) a file-size monitoring script with grandfathering.

The existing test infrastructure is mature (93 E2E specs, 6 encryption unit tests, well-factored helpers). The multi-tab specs should use Playwright's `BrowserContext` to create multiple pages within a single browser instance (sharing IndexedDB storage) -- this is the correct approach for simulating same-device tabs, distinct from the existing `multi-session-encryption.spec.ts` which uses separate browser contexts (simulating separate devices).

**Primary recommendation:** Structure this as 4-5 focused plans: multi-tab E2E tests, performance benchmark + fixture validation, architecture documentation, Phase 1 doc updates, and file-size monitoring script.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Create new dedicated Playwright specs for TEST-01 and TEST-02, separate from the existing `multi-session-encryption.spec.ts`. The existing spec tests cross-browser (simulating cross-device via two browser instances); the new specs test same-browser tabs via BrowserContext. Keeps concerns separate.
- **D-02:** Scope limited to the two required scenarios only: TEST-01 (two tabs, same chat, both decrypt) and TEST-02 (create in tab A, open in tab B, content decrypts). No additional reconnection or key conflict scenarios.
- **D-03:** Performance threshold is under 2 seconds for encrypting/decrypting a 100-message chat.
- **D-04:** Performance benchmark runs as a Vitest unit test in the encryption `__tests__/` directory. Fast, repeatable, no browser overhead.
- **D-05:** Create one new document: `docs/architecture/core/encryption-architecture.md` -- the end-to-end architecture overview. Module boundaries, data flow, Mermaid diagrams.
- **D-06:** Update the existing Phase 1 docs (`encryption-code-inventory.md`, `encryption-root-causes.md`, `encryption-formats.md`, `master-key-lifecycle.md`) to reflect the post-rebuild state.
- **D-07:** 500-line threshold for file-size monitoring.
- **D-08:** Report-only script in `scripts/` with grandfathering.
- **D-09:** Soft CI warning integration (not a blocker).

### Claude's Discretion
- Playwright test file naming and organization within `tests/`
- BrowserContext vs separate pages approach for multi-tab testing
- Mermaid diagram style and level of detail in architecture doc
- File-size script implementation details (baseline storage format, CI integration mechanism)
- Which directories the file-size script monitors

### Deferred Ideas (OUT OF SCOPE)
None.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TEST-01 | Playwright test: two tabs open same chat, send messages, both decrypt correctly | Multi-tab Playwright pattern using single BrowserContext with two pages; reuse login helpers from chat-test-helpers.ts |
| TEST-02 | Playwright test: create chat in tab A, open in tab B, content decrypts correctly | Same BrowserContext approach; tab B discovers via sidebar WebSocket sync |
| TEST-03 | All historical encrypted format test fixtures decrypt successfully | Existing `regression-fixtures.test.ts` (14 tests) and `formats.test.ts` (12 tests) already cover this -- run and confirm passing |
| TEST-04 | Performance test: encrypt/decrypt 100-message chat within 2s threshold | Vitest benchmark using real Web Crypto (node:crypto webcrypto); 100 sequential encrypt+decrypt operations with timing assertion |
| TEST-05 | File-size monitoring script that flags files over 500-line threshold | Bash/Node script in scripts/ with JSON baseline for grandfathering |
| ARCH-05 | Architecture documentation explaining full encryption flow end-to-end | New `encryption-architecture.md` with Mermaid diagrams; update 4 existing Phase 1 docs |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Playwright | 1.58.0 | E2E multi-tab testing | Already installed and configured; 93 existing specs |
| Vitest | (from vitest.config.ts) | Unit/performance testing | Already configured for UI package with jsdom |
| node:crypto webcrypto | Node.js built-in | Real Web Crypto for Vitest benchmarks | Required for actual AES-GCM performance measurement |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @playwright/test | 1.58.0 | Test assertions and fixtures | All E2E specs |
| Mermaid | (markdown rendering) | Architecture diagrams | In encryption-architecture.md |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Vitest benchmark | Playwright perf test | Vitest is faster, more repeatable, no browser overhead (decision D-04) |
| Extending multi-session-encryption.spec.ts | New spec files | Separate concerns: cross-device vs same-device tabs (decision D-01) |

## Architecture Patterns

### Recommended Project Structure
```
frontend/apps/web_app/tests/
├── multi-tab-encryption.spec.ts    # TEST-01 + TEST-02 (new)
├── multi-session-encryption.spec.ts # Existing cross-browser spec (unchanged)
├── helpers/
│   ├── chat-test-helpers.ts        # Reuse loginToTestAccount, startNewChat, etc.
│   └── env-guard.ts                # Reuse skipWithoutCredentials

frontend/packages/ui/src/services/encryption/__tests__/
├── performance.test.ts             # TEST-04 (new)
├── regression-fixtures.test.ts     # TEST-03 (existing, verify passing)
├── formats.test.ts                 # TEST-03 (existing, verify passing)
├── ChatKeyManager.test.ts          # Existing (unchanged)
├── import-audit.test.ts            # Existing (unchanged)

docs/architecture/core/
├── encryption-architecture.md      # ARCH-05 (new)
├── encryption-code-inventory.md    # Update for post-rebuild
├── encryption-root-causes.md       # Update for post-rebuild
├── encryption-formats.md           # Update for post-rebuild (likely minimal changes)
├── master-key-lifecycle.md         # Update for post-rebuild

scripts/
└── check-file-sizes.sh             # TEST-05 (new)
```

### Pattern 1: Multi-Tab Testing with Shared BrowserContext
**What:** Use a single Playwright BrowserContext with two pages (tabs) to simulate same-device multi-tab usage. Both pages share the same IndexedDB and BroadcastChannel.
**When to use:** TEST-01 and TEST-02 -- testing same-user, same-browser tab scenarios.
**Key difference from existing spec:** The existing `multi-session-encryption.spec.ts` uses TWO separate BrowserContexts (simulating two independent browsers/devices with separate storage). The new specs use ONE context with two pages (simulating two tabs in the same browser sharing storage).

```typescript
// Source: Playwright docs - BrowserContext pages share storage
const context = await browser.newContext({ baseURL });
const tabA = await context.newPage();
const tabB = await context.newPage();
// Both tabA and tabB share the same IndexedDB, localStorage, cookies
// BroadcastChannel messages propagate between them
```

**Critical:** Only ONE tab can log in. The second tab should navigate directly to `/chat` after the first tab completes login, because they share the same session storage. Do NOT log in twice in the same context -- the OTP would be rejected and the session cookie would conflict.

### Pattern 2: Vitest with Real Web Crypto
**What:** Override the jsdom crypto stubs with Node's `webcrypto` to get actual AES-GCM performance.
**When to use:** TEST-04 performance benchmark.
**Example:**
```typescript
// Source: existing regression-fixtures.test.ts pattern (lines 13-33)
import { webcrypto } from "node:crypto";
const realCrypto = webcrypto as unknown as Crypto;
Object.defineProperty(globalThis, "crypto", {
  value: realCrypto,
  writable: true,
  configurable: true,
});
// + btoa/atob polyfills from Buffer
```

### Pattern 3: File-Size Script with JSON Baseline
**What:** A script that counts lines in monitored files, compares against a JSON baseline of known large files, and reports new threshold violations.
**When to use:** TEST-05 file-size monitoring.
```bash
# Grandfathering approach: baseline JSON stores known large files
# New files crossing threshold are highlighted as regressions
# Existing files over threshold are listed but not flagged
```

### Anti-Patterns to Avoid
- **Logging in twice in same BrowserContext:** Two pages share cookies. The second login would overwrite the first session and trigger OTP rejection.
- **Using `performance.now()` in Vitest:** Node.js `performance.now()` in jsdom environment may not reflect actual crypto timings. Use `Date.now()` for wall-clock measurement or `process.hrtime.bigint()` for high precision.
- **Hard-coding chat IDs or test data:** Always generate test data dynamically and clean up afterward.
- **Forgetting crypto environment setup in Vitest:** The `test-setup.ts` mocks crypto stubs. Performance tests MUST override with real `webcrypto` BEFORE importing encryption modules.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Login flow in E2E | Custom login code | `loginToTestAccount` from `chat-test-helpers.ts` | Handles OTP retry, stay-logged-in toggle, all edge cases |
| Chat creation in E2E | Custom chat creation | `startNewChat` + `sendMessage` from `chat-test-helpers.ts` | Handles timing, editor detection, URL extraction |
| Decryption error detection | Custom error parsing | `assertChatDecryptedCorrectly` pattern from multi-session spec | Covers console errors, UI error states, screenshots |
| AES-GCM encrypt/decrypt | Raw crypto.subtle calls | `encryptWithChatKey`/`decryptWithChatKey` from `cryptoService` | Handles OM-header format, fingerprints, legacy fallback |
| Line counting | Custom parser | `wc -l` or `awk` | Standard Unix tool, handles edge cases |

## Common Pitfalls

### Pitfall 1: BrowserContext Sharing Semantics
**What goes wrong:** Assuming two pages in the same context are fully isolated, or assuming they share everything.
**Why it happens:** Playwright BrowserContext is the isolation boundary, not Page. Two pages in the same context share cookies, localStorage, and IndexedDB, but JavaScript execution contexts (including in-memory variables and BroadcastChannel instances) are per-page.
**How to avoid:** Log in only once (in tab A). Tab B should navigate after login completes and will inherit the session. BroadcastChannel propagation between tabs happens via the browser engine, not in-process.
**Warning signs:** OTP rejection errors during second login, session overwrite, duplicate login attempts.

### Pitfall 2: Crypto Setup Order in Vitest
**What goes wrong:** Importing encryption modules before overriding `globalThis.crypto` results in modules caching the mocked (stub) crypto object.
**Why it happens:** `test-setup.ts` provides jsdom crypto stubs. Module-level code in `cryptoService.ts` may capture references at import time.
**How to avoid:** Override `globalThis.crypto` with `webcrypto` BEFORE importing any encryption modules. Use dynamic import or place crypto setup in `beforeAll` before the module import.
**Warning signs:** Crypto operations returning null or throwing "not a function" errors in performance tests.

### Pitfall 3: TOTP Timing in Single-Context Multi-Tab
**What goes wrong:** The existing multi-session spec waits for a new OTP window between logins. In single-context (shared session), this is unnecessary -- but if you accidentally try to log in twice, the timing wait won't help because cookies conflict.
**Why it happens:** Copying patterns from multi-session spec without adapting.
**How to avoid:** Single login only. Tab B navigates to `/chat` directly after tab A's login.

### Pitfall 4: Flaky Performance Assertions
**What goes wrong:** Hard CI failures from timing-sensitive assertions.
**Why it happens:** CI machines have variable load; crypto performance varies with system state.
**How to avoid:** Use generous thresholds (2s per D-03 is already generous for 100 AES-GCM operations). Run multiple iterations and assert on the median or p95. Include warm-up iterations. Mark test as `slow` to prevent CI timeouts.
**Warning signs:** Intermittent failures in CI but not locally.

### Pitfall 5: Architecture Doc Going Stale
**What goes wrong:** Documentation drifts from code over time.
**Why it happens:** No automated validation that docs match code structure.
**How to avoid:** The import-audit test already validates ARCH-03 compliance. The architecture doc should reference file paths that are tested by import-audit.test.ts. Keep the doc focused on "why" and "how the pieces connect" rather than line-by-line implementation.

## Code Examples

### Multi-Tab Test Structure (TEST-01 / TEST-02)
```typescript
// Source: adapted from multi-session-encryption.spec.ts patterns
// Key difference: single BrowserContext, two pages (shared storage)

const { test, expect, chromium } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

test('TEST-01: two tabs decrypt same chat correctly', async () => {
  test.slow();
  test.setTimeout(300000);

  const browser = await chromium.launch();
  const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL;
  const context = await browser.newContext({ baseURL });

  const tabA = await context.newPage();
  const tabB = await context.newPage();

  try {
    // Login in tab A only -- tab B shares the session
    await loginToTestAccount(tabA);

    // Tab B navigates to /chat (already authenticated via shared cookies)
    await tabB.goto('/chat');
    await tabB.waitForURL(/chat/, { timeout: 15000 });

    // Tab A creates chat and sends message
    // ... (use existing helpers)

    // Tab B discovers chat via sidebar, opens it, asserts decryption
    // ... (use waitForChatInSidebarAndClick pattern)

  } finally {
    await context.close();
    await browser.close();
  }
});
```

### Performance Benchmark (TEST-04)
```typescript
// Source: adapted from regression-fixtures.test.ts crypto setup pattern
import { describe, it, expect, beforeAll } from "vitest";
import { webcrypto } from "node:crypto";

// Override crypto BEFORE importing encryption modules
const realCrypto = webcrypto as unknown as Crypto;
Object.defineProperty(globalThis, "crypto", {
  value: realCrypto, writable: true, configurable: true,
});
// + btoa/atob polyfills

import { encryptWithChatKey, decryptWithChatKey } from "../../cryptoService";

describe("TEST-04: encryption performance benchmark", () => {
  let chatKey: Uint8Array;

  beforeAll(() => {
    chatKey = new Uint8Array(32);
    crypto.getRandomValues(chatKey);
  });

  it("encrypts and decrypts 100 messages within 2s", async () => {
    const messages = Array.from({ length: 100 }, (_, i) =>
      `Message ${i}: ${crypto.getRandomValues(new Uint8Array(50)).join('')}`
    );

    const start = performance.now();

    const ciphertexts = [];
    for (const msg of messages) {
      ciphertexts.push(await encryptWithChatKey(msg, chatKey));
    }
    for (const ct of ciphertexts) {
      await decryptWithChatKey(ct, chatKey);
    }

    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(2000);
  });
});
```

### File-Size Monitor (TEST-05)
```bash
#!/usr/bin/env bash
# check-file-sizes.sh -- Report files exceeding 500-line threshold
# Grandfathered files listed but not flagged as regressions

THRESHOLD=500
BASELINE_FILE="scripts/.file-size-baseline.json"
# Scan encryption/sync directories primarily
WATCH_DIRS=(
  "frontend/packages/ui/src/services/encryption"
  "frontend/packages/ui/src/services"
)

# Count lines per file, compare against baseline
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Two separate browser launches for multi-session | BrowserContext pages for same-device tabs | Phase 5 | Correct isolation model per scenario |
| No encryption performance testing | Vitest benchmark with real Web Crypto | Phase 5 | Catches performance regressions |
| Manual file-size review | Automated monitoring script with grandfathering | Phase 5 | Prevents god-file regrowth |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (E2E) | Playwright 1.58.0 |
| Framework (Unit) | Vitest (via vitest.config.ts in ui package) |
| Config files | `frontend/apps/web_app/playwright.config.ts`, `frontend/packages/ui/vitest.config.ts` |
| Quick run (E2E) | `cd frontend/apps/web_app && npx playwright test tests/multi-tab-encryption.spec.ts` |
| Quick run (Unit) | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/performance.test.ts` |
| Full suite | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-01 | Two tabs, same chat, both decrypt | E2E | `npx playwright test tests/multi-tab-encryption.spec.ts -g "TEST-01"` | Wave 0 |
| TEST-02 | Create in tab A, open in tab B, decrypts | E2E | `npx playwright test tests/multi-tab-encryption.spec.ts -g "TEST-02"` | Wave 0 |
| TEST-03 | All historical fixtures decrypt | Unit | `npx vitest run src/services/encryption/__tests__/regression-fixtures.test.ts` | Exists (14 tests) |
| TEST-04 | 100-message encrypt/decrypt under 2s | Unit | `npx vitest run src/services/encryption/__tests__/performance.test.ts` | Wave 0 |
| TEST-05 | File-size monitoring script | Manual/CI | `bash scripts/check-file-sizes.sh` | Wave 0 |
| ARCH-05 | Architecture doc with diagrams | Manual | Verify file exists and has Mermaid blocks | Wave 0 |

### Sampling Rate
- **Per task commit:** Run relevant test file (E2E spec or Vitest file)
- **Per wave merge:** `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/`
- **Phase gate:** Full encryption test suite green + E2E multi-tab spec passing

### Wave 0 Gaps
- [ ] `frontend/apps/web_app/tests/multi-tab-encryption.spec.ts` -- covers TEST-01, TEST-02
- [ ] `frontend/packages/ui/src/services/encryption/__tests__/performance.test.ts` -- covers TEST-04
- [ ] `scripts/check-file-sizes.sh` -- covers TEST-05
- [ ] `scripts/.file-size-baseline.json` -- baseline for grandfathering

## Open Questions

1. **Tab B navigation after shared login**
   - What we know: Same BrowserContext shares cookies and IndexedDB. Tab B should be able to navigate to `/chat` without logging in.
   - What's unclear: Whether the app's client-side auth initialization (masterKey derivation, store hydration) works correctly when a second tab opens without going through the login flow. The app's `initializeApp()` in `app.ts` runs on mount and checks auth state.
   - Recommendation: Test this empirically. If tab B's auth hydration fails, may need to wait for tab A's BroadcastChannel key propagation before tab B navigates.

2. **Chat-test-helpers compatibility with multi-tab**
   - What we know: `loginToTestAccount` from `chat-test-helpers.ts` handles login with retry logic and "Stay logged in" toggle.
   - What's unclear: Whether the helper works correctly when called from a spec that manually creates the browser/context (vs using Playwright's default test fixtures).
   - Recommendation: The existing `multi-session-encryption.spec.ts` already manually creates browser/context and has its own login helper. Follow the same pattern -- either reuse `chat-test-helpers.ts` or inline a simpler version.

3. **TEST-03 verification scope**
   - What we know: `regression-fixtures.test.ts` has 14 tests and `formats.test.ts` has 12 tests. Both exist and cover Formats A-D.
   - What's unclear: Whether these tests have been run against the post-Phase-4 code. The imports point to `cryptoService` which re-exports from the new encryptor modules.
   - Recommendation: Run them as a first step. If they pass, TEST-03 is already satisfied. If any fail, that's a Phase 4 regression to fix.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Playwright | TEST-01, TEST-02 | Yes | 1.58.0 | -- |
| Vitest | TEST-03, TEST-04 | Yes | (configured) | -- |
| node:crypto webcrypto | TEST-04 | Yes | Node.js built-in | -- |
| wc (line count) | TEST-05 | Yes | /usr/bin/wc | -- |
| Mermaid rendering | ARCH-05 | Yes | GitHub/editor renders | -- |

**Missing dependencies:** None.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `multi-session-encryption.spec.ts` (484 lines) -- full E2E multi-browser encryption test pattern
- Existing codebase: `regression-fixtures.test.ts` (329 lines) -- crypto environment setup pattern for Vitest
- Existing codebase: `chat-test-helpers.ts` -- reusable login/chat helpers
- Existing codebase: `import-audit.test.ts` -- static analysis test pattern
- Existing codebase: `playwright.config.ts` -- Playwright configuration
- Existing codebase: `vitest.config.ts` -- Vitest configuration for UI package

### Secondary (MEDIUM confidence)
- Playwright docs: BrowserContext isolation model (pages within a context share storage)
- Node.js docs: `webcrypto` API compatibility with Web Crypto

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all tools already installed and configured in the project
- Architecture: HIGH -- patterns directly derived from existing 93 E2E specs and 6 encryption unit tests
- Pitfalls: HIGH -- identified from actual code patterns and existing test infrastructure analysis

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable -- testing patterns don't change fast)
