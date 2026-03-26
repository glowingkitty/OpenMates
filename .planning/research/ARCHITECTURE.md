# Architecture Patterns: Client-Side Encryption & Real-Time Sync

**Domain:** End-to-end encrypted chat with cross-device WebSocket sync
**Researched:** 2026-03-26
**Confidence:** HIGH (based on existing codebase analysis + established E2E encryption patterns)

## Current Architecture (As-Is)

The system already has a working E2E encryption and sync architecture. The rebuild is about fixing structural problems that cause recurring decryption failures -- not introducing new concepts. Understanding the current architecture is the foundation.

### Key Hierarchy

```
Master Key (AES-256-GCM, Web Crypto API)
  |-- stored in IndexedDB (openmates_crypto) or memory-only (stayLoggedIn=false)
  |-- one per user per device
  |-- used to wrap/unwrap chat keys
  |
  +-- Chat Key (AES-256-GCM, raw Uint8Array via tweetnacl)
       |-- one per chat
       |-- wrapped (encrypted) form stored in IndexedDB per-chat and synced to server
       |-- raw form held in ChatKeyManager in-memory cache
       |-- encrypts: message content, title, category, icon, tags, draft, sender name, embeds
```

### Current Component Map

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `cryptoKeyStorage.ts` | `services/` | Master key persistence (IndexedDB/memory) |
| `cryptoService.ts` | `services/` | AES-GCM encrypt/decrypt, key wrapping, PBKDF2, base64 helpers |
| `ChatKeyManager.ts` | `services/encryption/` | Chat key state machine, queue-and-flush, provenance tracking |
| `chatKeyManagement.ts` | `services/db/` | IDB chat key CRUD, bulk loading, version map caching |
| `chatSyncService.ts` | `services/` | WebSocket message orchestration, connection lifecycle |
| `chatSyncServiceHandlersCoreSync.ts` | `services/` | Initial sync, Phase 1 (last chat), cache priming, offline sync |
| `chatSyncServiceHandlersPhasedSync.ts` | `services/` | Phase 2 (recent chats) and Phase 3 (full sync), metadata healing |
| `chatSyncServiceHandlersAI.ts` | `services/` | AI streaming token handling, post-processing metadata |
| `chatSyncServiceSenders.ts` | `services/` | Outbound WebSocket message construction and sending |
| `websocketService.ts` | `services/` | Raw WebSocket connection, reconnection, auth, message routing |
| `ConnectionManager` (backend) | `routes/connection_manager.py` | Multi-device WebSocket routing, broadcast, grace periods |
| `EncryptionService` (backend) | `utils/encryption.py` | Vault transit encryption for server-side data (NOT chat content) |

---

## Recommended Architecture (Target)

The target is NOT a rewrite of the component set -- it is a clarification of boundaries, elimination of scattered crypto calls, and hardening of the key lifecycle. The same components exist, but with cleaner separation.

### Component Boundaries

