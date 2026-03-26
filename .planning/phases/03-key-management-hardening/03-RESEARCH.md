# Phase 3: Key Management Hardening - Research

**Researched:** 2026-03-26
**Domain:** Client-side encryption key lifecycle, cross-tab coordination, race condition prevention
**Confidence:** HIGH

## Summary

Phase 3 is the highest-risk phase of the encryption rebuild. It addresses the root causes of recurring "content decryption failed" errors by hardening ChatKeyManager as the single, race-condition-free authority for all chat key operations. The existing ChatKeyManager (1046 lines) is architecturally sound -- it already has a state machine, provenance tracking, queue-and-flush, BroadcastChannel cross-tab coordination, and critical-op locking. The work is about closing remaining gaps, not rewriting.

Three specific areas require attention: (1) adding Web Locks API mutex to prevent cross-tab key generation races, (2) implementing key-before-content buffering in sync handlers so encrypted content never arrives before its decryption key is available, and (3) resolving the 3 needs-investigation bypass items from the Phase 1 code inventory. The master key cross-device mechanism was confirmed architecturally sound in Phase 1 -- the gap is implementation reliability (key loading timing, not key distribution design).

**Primary recommendation:** Extend the existing ChatKeyManager with Web Locks for key generation, add a message buffer in sync handlers that holds encrypted content until `chatKeyManager.getKey()` resolves, and formalize the already-working cross-device master key distribution. Do not rewrite ChatKeyManager -- extend it incrementally with regression tests after each change.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Fix the 3 needs-investigation bypass items and route all chat-key operations exclusively through ChatKeyManager. Leave the 14 legitimate bypasses alone (master key ops, share encryption, email crypto) -- they operate on different key types and don't belong in ChatKeyManager.
- **D-02:** Clean architectural boundary: ChatKeyManager owns chat keys exclusively. Other key types (master key, share key, email key) use their own dedicated paths. This is the most reliable solution that doesn't break existing chats.
- **D-03:** The primary goal is prevention, not error handling. The architecture must make decryption failures structurally impossible by guaranteeing keys are always available before content arrives.
- **D-04:** As a safety net for edge cases: show a visible error in the chat UI + log to debug.py. Never fail silently. But the error path should be rare-to-never if the architecture is correct.
- **D-05:** Buffer encrypted messages until the decryption key is confirmed available. Messages may appear slightly delayed but will never fail to decrypt. This is the "hold messages" approach -- the most reliable guarantee against the key-before-content race condition that caused the majority of bug reports.

### Claude's Discretion
- Web Locks API integration details (lock naming, timeout, fallback for browsers without support)
- ChatKeyManager state machine extension details
- BroadcastChannel implementation for cross-tab key propagation
- Specific code changes to implement the message buffering guarantee

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| KEYS-01 | Cross-tab mutex via Web Locks API prevents two tabs from generating different keys for the same chat simultaneously | Web Locks API research (exclusive mode, AbortSignal timeout, lock naming pattern `om-chatkey-{chatId}`) |
| KEYS-02 | Key generation is blocked when a valid key already exists for a chat -- no overwrite, no duplicate | ChatKeyManager.createKeyForNewChat() already has immutability guard; needs Web Lock wrapping and IDB re-read before generation |
| KEYS-03 | All encrypt/decrypt operations receive keys exclusively from ChatKeyManager.withKey() -- zero bypass paths | Code inventory shows 0 confirmed violations, 3 needs-investigation items in hiddenChatService.ts and db.ts |
| KEYS-04 | Atomic key-before-content guarantee: encrypted content is never delivered to a device that doesn't yet have the decryption key | Message buffer pattern in sync handlers; hold incoming encrypted payloads until chatKeyManager.getKey() resolves |
| KEYS-05 | ChatKeyManager state machine correctly handles all transitions (unloaded to loading to ready, loading to failed, retry paths) | Current state machine analysis complete; needs `failed -> loading` retry transition and deadlock prevention |
| KEYS-06 | Master key cross-device mechanism is formally designed and implemented -- new devices can decrypt all existing chats | Phase 1 confirmed mechanism is architecturally sound (PBKDF2/HKDF deterministic derivation); formalize with documentation and add validation on login |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Web Locks API (`navigator.locks`) | Browser built-in (Baseline since March 2022) | Cross-tab mutex for key generation | Only browser-native mutex across tabs. Prevents the #1 bug pattern (two tabs generating different keys). |
| BroadcastChannel API | Browser built-in (Baseline since March 2022) | Cross-tab key propagation and cache invalidation | Already partially implemented in ChatKeyManager. Complete the keyLoaded path for cache warming. |
| Web Crypto API (`crypto.subtle`) | Browser built-in | AES-GCM encrypt/decrypt, key generation | Already in use. No changes needed to crypto primitives. |
| IndexedDB | Browser built-in | Key persistence (encrypted_chat_key per chat) | Already in use. No changes to storage layer. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Vitest | 3.2+ (existing) | Unit/integration tests for state machine, lock patterns | All ChatKeyManager changes must have test coverage |
| Playwright | 1.49 (existing) | Multi-tab E2E tests (Phase 5, not this phase) | Deferred to Phase 5 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Web Locks API | SharedWorker | SharedWorker is harder to debug and has inconsistent mobile support. Web Locks is simpler and achieves same coordination. |
| BroadcastChannel | localStorage `storage` event | Legacy pattern, string-only data, doesn't fire on writing tab. BroadcastChannel is the modern replacement. |

