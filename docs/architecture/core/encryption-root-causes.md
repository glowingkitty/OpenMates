# Encryption Decryption Failure Root Causes

> Analysis of 3 recent "Content decryption failed" bug reports from the same admin user
> testing across Mac and iPhone/iPad. All occurred within a 2-day window (March 24-25, 2026).
> Each report was traced to a different architectural weakness in the encryption key
> management and sync pipeline. The fixes span 4 commits, addressing key generation races,
> cross-device metadata corruption, sync-vs-render timing, and backwards compatibility.
>
> See: [Encryption Architecture](./encryption-architecture.md) for the post-rebuild overview.
>
> Related: [Chat Encryption Implementation](./chat-encryption-implementation.md) |
> [Zero-Knowledge Storage](./zero-knowledge-storage.md)

## Resolution Status (Post-Rebuild)

All three root causes identified in the audit have been resolved through the Phase 1-4 rebuild:

| Root Cause | Bug Report | Resolved In | Resolution |
|------------|-----------|-------------|------------|
| Bypass paths around ChatKeyManager + non-atomic key lifecycle | f305f5cf | Phase 2-3 | All bypass paths eliminated. `ChatKeyManager` is sole key authority with `createKeyForNewChat()` / `createAndPersistKey()` atomic API. Key fingerprint in ciphertext (OM header) enables fast wrong-key detection. |
| Cross-device metadata corruption from stale cached JS | a4ca102f | Phase 3-4 | Server-side guard blocks metadata alongside key overwrites. Client-side self-heal validates incoming metadata before accepting. Service worker `SKIP_WAITING` prevents stale-code scenarios. |
| Async key loading race (`getKeySync` before key ready) | 7d2d2efc | Phase 3 | `ChatKeyManager.withKey()` buffers operations until key is available. Web Locks mutex (`om-chatkey-{chatId}`) prevents duplicate key generation across tabs. Systematic `getKeySync` audit completed -- all critical paths converted to async `getKey()`. |

### Remaining Risk Areas Status

| Risk Area | Status |
|-----------|--------|
| `getKeySync()` usage audit | **Resolved.** Phase 3 classified all sites as (a) converted to async or (b) acceptable (sidebar render paths with async fallback). |
| Multi-tab coordination | **Resolved.** Phase 3 added Web Locks + BroadcastChannel propagation with pending-ops guard. |
| Phased sync ordering | **Mitigated.** Phase 4 converted all sync handler crypto imports to static encryptor imports. `withKey()` buffering ensures key-before-content. |
| Master key unavailability | **Unchanged.** Recovery requires re-login. This is by design (not a bug). |
| Format migration gap | **Accepted.** Dual-format reading works indefinitely. No migration path needed -- new writes use Format A, old reads auto-detect Format B. |

## Bug Report: f305f5cf

### Symptom

Chat encryption repeatedly breaks -- user messages fail to decrypt on secondary devices
(iPhone/iPad). Partial metadata decryption failures. Wrong keys stored on server. The admin
user reported "Content decryption failed" placeholders appearing on messages that were
readable on the originating Mac. 15+ crypto commits in 3 weeks had each patched a different
symptom, but the failures kept recurring from different code paths.

### Root Cause

Five architectural weaknesses combined to produce recurring key corruption:

1. **4 bypass paths around ChatKeyManager**: `chatCrudOperations.ts`, `forkChatService.ts`,
   `onboardingChatService.ts`, and `chatSyncServiceHandlersAppSettings.ts` all called
   `generateChatKey()` directly, bypassing the provenance tracking and immutability guard
   in `ChatKeyManager`. This meant keys were being generated without the state machine
   knowing about them.

2. **Non-atomic key lifecycle**: Key creation (`_generateChatKeyInternal()`) and key
   persistence (`encryptChatKeyWithMasterKey()` + IDB write) were separate async operations.
   If the browser tab was interrupted between them, key K1 existed in memory but K2 (a
   different key) ended up on the server.

3. **No wrong-key detection**: AES-GCM decryption with the wrong key produces a generic
   `OperationError`. There was no fast-fail mechanism to detect "wrong key" before
   attempting the full AES-GCM decryption, making debugging nearly impossible.

4. **Silent sync overwrite**: Phased sync silently overwrote the local key with the server
   key without detecting or handling conflicts between them.

5. **Silent server key ignore**: `receiveKeyFromServer()` silently ignored the server key
   if a local key already existed, even when the two keys differed -- hiding key conflicts
   instead of surfacing them.

### Fix Commit

`3d8148bc4` -- "permanent encryption key sync architecture"

**Changes across 4 phases:**
- Phase 1: Renamed `generateChatKey()` to `_generateChatKeyInternal()`, deprecated the
  direct export. All 4 bypass callers now use `chatKeyManager` exclusively.
