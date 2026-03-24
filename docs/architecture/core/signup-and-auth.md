---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/routes/auth_routes/auth_login.py
  - backend/core/api/app/routes/auth_routes/auth_passkey.py
  - backend/core/api/app/routes/auth_routes/auth_2fa_setup.py
  - frontend/packages/ui/src/services/cryptoService.ts
  - frontend/packages/ui/src/services/cryptoKeyStorage.ts
  - frontend/packages/ui/src/components/Login.svelte
  - frontend/packages/ui/src/components/signup/steps/secureaccount/SecureAccountTopContent.svelte
---

# Signup & Login

> Zero-knowledge authentication where the server never sees plaintext passwords, emails, or master encryption keys. Authentication is proven by successful client-side decryption.

## Why This Exists

- The server must authenticate users without ever seeing their password or email in plaintext
- Multiple login methods (password+2FA, passkey, recovery key) each need their own path to the same master key
- Session persistence must work reliably across Safari iOS/iPadOS strict cookie policies

## Implementation Status

- **Implemented:** email + password + OTP 2FA, passkey (PRF), recovery key login
- **Planned:** magic link login, API key access

## How It Works

### Signup Flow

**Step 1 -- Basics:** user provides username and email; server checks email uniqueness via `hashed_email`.

**Step 2 -- Confirm email:** 6-digit OTP sent to email, validated server-side.

**Step 3 -- Secure account:** user chooses password or passkey.

**Password path:**
1. Client generates master key via `generateExtractableMasterKey()` and a unique salt
2. Wrapping key derived via `deriveKeyFromPassword()` -- PBKDF2-SHA256, 100k iterations
3. Master key wrapped with wrapping key; only `hashed_email`, `encrypted_email`, salt, and wrapped master key sent to server
4. Plaintext password never transmitted

**Passkey path:**
1. Server generates WebAuthn registration options with PRF extension
2. Browser creates credential; client verifies PRF support (required for zero-knowledge)
3. Client generates master key, wraps it with `deriveWrappingKeyFromPRF()` (HKDF from PRF signature + user salt)
4. Wrapped master key uploaded to server

See [Passkeys](./passkeys.md) for full passkey details.

**Step 3.2 -- 2FA setup (password users only):** QR code scanned with authenticator app, 6-digit OTP verified. Password auth always requires 2FA -- they are set up together and cannot exist independently.

**Step 4 -- Recovery key:** mandatory. Auto-generated, auto-downloaded as `openmates_recovery_key.txt`. User must confirm storage before proceeding. See `RecoveryKeyTopContent.svelte`.

**Step 5 -- Profile image:** (work in progress)

### Login Flows

#### Password + 2FA Login

1. Client computes `hashed_email` for lookup
2. Server returns user's salt and wrapped master key
3. Client derives wrapping key via PBKDF2(password, salt) and unwraps master key
4. User enters OTP (or backup code); server verifies
5. If verified: server sets session cookies, client decrypts user data with master key

#### Passkey Login

1. User clicks "Login with passkey" (no email entry needed)
2. `POST /auth/passkey/assertion/initiate` returns WebAuthn challenge with PRF extension using global salt `SHA256(rp_id)[:32]`
3. Browser prompts for passkey authentication
4. `POST /auth/passkey/assertion/verify` verifies signature via `py_webauthn`, identifies user by `credential_id`, starts cache warming
5. Client derives wrapping key from PRF via `HKDF(PRF_signature, user_email_salt)`, unwraps master key
6. Client decrypts email from `encrypted_email_with_master_key`, derives `lookup_hash`
7. `POST /auth/login` with `lookup_hash` and `login_method: 'passkey'` completes session
8. Frontend waits for cache warming (via WebSocket sync status) before loading main interface

See [auth_passkey.py](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) and [Login.svelte](../../frontend/packages/ui/src/components/Login.svelte).

#### Recovery Key Login

Recovery key uses the same PBKDF2 derivation path as password login. Users who still have their recovery key use "Login with recovery key" on the login page -- this preserves all data. See [Account Recovery](./account-recovery.md) for the destructive reset flow when all credentials are lost.

### Session Persistence ("Stay Logged In")

| Setting | Cookie TTL | Master key storage | Cleanup |
|---------|------------|-------------------|---------|
| Unchecked (default) | 24 hours | Memory only (`memoryMasterKey`) | Auto-cleared on page close |
| Checked | 30 days | IndexedDB as CryptoKey | Persists across sessions |

The 30-day TTL addresses Safari iOS strict cookie policies that cause logout on page reload.

Implementation: preference captured during email lookup, stored in Redis, cookie `max_age` set to 2,592,000s or 86,400s accordingly. See [cryptoKeyStorage.ts](../../frontend/packages/ui/src/services/cryptoKeyStorage.ts) for storage logic.

**Validation layers:** page-load check, access-time validation, periodic validation timer. Memory keys need no cleanup handlers (cleared automatically when page closes).

## Edge Cases

- **Safari iOS cookie eviction:** 30-day TTL + `navigator.storage.persist()` for IndexedDB
- **Lost password + lost passkey + lost recovery key:** destructive account reset required (see [Account Recovery](./account-recovery.md))
- **Non-PRF passkey device:** signup blocked; user prompted to use password+2FA or switch to a PRF-capable manager

## Related Docs

- [Security Architecture](./security.md) -- zero-knowledge authentication overview
- [Zero-Knowledge Storage](./zero-knowledge-storage.md) -- master key lifecycle
- [Passkeys](./passkeys.md) -- WebAuthn PRF implementation
- [Account Recovery](./account-recovery.md) -- recovery and reset flows
