---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/services/cryptoService.ts
  - frontend/packages/ui/src/services/cryptoKeyStorage.ts
  - backend/core/api/app/utils/encryption.py
  - backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py
---

# Zero-Knowledge Storage

> All sensitive user data is encrypted client-side before storage; the server stores only encrypted blobs it cannot decrypt.

## Why This Exists

- User data must remain private even if the server is fully compromised
- Government data requests should be unanswerable: zero-knowledge means we cannot decrypt
- The exception: AI inference requires cleartext during active processing (see below)

## How It Works

### Two Encryption Tiers

**Client-Managed (true zero-knowledge):** chats, messages, app data, emails, profile settings. Key lives on the user's device. Server stores encrypted blobs only.

**Server-Managed (Vault-hybrid):** server-generated files (images, PDFs, videos), long-running task outputs. AES key wrapped by HashiCorp Vault using a user-specific key ID. Needed because the server must complete tasks while the user may be offline.

For the full breakdown of both tiers, see [Security Architecture](./security.md).

### Master Key Lifecycle

1. During signup, the client generates a unique master key via `generateExtractableMasterKey()` in [cryptoService.ts](../../frontend/packages/ui/src/services/cryptoService.ts)
2. The master key is wrapped using the chosen login method:
   - **Password:** PBKDF2-SHA256 (100k iterations) via `deriveKeyFromPassword()`
   - **Passkey:** HKDF from WebAuthn PRF signature + user salt via `deriveWrappingKeyFromPRF()`
   - **Recovery key:** PBKDF2-SHA256 (100k iterations) via `deriveKeyFromPassword()`
3. The wrapped master key is stored on the server; the plaintext master key stays client-side only

### Master Key Storage Modes

Managed in [cryptoKeyStorage.ts](../../frontend/packages/ui/src/services/cryptoKeyStorage.ts):

- **Stay Logged In = false (default):** master key in memory only (module-level variable `memoryMasterKey`). Auto-cleared on page close.
- **Stay Logged In = true:** master key persisted to IndexedDB as a CryptoKey object. Uses `navigator.storage.persist()` to prevent iOS Safari from evicting the DB.

### Per-Data-Type Key Isolation

| Data type | Key source | Implementation |
|-----------|-----------|----------------|
| Chat messages | Per-chat AES key, wrapped with master key | `encryptWithChatKey()` / `decryptWithChatKey()` |
| Chat titles, drafts | Master key directly | `encryptWithMasterKey()` / `decryptWithMasterKey()` |
| Embeds | Per-embed key derived from chat key via HKDF | `deriveEmbedKeyFromChatKey()` |
| Email address | SHA256(email + salt) for server lookup; master key for client storage | `deriveEmailEncryptionKey()` / `encryptEmail()` |
| App settings & memories | Per-app AES key, wrapped with master key | Same pattern as chat keys |

Compromise of one data type does not affect others.

### Chat Key Immutability

Once a chat has an `encrypted_chat_key`, the server will not accept a different key unless the client includes an explicit `allow_chat_key_rotation` flag (used for hidden-chat hide/unhide flows). This guard operates at two levels:

1. **WebSocket handler** in [encrypted_chat_metadata_handler.py](../../backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py) compares incoming key against cached key
2. **Persistence task** in [persistence_tasks.py](../../backend/core/api/app/tasks/persistence_tasks.py) checks against Directus before writing

This prevents a misconfigured device from corrupting the chat key across devices.

### AI Inference Exception

**Zero-knowledge storage does not mean zero server access during active use.** For AI inference:

- The client sends cleartext chat content for processing
- The server caches the last 3 active chats per user via HashiCorp Vault encryption (72-hour TTL, LRU eviction)
- This cache is separate from permanent encrypted storage and improves inference performance
- The server cannot access stored chat history without user cooperation

## Cryptographic Standards

- **Symmetric encryption:** AES-256-GCM with random 12-byte IVs
- **Key derivation:** PBKDF2-SHA256 with 100,000 iterations (passwords, recovery keys)
- **Passkey derivation:** HKDF-SHA256 with info `"masterkey_wrapping"` (PRF signatures)
- **Random generation:** `crypto.getRandomValues()` (Web Crypto API)

All constants defined in [cryptoService.ts](../../frontend/packages/ui/src/services/cryptoService.ts): `AES_KEY_LENGTH = 256`, `AES_IV_LENGTH = 12`, `PBKDF2_ITERATIONS = 100000`.

## Edge Cases

- **Server compromise:** yields only encrypted blobs and hashes; no access to passwords, emails, chat content, or master keys
- **Browser eviction (iOS Safari):** `navigator.storage.persist()` + `STAY_LOGGED_IN_FLAG` in localStorage tracks whether key loss is expected or unexpected
- **Tab/device race on embed keys:** embed keys are derived deterministically from chat key + embed ID via HKDF, so all tabs produce the same key

## Related Docs

- [Security Architecture](./security.md) -- encryption tiers, S3 access, controls summary
- [Chat Encryption Implementation](./chat-encryption-implementation.md) -- field-level encryption details
- [Signup & Login](./signup-and-auth.md) -- master key creation during signup
- [Passkeys](./passkeys.md) -- PRF-based key wrapping
- [Email Privacy](../privacy/email-privacy.md) -- email encryption specifics
