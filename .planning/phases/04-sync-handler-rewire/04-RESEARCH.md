# Phase 4: Sync Handler Rewire - Research

**Researched:** 2026-03-26
**Domain:** Client-side encryption routing in sync handlers + WebSocket key delivery acknowledgment
**Confidence:** HIGH

## Summary

Phase 4 rewires all sync handler encrypt/decrypt paths to route through MessageEncryptor/MetadataEncryptor (via ChatKeyManager), adds WebSocket key delivery acknowledgment (SYNC-01), completes BroadcastChannel cross-tab propagation (SYNC-02), and splits the 2851-line chatSyncServiceSenders.ts into focused modules. Phase 3 already converted 10 decrypt paths to withKey() in the handler files -- Phase 4 completes the picture by converting the encrypt-side paths (primarily in senders and AI handlers) and adding the sender file decomposition.

The codebase is well-prepared: MessageEncryptor and MetadataEncryptor exist as stateless modules (Phase 2), ChatKeyManager has withKey() buffering and BroadcastChannel (Phase 3), and cryptoService.ts already re-exports from the encryptor modules. The main work is (1) changing ~25 inline `import("./cryptoService")` encrypt calls in sender/handler files to use the encryptors directly via ChatKeyManager, (2) implementing a new `key_received` WebSocket message type on both frontend and backend, and (3) splitting the senders file into 3-4 focused modules with a barrel re-export.

**Primary recommendation:** Convert encrypt paths file-by-file (senders first, then AI, then remaining handlers), split senders before converting its encrypt paths (cleaner diffs), and implement the WebSocket ack protocol as a separate plan to isolate backend changes.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Full round-trip WebSocket acknowledgment -- recipient sends explicit `key_received` message back through WebSocket after receiving a key. Sender waits for ack before sending encrypted content.
- D-02: Leverage existing phased sync + withKey() buffering from Phase 3 for reconnection. No new reconnection protocol needed -- verify existing path works correctly.
- D-03: Route all inline encrypt calls through MessageEncryptor/MetadataEncryptor AND split chatSyncServiceSenders.ts (2100+ lines) into focused modules.

### Claude's Discretion
- How to split chatSyncServiceSenders.ts (module boundaries, naming)
- WebSocket ack message format and protocol details
- Which encrypt paths to convert vs which are already clean
- BroadcastChannel completion for SYNC-02 (partially done in Phase 3)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SYNC-01 | WebSocket key delivery includes acknowledgment | New `key_received` message type on frontend + backend; sender-side wait-for-ack with timeout |
| SYNC-02 | Cross-tab key propagation via BroadcastChannel | BroadcastChannel already exists in ChatKeyManager; verify keyLoaded handler completes the flow for encrypt-path tabs |
| SYNC-03 | Foreground devices decrypt streaming AI correctly | AI handler encrypt paths (title/icon/category/summary/tags) routed through encryptors with withKey() |
| SYNC-04 | Background devices decrypt synced updates correctly | withKey() buffering (Phase 3) already handles this; verify encrypt side also buffers |
| SYNC-05 | Reconnection scenario works correctly | Phased sync re-runs on reconnect; withKey() queues operations until key arrives; no new protocol needed |
| ARCH-03 | All sync handlers route crypto through encryptor modules | ~25 encrypt call sites in senders + handlers must import from encryptors, not cryptoService |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **No silent failures:** All encryption errors must be visible and logged (already the pattern in existing code)
- **No magic values:** Extract raw strings/numbers to named constants (applies to new message type constants)
- **File headers:** Every new .ts file needs a 5-10 line header comment
- **DRY:** Shared logic goes to `frontend/packages/ui/src/utils/` or `frontend/packages/ui/src/services/encryption/`
- **Clean Code:** Remove unused functions/imports after refactoring
- **Two-Commit Rule:** When moving functions between modules, all call sites must update in the same commit
- **ARCH-04:** All encryption-related modules must stay under 500 lines
- **Never run pnpm build** (crashes the server)
- **Deploy via sessions.py** after every task

## Architecture Patterns

### Encrypt Path Conversion Pattern

Phase 3 established the withKey() pattern for decrypt paths. The encrypt-side equivalent uses the same approach but targets `encryptWithChatKey` / `encryptArrayWithChatKey` calls.

**Current pattern (to eliminate):**
```typescript
// Inline import from cryptoService re-exports
const { encryptWithChatKey } = await import("./cryptoService");
const encrypted = await encryptWithChatKey(plaintext, chatKey);
```

