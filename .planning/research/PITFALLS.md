# Domain Pitfalls: Client-Side Encryption & Real-Time Sync Rebuild

**Domain:** Encrypted chat application with cross-device WebSocket sync
**Researched:** 2026-03-26
**Confidence:** HIGH (based on actual codebase failure patterns, commit history, and known bug reports)

---

## Critical Pitfalls

Mistakes that cause data loss, unreadable chats, or require emergency rollbacks.

### Pitfall 1: Key Generation Races — Creating Keys When Existing Keys Should Be Used

**What goes wrong:** A code path that needs a chat key finds no key in memory, assumes the chat is new, and generates a fresh key (K2). The original key (K1) was the correct one — it just had not loaded yet from IndexedDB or had not arrived via WebSocket. Now half the chat's messages are encrypted with K1 and the other half with K2. Neither key can decrypt the other's ciphertext.

**Why it happens:** IndexedDB reads are async. WebSocket key delivery is async. Any `getOrGenerateKey()` pattern that falls through to generation when the async lookup returns null (but the key is in-flight) creates this race. In OpenMates, this was the root cause of the recurring "content decryption failed" errors — `sendEncryptedStoragePackage` would create K2 because the IDB cache was empty, even though K1 was the correct key arriving moments later.

**Consequences:** Permanent data corruption. Messages encrypted with the wrong key cannot be decrypted without manual intervention. The user sees "content decryption failed" on random messages.

**Prevention:**
- NEVER combine "get" and "generate" in a single function. Generation must be an explicit, separate call (`createKeyForNewChat`) that asserts no key exists. This is already the design in `ChatKeyManager.ts` — the rebuild must preserve and enforce it.
- All code paths that need a key must use `getKey()` (async, waits for loading) or `withKey()` (queues the operation). Never `getKeySync() || generateNew()`.
- Add a runtime assertion: if `createKeyForNewChat` is called for a chatId that already has messages in IndexedDB, throw immediately (the chat is not new).

**Detection:** Key provenance tracking (`KeySource` in `ChatKeyManager`) is the primary detection mechanism. If you see provenance `"created"` on a secondary device, something went wrong. Log and alert on provenance mismatches across devices.

**Which phase should address it:** Phase 1 (Audit) — verify all code paths that call `createKeyForNewChat` and confirm none can fire on a secondary device for an existing chat.

---

### Pitfall 2: Cross-Device Key Delivery Depends on WebSocket Being Connected

**What goes wrong:** Device B opens the app while Device A is mid-conversation. Device B needs the chat key to decrypt incoming messages. The key is delivered via WebSocket (`receiveKeyFromServer`), but if the WebSocket connection drops between the initial sync response and the first `ai_typing_started` message, Device B never receives the key. All subsequent messages arrive as undecryptable ciphertext.

**Why it happens:** WebSocket is inherently unreliable — mobile devices suspend connections, networks switch, browser tabs get backgrounded. The key delivery piggybacks on sync messages rather than having its own guaranteed delivery mechanism with acknowledgment and retry.

**Consequences:** Device B cannot decrypt any messages for that chat until it reconnects and re-syncs. If the user is actively watching the conversation on Device B, they see encrypted garbage or "[Decryption failed]" placeholders.

**Prevention:**
- Every encrypted payload (not just the first) should include `encrypted_chat_key` so that even if earlier messages were missed, any single message is self-contained for key bootstrapping. The current architecture already does this for `ai_typing_started` and `new_chat_message` — verify this is consistent across ALL message types that carry encrypted content.
- Phased sync Phase 1 (last active chat) must always include `encrypted_chat_key` in the payload, not just when versions mismatch. Commit `87c1757f3` fixed this for embed_keys — verify the same pattern holds for chat keys.
- On reconnect, the client should re-request keys for any chats in `"loading"` or `"failed"` state.

**Detection:** Monitor for chats where `ChatKeyManager` state is `"failed"` more than 10 seconds after WebSocket connects. This indicates a key was never delivered.

**Which phase should address it:** Phase 2 (Architecture Design) — design the key delivery guarantee as a first-class concern, not a side-effect of sync messages.

---

### Pitfall 3: Multi-Tab / Multi-Window Key Cache Invalidation During Auth Events

**What goes wrong:** Tab A triggers a logout/re-auth event that calls `clearAll()` on `ChatKeyManager`. Tab B is mid-encryption (`sendEncryptedStoragePackage`). Tab B's in-memory keys are wiped between reading the key and writing the ciphertext, causing it to fall through to key generation (K2). The original key (K1) is lost from memory.