**Installation:**
```bash
# No new packages needed. All APIs are browser built-in.
```

## Architecture Patterns

### Recommended Changes to ChatKeyManager

The file is 1046 lines. Changes should be surgical, not a rewrite.

```
ChatKeyManager.ts (existing 1046 lines)
  +-- Web Locks wrapper for createKeyForNewChat / createAndPersistKey
  +-- BroadcastChannel keyLoaded handler (warm cache from other tabs)
  +-- State machine: add failed -> loading retry transition
  +-- Message buffer integration point (emitKeyReady event)

Sync handlers (chatSyncServiceHandlers*.ts)
  +-- Message buffer: hold encrypted payloads until key is ready
  +-- Use chatKeyManager.withKey() for all encrypt/decrypt paths
```

### Pattern 1: Web Lock Around Key Generation

**What:** Wrap `createKeyForNewChat()` and `createAndPersistKey()` with `navigator.locks.request()` in exclusive mode so only one tab can generate a key for a given chatId.

**When to use:** Every key generation call.

**Example:**
```typescript
// Source: MDN Web Locks API + existing ChatKeyManager pattern
async createAndPersistKeyLocked(chatId: string): Promise<{
  chatKey: Uint8Array;
  encryptedChatKey: string;
}> {
  // Guard: browser without Web Locks (SSR, older browsers)
  if (typeof navigator === 'undefined' || !navigator.locks) {
    return this.createAndPersistKey(chatId);
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10_000);

  try {
    return await navigator.locks.request(
      `om-chatkey-${chatId}`,
      { signal: controller.signal },
      async () => {
        // Re-check: another tab may have created the key while we waited
        const existing = this.keys.get(chatId);
        if (existing) {
          const encryptedChatKey = await encryptChatKeyWithMasterKey(existing);
          return { chatKey: existing, encryptedChatKey: encryptedChatKey! };
        }
        // Also check IDB in case another tab persisted but we haven't loaded
        const loaded = await this.getKey(chatId);
        if (loaded) {
          const encryptedChatKey = await encryptChatKeyWithMasterKey(loaded);
          return { chatKey: loaded, encryptedChatKey: encryptedChatKey! };
        }
        // No key exists anywhere -- safe to generate
        return this.createAndPersistKey(chatId);
      }
    );
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      console.error(`[ChatKeyManager] Web Lock timeout for key creation: ${chatId}`);
      // Fallback: attempt without lock (better than failing)
      return this.createAndPersistKey(chatId);
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}
```

### Pattern 2: Message Buffer for Key-Before-Content Guarantee

**What:** Sync handlers hold encrypted messages in a per-chat buffer when the key is not yet available. When the key arrives (via `receiveKeyFromServer` or `loadKeyFromDB`), the buffer flushes automatically.

