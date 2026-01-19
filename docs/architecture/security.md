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

| Category | Status | Details | Documentation |
|----------|--------|---------|---------------|
| **Authentication** | ✅ 6/8 | Zero-knowledge login, 2FA mandatory | [Signup & Login](./signup_login.md) |
| **Encryption** | ✅ 7/7 | AES-256-GCM, Client-Managed & Server-Managed | [Encryption Tiers](#encryption-tiers-dual-mode) |
| **Email Privacy** | ✅ Implemented | Client-side encrypted storage | [Email Privacy](./email_privacy.md) |
| **Device Management** | 🔄 Planned | QR login, remote logout | [Device Management](./device_session_management.md) |
| **Passkey Support** | ✅ Implemented | WebAuthn with PRF extension | [Passkeys](./passkeys.md) |

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
- **Security**: Data is encrypted at rest in S3 and Directus. The server can temporarily "unwrap" the key to process the file (e.g., AI modifying a previously generated image, or generating a download stream).
- **Reasoning**: Necessary for long-running tasks that complete while the user is offline. Without this, the user would need to stay online with an open browser to encrypt the final result of a 30-second image generation.

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
User's Device (🔓 Plaintext)      |     Server (🔑 Vault Wrapped)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                  │
Requests AI Generation ────────→ │ 1. Dispatches long-running task
                                  │ 2. Task generates file (e.g. Image)
                                  │ 3. Generates AES key
                                  │ 4. Wraps AES key with Vault (User-ID)
Downloads Decrypted File ←─────  │ 5. Stores encrypted file in S3
                                  │
```

## Implementation Guide

### New to OpenMates Security?

1. **Authentication flows**: Start with [Signup & Login](./signup_login.md)
2. **Client-side encryption**: See [Zero-Knowledge Storage](./zero_knowledge_storage.md)
3. **Email privacy**: Check [Email Privacy](./email_privacy.md)
4. **Device management**: Review [Device & Session Management](./device_session_management.md)
5. **Passkey implementation**: See [Passkeys](./passkeys.md)

### Working on Specific Features?

- **User signup/login**: [Signup & Login](./signup_login.md) + `backend/core/api/app/routes/auth_routes/auth_login.py`
- **Chat encryption**: [Zero-Knowledge Storage](./zero_knowledge_storage.md) + `frontend/packages/ui/src/services/cryptoService.ts`
- **Email handling**: [Email Privacy](./email_privacy.md) + `backend/core/api/app/utils/encryption.py`
- **Session security**: [Device Management](./device_session_management.md) + WebSocket handlers

## Key Implementation Files

### Frontend Security
- **[`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)**: Core client-side encryption/decryption
- **[`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)**: Local encrypted database operations
- **[`frontend/packages/ui/src/components/Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte)**: Authentication interface

### Backend Security
- **[`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py)**: Zero-knowledge authentication
- **[`backend/core/api/app/utils/encryption.py`](../../backend/core/api/app/utils/encryption.py)**: Server-side encryption utilities (Vault)
- **[`backend/core/api/app/routes/auth_routes/auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py)**: WebAuthn passkey implementation

### Safety & AI Security
- **[`backend/apps/ai/processing/preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)**: Request safety analysis
- **[Prompt Injection Protection](./prompt_injection_protection.md)**: LLM safety architecture
- **[LLM Hallucination Mitigation](./llm_hallucination_mitigation.md)**: Controls to reduce fabricated URLs, tool-result hallucinations, and planned improvements

## Security Design Assumptions

1. **Servers will be compromised**: Store all user data encrypted with user-controlled keys
2. **Government data requests**: Zero-knowledge design means we can't decrypt user data even under legal pressure
3. **Prompt injection attacks**: Embrace transparency, use defense-in-depth, minimize data exposure in prompts