**Target pattern (route through encryptor):**
```typescript
// Direct import from MessageEncryptor
import { encryptWithChatKey } from "./encryption/MessageEncryptor";
// Key obtained via ChatKeyManager (already the case in most paths)
const encrypted = await encryptWithChatKey(plaintext, chatKey);
```

The conversion is straightforward because:
1. MessageEncryptor already exports `encryptWithChatKey` with the same signature
2. cryptoService.ts already re-exports from MessageEncryptor (so existing calls work)
3. The goal is to change the import source, not the API

For master key operations (encryptWithMasterKey, decryptWithMasterKey), import from MetadataEncryptor instead.

### Sender File Split Strategy

The 2851-line chatSyncServiceSenders.ts contains 28 exported functions. Natural module boundaries based on domain:

| Module | Functions | Lines (est.) | Domain |
|--------|-----------|-------------|--------|
| `sendersChatMessages.ts` | sendNewMessageImpl, sendEncryptedStoragePackage, sendCompletedAIResponseImpl | ~1400 | Message sending + encrypted storage (the complex crypto paths) |
| `sendersChatManagement.ts` | sendUpdateTitleImpl, sendDeleteChatImpl, sendDeleteMessageImpl, sendUpdateChatKeyImpl, sendSetActiveChatImpl | ~400 | Chat CRUD operations |
| `sendersDrafts.ts` | sendUpdateDraftImpl, sendDeleteDraftImpl, sendDeleteDraftEmbedImpl | ~150 | Draft management |
| `sendersEmbeds.ts` | sendStoreEmbedImpl, sendRequestEmbed, sendStoreEmbedKeysImpl | ~200 | Embed operations |
| `sendersSync.ts` | queueOfflineChangeImpl, sendOfflineChangesImpl, sendScrollPositionUpdateImpl, sendChatReadStatusImpl, sendPostProcessingMetadataImpl, sendLoadMoreChatsImpl, sendSyncInspirationChatImpl, sendCancelAiTaskImpl, sendCancelSkillImpl, sendCancelPdfProcessingImpl, sendAppSettingsMemoriesConfirmedImpl, sendStoreAppSettingsMemoriesEntryImpl, sendDeleteNewChatSuggestionImpl, sendDeleteNewChatSuggestionByIdImpl | ~600 | Sync utilities + misc senders |
| `chatSyncServiceSenders.ts` (barrel) | Re-exports all | ~30 | Backwards compatibility barrel |