**When to use:** Every sync handler that receives encrypted content (`ai_typing_started`, `new_chat_message`, `phased_sync`, `ai_background_response_completed`).

**Example:**
```typescript
// In sync handler receiving encrypted message:
const chatKey = chatKeyManager.getKeySync(chatId);
if (chatKey) {
  // Fast path: key available, decrypt immediately
  await decryptAndStore(message, chatKey);
} else {
  // Key not yet available -- use withKey to buffer
  await chatKeyManager.withKey(chatId, `decrypt-msg-${messageId}`, async (key) => {
    await decryptAndStore(message, key);
  });
}
```

The existing `queueOperation` / `withKey` / `flushPendingOps` infrastructure in ChatKeyManager already implements this pattern. The work is ensuring every sync handler uses it consistently instead of falling through to error paths.

### Pattern 3: BroadcastChannel Key Propagation (Complete)

**What:** When a tab loads or generates a key, broadcast the encrypted form to other tabs so they can warm their cache without an IDB read.

**Current state:** The `keyLoaded` message type already exists in the CrossTabMessage union but the handler is a no-op comment: "Instead we rely on the existing lazy-load path."

**Completion:**
```typescript
// In handleCrossTabMessage:
if (msg.type === 'keyLoaded') {
  // Only warm cache if we don't already have this key
  if (!this.keys.has(msg.chatId)) {
    // Decrypt the encrypted form using our local master key
    this.receiveKeyFromServer(msg.chatId, msg.encryptedChatKey)
      .catch(err => console.debug('[ChatKeyManager] Cross-tab key warm failed:', err));
  }
}

// After key is loaded/created, broadcast:
private broadcastKeyLoaded(chatId: string, encryptedChatKey: string): void {
  this.broadcastChannel?.postMessage({
    type: 'keyLoaded',
    chatId,
    encryptedChatKey,
  } satisfies CrossTabMessage);
}
```

### Anti-Patterns to Avoid

- **Never generate a key in a sync handler.** If the key is missing during a receive path, buffer the operation. Only `createKeyForNewChat` / `createAndPersistKey` may generate keys.
- **Never use `getKeySync()` as the sole key acquisition in a decrypt path.** It returns null if the key is still loading. Use `getKey()` (async) or `withKey()` (buffers) instead. The Phase 1 root cause analysis (bug 7d2d2efc) was exactly this pattern.
- **Never call `decryptChatKeyWithMasterKey()` directly in sync handlers.** Always go through `chatKeyManager.receiveKeyFromServer()` which handles conflict detection, provenance tracking, and queue flushing.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-tab mutex | Custom SharedArrayBuffer locking | `navigator.locks.request()` | Browser-native, works across tabs and workers, handles deadlocks |
| Cross-tab messaging | Custom localStorage polling | BroadcastChannel API | Purpose-built, structured data, fires on all tabs including sender |
| Operation timeout | Manual setTimeout tracking | `AbortController` + `signal` option on `navigator.locks.request()` | Standard pattern, integrates with Web Locks natively |
| Key caching | Local Maps in individual modules | ChatKeyManager singleton | Single source of truth prevents cache drift (Anti-Pattern 3 from Architecture research) |

## Common Pitfalls

### Pitfall 1: Web Lock Deadlock from Nested Locks
**What goes wrong:** Code acquires lock A, then inside the callback tries to acquire lock A again. Web Locks does not support re-entrant locking -- the inner request waits forever.
**Why it happens:** A helper function wraps key creation in a lock, and a caller also wraps the entire flow in a lock with the same name.
**How to avoid:** Lock at the lowest level only (inside `createAndPersistKey`). Callers never acquire their own locks. Use `ifAvailable: true` for diagnostic checks.
**Warning signs:** Lock acquisition takes > 5 seconds in development.

### Pitfall 2: Web Lock Orphaned by Page Unload
**What goes wrong:** Tab holding a lock closes or crashes. Other tabs waiting for that lock are blocked indefinitely.
**Why it happens:** Web Locks are released when the holding tab is closed, but there is a brief window during `beforeunload` where the lock may not be released immediately.
**How to avoid:** Always use `AbortController` with a timeout (10 seconds) on lock requests. If the lock cannot be acquired within the timeout, fall back to the unlocked path (which has the existing immutability guard as a safety net).
**Warning signs:** `AbortError` appearing in production logs.