**Why it happens:** `BroadcastChannel` propagates `clearAll` across tabs, but there is no coordination with in-flight crypto operations in other tabs. This is the exact bug that commit `38e64d359` (critical operation lock) fixed — but the fix only protects within a single tab. Cross-tab, the lock is not shared.

**Consequences:** Key corruption (K1 replaced by K2 in one tab). Same as Pitfall 1 but triggered by auth events rather than sync races.

**Prevention:**
- The `criticalOpCount` lock pattern in `ChatKeyManager` is correct for single-tab protection. For cross-tab, the `BroadcastChannel` `clearAll` message must be handled with the same deferred-clear logic (already implemented in `handleCrossTabMessage`).
- During the rebuild, verify that ALL operations that encrypt data (not just `sendEncryptedStoragePackage`) acquire the critical-op lock. Check `messageOperations.ts:481` and any other encrypt-then-send patterns.
- Add an integration test: open two tabs, trigger auth re-verification in one while the other is encrypting. Verify no key corruption.

**Detection:** Log whenever `clearAll()` is deferred due to critical-op lock. If this never fires in production, either the lock is not being acquired or the race does not occur in practice.

**Which phase should address it:** Phase 3 (Refactor) — ensure critical-op lock coverage is complete before modifying any encryption code paths.

---

### Pitfall 4: IndexedDB Transaction Timing — Reads After Writes May Return Stale Data

**What goes wrong:** Code writes an `encrypted_chat_key` to IndexedDB, then immediately reads it back in a different transaction. The read returns `null` because the write transaction has not committed yet. The caller concludes the key does not exist and either generates a new one or fails decryption.

**Why it happens:** IndexedDB transactions are async and do not guarantee read-after-write consistency across separate transactions. The Web API provides `oncomplete` callbacks, but if code does not await transaction completion before starting a new transaction, it may read stale data. This is exacerbated by Svelte's reactive system, which may trigger re-renders that start new reads before the write completes.

**Consequences:** Phantom "key not found" errors that are intermittent and hardware-dependent (faster devices hit it less). Difficult to reproduce reliably.

**Prevention:**
- Always await the IDB transaction's `oncomplete` promise before starting a dependent read. The `createAndPersistKey` method in `ChatKeyManager` does this correctly — verify all other write-then-read patterns do too.
- For critical operations (key persistence), use a single IDB transaction for both the write and any dependent reads. IDB guarantees consistency within a single transaction.
- Never rely on IndexedDB as the source of truth for in-memory key state. `ChatKeyManager`'s in-memory `Map<string, Uint8Array>` is the primary cache; IndexedDB is the persistence layer. Reads should hit memory first (`getKeySync`), IDB second (`getKey`).

**Detection:** If `loadKeyFromDB` returns `null` for a chatId that was just persisted via `createAndPersistKey`, the transaction ordering is broken. Add a debug assertion: after `persistEncryptedChatKeyFn`, immediately read back and compare.

**Which phase should address it:** Phase 3 (Refactor) — audit all IDB write-then-read sequences during the encryption code restructuring.

---

### Pitfall 5: Backwards Compatibility — Breaking Existing Encrypted Data During Migration

**What goes wrong:** A refactor changes the encryption format (e.g., adding a key fingerprint prefix to ciphertext, changing IV derivation, modifying the encrypted_chat_key wrapping format). Old messages encrypted in the old format become undecryptable because the new code does not recognize the old format.

**Why it happens:** The developer tests with fresh data and the new format works perfectly. They forget (or do not know) that thousands of existing messages use the old format. The format sniffing/fallback code is missing or incomplete.

**Consequences:** Every existing encrypted chat becomes unreadable. In OpenMates, this happened with commit `e418f49e6` — a fingerprint format change broke CLI decryption of existing chat metadata.

**Prevention:**
- NEVER change the ciphertext format without a format version prefix. Before the rebuild, document the exact current format: `[IV (12 bytes)][ciphertext][auth tag (16 bytes)]` (or whatever it is). The new code must always try the current format first, then fall back to legacy format detection.
- Write a migration verification test: take a snapshot of 10+ real encrypted messages (from different time periods) and their keys. After every code change, verify all 10+ decrypt successfully. This test runs in CI.
- The `encrypted_chat_key` wrapping format is especially sensitive — it is stored on the server and shared across devices. Changing it without a fallback breaks every device that has not updated yet.
- Embed encryption keys derived via `deriveEmbedKey` must use the same derivation parameters. If the derivation changes, old embeds become undecryptable.

