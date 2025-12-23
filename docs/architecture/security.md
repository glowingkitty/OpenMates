# Security Architecture Overview

> Zero-knowledge architecture where the server never sees passwords, emails, or encryption keys.

## Core Security Principles

- **Server = encrypted storage only**: Stores encrypted blobs it cannot decrypt
- **Client-side encryption**: All sensitive data encrypted before leaving user's device
- **Multiple login methods**: Password, passkey, recovery key support with individual wrapped keys
- **Granular key isolation**: Separate encryption keys for chats, apps, emails, embeds

## Security Controls Summary

| Category | Status | Details | Documentation |
|----------|--------|---------|---------------|
| **Authentication** | ✅ 6/8 | Zero-knowledge login, 2FA mandatory | [Signup & Login](./signup_login.md) |
| **Encryption** | ✅ 6/7 | AES-256-GCM, client-side keys | [Zero-Knowledge Storage](./zero_knowledge_storage.md) |
| **Email Privacy** | ✅ Implemented | Client-side encrypted storage | [Email Privacy](./email_privacy.md) |
| **Device Management** | 🔄 Planned | QR login, remote logout | [Device Management](./device_session_management.md) |
| **Passkey Support** | ✅ Implemented | WebAuthn with PRF extension | [Passkeys](./passkeys.md) |

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

**Implementation**: [`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py) and [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)

## Quick Architecture Diagram

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

## Security Design Assumptions

1. **Servers will be compromised**: Store all user data encrypted with user-controlled keys
2. **Government data requests**: Zero-knowledge design means we can't decrypt user data even under legal pressure
3. **Prompt injection attacks**: Embrace transparency, use defense-in-depth, minimize data exposure in prompts