### Pitfall 3: getKeySync() in Decrypt Paths on Secondary Devices
**What goes wrong:** A decrypt path uses `getKeySync()` which returns null because the key is still being loaded from IDB. The code falls through to an error path showing "[Content decryption failed]".
**Why it happens:** This was the exact root cause of bug 7d2d2efc. `getKeySync()` is a synchronous memory-only lookup. On secondary devices, the key must be asynchronously loaded from `encrypted_chat_key` via master key decryption.
**How to avoid:** Replace `getKeySync()` in all decrypt paths with either `getKey()` (async, waits for loading) or `withKey()` (buffers the operation). Reserve `getKeySync()` for quick checks where null is an acceptable result (e.g., "is key loaded?" checks, not "give me the key for decryption").
**Warning signs:** `getKeySync()` calls where the null path leads to error handling instead of buffering.

### Pitfall 4: BroadcastChannel keyLoaded Creating Load Storms
**What goes wrong:** When tab A broadcasts `keyLoaded` for 100 chats during bulk init, all other tabs simultaneously attempt to decrypt 100 encrypted_chat_key values, causing UI jank.
**Why it happens:** No throttling or batching on the receiving side.
**How to avoid:** Only process `keyLoaded` messages for chats the receiving tab has pending operations for (check `pendingOps.has(chatId)` before initiating async decryption). Ignore keyLoaded for chats with no pending operations -- they will lazy-load when needed.
**Warning signs:** High CPU usage in background tabs during sync.

### Pitfall 5: Breaking the Critical-Op Lock with Web Locks
**What goes wrong:** The existing `criticalOpCount` lock protects against `clearAll()` during in-flight encryption. Adding Web Locks must not bypass this protection. If a Web Lock callback runs while `clearAll()` is deferred, the key may be generated into a cache that is about to be cleared.
**How to avoid:** Inside the Web Lock callback, check `this.deferredClearAll`. If true, abort key generation (the user is logging out). Also acquire the critical-op lock before starting encryption within the Web Lock scope.
**Warning signs:** Keys being created immediately after logout events.

## Code Examples

### Current getKeySync Usage That Needs Attention

There are approximately 35+ `getKeySync()` calls across sync handlers. Most follow this pattern:

```typescript
// CURRENT (potentially racy on secondary devices):
const chatKey = chatKeyManager.getKeySync(payload.chat_id);
if (!chatKey) {
  // Various error handling -- some abort, some try fallbacks
}

// TARGET (buffered, never fails):
await chatKeyManager.withKey(payload.chat_id, "decrypt-incoming-title", async (key) => {
  const title = await decryptWithChatKey(payload.encrypted_title, key);
  // process decrypted title...
});
```

Key files with getKeySync() calls that need review:
- `chatSyncServiceHandlersAI.ts` -- 12 calls (AI streaming, post-processing)
- `chatSyncServiceHandlersChatUpdates.ts` -- 7 calls (broadcast handlers)
- `chatSyncServiceSenders.ts` -- 3 calls (outbound encryption)
- `chatSyncServiceHandlersPhasedSync.ts` -- 1 call (metadata validation)
- `chatMetadataCache.ts` -- 3 calls (sidebar cache)
- `db/chatKeyManagement.ts` -- 5 calls (DB-level operations)

Not all of these need changing -- some are legitimately sync-safe (e.g., in render paths where showing a placeholder is acceptable). The planner must classify each into: (a) must convert to withKey/getKey, (b) acceptable as-is with null handling.

### 3 Needs-Investigation Bypass Items

From the Phase 1 code inventory:

1. **`hiddenChatService.ts` line 155 -- `getKeyFromStorage()` direct import**
   - Gets master key for PBKDF2 derivation of hidden chat combined secret
   - **Verdict:** Legitimate master key operation. Not a ChatKeyManager bypass. The import is fragile but functionally correct. LOW priority -- add a comment documenting why it is legitimate.

