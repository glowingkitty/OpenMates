# Technology Stack: Client-Side Encryption, Key Management & Real-Time Sync

**Project:** Encryption & Sync Architecture Rebuild
**Researched:** 2026-03-26
**Mode:** Ecosystem (stack dimension)
**Overall Confidence:** HIGH -- recommendations are grounded in the existing codebase, Web Crypto API standards (verified via MDN), and browser platform APIs already at Baseline Widely Available status.

---

## Executive Summary

The existing OpenMates encryption stack is fundamentally sound in its choice of primitives: AES-GCM 256-bit via the Web Crypto API, PBKDF2 for key derivation, CryptoKey objects stored in IndexedDB. The problems documented in PROJECT.md are architectural (race conditions, scattered code, inconsistent key lifecycle), not cryptographic. The rebuild should keep the same crypto primitives (per project constraints) and focus on three areas: (1) a strict key lifecycle state machine, (2) atomic cross-device key sync over the existing WebSocket, and (3) cross-tab coordination using browser platform APIs.

No new crypto libraries are needed. The primary technology additions are browser platform APIs (Web Locks API, BroadcastChannel API) and architectural patterns, not npm packages.

---

## Recommended Stack

### Core Cryptography -- KEEP AS-IS

The existing Web Crypto API usage is the correct choice. Do not introduce alternative crypto libraries.

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Web Crypto API (`crypto.subtle`) | Browser built-in | AES-GCM encrypt/decrypt, key generation, PBKDF2/HKDF derivation, key wrapping | Native, hardware-accelerated, non-extractable key support, zero bundle cost. Already used throughout `cryptoService.ts`. No JS library matches its security properties. | HIGH |
| AES-GCM 256-bit | N/A (algorithm) | Symmetric encryption of chat content, messages, embeds | Authenticated encryption (integrity + confidentiality in one pass). 12-byte random IV per operation. Already the standard across the codebase. | HIGH |
| PBKDF2 (100k iterations) | N/A (algorithm) | Password-to-key derivation for master key wrapping | Already used in `cryptoService.ts`. 100k iterations is adequate for 2025/2026 -- OWASP recommends 600k for PBKDF2-SHA256 but this wraps an already-random key, not a user password, so 100k is fine. | HIGH |
| HKDF-SHA256 | N/A (algorithm) | Deriving sub-keys from master key material | Already used in `cryptoService.ts` for embed key derivation. Correct choice for deriving multiple keys from high-entropy input. | HIGH |
| AES-KW (Key Wrap) | N/A (algorithm) | Wrapping chat keys with master key for server storage | Already used via `crypto.subtle.wrapKey()`. Purpose-built for key wrapping -- ensures wrapped keys can only be used as keys after unwrapping. | HIGH |

### Key Storage -- KEEP AS-IS

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| IndexedDB (`openmates_crypto` DB) | Browser built-in | Master key persistence (as `CryptoKey` object) | Stores structured-clone-compatible `CryptoKey` objects natively. Better isolation than localStorage. Already implemented in `cryptoKeyStorage.ts`. | HIGH |
| IndexedDB (`chats_db`) | Browser built-in | Per-chat encrypted key cache, chat data | Already stores `encrypted_chat_key` per chat. The rebuild should ensure chat keys are stored as wrapped blobs (not raw bytes). | HIGH |
| Memory (module-level variable) | N/A | Master key for `stayLoggedIn=false` sessions | Already implemented. Key auto-clears on page close. Correct behavior. | HIGH |
| `navigator.storage.persist()` | Browser built-in | Prevent iOS Safari from evicting IndexedDB | Already implemented. Critical for mobile reliability. | HIGH |

### Cross-Tab Coordination -- NEW ADDITIONS

These are the primary technology additions for the rebuild. Both APIs are Baseline Widely Available (since March 2022).

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Web Locks API (`navigator.locks`) | Browser built-in | Mutex for key generation, key write operations, and IndexedDB migrations | Prevents the core race condition: two tabs simultaneously generating different keys for the same chat. Exclusive locks ensure only one tab performs key creation. Available since March 2022, works across tabs and workers. | HIGH |
| BroadcastChannel API | Browser built-in | Cross-tab key propagation and state invalidation | When one tab generates or receives a new chat key, it broadcasts to other tabs so they update their in-memory cache without requiring a server round-trip. Available since March 2022. | HIGH |