- Phase 2: New `createAndPersistKey()` on ChatKeyManager -- atomically creates key,
  encrypts with master key, and persists to IDB before returning.
- Phase 3: New ciphertext format `[0x4F 0x4D][4-byte fingerprint][IV][ciphertext]` embeds
  key fingerprint in every encrypted field. `decryptWithChatKey` validates fingerprint
  before AES-GCM, fast-failing with "key fingerprint mismatch" on wrong key.
- Phase 4: `mergeServerChatWithLocal` made async, loads server key into ChatKeyManager on
  conflict. `receiveKeyFromServer` detects key conflicts and logs explicit warnings.

### Pitfall Category

- **Pitfall 1** (Key Generation Races) -- primary cause
- **Pitfall 4** (IndexedDB Transaction Timing) -- contributing factor for non-atomic lifecycle

### Completeness Assessment

**Mostly complete.** The bypass elimination and atomic key lifecycle address the root causes.
The key fingerprint in ciphertext provides detection for future mismatches. However:

- The `onboardingChatService.ts` still imports `encryptWithChatKey` directly from
  `cryptoService.ts` (not through ChatKeyManager). This is architecturally acceptable since
  it obtains the key from `chatKeyManager.createAndPersistKey()` first, but the pattern of
  direct crypto imports means future developers could accidentally use a stale key reference.
- The ciphertext format change introduced a backwards compatibility surface (addressed by
  bug report below at `e418f49e6`).

---

## Bug Report: a4ca102f

### Symptom

Cross-device title corruption. Chat titles, icons, and categories showed garbled/corrupted
content on the secondary device (iPad). The `encrypted_chat_key` itself was correct on the
server (the immutability guard protected it), but the encrypted metadata fields
(`encrypted_title`, `encrypted_icon`, `encrypted_category`) were encrypted with the wrong
key.

### Root Cause

iPadOS Safari cached old JavaScript (pre-March 9 fix `3846d7e27`) that still used the old
code path generating new random keys on secondary devices instead of waiting for the
originator's key. When this stale code ran:

1. The secondary device generated key K2 (wrong key).
2. The server's key immutability guard correctly blocked K2 from overwriting K1 in
   `encrypted_chat_key`.
3. However, the `encrypted_title`, `encrypted_icon`, and `encrypted_category` fields had
   **no such guard**. They were encrypted with K2 and the server accepted them.
4. Now the metadata was encrypted with K2 while the chat key was K1. Every device that
   loaded K1 (the correct key) could not decrypt the title/icon/category.

### Fix Commit

`debbf2772` -- "prevent cross-device title corruption and add self-heal for encrypted metadata"

**Changes (3 files, +205/-21 lines):**
- **Server-side** (`persistence_tasks.py`): When the key immutability guard blocks an
  incoming key, also block `encrypted_title`/`encrypted_icon`/`encrypted_category` from
  that same request -- they were encrypted with the rejected wrong key.
- **Client-side broadcast handler** (`chatSyncServiceHandlersChatUpdates.ts`): Validate
  incoming encrypted metadata by attempting decryption before accepting. If incoming fails
  but local decrypts fine, reject incoming and re-send local version (self-heal).
- **Client-side phased sync** (`chatSyncServiceHandlersPhasedSync.ts`): After merging
  server + local chat data, validate encrypted metadata fields decrypt correctly. If
  server's version is corrupted but local is valid, preserve local.

### Pitfall Category

- **Pitfall 5** (Backwards Compatibility) -- stale cached code running old format
- **Pitfall 8** (Service Worker Cache) -- iPadOS Safari serving old JS
- **Pitfall 1** (Key Generation Races) -- the stale code generated wrong keys

### Completeness Assessment

**Complete for the specific vector.** The server-side guard now blocks metadata alongside
key overwrites, and the client-side self-heal mechanism can recover from existing corrupted
metadata. The service worker `SKIP_WAITING` fix (`1df0863d0`) prevents future stale-code
scenarios. Remaining risk: if a new stale-code vector emerges from a different cache
mechanism (e.g., CDN edge cache), the server guard will catch it.

---

## Bug Report: 7d2d2efc

### Symptom

Chat user messages show "[Content decryption failed]" placeholder on iPad/iPhone when
opening a chat created on Mac. Server data is healthy (debug tool confirms OK), client
health check also passes -- but the rendered HTML has the failure placeholder. Issue
persists even after fresh login.

### Root Cause

`decryptMessageFields()` at line 642 of `chatKeyManagement.ts` used
`chatKeyManager.getKeySync(chatId)` -- a synchronous, memory-only lookup. On secondary
devices, the chat key had not finished async loading (decrypting `encrypted_chat_key` with
the master key) when messages were first rendered.