| Component | Responsibility | Communicates With | Does NOT Do |
|-----------|---------------|-------------------|-------------|
| **MasterKeyService** (`cryptoKeyStorage.ts` + master key parts of `cryptoService.ts`) | Generate, persist, retrieve, and clear the master CryptoKey. Request persistent storage. Hybrid memory/IDB strategy. | ChatKeyManager (provides unwrap capability) | Encrypt chat content, manage chat keys, touch WebSocket |
| **CryptoOperations** (pure functions from `cryptoService.ts`) | Stateless AES-GCM encrypt/decrypt, base64 encode/decode, key wrapping/unwrapping. No state, no side effects. | Called by ChatKeyManager, MessageEncryptor, MetadataEncryptor | Hold keys in memory, manage state, interact with IDB |
| **ChatKeyManager** (`encryption/ChatKeyManager.ts`) | Chat key state machine: unloaded/loading/ready/failed. Key provenance. Queue-and-flush for deferred operations. Cross-tab coordination. Critical-op lock. | MasterKeyService (for unwrapping), IDB (for encrypted key fetch/persist), SyncEngine (receives keys from server) | Encrypt/decrypt message content, decide when to create keys, interact with WebSocket directly |
| **MessageEncryptor** (new -- extract from scattered inline calls) | Encrypt/decrypt individual message fields (content, sender_name). Takes key as parameter. Stateless. | CryptoOperations (for raw encrypt/decrypt) | Manage keys, interact with IDB, know about sync |
| **MetadataEncryptor** (new -- extract from scattered inline calls) | Encrypt/decrypt chat-level metadata (title, icon, category, tags, draft). Takes key as parameter. Stateless. | CryptoOperations (for raw encrypt/decrypt) | Manage keys, interact with IDB, know about sync |
| **SyncEngine** (`chatSyncService.ts` + handler modules) | Orchestrate the 3-phase sync protocol, route WebSocket messages to handlers, manage sync state. | ChatKeyManager (get/receive keys), MessageEncryptor/MetadataEncryptor (encrypt/decrypt during sync), WebSocketTransport (send/receive) | Perform raw crypto, manage keys, hold crypto state |
| **WebSocketTransport** (`websocketService.ts`) | Raw WebSocket connection lifecycle, auth, reconnection, message framing, handler dispatch. | SyncEngine (dispatches incoming messages to), ConnectionManager on backend | Encryption, key management, sync state, IDB |
| **ConnectionManager** (backend) | Route messages to correct devices. Broadcast to all user devices. Track active chat per connection. Grace period for reconnects. | WebSocket handlers (delegates to per-message-type handlers) | Encryption (server never sees plaintext chat content) |
| **DecryptionFailureCache** (`db/decryptionFailureCache.ts`) | Track known decryption failures to avoid repeated error logs. Auto-cleared when keys change. | ChatKeyManager (cleared on key change) | Fix failures, manage keys |

### Module Structure (Suggested File Tree)

```
frontend/packages/ui/src/services/
  encryption/
    ChatKeyManager.ts          # Key state machine (existing, keep)
    MasterKeyService.ts        # Extract from cryptoKeyStorage.ts + cryptoService.ts master key parts
    CryptoOperations.ts        # Extract pure functions from cryptoService.ts
    MessageEncryptor.ts        # NEW: stateless message field encrypt/decrypt
    MetadataEncryptor.ts       # NEW: stateless metadata field encrypt/decrypt
    DecryptionFailureCache.ts  # Move from db/decryptionFailureCache.ts
    __tests__/                 # Existing + new tests
  sync/
    SyncEngine.ts              # Refactored chatSyncService.ts (thinner orchestrator)
    handlers/
      CoreSyncHandler.ts       # From chatSyncServiceHandlersCoreSync.ts
      PhasedSyncHandler.ts     # From chatSyncServiceHandlersPhasedSync.ts
      AIStreamHandler.ts       # From chatSyncServiceHandlersAI.ts
      ChatUpdateHandler.ts     # From chatSyncServiceHandlersChatUpdates.ts
      AppSettingsHandler.ts    # From chatSyncServiceHandlersAppSettings.ts
    SyncSenders.ts             # From chatSyncServiceSenders.ts
  WebSocketTransport.ts        # Renamed from websocketService.ts (no logic change)
  db/
    chatKeyManagement.ts       # Existing (IDB key CRUD, version map)
    ...
```

---

## Data Flow

### Flow 1: New Message (Originating Device)