**Detection:** A spike in `recordDecryptionFailure` calls in `decryptionFailureCache.ts` after a deploy indicates a format compatibility break.

**Which phase should address it:** Phase 1 (Audit) — document the exact binary format of every encrypted field before any code changes. Phase 3 (Refactor) — implement format sniffing with fallback in every decrypt function.

---

## Moderate Pitfalls

### Pitfall 6: WebSocket Message Ordering — Out-of-Order Delivery Corrupts Incremental State

**What goes wrong:** The server sends `ai_typing_started` (which includes the chat key) followed by streaming tokens. Due to network buffering or reconnection, the client receives tokens before `ai_typing_started`. The tokens cannot be decrypted because the key has not arrived yet. They are either dropped or cached, but the caching logic has its own bugs.

**Prevention:**
- Design message handlers to be idempotent and order-independent where possible. If a streaming token arrives before the key, queue it in memory and replay once the key arrives (the `withKey` / pending ops pattern in `ChatKeyManager` handles this).
- Every WebSocket message that carries encrypted content must include `encrypted_chat_key` as a fallback bootstrapping mechanism, not just the initial message.
- Add sequence numbers to WebSocket messages. The client can detect gaps and request retransmission of missed messages during sync.

**Detection:** If `withKey` queue depth exceeds 5 operations for a single chat, it likely means the key message was lost. Log a warning and trigger a key re-request.

**Which phase should address it:** Phase 2 (Architecture Design) — define message ordering guarantees and key delivery as part of the protocol specification.

---

### Pitfall 7: Phased Sync Race — Phase 2/3 Arrives While Phase 1 Is Still Decrypting

**What goes wrong:** Phased sync sends chat data in phases (Phase 1: last active chat, Phase 2: remaining chats, Phase 3: full content). Phase 2 starts arriving while Phase 1 decryption is still in progress. Both phases write to the same IndexedDB store. Phase 2 overwrites Phase 1's partially-decrypted data, or Phase 1's completion handler re-encrypts data that Phase 2 already updated.

**Prevention:**
- Use a per-chat mutex/lock for IndexedDB writes. No two sync phases should write to the same chat record concurrently. The `yieldToMainThread()` pattern in `chatSyncServiceHandlersCoreSync.ts` helps with UI responsiveness but does not prevent concurrent IDB writes.
- Phase 2/3 handlers should check if Phase 1 processing is complete for a given chatId before writing. If not, queue the Phase 2/3 update.
- Commit `a02969eb8` ("eliminate wasted decryption during chat sync and deduplicate Phase 2/3 processing") addressed some of this — verify it covers all paths.

**Detection:** If the same chatId is written to IDB by two different sync phases within 100ms, something is wrong. Add a debug counter per chatId per sync session.

**Which phase should address it:** Phase 3 (Refactor) — implement per-chat write locking as part of the sync service restructuring.

---

### Pitfall 8: Service Worker Cache Serving Stale Encryption Code

**What goes wrong:** A deploy updates the encryption code (e.g., new format handling, bug fix). The service worker serves the cached old version to returning users. The old code encrypts data in the old format, creating a split where some devices run new code and some run old code. Cross-device sync breaks because the formats diverge.

**Prevention:**
- The service worker must invalidate the cache on deploy. Commit `1df0863d0` added `SKIP_WAITING` — verify this is still working correctly.
- Add a version handshake to the WebSocket connection. The server includes a `min_client_version` field. If the client version is below the minimum, the server sends a "please refresh" message and refuses encrypted operations until the client updates.
- Never deploy a breaking encryption change without first deploying the backwards-compatible reader. Deploy sequence: (1) deploy code that can READ both old and new formats, (2) wait for all clients to update, (3) deploy code that WRITES the new format.

**Detection:** If the server receives encrypted data it cannot process (e.g., vault re-encryption fails), the client is likely running stale code. Log the client version on every WebSocket message.

**Which phase should address it:** Phase 2 (Architecture Design) — define the version handshake protocol. Phase 4 (Implementation) — implement two-phase deployment for format changes.

---

### Pitfall 9: Master Key Loss or Rotation Breaks All Chat Keys

