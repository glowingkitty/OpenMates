# Feature Landscape

**Domain:** Client-side encrypted chat with cross-device sync
**Researched:** 2026-03-26
**Context:** Existing OpenMates system with AES-GCM encryption, master key wrapping, WebSocket sync, IndexedDB local storage. Rebuild focused on fixing "content decryption failed" errors caused by inconsistent key management and race conditions.

---

## Table Stakes

Features users expect. Missing = encryption system is broken or untrustworthy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Single key authority per chat** | Two devices generating different keys for the same chat = permanent data loss. Only the originating device creates the key; all others receive it. | Med | Current `ChatKeyManager.createKeyForNewChat()` is correct in principle but race conditions in `chatSyncServiceSenders.ts` (lines 1935-2107) show the "double-generate" bug still exists |
| **Atomic key-before-content guarantee** | A device must possess the decryption key before it receives encrypted content. Violating this = undecryptable messages. | High | The phased sync handler already sends `encrypted_chat_key` with chat metadata, but cache misses (initial_sync_handler lines 237-248) show keys sometimes arrive late or not at all |
| **Immutable keys (no silent replacement)** | Once a chat key is set, replacing it silently makes all prior messages undecryptable. Key replacement must be an explicit, audited migration. | Med | `ChatKeyManager` enforces this with provenance tracking and the `CHAT_KEY_GUARD` on the backend. Current implementation is correct but bypass paths exist in legacy code |
| **Master key derivation from password** | The master key wraps all chat keys. It must be derived deterministically from the user's password so it can be reconstructed on any device. Loss of master key = loss of all chat access. | Med | Currently uses Web Crypto `wrapKey`/`unwrapKey` with password-derived key. Working correctly. |
| **Encrypted key transport (server never sees plaintext chat keys)** | Chat keys are encrypted with the master key before server storage/transit. The server stores `encrypted_chat_key` (ciphertext). Zero-knowledge architecture. | Low | Already implemented. Server stores only `encrypted_chat_key` field in Directus. |
| **Cross-device key delivery via server relay** | When device B joins, it must receive all chat keys (encrypted with master key) via the server. The server relays but cannot read. | Med | Implemented via WebSocket `encrypted_chat_metadata` handler + phased sync. The failure mode is when the relay loses the key or delivers it after content. |
| **Backwards compatibility with existing encrypted data** | Any architectural change must still decrypt all previously encrypted chats. Migration must be non-destructive. | High | PROJECT.md constraint. ~All existing chats for admin user f21b15a5 must remain readable. Requires maintaining support for current ciphertext format (AES-GCM with IV prefix). |
| **Decryption failure visibility (never silent)** | When decryption fails, the user must see a clear error -- not blank content, not corrupted text, not a silent fallback. | Low | Already partially implemented (`decryptionFailureCache.ts`). Needs consistent application across all decrypt call sites. |
| **Key state machine with explicit transitions** | Key lifecycle must be a state machine (`unloaded -> loading -> ready -> failed`) with no implicit transitions. Prevents "key in limbo" states. | Med | `ChatKeyManager` implements this correctly. The issue is code paths that bypass the manager (legacy direct crypto calls). |
| **Operation queuing when key unavailable** | Encrypt/decrypt operations attempted before key arrival must queue and auto-execute when the key arrives, not fail silently or generate a new key. | Med | `ChatKeyManager.withKey()` implements this with `QueuedOperation` queue, 30s timeout, max 50 ops. Correct design. |
| **Cross-tab key coordination** | Multiple browser tabs must share key state. A logout in tab A must clear keys in tab B. A key loaded in tab A should be available in tab B. | Med | `BroadcastChannel("openmates_crypto_v1")` handles `clearAll` cross-tab. `keyLoaded` broadcast exists but receiver doesn't warm cache (relies on lazy-load). |
| **Graceful degradation on crypto API absence** | If Web Crypto API is unavailable (rare but possible in some WebView contexts), the system must fail clearly, not corrupt data. | Low | Not currently implemented -- should check for `crypto.subtle` at init and show a clear "unsupported browser" message |

