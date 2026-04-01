<!--
  Master Key Cross-Device Distribution Mechanism

  Formalizes why cross-device key "transport" is not needed: the master key
  is derived deterministically from user credentials + server-stored salt,
  so every device independently arrives at the same key. This document
  complements master-key-lifecycle.md (which covers the full derivation chain)
  by focusing specifically on the cross-device angle.

  Requirement: KEYS-06
  See also: master-key-lifecycle.md, signup-and-auth.md
-->

---
status: active
last_verified: 2026-03-26
requirement: KEYS-06
related:
  - docs/architecture/core/master-key-lifecycle.md
  - docs/architecture/core/signup-and-auth.md
  - frontend/packages/ui/src/services/cryptoService.ts
  - frontend/packages/ui/src/services/encryption/ChatKeyManager.ts
---

# Master Key Cross-Device Distribution

> No key transport protocol is needed -- deterministic derivation is the distribution mechanism.

## Core Principle

The master key in OpenMates is never "sent" between devices. Instead, every device that can authenticate the user independently derives the same master key using the same inputs:

1. **User credential** (password, passkey PRF output, or recovery key)
2. **Server-stored salt** (unique per user, downloaded during login)
3. **Server-stored wrapped master key blob** (AES-GCM encrypted, downloaded during login)

The credential + salt produce a **wrapping key** via PBKDF2 (100,000 iterations, SHA-256). The wrapping key unwraps the server-stored blob to yield the master key. Since the inputs are deterministic and the blob is the same everywhere, every device arrives at the same 256-bit AES-GCM master key.

## Why Cross-Device Transport Is Unnecessary

Traditional E2E encryption systems (Signal, Matrix) need device-to-device key exchange because keys are generated randomly on a single device. OpenMates avoids this complexity:

| Approach | How key reaches new device | Complexity |
|----------|---------------------------|------------|
| Signal-style | QR code scan, device verification, key backup | High |
| iCloud Keychain | Cloud-stored keys, device trust chain | Medium |
| **OpenMates** | Derive from password + server blob | **Low** |

The tradeoff: OpenMates ties master key security to password strength (or passkey PRF output). This is acceptable for the product's threat model -- the server never sees the master key in plaintext, and PBKDF2 with 100k iterations provides adequate brute-force resistance.

## New Device Login Flow

```
New Device                          Server
    |                                  |
    |  1. Authenticate (password/passkey)
    |  -------------------------------->
    |                                  |
    |  2. Receive: salt, wrapped_master_key_blob
    |  <--------------------------------
    |                                  |
    |  3. Derive wrapping key:
    |     PBKDF2(password, salt, 100k)
    |                                  |
    |  4. Unwrap master key:
    |     AES-GCM-decrypt(blob, wrapping_key)
    |                                  |
    |  5. Bulk-load encrypted_chat_keys
    |  -------------------------------->
    |                                  |
    |  6. Receive all encrypted_chat_key records
    |  <--------------------------------
    |                                  |
    |  7. For each chat:
    |     chat_key = AES-GCM-decrypt(encrypted_chat_key, master_key)
    |     ChatKeyManager.injectKey(chatId, chat_key, "bulk_init")
    |                                  |
    |  8. All chats decryptable
    |                                  |
```

After step 7, all chat keys are in ChatKeyManager's memory with `bulk_init` provenance. The user can immediately read and write encrypted messages.

## Validation on Login

On every login (including new devices), the system validates master key correctness:

1. **Derive master key** from credentials + server blob
2. **Attempt to unwrap at least one `encrypted_chat_key`** from the user's chat list
3. **If unwrap succeeds**: master key is correct, proceed with bulk load
4. **If unwrap fails for ALL keys**: master key derivation failed -- credentials may have changed, or the wrapped blob is corrupt. Surface an error to the user.

This "fail fast" validation catches credential drift (e.g., password changed on another device but wrapped blob not re-encrypted) before the user encounters "content decryption failed" errors in the UI.

**Implementation:** `loadChatKeysFromDatabase()` in `chatSyncServiceSenders.ts` performs the bulk load and tracks success/failure counts. If zero keys decrypt successfully out of N attempts, it logs a critical error.

## Cross-Tab Key Distribution (Same Device)

Within a single device, multiple browser tabs share the same origin and therefore the same IndexedDB. Cross-tab key coordination uses BroadcastChannel (`openmates_crypto_v1`):

- **`clearAll` message**: Tab logging out broadcasts to other tabs to clear their in-memory key caches
- **`keyLoaded` message**: Tab that loads/creates a key broadcasts to other tabs. Receiving tabs warm their ChatKeyManager cache only if they have pending operations for that chat (Pitfall 4 prevention -- no unnecessary async work)

This is distinct from cross-device distribution. Cross-tab is about cache coherence; cross-device is about key availability.

## Security Properties

| Property | Guarantee |
|----------|-----------|
| Server never sees master key | Wrapped blob is encrypted before upload; server stores ciphertext only |
| Deterministic derivation | Same credential + salt + blob = same master key on every device |
| No device trust chain | No need to "trust" or "verify" new devices -- authentication IS the trust |
| Forward secrecy | Not provided -- compromise of password exposes all past messages. Acceptable for product model |
| Key rotation | Changing password re-wraps the master key blob with a new wrapping key. The master key itself does not change (preserves existing encrypted data) |

## Reference

For the complete derivation chain (PBKDF2 parameters, passkey PRF path, recovery key path, wrapping/unwrapping implementation), see [master-key-lifecycle.md](./master-key-lifecycle.md).