The sequence:
1. Device B connects, receives phased sync with encrypted messages + `encrypted_chat_key`.
2. `decryptMessageFields()` is called to render messages.
3. It calls `getKeySync(chatId)` which checks only the in-memory Map.
4. The key is still being async-decrypted from `encrypted_chat_key` via master key.
5. `getKeySync` returns `null` -> message shows "[Content decryption failed]" placeholder.
6. UI never re-renders when the key arrives later (no reactive binding to key state).

Commit `ba738052` ("migrate all chatDB.getChatKey calls to async chatKeyManager.getKey")
intended to fix this class of race but **missed `decryptMessageFields`** -- the most
critical call site.

### Fix Commit

`33e87e0be` -- "use async key lookup in decryptMessageFields to prevent race on secondary devices"

**Change (1 file, +8/-2 lines):**
- Changed `getKeySync(chatId)` to `await getKey(chatId)` in `decryptMessageFields()`.
- The function was already `async`, so this change was safe. `getKey()` has a fast
  in-memory path (returns immediately if key is cached) and an async IDB fallback (loads +
  decrypts `encrypted_chat_key` if not in memory). Zero-cost on originating device.

### Pitfall Category

- **Pitfall 1** (Key Generation Races) -- specifically, the sync-vs-render race variant
- **Pitfall 4** (IndexedDB Transaction Timing) -- async key loading not completing before render

### Completeness Assessment

**Complete for `decryptMessageFields`.** However, a systematic audit should verify that no
other call sites use `getKeySync()` in contexts where the key might still be loading. The
`getKeySync` method remains available for performance-critical paths where the key is
guaranteed to already be loaded (e.g., mid-encryption where the key was just obtained).

---

## Additional Fix: CLI Backwards Compatibility

### Fix Commit

`e418f49e6` -- "CLI decryption of chat metadata after fingerprint format change"

**Related to bug f305f5cf fix.** The ciphertext format change introduced in `3d8148bc4`
(adding `[OM magic 2B][key fingerprint 4B]` prefix) broke the CLI's decryption of chat
metadata. The CLI's `decryptWithAesGcmCombined()` only handled the legacy
`[IV 12B][ciphertext]` format, treating the 6-byte header as part of the IV.

**Fix:** Detect "OM" magic bytes (`0x4F`, `0x4D`) at the start of ciphertext and skip the
6-byte header before extracting IV and ciphertext.

**Pitfall Category:** Pitfall 5 (Backwards Compatibility)

---

## Common Patterns

All 3 bug reports share these common patterns:

1. **Cross-device is where bugs manifest.** All failures occurred on secondary devices
   (iPad/iPhone) while the originating device (Mac) worked correctly. The originating device
   always has the key in memory; secondary devices must load it asynchronously.

2. **Async timing is the root cause.** Every bug was fundamentally about code executing
   before an async operation (key loading, key decryption, IDB persistence) had completed.
   Synchronous assumptions in an async system.

3. **Single-symptom fixes missed sibling code paths.** Commit `ba738052` fixed all
   `chatDB.getChatKey` calls but missed `decryptMessageFields`. Commit `3d8148bc4` fixed
   bypass paths but the ciphertext format change broke CLI. Each fix addressed one
   manifestation while the architectural pattern produced more.

4. **Server-side guards are incomplete without metadata protection.** The key immutability
   guard protected `encrypted_chat_key` but not the metadata encrypted with it. This gap
   allowed metadata corruption even when the key itself was safe.

## Remaining Risk Areas

1. **`getKeySync()` usage audit**: Any remaining `getKeySync()` call in a context where the
   key might still be loading is a latent bug. Needs systematic grep and classification.

2. **Multi-tab coordination**: The `criticalOpCount` lock protects within a single tab.
   Cross-tab key invalidation during auth events (Pitfall 3) has not been fully tested.

3. **Phased sync ordering**: Phase 2/3 data arriving while Phase 1 is still decrypting
   (Pitfall 7) is architecturally unaddressed. The current code relies on JavaScript's
   single-threaded execution model, which does not protect against IDB transaction interleaving.

4. **Master key unavailability**: If `getKeyFromStorage()` returns null during a decrypt
   operation (e.g., after IndexedDB corruption or auth state loss), all chat keys become
   inaccessible. There is no recovery mechanism beyond re-login.

5. **Format migration gap**: The dual-format ciphertext handling (legacy `[IV][ciphertext]`
   vs new `[OM][fingerprint][IV][ciphertext]`) works for reading, but there is no migration
   path to update old ciphertext to the new format. Over time, this creates a maintenance
   burden.

---

*Root cause analysis: 2026-03-26*
*Bug reports: f305f5cf, a4ca102f, 7d2d2efc*
*Fix commits: 3d8148bc4, 33e87e0be, debbf2772, e418f49e6*

*Last updated: 2026-03-26 (post-Phase-4 rebuild)*