```
User types message
  |
  v
SyncEngine.sendMessage(chatId, plaintext)
  |
  v
ChatKeyManager.getKeySync(chatId)  -- key MUST already be ready (chat exists)
  |   |
  |   +-- null? ABORT. Log error. Never create a key here.
  |
  v
MessageEncryptor.encryptContent(plaintext, chatKey)  -- stateless, returns ciphertext
  |
  v
MetadataEncryptor.encryptTitle(title, chatKey)  -- if title changed
MetadataEncryptor.encryptCategory(category, chatKey)  -- if category assigned
  |
  v
SyncSenders.sendEncryptedChatMetadata({
  chat_id, message_id,
  encrypted_content, encrypted_title, encrypted_category,
  encrypted_chat_key,  -- wrapped form for server storage
  versions: { messages_v, last_edited_overall_timestamp }
})
  |
  v
WebSocketTransport.send(payload)  -- raw WebSocket send
  |
  v  [Server]
ConnectionManager receives -> routes to encrypted_chat_metadata_handler
  |
  v
Handler persists to Directus (encrypted fields stored as-is)
Handler broadcasts to other devices via broadcast_to_user(exclude_device_hash=sender)
```

### Flow 2: New Chat Creation (Key Genesis)

```
User initiates new chat
  |
  v
ChatKeyManager.createAndPersistKey(chatId)
  |-- generates random AES key via tweetnacl
  |-- wraps with master key -> encrypted_chat_key
  |-- persists encrypted_chat_key to IndexedDB
  |-- sets state = 'ready', provenance = 'created'
  |
  v
Returns { chatKey, encryptedChatKey }
  |
  v
SyncEngine includes encrypted_chat_key in first message payload to server
  |
  v  [Server]
Server stores encrypted_chat_key in Directus chat record
Server broadcasts chat creation to other devices (includes encrypted_chat_key)
```

### Flow 3: Cross-Device Key Arrival (Secondary Device)

```
WebSocketTransport receives message with encrypted_chat_key for unknown chat
  |
  v
SyncEngine dispatches to handler (AI typing, phased sync, or new message)
  |
  v
ChatKeyManager.receiveKeyFromServer(chatId, encryptedChatKey)
  |-- decrypts encrypted_chat_key using master key
  |-- if key already cached AND matches: no-op
  |-- if key already cached AND DIFFERS: log KEY CONFLICT, accept server key (server is truth)
  |-- if new key: cache with provenance = 'server_sync'
  |-- flushPendingOps(chatId) -- executes any queued decrypt/encrypt operations
  |
  v
Queued operations execute (e.g., decrypt incoming message content for display)
```

### Flow 4: App Initialization (Bulk Key Load)

```
initializeApp()
  |
  v
ChatDatabase opens IndexedDB
  |
  v
loadChatKeysFromDatabase()
  |-- cursor over all chats in IDB
  |-- for each chat with encrypted_chat_key:
  |     decryptChatKeyWithMasterKey(encrypted_chat_key)
  |     collect [chatId, rawKey] pairs
  |-- also collects version map (messages_v, title_v, draft_v) per chat
  |
  v
ChatKeyManager.bulkInject(entries, 'bulk_init')
  |-- injects all keys with immutability guard
  |-- lower priority than master_key/server_sync sources
  |
  v
chatSyncService.connect() -> WebSocket opens
  |
  v
initial_sync_request sent with version map from cached data
  |
  v
Phased sync begins (Phase 1: last chat, Phase 2: recent, Phase 3: full)
  |-- each phase delivers encrypted_chat_key for any new/updated chats
  |-- ChatKeyManager.receiveKeyFromServer() for each
```

### Flow 5: AI Streaming Response (Foreground Device)

```
Server streams AI tokens via WebSocket (ai_message_update)
  |
  v
SyncEngine -> AIStreamHandler.handleAIMessageUpdate()
  |
  v
Tokens arrive as plaintext (server has cleartext during AI processing)
  |
  v
AIStreamHandler accumulates tokens, updates aiTypingStore for live display
  |
  v
On ai_response_completed:
  |
  v
ChatKeyManager.withKey(chatId, "encrypt AI response", async (key) => {
  MessageEncryptor.encryptContent(fullResponse, key)
  -> persist encrypted form to IndexedDB
  -> send encrypted metadata to server for cross-device sync
})
```

### Flow 6: Background Device Receives Completed AI Response