---

## Differentiators

Features that set the product apart. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Key provenance tracking** | Every key records its source (created, master_key, server_sync, share_link, etc.) and timestamp. Makes debugging decryption failures trivial. | Low | Already implemented in `ChatKeyManager` with `KeyProvenance` type. Rare in chat apps -- most treat keys as opaque. |
| **Key fingerprint comparison** | Short fingerprints (FNV-1a hash) allow quick visual/programmatic comparison of keys across devices without exposing key material. | Low | Already implemented (`computeKeyFingerprint`). Could be surfaced in a debug UI. |
| **Critical operation locking** | `criticalOpCount` prevents `clearAll()` from wiping keys mid-operation (e.g., during `sendEncryptedStoragePackage`). Prevents the K1->K2 corruption class of bugs. | Med | Already implemented. This is defense-in-depth that most chat apps lack. |
| **Phased sync with progressive decryption** | Instead of blocking on full sync, chats load progressively: metadata first (sidebar), then content (on demand). Decryption happens lazily per-chat. | Med | Already implemented in the phased sync handler. Reduces perceived load time. |
| **Hidden chat encryption (dual-layer)** | Chats can be hidden behind a separate combined secret, re-encrypting the chat key with a different wrapping key. Plausible deniability. | High | Already implemented via `hiddenChatService.ts`. Unusual feature -- most encrypted chat apps don't offer this. |
| **Share link with URL-fragment key** | Shared chat links embed the decryption key in the URL fragment (never sent to server). Recipients can decrypt without an account. | Med | Already working. PROJECT.md says don't touch it. Elegant zero-knowledge sharing. |
| **Vault-encrypted server-side cache** | Server caches last 3 active chats encrypted with HashiCorp Vault keys for AI inference. Separates transport encryption (client) from storage encryption (server). | Med | Already implemented. Allows AI features without compromising E2EE model for the broader chat history. |
| **Decryption failure cache with auto-retry** | Failed decryptions are cached to avoid repeated failed attempts, but automatically retry when the key state changes. | Low | `decryptionFailureCache.ts` exists. Could be enhanced with automatic retry on key arrival events. |
| **Per-device key audit log** | Track which device loaded which key, when, and via what mechanism. Enables forensic analysis of key sync failures. | Med | Partially exists via provenance. A full audit log (persisted, not just in-memory) would be new. |
| **Encryption health dashboard** | Admin-facing UI showing key sync status across devices, decryption success rates, key age distribution. | High | Not implemented. Would be a strong differentiator for transparency-focused users. |