2. **`hiddenChatService.ts` lines 17-18, 257, 490, 623 -- direct `encryptChatKeyWithMasterKey`/`decryptChatKeyWithMasterKey` imports**
   - Hidden chats use a different wrapping key (combined secret vs master key). ChatKeyManager is unaware of hidden chat key wrapping.
   - **Verdict:** This IS a gap. When a chat is hidden, the key is re-wrapped with the combined secret. When unhidden, it is re-wrapped with the master key. ChatKeyManager's provenance tracking does not capture these transitions.
   - **Recommendation:** Add `hideChat(chatId)` / `unhideChat(chatId)` methods to ChatKeyManager that handle the re-wrapping internally. This keeps key wrapping consolidated. MEDIUM priority.

3. **`db.ts` line 532 -- `getKeyFromStorage()` direct import**
   - Checks master key availability during DB init to decide whether to attempt bulk key loading.
   - **Verdict:** Legitimate. This is a master key availability check, not a chat key bypass. LOW priority -- acceptable as-is.

**Summary:** Only item 2 (hiddenChatService key wrapping) is a real gap that should be addressed. Items 1 and 3 are legitimate master key operations that correctly bypass ChatKeyManager.

### Web Locks Lock Naming Convention

```typescript
// Key generation lock (exclusive, per-chat)
const LOCK_PREFIX = 'om-chatkey-';  // e.g., 'om-chatkey-abc123'

// Key generation uses exclusive mode (only one tab generates at a time)
// 10-second timeout via AbortController
// Fallback to unlocked path on timeout (immutability guard is the safety net)
```

### State Machine Transitions (Current + Proposed)

```
Current:
  unloaded --[getKey()]--> loading --[success]--> ready
  unloaded --[getKey()]--> loading --[failure]--> failed
  ready    --[removeKey()]--> (deleted)
  *        --[clearAll()]--> (all deleted)

Proposed additions:
  failed   --[retryKey()]--> loading --[success]--> ready    # NEW: retry from failed
  failed   --[retryKey()]--> loading --[failure]--> failed   # NEW: retry fails again
  ready    --[receiveKeyFromServer() conflict]--> ready      # EXISTING: server wins
  loading  --[createKeyForNewChat()]--> ready                # NEW: Web Lock grants, generate
```

The `reloadKey()` method already handles `failed -> loading` by resetting state. The formal transition just needs documentation and a test.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `getOrGenerateChatKey()` combined get+generate | Separate `getKey()` and `createKeyForNewChat()` | Commit 3d8148bc4 (March 2026) | Eliminated the #1 root cause of key corruption |
| No key provenance | `KeyProvenance` tracking (source, timestamp, fingerprint) | Commit 3d8148bc4 | Enables debugging which key is wrong and where it came from |
| No cross-tab key coordination | BroadcastChannel `clearAll` + critical-op lock | Commit 38e64d359 | Prevents multi-tab auth disruption key corruption |
| Sync `getKeySync()` in all paths | Async `getKey()` with IDB fallback | Commit 33e87e0be (partial) | Fixed secondary device race; some paths still use sync lookup |