```
WebSocket receives ai_background_response_completed
  (includes encrypted message content, encrypted_chat_key)
  |
  v
ChatKeyManager.receiveKeyFromServer(chatId, encryptedChatKey)
  |-- ensures key is available
  |
  v
MessageEncryptor.decryptContent(encrypted_content, chatKey)
  |
  v
Store decrypted message in IndexedDB
Update UI stores (unread count, chat list preview)
```

---

## Patterns to Follow

### Pattern 1: Key-as-Parameter (Dependency Injection for Crypto)

**What:** Every encrypt/decrypt function receives the key as an explicit parameter. No function ever looks up a key internally.

**When:** Always. This is the fundamental architectural rule.

**Why:** Eliminates the class of bugs where a function silently uses the wrong key (e.g., generates a new one when lookup fails). TypeScript enforces non-null at the call site.

**Example:**
```typescript
// GOOD: Key is explicit parameter
function encryptContent(plaintext: string, chatKey: Uint8Array): Promise<string>;

// BAD: Function looks up its own key
function encryptContent(chatId: string, plaintext: string): Promise<string>;
```

### Pattern 2: State Machine for Key Lifecycle

**What:** Each chat key has exactly one state: `unloaded | loading | ready | failed`. Transitions are explicit and logged.

**When:** All key operations go through ChatKeyManager, which enforces the state machine.

**Why:** Prevents race conditions where two concurrent `getKey()` calls both trigger IDB reads and potentially return different results. The `loading` state + shared promise ensures at most one IDB read per chat key.

### Pattern 3: Queue-and-Flush for Deferred Operations

**What:** When an operation needs a key that is not yet `ready`, it is queued (with timeout). When the key arrives, all queued operations execute automatically.

**When:** Any write path that might execute before the key is available (e.g., post-processing metadata arriving before phased sync delivers the key).

**Why:** Avoids the temptation to "just generate a new key" when the real key has not arrived yet. The queue pattern makes the system eventually consistent without creating key conflicts.

### Pattern 4: Server-as-Source-of-Truth for Keys

**What:** When a key conflict is detected (local key differs from server-provided key), the server key wins. The conflict is logged prominently for debugging.

**When:** `receiveKeyFromServer()` detects a fingerprint mismatch.

**Why:** The server stores the canonical encrypted_chat_key at chat creation time. If a secondary device somehow generated a different key (a bug), trusting the server key preserves access to messages encrypted on the originating device.

### Pattern 5: Immutable Keys with Provenance

**What:** Once a key is set in ChatKeyManager for a chat, it cannot be silently replaced. Replacement requires either `force=true` or detection via `receiveKeyFromServer` (server wins). Every key records its source and timestamp.

**When:** All key injection paths.

**Why:** The root cause of "content decryption failed" was often silent key replacement -- a tab clearing all keys during a critical operation, causing regeneration of a different key. Immutability + critical-op lock prevents this.

### Pattern 6: Cross-Tab Coordination via BroadcastChannel

**What:** `clearAll()` on logout broadcasts to all open tabs, so no tab retains stale decrypted keys. The critical-op lock is respected: if another tab is mid-encryption, the clear is deferred.

**When:** Logout, forced logout, session expiry.

**Why:** Without this, a stale tab could encrypt new data with an old key from a previous session, creating unrecoverable ciphertext.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Implicit Key Generation

**What:** A function that is supposed to return a key decides to generate a new one when lookup fails (e.g., the old `getOrGenerateChatKey()`).

**Why bad:** Creates a second key for an existing chat. Messages encrypted with key A cannot be decrypted with key B. The user sees "content decryption failed" permanently.

**Instead:** Return null from key lookup. Let the caller decide (show placeholder, queue operation, or abort). Only `createKeyForNewChat()` / `createAndPersistKey()` may generate keys.

### Anti-Pattern 2: Encrypting Before Key Is Confirmed Ready

**What:** Starting encryption immediately when a message arrives, before verifying the chat key state is `ready`.