**Key insight:** The barrel re-export pattern (from Phase 2's cryptoService.ts split) ensures zero breaking changes at call sites. All existing `import { sendXyz } from "./chatSyncServiceSenders"` continue working.

### WebSocket Key Delivery Ack Protocol

**New message types:**

Frontend-to-server: `key_received`
```typescript
{
  type: "key_received",
  payload: {
    chat_id: string,
    device_hash: string  // identifies which device acknowledged
  }
}
```

Server-to-sender: `key_delivery_confirmed`
```typescript
{
  type: "key_delivery_confirmed",
  payload: {
    chat_id: string,
    device_hash: string,  // which device confirmed
    all_devices_confirmed: boolean  // true when all connected devices have ack'd
  }
}
```

**Flow:**
1. Device A sends encrypted_chat_metadata with encrypted_chat_key
2. Server stores key, broadcasts to Device B, C, etc.
3. Each receiving device processes key via `receiveKeyFromServer()`, then sends `key_received`
4. Server receives `key_received`, tracks per-device ack state
5. Server sends `key_delivery_confirmed` back to Device A
6. Device A's sender can optionally wait for ack with a timeout (non-blocking, since withKey buffering handles the gap)

**Implementation location:**
- Frontend: New handler registration in chatSyncService.ts websocket message routing
- Backend: New handler file `key_received_handler.py` in websocket_handlers/
- Backend: ConnectionManager tracks ack state per chat_id per user

**Timeout strategy:** Sender waits up to 5 seconds for ack. If timeout, log warning but proceed (the key is already stored server-side and will be available on reconnect). This makes the ack protocol additive/observational rather than blocking.

### BroadcastChannel Completion (SYNC-02)

Phase 3 implemented the core BroadcastChannel mechanism:
- `keyLoaded` message broadcasts when a key is loaded in any tab
- `clearAll` propagates key cache clearing across tabs
- `handleCrossTabMessage` processes incoming messages

What remains for SYNC-02 completion:
1. Verify that `keyLoaded` handler properly unwraps the encrypted key and injects it (already implemented in Phase 3's Plan 02)
2. Verify that encrypt-path tabs (not just decrypt-path tabs) benefit from the cross-tab key propagation
3. Add test coverage for the cross-tab scenario

Based on code review, the BroadcastChannel implementation appears complete from Phase 3. The `keyLoaded` handler at line 244 of ChatKeyManager.ts receives the encrypted key, calls `receiveKeyFromServer()` which handles decryption and injection. This covers both encrypt and decrypt paths since both use `getKey()` / `getKeySync()` / `withKey()`.

**Recommendation:** SYNC-02 requires verification, not new implementation. Add an integration test that simulates the BroadcastChannel flow.

## Encrypt Call Site Inventory (What to Convert)

### chatSyncServiceSenders.ts (primary target -- 15 encrypt calls)

| Line | Function | Current Import | Target Import |
|------|----------|---------------|---------------|
| 50-53 | sendUpdateTitleImpl | `import("./cryptoService").encryptWithChatKey` | MessageEncryptor.encryptWithChatKey |
| 1039-1040 | sendNewMessageImpl | `import("./cryptoService").decryptWithChatKey` | MessageEncryptor.decryptWithChatKey |
| 1124-1134 | sendNewMessageImpl (embeds) | `import("./cryptoService").*` | MetadataEncryptor embed functions |
| 1999-2000 | sendEncryptedStoragePackage | `import("./cryptoService").decryptChatKeyWithMasterKey` | MetadataEncryptor.decryptChatKeyWithMasterKey |
| 2066-2067 | sendEncryptedStoragePackage | `import("./cryptoService").decryptChatKeyWithMasterKey` | MetadataEncryptor.decryptChatKeyWithMasterKey |
| 2104-2105 | sendEncryptedStoragePackage | `import("./cryptoService").encryptChatKeyWithMasterKey` | MetadataEncryptor.encryptChatKeyWithMasterKey |
| 2132-2222 | sendEncryptedStoragePackage | `import("./cryptoService").encryptWithChatKey` (x9) | MessageEncryptor.encryptWithChatKey |
| 2140-2142 | sendEncryptedStoragePackage | `import("./cryptoService").decryptWithChatKey` | MessageEncryptor.decryptWithChatKey |

### chatSyncServiceHandlersAI.ts (11 encrypt calls, partially converted in Phase 3)

| Line | Function | Type |
|------|----------|------|
| 1125-1202 | AI metadata encrypt (title/icon/category) | encryptWithChatKey (x5) |
| 1268 | Key wrapping for AI metadata send | encryptChatKeyWithMasterKey |
| 1847-1922 | Post-processing metadata | encryptWithChatKey, encryptArrayWithChatKey, encryptWithMasterKey |
| 2112 | App-specific data | encryptWithMasterKey |
| 2410-2503 | Embed encryption | encryptWithEmbedKey (multiple) |
| 2955-3503 | Embed key derivation + encryption | deriveEmbedKeyFromChatKey, encryptWithEmbedKey |

### chatSyncServiceHandlersChatUpdates.ts (5 encrypt calls)

| Line | Function | Type |
|------|----------|------|
| 1382-1397 | Broadcast self-heal re-encrypt | encryptWithChatKey (x3) |
| 1748-1749 | Key wrapping for server send | encryptChatKeyWithMasterKey |

### chatSyncServiceHandlersAppSettings.ts (4 encrypt calls)

| Line | Function | Type |
|------|----------|------|
| 1067-1093 | App settings response encrypt | encryptWithChatKey (x1) |
| 1219-1252 | App settings response encrypt (2nd handler) | encryptWithChatKey (x1) |
| 2219-2283 | System chat title + content encrypt | encryptWithChatKey (x2) |

### Already clean (no conversion needed)

- `chatSyncServiceHandlersCoreSync.ts` -- decrypt only, already converted in Phase 3
- `chatSyncServiceHandlersPhasedSync.ts` -- decrypt only, already converted in Phase 3
- `chatMetadataCache.ts` -- decrypt only, already converted in Phase 3

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Key delivery guarantee | Custom retry/polling protocol | WebSocket ack + existing withKey() buffering | withKey() already handles the gap between key arrival and crypto operation |
| Cross-tab key sync | Custom SharedWorker or localStorage polling | BroadcastChannel (already implemented) | BroadcastChannel is the standard API, already working in ChatKeyManager |
| File splitting barrel exports | Manual import path updates at every call site | Re-export barrel in chatSyncServiceSenders.ts | Phase 2 proved this pattern -- zero breaking changes |
| Reconnection protocol | New state machine for reconnection | Existing phased sync (already re-runs on reconnect) | Decision D-02 explicitly chose this approach |

## Common Pitfalls

### Pitfall 1: Splitting a File and Breaking Dynamic Imports
**What goes wrong:** chatSyncServiceSenders.ts is imported dynamically in several places via `await import("./chatSyncServiceSenders")`. After splitting into sub-modules, these dynamic imports would need to change.
**Why it happens:** The file is both imported statically (by chatSyncService.ts) and dynamically (by other modules for code-splitting).
**How to avoid:** Keep chatSyncServiceSenders.ts as a barrel that re-exports from the sub-modules. Dynamic imports continue to work unchanged. The barrel file should be ~30 lines of re-exports.
**Warning signs:** Runtime errors like "sendNewMessageImpl is not a function" after the split.

### Pitfall 2: Ack Protocol Blocking the Send Path
**What goes wrong:** If the `key_received` ack is implemented as a blocking wait before sending encrypted content, a disconnected secondary device (or one that never acks) blocks the sender indefinitely.
**Why it happens:** Over-engineering the ack protocol to be synchronous.
**How to avoid:** Make the ack non-blocking with a timeout. The sender proceeds after 5 seconds regardless. The ack is for observability and confidence, not for gating the send. withKey() on the receiving side handles the key-not-yet-available case.
**Warning signs:** Messages appearing to "hang" when only one device is online.

### Pitfall 3: Import Cycle Between New Sender Modules
**What goes wrong:** After splitting senders, sendersChatMessages.ts imports from sendersEmbeds.ts which imports from sendersChatMessages.ts -- circular dependency causes undefined exports at runtime.
**Why it happens:** Shared helper functions or types are referenced across the new modules.
**How to avoid:** Extract shared types/helpers to a separate `sendersTypes.ts` or `sendersUtils.ts` module that both can import. Keep the dependency graph acyclic.
**Warning signs:** `undefined` function errors at runtime, only in certain import orders.

### Pitfall 4: Losing Critical-Op Lock Coverage During Refactor
**What goes wrong:** sendEncryptedStoragePackage uses `chatKeyManager.acquireCriticalOp()` to prevent key cache wipes during encryption. After moving the function to a sub-module, the lock acquisition is accidentally removed or the `finally` block releasing it is lost.
**Why it happens:** Copy-paste errors during file moves, or "cleanup" that removes seemingly redundant code.
**How to avoid:** The critical-op lock is a mandatory part of sendEncryptedStoragePackage. Search for `acquireCriticalOp` and `releaseCriticalOp` after every refactor step. Both must exist in the same function.
**Warning signs:** Intermittent "content decryption failed" errors during auth re-verification events.

### Pitfall 5: Backend Handler Missing for key_received
**What goes wrong:** Frontend sends `key_received` but backend has no handler registered for that message type. The message is silently dropped.
**Why it happens:** The WebSocket message router in websockets.py uses a large if/elif chain. Forgetting to add the new message type means no error, just silent no-op.
**How to avoid:** Add the handler to the message routing in websockets.py AND create the handler file in websocket_handlers/. Test with a log statement to confirm the handler fires.
**Warning signs:** No server-side log when key_received is sent from client.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | vitest 3.2.4 |
| Config file | frontend/packages/ui/vitest.config.ts |
| Quick run command | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ --reporter=verbose` |
| Full suite command | `cd frontend/packages/ui && npx vitest run --reporter=verbose` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SYNC-01 | Key delivery ack sent after receiveKeyFromServer | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ChatKeyManager.test.ts -t "key_received" -x` | Wave 0 |
| SYNC-02 | BroadcastChannel propagates key to other tabs | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ChatKeyManager.test.ts -t "BroadcastChannel" -x` | Partial (Phase 3 added some) |
| SYNC-03 | AI streaming decrypt works with encryptor routing | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ChatKeyManager.test.ts -t "streaming" -x` | Wave 0 |
| SYNC-04 | Background device decrypt via withKey buffering | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ChatKeyManager.test.ts -t "withKey" -x` | Exists (Phase 3) |
| SYNC-05 | Reconnection triggers phased sync | manual-only | Manual verification via dev tools | N/A |
| ARCH-03 | No direct cryptoService encrypt imports in sync handlers | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/import-audit.test.ts -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ --reporter=verbose`
- **Per wave merge:** `cd frontend/packages/ui && npx vitest run --reporter=verbose`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `src/services/encryption/__tests__/import-audit.test.ts` -- static import audit verifying no `import("./cryptoService")` in sync handler files (covers ARCH-03)
- [ ] Key delivery ack test cases in ChatKeyManager.test.ts (covers SYNC-01)
- [ ] BroadcastChannel encrypt-path verification (covers SYNC-02, extends existing tests)

## Code Examples

### Verified encrypt path conversion (from existing codebase pattern)

**Before (chatSyncServiceSenders.ts line 50):**
```typescript
const { encryptWithChatKey } = await import("./cryptoService");
const encryptedTitle = await encryptWithChatKey(new_title, chatKey);
```

**After (direct import from encryptor):**
```typescript
import { encryptWithChatKey } from "./encryption/MessageEncryptor";
// chatKey already obtained from ChatKeyManager above
const encryptedTitle = await encryptWithChatKey(new_title, chatKey);
```

### Barrel re-export pattern (from Phase 2's cryptoService.ts, line 853-867)

```typescript
// chatSyncServiceSenders.ts (becomes barrel after split)
export { sendNewMessageImpl } from "./sendersChatMessages";
export { sendUpdateTitleImpl, sendDeleteChatImpl } from "./sendersChatManagement";
export { sendUpdateDraftImpl, sendDeleteDraftImpl } from "./sendersDrafts";
// ... etc
```

### WebSocket ack handler registration (backend pattern from websockets.py)

```python
# In websockets.py message routing (elif chain around line 2269)
elif message_type == "key_received":
    await handle_key_received(
        websocket, manager, cache_service,
        user_id, user_id_hash, device_fingerprint_hash,
        payload
    )
```

### Backend key_received handler skeleton

```python
async def handle_key_received(
    websocket, manager, cache_service,
    user_id, user_id_hash, device_fingerprint_hash, payload
):
    chat_id = payload.get("chat_id")
    logger.info(f"Key received ack from device {device_fingerprint_hash} for chat {chat_id}")

    # Notify the originating device that this device has the key
    await manager.broadcast_to_user(
        {"type": "key_delivery_confirmed", "payload": {
            "chat_id": chat_id,
            "device_hash": device_fingerprint_hash,
        }},
        user_id,
        exclude_device_hash=device_fingerprint_hash  # Don't echo back to acker
    )
```

## Open Questions

1. **Embed key operations -- which encryptor module?**
   - What we know: `deriveEmbedKeyFromChatKey`, `encryptWithEmbedKey`, `wrapEmbedKeyWithMasterKey` are in cryptoService.ts. MetadataEncryptor already handles some embed operations.
   - What's unclear: Whether embed key derivation/encryption should route through MetadataEncryptor or remain in cryptoService.ts.
   - Recommendation: Leave embed key operations in cryptoService.ts for now since they are not part of the "sync handler encrypt path" scope (they are already well-encapsulated). Focus ARCH-03 on the `encryptWithChatKey` / `encryptWithMasterKey` paths that are scattered inline.

2. **sendEncryptedStoragePackage key management complexity**
   - What we know: This function (lines 1914-2347) contains extensive key acquisition logic: getKey, decrypt from IDB, hidden chat fallback, createAndPersistKey, re-read guard. This is 400+ lines of key management interleaved with encryption.
   - What's unclear: Whether to refactor the key acquisition into ChatKeyManager or keep it inline.
   - Recommendation: Keep the key acquisition logic co-located with sendEncryptedStoragePackage for now. It is context-specific (new chat detection, hidden chat fallback, critical-op lock) and moving it would create a leaky abstraction. The file split already reduces cognitive load.

3. **chatSyncServiceHandlersAppSettings.ts encrypt paths**
   - What we know: 4 encrypt calls exist in app settings handlers (system chat creation, response encryption).
   - What's unclear: Whether these are high-priority for ARCH-03 or can be deferred.
   - Recommendation: Include them. They are straightforward single-line conversions and completing them achieves the "zero direct crypto calls" goal.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis of all files listed in CONTEXT.md canonical references
- `docs/architecture/core/encryption-code-inventory.md` -- complete call site inventory with line numbers
- `.planning/phases/03-key-management-hardening/03-03-SUMMARY.md` -- Phase 3 conversion record
- `.planning/research/ARCHITECTURE.md` -- target architecture patterns
- `.planning/research/PITFALLS.md` -- known domain pitfalls

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` -- requirement definitions for SYNC-01 through SYNC-05, ARCH-03
- `.planning/ROADMAP.md` -- phase boundaries and success criteria

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries needed, all work uses existing modules
- Architecture: HIGH -- patterns proven in Phase 2 (extract-and-redirect) and Phase 3 (withKey conversion)
- Pitfalls: HIGH -- based on actual codebase failure patterns documented in research/PITFALLS.md
- WebSocket ack protocol: MEDIUM -- new protocol, but simple message routing following established backend patterns

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable -- no external dependency changes expected)