### Real-Time Sync -- KEEP EXISTING WEBSOCKET

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| WebSocket (existing) | Browser built-in | Cross-device chat and key sync | Already implemented (`websocketService.ts`, `chatSyncService.ts`). The rebuild should add explicit key-sync message types, not replace the transport. | HIGH |
| Phased sync protocol (existing) | Custom | Initial sync on page load | Already implemented in `initial_sync_handler.py`. Rebuild should ensure key availability is resolved before message decryption attempts. | HIGH |

### Email Encryption -- KEEP AS-IS (Out of Scope)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `tweetnacl` | 1.0 | Email encryption (XSalsa20-Poly1305) | Only used for email encrypt/decrypt to match PyNaCl format on backend. Out of scope for this rebuild -- it works fine and is isolated to two functions in `cryptoService.ts`. | HIGH |

### Testing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Vitest | 3.2+ (existing) | Unit tests for key lifecycle, encryption round-trips, state machine transitions | Already in use. `ChatKeyManager.test.ts` exists. Extend coverage to new lock/broadcast patterns. | HIGH |
| Playwright | 1.49 (existing) | E2E tests for cross-device sync scenarios | Already in use. Add multi-tab test scenarios using Playwright's `browser.newContext()`. | HIGH |
| `@vitest/coverage-v8` | (match Vitest) | Coverage reporting for encryption module | Encryption code must have high coverage -- decryption failures are the #1 reported bug class. | MEDIUM |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Symmetric encryption | Web Crypto AES-GCM | `tweetnacl` SecretBox (XSalsa20-Poly1305) | AES-GCM is hardware-accelerated via Web Crypto. tweetnacl is pure JS -- slower and no non-extractable key support. Keep tweetnacl only for the backend-compatible email encryption path. |
| Symmetric encryption | Web Crypto AES-GCM | libsodium.js (`sodium-plus`, `libsodium-wrappers`) | Adds 200KB+ to bundle for capabilities Web Crypto already provides. libsodium is excellent for server-side or when you need algorithms Web Crypto lacks (e.g., ChaCha20), but AES-GCM via Web Crypto covers all OpenMates use cases. |
| Key storage | IndexedDB (CryptoKey objects) | localStorage (Base64 strings) | localStorage stores strings -- keys would need to be exportable Base64, losing CryptoKey isolation. IndexedDB stores CryptoKey objects via structured clone. |
| Key storage | IndexedDB (CryptoKey objects) | OPFS (Origin Private File System) | OPFS is for file-like data, not structured objects. IndexedDB is the standard for CryptoKey persistence. OPFS would add complexity with no security benefit. |
| Cross-tab sync | BroadcastChannel + Web Locks | `SharedWorker` | SharedWorker provides a single execution context across tabs -- architecturally cleaner but significantly harder to debug, not available in all contexts (e.g., some mobile browsers have inconsistent support), and BroadcastChannel + Web Locks achieves the same coordination with simpler code. |
| Cross-tab sync | BroadcastChannel + Web Locks | localStorage `storage` event | Legacy pattern. Only works for string data, fires on other tabs only (not the writing tab), and cannot coordinate mutexes. BroadcastChannel is the modern replacement. |
| Cross-device sync | WebSocket (existing) | WebRTC DataChannel (peer-to-peer) | Adds massive complexity (STUN/TURN, peer discovery, NAT traversal) for a problem the existing WebSocket already solves. WebRTC makes sense for peer-to-peer apps without a server; OpenMates has a server. |
| Cross-device sync | WebSocket (existing) | Server-Sent Events (SSE) + REST | SSE is one-directional (server to client). Chat sync is bidirectional. Would require SSE + separate REST POST calls, adding complexity vs. a single WebSocket. |
| E2E encryption protocol | Per-chat symmetric key (current) | Signal Protocol (Double Ratchet) | Signal Protocol is for multi-party messaging with forward secrecy. OpenMates encrypts a single user's chats across their own devices -- not a multi-party scenario. Signal adds ratchet state management, prekey servers, and session management with no benefit for single-user encryption. |
| Key derivation | PBKDF2 | Argon2 (via WASM) | Argon2 is superior for password hashing but Web Crypto does not support it natively. Would require a WASM module (e.g., `argon2-browser`), adding bundle size and complexity. PBKDF2 is fine here because it wraps an already-random 256-bit key, not a weak password. |