**Why bad:** If the key is still `loading` or `unloaded`, the code path might fall through to a generate-new-key fallback, creating key corruption.

**Instead:** Use `chatKeyManager.withKey(chatId, label, callback)` which handles all states correctly -- immediate execution if ready, IDB load if unloaded, queue if unavailable.

### Anti-Pattern 3: Dual Key Caches

**What:** Maintaining separate key caches in different modules (e.g., ChatKeyManager + a local Map in chatKeyManagement.ts).

**Why bad:** Caches can drift out of sync, leading to one module using an outdated key.

**Instead:** ChatKeyManager is the SINGLE source of truth. All other modules call `chatKeyManager.getKeySync()` or `chatKeyManager.getKey()`. The legacy `chatKeys` map in `chatKeyManagement.ts` has been removed.

### Anti-Pattern 4: Server Storing Plaintext Chat Content

**What:** Persisting unencrypted message content in Directus or cache.

**Why bad:** Violates zero-knowledge architecture. Server should only see plaintext during active AI processing (in-memory), never at rest.

**Instead:** Server stores only encrypted fields. The vault-encrypted cache of last 3 active chats is the one controlled exception (encrypted with Vault transit, not user keys).

---

## Scalability Considerations

| Concern | Current (1 user) | At 100 users | At 10K users |
|---------|-------------------|--------------|--------------|
| Key cache memory | All keys in memory per tab | Same (keys are 32 bytes each, negligible) | Same -- 10K chats x 32 bytes = 320KB, trivial |
| Bulk key loading | Cursor over all IDB chats on init | Add pagination to bulk load (100 at a time) | Lazy-load keys on demand instead of bulk |
| WebSocket connections | 1-3 connections per user | Connection pooling on backend | Horizontal scaling with Redis pub/sub for cross-instance broadcast |
| Key sync broadcasts | Broadcast to all user devices | Same pattern works | Same -- devices per user is bounded (< 10 typically) |
| Phased sync | 3-phase with 30s timeout | Add phase size limits | Paginate Phase 3, add cursor-based incremental sync |

---

## Build Order Implications

The dependency graph dictates implementation order:

```
Layer 0 (no dependencies, build first):
  CryptoOperations.ts  -- pure functions, no state
  MessageEncryptor.ts   -- depends only on CryptoOperations
  MetadataEncryptor.ts  -- depends only on CryptoOperations

Layer 1 (depends on Layer 0):
  MasterKeyService.ts   -- depends on CryptoOperations for key wrapping
  DecryptionFailureCache.ts  -- standalone utility

Layer 2 (depends on Layer 1):
  ChatKeyManager.ts     -- depends on MasterKeyService (unwrap), CryptoOperations (encrypt chat key)
  chatKeyManagement.ts  -- depends on ChatKeyManager, CryptoOperations

Layer 3 (depends on Layer 2):
  Sync handlers         -- depend on ChatKeyManager, MessageEncryptor, MetadataEncryptor
  SyncEngine            -- depends on ChatKeyManager, handlers, WebSocketTransport

Layer 4 (depends on Layer 3):
  Integration/E2E tests -- test full flow from SyncEngine through crypto to IDB
```

**Critical dependency chain:** Nothing in the sync layer should import from `encryption/` internals except through ChatKeyManager's public API. The sync handlers call `chatKeyManager.withKey()`, `chatKeyManager.receiveKeyFromServer()`, and the stateless encryptor functions -- they never call `cryptoService.ts` directly.

### Phase Ordering Rationale

1. **Audit first** -- Map every code path that touches encryption. The ChatKeyManager already has good structure; the problem is scattered crypto calls in sync handlers that bypass it.

2. **Extract pure crypto functions** (Layer 0) -- This is low-risk refactoring. Extract `MessageEncryptor` and `MetadataEncryptor` as thin wrappers around existing `encryptWithChatKey`/`decryptWithChatKey` calls. No behavior change.