**Not yet implemented:**
- Web Locks for key generation mutex (browser-native, no polyfill)
- BroadcastChannel `keyLoaded` message handling (type exists, handler is no-op)
- Message buffering in sync handlers (pattern exists in `withKey`, not consistently used)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest 3.2+ (existing, jsdom environment) |
| Config file | `frontend/packages/ui/vitest.config.ts` |
| Quick run command | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ChatKeyManager.test.ts` |
| Full suite command | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| KEYS-01 | Two concurrent createAndPersistKey calls produce one key | unit | `npx vitest run ChatKeyManager.test.ts -t "web lock"` | Needs new tests |
| KEYS-02 | createKeyForNewChat rejects when key exists | unit | `npx vitest run ChatKeyManager.test.ts -t "existing"` | Partial (existing test checks warn, not lock) |
| KEYS-03 | All encrypt/decrypt routed through ChatKeyManager | manual audit + grep | `grep -r "getKeySync\|getKey(" --include="*.ts" services/` | Manual |
| KEYS-04 | Encrypted message buffered until key ready | unit | `npx vitest run ChatKeyManager.test.ts -t "withKey.*queue"` | Partial (queueOperation tested) |
| KEYS-05 | State machine transitions: all valid, no deadlocks | unit | `npx vitest run ChatKeyManager.test.ts -t "state"` | Needs new tests |
| KEYS-06 | Master key cross-device: login on new device decrypts keys | manual + existing regression | `npx vitest run regression-fixtures.test.ts` | Existing (14 tests) |

### Sampling Rate
- **Per task commit:** `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/`
- **Per wave merge:** Full encryption test suite (65 tests across 5 test files)
- **Phase gate:** All encryption tests green + regression fixtures pass

### Wave 0 Gaps
- [ ] `ChatKeyManager.test.ts` -- Add Web Locks mock tests (navigator.locks not available in jsdom, needs mock)
- [ ] `ChatKeyManager.test.ts` -- Add state machine transition tests (failed -> loading retry)
- [ ] `ChatKeyManager.test.ts` -- Add BroadcastChannel keyLoaded handler tests
- [ ] `ChatKeyManager.test.ts` -- Add withKey buffering + flush timing tests

## Open Questions

1. **jsdom Web Locks mock**
   - What we know: jsdom does not implement `navigator.locks`. The existing test file stubs `crypto` but not locks.
   - What's unclear: Best approach for mocking -- custom mock object vs vitest spy vs real browser tests.
   - Recommendation: Create a minimal `navigator.locks.request()` mock that simulates exclusive locking behavior (queue requests, execute serially). This is sufficient for unit tests. Cross-tab E2E tests in Phase 5 will use Playwright with real browsers.

2. **`chatSyncServiceSenders.ts` lines 1999-2069 -- duplicate key acquisition path**
   - What we know: `sendEncryptedStoragePackage` has its own key acquisition logic (IDB read, master key decrypt, hidden chat fallback) that partially duplicates ChatKeyManager.
   - What's unclear: Whether this can be fully replaced with `chatKeyManager.getKey()` or if the fallback paths serve a purpose ChatKeyManager doesn't cover.
   - Recommendation: This belongs in Phase 4 (sync handler rewire). For Phase 3, ensure ChatKeyManager's `getKey()` path handles all the same fallbacks. Then Phase 4 replaces the inline logic.

3. **Hidden chat key wrapping gap**
   - What we know: `hiddenChatService.ts` wraps/unwraps keys with a combined secret, bypassing ChatKeyManager provenance tracking.
   - What's unclear: Whether adding `hideChat()`/`unhideChat()` to ChatKeyManager introduces circular dependency with hiddenChatService.
   - Recommendation: ChatKeyManager should accept a `wrappingKey` parameter in new methods, avoiding direct import of hiddenChatService. The hidden chat service calls `chatKeyManager.rewrapKey(chatId, oldWrappingKey, newWrappingKey)` or similar.

## Sources

### Primary (HIGH confidence)
- `ChatKeyManager.ts` (1046 lines) -- complete read, all methods analyzed
- `MessageEncryptor.ts` (338 lines) -- complete read, Phase 2 extraction verified
- `encryption-root-causes.md` -- 3 bug reports, 4 fix commits, common patterns documented
- `encryption-code-inventory.md` -- 135+ call sites, 14 legitimate bypasses, 3 needs-investigation
- `master-key-lifecycle.md` -- full derivation chain, cross-device mechanism confirmed sound
- MDN Web Locks API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API
- MDN LockManager.request(): https://developer.mozilla.org/en-US/docs/Web/API/LockManager/request

### Secondary (MEDIUM confidence)
- `.planning/research/STACK.md` -- Web Locks + BroadcastChannel recommendations (from project research phase)
- `.planning/research/ARCHITECTURE.md` -- withKey pattern, data flow diagrams
- `.planning/research/PITFALLS.md` -- 13 pitfalls catalogued from commit history

### Tertiary (LOW confidence)
- None -- all findings are grounded in codebase analysis and official MDN documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Browser built-in APIs, no new dependencies, already partially implemented
- Architecture: HIGH -- Extending existing well-structured ChatKeyManager, patterns verified in codebase
- Pitfalls: HIGH -- All pitfalls derived from actual bug reports and commit history in this codebase

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable domain -- browser APIs don't change frequently)