---

## What NOT to Use

| Technology | Why Not |
|------------|---------|
| `libsodium-wrappers` / `sodium-plus` | Bundle bloat (200KB+). Web Crypto API covers all needed algorithms natively. |
| `openpgp.js` | PGP is for email-style encryption with public key infrastructure. Wrong model for single-user chat encryption. |
| `matrix-js-sdk` / Olm/Megolm | Matrix protocol crypto is for federated multi-user rooms. Massive dependency for an irrelevant use case. |
| `node-forge` | Legacy library, slow pure-JS implementations. Web Crypto is faster and more secure. |
| Any "encryption wrapper" npm packages | Most are thin wrappers around Web Crypto that add abstraction without value. The raw `crypto.subtle` API is well-documented and already used throughout the codebase. |
| `idb` (IndexedDB wrapper library) | The existing raw IndexedDB code works fine. Adding a wrapper library for 3 object stores is unnecessary abstraction. |
| WASM-based crypto libraries | Web Crypto is already hardware-accelerated. WASM crypto adds bundle size and complexity for equivalent or worse performance. |

---

## Architecture Patterns (Stack-Level)

### Key Hierarchy (Already In Place -- Formalize)

```
Master Key (AES-GCM 256-bit, CryptoKey in IndexedDB)
  |
  +-- wraps --> Chat Key A (AES-GCM 256-bit, raw bytes wrapped with AES-KW)
  +-- wraps --> Chat Key B
  +-- wraps --> Chat Key N
  |
  +-- HKDF derives --> Embed Sub-Key (per embed, deterministic from chat key + embed ID)
```

### Cross-Tab Coordination Pattern (New)

```
Tab 1: navigator.locks.request("chat-key-{chatId}", async () => {
          // Generate key, store in IndexedDB
          broadcastChannel.postMessage({ type: "key-ready", chatId, ... })
        })

Tab 2: broadcastChannel.onmessage = (e) => {
          if (e.data.type === "key-ready") {
            // Load key from IndexedDB into memory cache
          }
        }
```

### Cross-Device Key Sync Pattern (Existing WebSocket -- Formalize)

```
Device A (originator):
  1. Generate chat key
  2. Wrap with master key --> encrypted_chat_key
  3. Send via WebSocket: { type: "key_sync", chat_id, encrypted_chat_key }

Device B (receiver):
  1. Receive key_sync message
  2. Unwrap encrypted_chat_key with local master key
  3. Store in ChatKeyManager (state: "ready", source: "server_sync")
  4. Flush queued decrypt operations for this chat
```

---

## Version Constraints

All crypto is via browser built-in APIs. No version pinning needed for:
- Web Crypto API (available since 2015)
- Web Locks API (Baseline since March 2022)
- BroadcastChannel API (Baseline since March 2022)
- IndexedDB (available since 2015)
- `navigator.storage.persist()` (Baseline since 2022)

The only npm dependency in the encryption stack is `tweetnacl@1.0` for the out-of-scope email encryption path.

### Browser Minimums

These APIs require:
- Chrome 69+ / Edge 79+ / Firefox 96+ / Safari 15.4+
- All well within the SvelteKit app's existing browser target

---

## Installation

No new npm packages required. The rebuild is an architectural refactor using existing browser APIs.

```bash
# Nothing to install. The stack is:
# - Web Crypto API (browser built-in)
# - Web Locks API (browser built-in)
# - BroadcastChannel API (browser built-in)
# - IndexedDB (browser built-in)
# - tweetnacl@1.0 (already installed, email-only)
```

---

## Sources

- MDN Web Crypto API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Crypto_API (verified 2026-03-26)
- MDN SubtleCrypto: https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto (verified 2026-03-26)
- MDN Web Locks API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API (verified 2026-03-26, Baseline March 2022)
- MDN BroadcastChannel API: https://developer.mozilla.org/en-US/docs/Web/API/Broadcast_Channel_API (verified 2026-03-26, Baseline March 2022)
- Existing codebase analysis: `cryptoService.ts`, `cryptoKeyStorage.ts`, `ChatKeyManager.ts`, `chatSyncService.ts`

---

*Stack research: 2026-03-26*
