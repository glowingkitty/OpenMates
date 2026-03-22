# Security Architecture Overview

> Zero-knowledge architecture where the server never sees passwords, emails, or encryption keys.

## Core Security Principles

- **Server = encrypted storage only**: Stores encrypted blobs it cannot decrypt by default
- **Dual-Mode Encryption**: Standard user data is **Client-Side Encrypted** (Zero-Knowledge). Server-generated files (images, PDFs) use **Server-Managed Encryption** (Vault) for functionality.
- **Client-side encryption**: Most sensitive data encrypted before leaving user's device
- **Multiple login methods**: Password, passkey, recovery key support with individual wrapped keys
- **Granular key isolation**: Separate encryption keys for chats, apps, emails, embeds
- **Password requires 2FA**: Password authentication always requires two-factor authentication - they are set up together and cannot exist independently

## Security Controls Summary

| Category              | Status         | Details                                        | Documentation                                   |
| --------------------- | -------------- | ---------------------------------------------- | ----------------------------------------------- |
| **Authentication**    | ✅ 6/8         | Zero-knowledge login, 2FA mandatory            | [Signup & Login](./signup-and-auth.md)          |
| **Encryption**        | ✅ 7/7         | AES-256-GCM, Client-Managed & Server-Managed   | [Encryption Tiers](#encryption-tiers-dual-mode) |
| **S3 File Access**    | ✅ Implemented | Private bucket + presigned URLs (15-min TTL)   | [S3 Access Control](#s3-file-access-control)    |
| **Email Privacy**     | ✅ Implemented | Client-side encrypted storage                  | [Email Privacy](./email-privacy.md)             |
| **PII Anonymization** | ✅ Implemented | Client-side detection, placeholder replacement | [PII Anonymization](./pii-protection.md)        |
| **Device Management** | 🔄 Planned     | QR login, remote logout                        | [Device Management](./device-sessions.md)       |
| **Passkey Support**   | ✅ Implemented | WebAuthn with PRF extension                    | [Passkeys](./passkeys.md)                       |

## Encryption Tiers (Dual-Mode)

OpenMates implements a hybrid encryption model to balance maximum privacy with the practical needs of AI-powered features and long-running server tasks.

### 1. Client-Managed (Zero-Knowledge)

**Used for**: Chat messages, most app data, profile settings, email content.

- **Key Location**: User's device (never sent to server).
- **Security**: The server stores only encrypted blobs. Even with physical access to the database or a compromise of the backend, the server cannot read this data.
- **Limitation**: The server cannot process this data in the background (e.g., AI cannot analyze a client-side encrypted chat history while the user is offline).

### 2. Server-Managed (Vault-Hybrid)

**Used for**: Server-generated files (Images, PDFs, Videos), long-running task outputs.

- **Key Location**: Encrypted by a unique AES key, which is then **wrapped by HashiCorp Vault** using a user-specific key ID.
- **Security**: Data is encrypted at rest in S3 (private bucket — no anonymous access) and Directus. The server can temporarily "unwrap" the key to process the file (e.g., AI modifying a previously generated image, or generating a download stream).
- **Reasoning**: Necessary for long-running tasks that complete while the user is offline. Without this, the user would need to stay online with an open browser to encrypt the final result of a 30-second image generation.

---

## S3 File Access Control

All user-uploaded and server-generated files in the **chatfiles bucket** are stored with **private ACL** — no anonymous or public S3 access is permitted. Both encrypted uploads and server-generated encrypted files use this bucket.

> Profile images use a separate bucket with public-read ACL and contain no sensitive data (unencrypted thumbnails).

### Client-Side File Access (Presigned URLs)

When the frontend needs to display a file (image, audio, PDF), it uses a short-lived presigned URL:

1. **Client requests a presigned URL**: `GET /v1/embeds/presigned-url?s3_key=<key>` (authenticated via session cookie or API key, rate-limited to 120 req/min)
2. **API validates** the user is authenticated, then calls S3 to generate a **15-minute presigned URL**
3. **Client fetches the encrypted blob** directly from S3 using the presigned URL
4. **Client decrypts** using the AES key stored locally (Client-Managed) or unwrapped from Vault (Server-Managed)
5. **On 403 (expired URL)**: the frontend automatically retries with a fresh presigned URL — the existing in-memory blob cache prevents redundant fetches

The presigned URL grants temporary read access to a single S3 object. It does not reveal the encryption key or bypass decryption — the blob at that URL is still AES-256-GCM encrypted.

### Server-Side File Access (Internal API)

Skills and background tasks (running in separate containers) access S3 via an internal endpoint that uses server-side AWS credentials — they never receive presigned URLs or plaintext keys from the client:

- `GET /internal/s3/download?s3_key=<key>` — returns the raw encrypted bytes to the calling skill
- Skills then unwrap the AES key from Vault and decrypt in-memory
- This endpoint is internal-only (not exposed through the public API gateway)

### Audio Transcription Security

The audio transcription skill (`transcribe_skill.py`) follows the same Vault-Transit pattern as images and PDFs:

- Client sends `vault_wrapped_aes_key` (not a plaintext AES key)
- The `apps_api.py` handler resolves the user's `vault_key_id` from cache/Directus and injects it as `_user_vault_key_id`
- The skill unwraps the AES key from Vault using the user's key ID, then decrypts the audio blob obtained via the internal S3 download endpoint

This prevents the client from ever transmitting a raw encryption key over the network.

### Architecture Diagram (S3 Access)

```
Client (Browser)                     API Server                    S3 (Private Bucket)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                      │
GET /v1/embeds/presigned-url ───────→ │ Validates auth
                                      │ Calls S3 GeneratePresignedUrl (15 min TTL)
         ← presigned URL ─────────── │
                                      │
GET <presigned S3 URL> ────────────────────────────────────────────────────────────→
         ← encrypted blob ←───────────────────────────────────────────────────────
                                      │
Decrypt with local AES key            │
(Web Crypto API, never leaves device) │


Skill Container                       API Server (Internal)         S3 (Private Bucket)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                      │
GET /internal/s3/download?key=… ────→ │ Uses server AWS credentials
                                      │ Calls S3 GetObject
         ← encrypted bytes ────────  │ ←─────────────────────────────────────────
                                      │
Vault.unwrap(vault_wrapped_aes_key)   │
Decrypt bytes in memory               │
```

### Key Implementation Files

- **[`backend/core/api/app/routes/embeds_api.py`](../../backend/core/api/app/routes/embeds_api.py)**: `GET /v1/embeds/presigned-url` endpoint
- **[`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py)**: `GET /internal/s3/download` endpoint
- **[`backend/core/api/app/services/s3/config.py`](../../backend/core/api/app/services/s3/config.py)**: Bucket ACL configuration (`private`)
- **[`frontend/packages/ui/src/services/presignedUrlService.ts`](../../frontend/packages/ui/src/services/presignedUrlService.ts)**: Client presigned URL fetch + 403 retry logic

---

## Zero-Knowledge Authentication

OpenMates uses zero-knowledge authentication where servers never see passwords, emails, or encryption keys in plaintext.

### How Authentication Works

**Client-Side (User's Device)**:

1. Derives `lookup_hash = SHA256(password + salt)`
2. Sends only the hash to server (never plaintext password)
3. Decrypts master key locally to verify authentication

**Server-Side**:

1. Locates user by `hashed_email = SHA256(email)`
2. Verifies `lookup_hash` exists in user's registered hashes
3. Never sees or stores plaintext credentials

### Security Result

Even if servers are compromised, attackers only get useless hashes without access to:

- User passwords (only hashes stored)
- Email addresses (encrypted with user keys)
- Chat content (encrypted with user keys)
- Master encryption keys (never transmitted)

### Password + 2FA Requirement

Password authentication **always requires 2FA** to be enabled. When a user sets up a password:

1. User enters and confirms new password
2. If 2FA is not already enabled, user MUST complete 2FA setup first
3. Password is ONLY saved to server AFTER 2FA setup completes successfully
4. If user cancels 2FA setup, password is NOT saved - both must succeed together

This ensures that password-based authentication is always protected by a second factor, preventing unauthorized access even if the password is compromised.

**Implementation**: [`frontend/packages/ui/src/components/settings/security/SettingsPassword.svelte`](../../frontend/packages/ui/src/components/settings/security/SettingsPassword.svelte)

**Implementation**: [`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py) and [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)

## Architecture Diagram

### Client-Managed Flow (Default)

```
User's Device (🔐 Encrypted)     |     Server (🔒 Encrypted Blobs Only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                  │
Password → Derives Hash ───────→ │ Verifies Hash (never sees password)
           (stays local)          │
                                  │
Email → Encrypts ─────────────→ │ Stores encrypted blob (can't read)
        (with user salt)          │
                                  │
Master Key → Encrypts Data ───→ │ Stores encrypted chats/apps (can't decrypt)
            (stays local)         │
```

### Server-Managed Flow (Generated Files)

```
User's Device (🔓 Plaintext)      |     Server (🔑 Vault Wrapped)       |  S3 (🔒 Private)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│━━━━━━━━━━━━━━━━━
                                   │                                      │
Requests AI Generation ────────→ │ 1. Dispatches long-running task      │
                                   │ 2. Task generates file (e.g. Image)  │
                                   │ 3. Generates random AES key          │
                                   │ 4. Encrypts file with AES key        │
                                   │ 5. Wraps AES key with Vault (User-ID)│
                                   │ 6. Stores encrypted file ──────────→ │ ACL: private
                                   │                                      │
GET /v1/embeds/presigned-url ────→ │ 7. Generates 15-min presigned URL   │
         ← presigned URL ────────  │                                      │
Fetches encrypted blob via URL ──────────────────────────────────────────→│
         ← encrypted blob ←───────────────────────────────────────────────│
Vault.unwrap → Decrypt locally    │                                      │
```

## Implementation Guide

### New to OpenMates Security?

1. **Authentication flows**: Start with [Signup & Login](./signup-and-auth.md)
2. **Client-side encryption**: See [Zero-Knowledge Storage](./zero-knowledge-storage.md)
3. **Email privacy**: Check [Email Privacy](./email-privacy.md)
4. **Device management**: Review [Device & Session Management](./device-sessions.md)
5. **Passkey implementation**: See [Passkeys](./passkeys.md)

### Working on Specific Features?

- **User signup/login**: [Signup & Login](./signup-and-auth.md) + `backend/core/api/app/routes/auth_routes/auth_login.py`
- **Chat encryption**: [Zero-Knowledge Storage](./zero-knowledge-storage.md) + `frontend/packages/ui/src/services/cryptoService.ts`
- **Email handling**: [Email Privacy](./email-privacy.md) + `backend/core/api/app/utils/encryption.py`
- **Session security**: [Device Management](./device-sessions.md) + WebSocket handlers

## Key Implementation Files

### Frontend Security

- **[`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)**: Core client-side encryption/decryption
- **[`frontend/packages/ui/src/services/presignedUrlService.ts`](../../frontend/packages/ui/src/services/presignedUrlService.ts)**: Presigned URL fetching with 403 retry logic
- **[`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)**: Local encrypted database operations
- **[`frontend/packages/ui/src/components/Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte)**: Authentication interface

### Backend Security

- **[`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py)**: Zero-knowledge authentication
- **[`backend/core/api/app/utils/encryption.py`](../../backend/core/api/app/utils/encryption.py)**: Server-side encryption utilities (Vault)
- **[`backend/core/api/app/routes/auth_routes/auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py)**: WebAuthn passkey implementation
- **[`backend/core/api/app/routes/embeds_api.py`](../../backend/core/api/app/routes/embeds_api.py)**: Presigned URL endpoint for client file access
- **[`backend/core/api/app/routes/internal_api.py`](../../backend/core/api/app/routes/internal_api.py)**: Internal S3 download endpoint for skills/tasks
- **[`backend/core/api/app/services/s3/config.py`](../../backend/core/api/app/services/s3/config.py)**: S3 bucket ACL configuration

### Safety & AI Security

- **[`backend/apps/ai/processing/preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)**: Request safety analysis
- **[Prompt Injection Protection](./prompt-injection.md)**: LLM safety architecture
- **[LLM Hallucination Mitigation](./hallucination-mitigation.md)**: Controls to reduce fabricated URLs, tool-result hallucinations, and planned improvements

## Security Design Assumptions

1. **Servers will be compromised**: Store all user data encrypted with user-controlled keys
2. **Government data requests**: Zero-knowledge design means we can't decrypt user data even under legal pressure
3. **Prompt injection attacks**: Embrace transparency, use defense-in-depth, minimize data exposure in prompts