---

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Key rotation for existing chats** | Re-encrypting all messages with a new key is extremely complex, error-prone, and unnecessary for a single-user/small-user system. The "rotate key" concept implies the old key was compromised, but in this architecture the key is always encrypted at rest. | Keep keys immutable per chat. If a key is truly compromised, mark the chat as compromised and create a new chat. |
| **Per-message keys** | Signal Protocol uses per-message ratcheting, but that's for multi-party E2EE between untrusted parties. OpenMates encrypts the user's own data across their own devices -- a shared symmetric key per chat is correct and simpler. | Keep per-chat symmetric key (AES-GCM). |
| **Client-side key escrow / recovery questions** | "Security questions" or "recovery phrases" for master key recovery add attack surface and false security. If the master key is lost, the correct answer is that the data is gone (or rely on server-side Vault cache for recent chats). | Document that master key loss = data loss for old chats. Server Vault cache provides recent chat recovery. |
| **Custom crypto primitives** | PROJECT.md explicitly forbids this. Using standard Web Crypto AES-GCM + TweetNaCl XSalsa20-Poly1305 is correct. Rolling custom crypto is the #1 security anti-pattern. | Keep existing AES-GCM (Web Crypto) for chat content, XSalsa20-Poly1305 (TweetNaCl) for email encryption. |
| **Lazy key generation on first encrypt** | Generating a key "just in time" when the first message is encrypted creates the exact race condition causing current bugs (two devices both "first encrypt" simultaneously). | Always generate key explicitly at chat creation time via `createKeyForNewChat()`, never implicitly. |
| **Shared master key across users** | If OpenMates adds multi-user chats, do NOT share the master key. Each user should have their own master key; chat keys would need to be wrapped per-recipient. | Keep master key per-user. For future multi-user: wrap chat key N times (once per participant's public key). |
| **Offline key generation for remote chats** | A device should never generate a key for a chat it didn't originate. If the key isn't available, it waits (queue) or fails -- never generates a substitute. | Use the operation queue (`withKey`) to wait for key arrival. Show "waiting for encryption key" UI state. |
| **Browser extension or OS-level key storage** | Adds deployment complexity and attack surface. IndexedDB with non-extractable CryptoKey is the correct browser-native approach. | Keep IndexedDB for master key storage. CryptoKey non-extractable flag provides hardware-backed protection where available. |

---

## Feature Dependencies

```
Master Key Derivation
  --> Encrypted Key Transport (chat keys wrapped with master key)
    --> Cross-Device Key Delivery (wrapped keys relayed via server)
      --> Atomic Key-Before-Content (key must arrive before encrypted content)
        --> Operation Queuing (operations wait for key)

Single Key Authority
  --> Immutable Keys (once set, never replaced)
    --> Key State Machine (explicit transitions prevent accidental replacement)
      --> Cross-Tab Coordination (state shared across tabs)

Decryption Failure Visibility
  --> Decryption Failure Cache (track what failed)
    --> Key Provenance Tracking (debug WHY it failed)

Hidden Chat Encryption
  --> Master Key Derivation (base layer)
  --> Combined Secret Derivation (additional layer)
  --> Key Re-wrapping (chat key wrapped with combined secret instead of master key)

Backwards Compatibility
  --> All of the above (nothing can break existing ciphertext format)
```

---

## MVP Recommendation

For the encryption/sync rebuild, prioritize in this order:

### Phase 1: Fix the Foundation (Critical Path)
1. **Single key authority per chat** -- eliminate all code paths that can generate a duplicate key
2. **Atomic key-before-content guarantee** -- ensure phased sync always delivers key before content
3. **Immutable keys** -- remove all bypass paths around `ChatKeyManager`
4. **Backwards compatibility** -- every change must pass a "decrypt all existing chats" test

### Phase 2: Harden the Architecture
5. **Key state machine enforcement** -- route ALL crypto operations through `ChatKeyManager`, eliminate direct `cryptoService` calls from sync handlers
6. **Cross-tab coordination** -- warm key cache on `keyLoaded` broadcast instead of lazy-load
7. **Decryption failure visibility** -- consistent error surfaces across all decrypt call sites

### Phase 3: Observability
8. **Key provenance tracking** -- already exists, ensure it's logged/surfaced in debug tools
9. **Per-device key audit log** -- persist provenance events for post-mortem analysis
10. **Graceful degradation on crypto API absence** -- init-time check with clear error

**Defer:**
- **Encryption health dashboard**: High complexity, low urgency with single-user system
- **Key rotation**: Anti-feature for current architecture
- **Per-device audit log persistence**: Nice-to-have after the core is solid

---

## Sources

- OpenMates codebase analysis (PRIMARY): `ChatKeyManager.ts`, `cryptoService.ts`, `chatSyncServiceSenders.ts`, `chatSyncServiceHandlersPhasedSync.ts`, `encrypted_chat_metadata_handler.py`, `initial_sync_handler.py`, `phased_sync_handler.py`
- OpenMates project context: `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONCERNS.md`
- Domain knowledge: Signal Protocol design (per-message ratcheting vs per-chat symmetric keys), Matrix Megolm protocol (session-based encryption), Web Crypto API capabilities (AES-GCM, CryptoKey non-extractable), TweetNaCl XSalsa20-Poly1305 -- confidence: HIGH (well-established cryptographic patterns, not version-dependent)
- Note: WebSearch was unavailable during this research. Feature categorization is based on codebase analysis + established encryption engineering principles. Confidence remains HIGH because this is an architecture/patterns question, not a rapidly-changing library ecosystem question.