3. **Consolidate key management** (Layer 1-2) -- Extract `MasterKeyService` from the tangled `cryptoService.ts` + `cryptoKeyStorage.ts`. ChatKeyManager is already well-structured; main work is ensuring all callers go through it.

4. **Rewire sync handlers** (Layer 3) -- Update sync handlers to use the new encryptors instead of inline crypto calls. This is where bugs get fixed: every encrypt/decrypt call now receives the key as a parameter from `chatKeyManager.withKey()`.

5. **Integration testing** (Layer 4) -- End-to-end tests simulating multi-device sync with key creation on device A and message decryption on device B.

### What Depends on What (Critical Build Constraints)

- MessageEncryptor/MetadataEncryptor MUST exist before rewiring sync handlers (Layer 3 needs Layer 0).
- ChatKeyManager changes (if any) MUST be backward-compatible -- it already serves the running app. No breaking API changes.
- Backend changes are minimal -- the server already stores encrypted fields as opaque blobs. Only the `encrypted_chat_metadata_handler` key immutability guard may need review.
- Every phase MUST preserve backward compatibility with existing encrypted chats. A migration that breaks old ciphertext is unacceptable.

---

## Key Lifecycle x Device Registration x WebSocket Sync

### Device Registration Flow

```
New device opens app
  |
  v
Auth flow (passkey/login) -> JWT + ws_token issued
  |
  v
Device fingerprint generated: SHA256(OS:Country:UserID:SessionID)
  |-- Device hash (without sessionId) used for "new device" detection
  |-- Connection hash (with sessionId) used for WebSocket routing
  |
  v
Master key MUST exist or be generated:
  |-- First device ever: Generate new master key, store in IDB
  |-- Existing user, new device: User must transfer master key
  |     (currently: re-login generates new master key -- existing chats
  |      use encrypted_chat_key wrapped with the NEW master key from server)
  |
  v
WebSocket connects with connection hash
  |
  v
Initial sync delivers encrypted_chat_keys for all chats
  |-- Each encrypted_chat_key is wrapped with this device's master key
  |     (server re-wraps during sync? NO -- the encrypted_chat_key is
  |      wrapped with the user's master key, which is the same across devices
  |      when the user transfers it. If the master key differs, decryption fails.)
```

### Master Key Problem (Architectural Gap)

The current system has an unresolved tension: if a user logs in on a new device, a NEW master key is generated. But existing `encrypted_chat_key` values were wrapped with the OLD master key. This means:

- **Originating device:** Has keys wrapped with its master key -- works fine.
- **New device:** Gets a fresh master key, but server-stored `encrypted_chat_key` values are wrapped with the old master key -- decryption fails.

The system appears to work around this by having the originating device re-encrypt and re-upload keys, or by having the server cache unwrapped keys temporarily. This is a likely root cause of cross-device decryption failures and should be investigated during the audit phase.

**Healthy architecture requires:** Either (a) a single master key shared across all devices (via transfer/recovery), or (b) per-device key wrapping where the server stores one wrapped copy per device. Option (a) is simpler and matches what Signal/WhatsApp do with QR-code key transfer.

---

## Sources

- Codebase analysis: `ChatKeyManager.ts` (1047 lines, well-documented state machine)
- Codebase analysis: `cryptoService.ts` (AES-GCM, key wrapping)
- Codebase analysis: `cryptoKeyStorage.ts` (master key persistence)
- Codebase analysis: `chatSyncService*.ts` (sync protocol, phased sync)
- Codebase analysis: `connection_manager.py` (multi-device WebSocket routing)
- Codebase analysis: `encrypted_chat_metadata_handler.py` (server-side encrypted storage)
- Codebase analysis: `encryption.py` (Vault transit for server-side encryption)
- E2E encryption patterns: Signal Protocol (double ratchet not applicable here, but key distribution model is relevant)
- Web Crypto API: AES-GCM with extractable keys in IndexedDB (standard pattern, HIGH confidence)

---

*Architecture analysis: 2026-03-26*