**What goes wrong:** Chat keys are wrapped (encrypted) with the user's master key. If the master key changes (password reset, key rotation) or is lost (cleared from memory during a bug), all wrapped chat keys become undecryptable. Every chat key must be re-wrapped with the new master key, but this requires having the old master key available simultaneously.

**Prevention:**
- Master key rotation must be a transactional operation: (1) decrypt all chat keys with old master key, (2) re-encrypt all with new master key, (3) persist all re-wrapped keys, (4) only then discard the old master key.
- Never clear the master key from memory during normal operation. The `clearAll()` on `ChatKeyManager` should NOT clear the master key — only the per-chat keys. The master key has its own lifecycle tied to authentication.
- Store a recovery mechanism (e.g., backup codes that can derive the master key) so that a lost master key does not mean permanently lost chats.

**Detection:** After any auth event (login, token refresh, session resume), verify that `decryptChatKeyWithMasterKey` succeeds for at least one known chat. If it fails, the master key is wrong or missing.

**Which phase should address it:** Phase 1 (Audit) — document exactly when and how the master key is derived, stored, and cleared. Phase 2 (Architecture Design) — define master key lifecycle separately from chat key lifecycle.

---

### Pitfall 10: Embed Encryption Keys Derived Inconsistently Across Devices

**What goes wrong:** Embed keys are derived deterministically from the chat key and embed ID (see `deriveEmbedKey`). If the derivation parameters change, or if different devices use different chat keys for the same embed (due to Pitfall 1), the derived embed keys diverge. The embed is encrypted with one derived key on Device A and cannot be decrypted on Device B.

**Prevention:**
- Embed key derivation must be purely deterministic: `embedKey = HKDF(chatKey, embedId)`. No random salt, no timestamps, no device-specific input. Commit `45252837b` ("deterministic embed key derivation") fixed a multi-tab race here — verify the fix is complete.
- If the chat key is wrong (Pitfall 1), every embed in that chat is also wrong. Fixing embed encryption without fixing chat key races is futile.
- Commit `87c1757f3` ensured embed_keys are sent for all chats in phased sync — verify this covers the full embed lifecycle (creation, sync, re-key).

**Detection:** If an embed decrypts successfully on the originating device but fails on a secondary device, the chat key diverged. Compare key fingerprints across devices.

**Which phase should address it:** Phase 3 (Refactor) — derive embed keys from the single source of truth (`ChatKeyManager`) rather than any local cache.

---

## Minor Pitfalls

### Pitfall 11: Console Logging Leaks Decrypted Content in Production

**What goes wrong:** Debug logging during encryption/decryption prints plaintext content or raw key bytes to the browser console. In production, this defeats the purpose of client-side encryption — anyone with console access can read the data.

**Prevention:**
- All crypto debug logging must use `console.debug()` (suppressed in production builds) not `console.log()` or `console.info()`.
- Never log the raw key bytes. Log only key fingerprints (first 8 hex chars of the hash).
- Audit all `console.info` and `console.warn` calls in the `encryption/`, `db/`, and `chatSyncService*` files for plaintext leakage.

**Which phase should address it:** Phase 3 (Refactor) — as part of cleaning up the encryption module, standardize logging levels.

---

### Pitfall 12: Performance Regression from Decrypting All Messages on Every Sync

**What goes wrong:** A sync event triggers re-decryption of every message in every chat, even when the messages have not changed. This causes UI jank, especially on mobile devices with hundreds of chats.

**Prevention:**
- Use version numbers (`messages_v`, `title_v`, `draft_v`) to skip decryption when the local version matches the server version. The `ChatVersionEntry` cache in `chatKeyManagement.ts` exists for this purpose.
- Commit `a02969eb8` ("eliminate wasted decryption during chat sync") and `51f3be408` ("cache permanent decryption failures") addressed this — verify these optimizations survive the rebuild.
- Commit `718450001` fixed a "chat sync timeout for stayLoggedIn users after crypto perf regression" — this is evidence that performance-naive encryption changes can break production.

**Which phase should address it:** Phase 4 (Implementation) — performance testing with realistic data volumes (100+ chats, 1000+ messages) as part of acceptance criteria.

---

### Pitfall 13: New Chat Fields Not Added to Encryption/Decryption Scope

**What goes wrong:** A new field is added to the Chat model (e.g., `summary`, `mood`, `tags`). The field is stored in plaintext in IndexedDB and synced to the server unencrypted, breaking the E2EE guarantee for that field.

**Prevention:**
- The concern at `chatCrudOperations.ts` lines 182 and 271 documents this exact issue — new fields are not yet encrypted.
- Maintain an explicit "encrypted fields" list in the architecture doc. Every PR that adds a chat field must update this list and add the corresponding encrypt/decrypt calls.
- Add a lint rule or test: if a new field is added to the `Chat` TypeScript type, verify it appears in both `encryptChatFields` and `decryptChatFields` (or is explicitly listed as "intentionally unencrypted" with a reason).

**Which phase should address it:** Phase 1 (Audit) — create the definitive encrypted fields list. Phase 2 (Architecture Design) — design the field encryption registry so new fields cannot be forgotten.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Audit (Phase 1) | Incomplete inventory of encrypt/decrypt code paths — missing one path means the rebuild leaves a legacy race condition alive | Use `grep` for ALL calls to `encryptWithChatKey`, `decryptWithChatKey`, `_generateChatKeyInternal`, `createKeyForNewChat`. Cross-reference with the 15+ encryption-related commits from March 2026. |
| Architecture Design (Phase 2) | Designing for the happy path only — ignoring WebSocket drops, tab backgrounding, mobile app suspension | For every state transition in the new architecture, ask: "What if the WebSocket disconnects HERE?" and "What if the browser tab is backgrounded HERE?" |
| Refactor (Phase 3) | Big-bang refactor that changes too many files at once — if anything breaks, rollback scope is enormous | Refactor one module boundary at a time. Each change must be independently deployable and backwards-compatible. Test with the existing encrypted data snapshot after each change. |
| Refactor (Phase 3) | Breaking the `ChatKeyManager` singleton invariant — introducing a second source of truth for keys | The `ChatKeyManager` singleton MUST remain the ONLY place keys are stored in memory. Any new module that needs a key must go through `chatKeyManager.getKey()` or `chatKeyManager.getKeySync()`. No local caching of keys in other modules. |
| Testing (Phase 4) | Testing only with fresh data — never loading chats encrypted with the pre-rebuild code | Before the rebuild starts, export 10+ encrypted chat records (with their encrypted_chat_keys and encrypted messages) as test fixtures. Run decryption tests against these fixtures after every code change. |
| Deployment (Phase 5) | Deploying encryption changes without a rollback plan — if the new code corrupts keys, there is no recovery | Keep the old encryption code paths as fallbacks for at least 2 weeks after deployment. Feature-flag the new code so it can be disabled without a code deploy. |

---

## OpenMates-Specific Historical Patterns

These are the actual failure patterns from the commit history, not theoretical risks:

| Commit | What Broke | Root Cause Category |
|--------|-----------|-------------------|
| `3d8148bc4` | Key corruption, multiple bypass paths generating wrong keys | Pitfall 1 (Key Generation Races) |
| `33e87e0be` | Secondary devices using sync `getKeySync()` returning null, falling through | Pitfall 1 + Pitfall 4 (IDB Timing) |
| `debbf2772` | Cross-device title corruption from encrypted metadata race | Pitfall 6 (Message Ordering) |
| `e418f49e6` | CLI decryption broke after fingerprint format change | Pitfall 5 (Backwards Compatibility) |
| `38e64d359` | Auth disruption wiping keys mid-encryption | Pitfall 3 (Multi-Tab Invalidation) |
| `45252837b` | Multi-tab embed encryption race producing different keys | Pitfall 10 (Embed Key Derivation) |
| `87c1757f3` | Embed keys not sent for unchanged chats in phased sync | Pitfall 2 (Key Delivery) |
| `718450001` | Sync timeout from crypto performance regression | Pitfall 12 (Performance) |

The pattern is clear: **5 out of 8 major bugs were key management races (Pitfalls 1, 2, 3)**. The rebuild must treat key lifecycle as the single highest-priority design concern.

---

## Sources

- Codebase analysis: `ChatKeyManager.ts`, `chatKeyManagement.ts`, `decryptionFailureCache.ts`, `chatSyncServiceHandlersCoreSync.ts`
- Commit history: `git log --grep="encrypt\|decrypt\|key sync" --since="2026-03-01"` (15+ relevant commits)
- Bug reports referenced in `.planning/PROJECT.md` (issues f305f5cf, a4ca102f, 7d2d2efc)
- Known concerns: `.planning/codebase/CONCERNS.md` (encryption fields not added, embed rekeying not implemented)
- Confidence: HIGH — all pitfalls are grounded in actual observed failures in this codebase, not theoretical risks

---

*Pitfalls analysis: 2026-03-26*
